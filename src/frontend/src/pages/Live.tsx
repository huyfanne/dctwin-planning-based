import { useEffect, useMemo, useRef, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts';
import { getLive, getLiveSeries, liveStreamUrl, type LiveFrame, type LiveSeriesPoint } from '../api';

// Same reconnect budget as the NewPlan progress stream: a proxy can drop a healthy SSE
// connection, so reconnect quietly a few times — then drop to plain 5 s polling so the
// page stays live instead of dying with an error.
const MAX_STREAM_RETRIES = 5;
const STREAM_RECONNECT_MS = 2000;
const POLL_FALLBACK_MS = 5000;
const SERIES_REFRESH_MS = 15000;
const SERIES_WINDOW_MIN = 30;
const INLET_CAP_C = 26.0;
const COMPLIANCE_TOLERANCE = 0.5;            // per-axis |held − commanded| tolerance

const RACKS = Array.from({ length: 22 }, (_, i) => `ite-${i + 1}`);

const AXES: { key: string; label: string; unit: string }[] = [
  { key: 'sat_c',     label: 'CRAH Supply Air Temp',      unit: '°C' },
  { key: 'flow_kg_s', label: 'CRAH Air Mass Flow',        unit: 'kg/s' },
  { key: 'chwst_c',   label: 'Chilled Water Supply Temp', unit: '°C' },
];

// Keyframes for the ≥26 °C pulsing tile border — local to this page (inline animation).
const PULSE_CSS = `@keyframes live-pulse-border {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.65); }
  50%      { box-shadow: 0 0 0 5px rgba(239, 68, 68, 0); }
}`;

type Zone = 'green' | 'amber' | 'red' | 'none';

function inletZone(v: number | null): Zone {
  if (v == null) return 'none';
  if (v >= 25.5) return 'red';
  if (v >= 24.5) return 'amber';
  return 'green';
}

const ZONE_STYLE: Record<Zone, { color: string; bg: string; border: string }> = {
  green: { color: 'var(--green)',      bg: 'var(--green-dim)', border: 'rgba(16, 185, 129, 0.35)' },
  amber: { color: 'var(--amber)',      bg: 'var(--amber-dim)', border: 'rgba(245, 158, 11, 0.45)' },
  red:   { color: 'var(--red)',        bg: 'var(--red-dim)',   border: 'rgba(239, 68, 68, 0.55)' },
  none:  { color: 'var(--text-muted)', bg: 'var(--bg-panel)',  border: 'var(--border-dim)' },
};

function fmt(v: number | null | undefined, digits = 1): string {
  return v != null ? Number(v).toFixed(digits) : '—';
}

// Status chip for the rack-detail table: zone styling + an operator-readable label.
function rackChip(v: number | null): { label: string; zone: Zone } {
  if (v == null) return { label: 'No Data', zone: 'none' };
  if (v >= INLET_CAP_C) return { label: 'Over Cap', zone: 'red' };
  const zone = inletZone(v);
  return { label: zone === 'red' ? 'Hot' : zone === 'amber' ? 'Warm' : 'Nominal', zone };
}

function fmtClock(t: number): string {
  const d = new Date(t > 1e12 ? t : t * 1000);   // accept epoch seconds or ms
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// Compliance keys may arrive long ("sat_c") or short ("sat") — accept both.
function axisVal(rec: Record<string, number> | null | undefined, key: string): number | null {
  if (!rec) return null;
  if (rec[key] != null) return rec[key];
  return rec[key.split('_')[0]] ?? null;
}

export default function Live() {
  const [frame, setFrame]     = useState<LiveFrame | null>(null);
  const [series, setSeries]   = useState<Record<string, LiveSeriesPoint[]> | null>(null);
  const [error, setError]     = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // Live frame: initial snapshot + SSE with the NewPlan reconnect pattern, then poll fallback.
  useEffect(() => {
    let stopped = false;
    let retries = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let pollTimer: ReturnType<typeof setInterval> | undefined;

    const apply = (f: LiveFrame) => { if (!stopped) { setFrame(f); setError(null); } };

    const startPolling = () => {
      if (stopped || pollTimer) return;
      setPolling(true);
      const tick = () => { getLive().then(apply).catch(() => { /* keep the last frame */ }); };
      tick();
      pollTimer = setInterval(tick, POLL_FALLBACK_MS);
    };

    const open = () => {
      if (stopped) return;
      const es = new EventSource(liveStreamUrl());
      esRef.current = es;
      es.onmessage = (e) => { retries = 0; apply(JSON.parse(e.data) as LiveFrame); };
      es.onerror = () => {
        es.close();
        if (stopped) return;
        retries += 1;
        if (retries > MAX_STREAM_RETRIES) startPolling();
        else timer = setTimeout(open, STREAM_RECONNECT_MS);
      };
    };

    getLive().then(apply).catch((e: unknown) => {
      if (!stopped && !pollTimer) setError(e instanceof Error ? e.message : 'Failed to reach the live feed');
    });
    open();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (pollTimer) clearInterval(pollTimer);
      esRef.current?.close();
    };
  }, []);

  // Rolling 30-min series, refreshed in the background.
  useEffect(() => {
    let live = true;
    const load = () => {
      getLiveSeries(SERIES_WINDOW_MIN)
        .then(s => { if (live) setSeries(s.series); })
        .catch(() => { /* the frame stream is the primary signal */ });
    };
    load();
    const id = setInterval(load, SERIES_REFRESH_MS);
    return () => { live = false; clearInterval(id); };
  }, []);

  const rows = useMemo(() => {
    const power = series?.hall_power_kw ?? [];
    const inlet = series?.worst_inlet_c ?? [];
    const byT = new Map<number, { t: number; power?: number; inlet?: number }>();
    for (const p of power) byT.set(p.t, { ...(byT.get(p.t) ?? { t: p.t }), power: p.v });
    for (const p of inlet) byT.set(p.t, { ...(byT.get(p.t) ?? { t: p.t }), inlet: p.v });
    return [...byT.values()].sort((a, b) => a.t - b.t);
  }, [series]);

  if (!frame) {
    return error ? (
      <div className="mt-4">
        <div className="error-msg">{error}</div>
      </div>
    ) : (
      <div className="flex items-center gap-3 mt-6" style={{ padding: '48px 0' }}>
        <div className="spinner" />
        <span className="text-dim" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.1em', fontSize: 13 }}>
          CONNECTING TO LIVE FEED…
        </span>
      </div>
    );
  }

  const pv = (name: string): number | null => frame.points[name]?.value ?? null;
  const rackVals = RACKS
    .map(r => frame.points[`rack_inlet_c/${r}`]?.value)
    .filter((v): v is number => v != null);
  // Hotspot list: every rack ranked by inlet descending; missing telemetry sinks to the bottom.
  const rackDetail = RACKS
    .map(rack => ({ rack, inlet: frame.points[`rack_inlet_c/${rack}`]?.value ?? null }))
    .sort((a, b) => (b.inlet ?? -1e9) - (a.inlet ?? -1e9));
  const worst = rackVals.length ? Math.max(...rackVals) : null;
  const margin = worst != null ? INLET_CAP_C - worst : null;
  const hasCritical = frame.alerts.some(a => a.level === 'critical');
  const comp = frame.compliance;

  return (
    <div className="animate-in">
      <style>{PULSE_CSS}</style>

      {/* Header */}
      <div className="section-header">
        <div>
          <h2 className="section-title">
            <span className="title-accent">◉</span> Live Telemetry
          </h2>
          <p className="text-dim text-sm mt-2" style={{ fontFamily: 'var(--font-data)' }}>
            1F 2A hall · updated <strong style={{ color: 'var(--text-primary)' }}>{fmtClock(frame.ts)}</strong>
            {' · '}{polling ? 'poll fallback · 5 s' : 'live stream'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {frame.simulated && (
            <span className="badge badge-pending"
              title="Built-in simulated telemetry feed — no physical BMS attached">
              Simulated Feed
            </span>
          )}
          <span className="live-dot">Live</span>
        </div>
      </div>

      {/* Alert banner */}
      {frame.alerts.length > 0 ? (
        <div role="alert" className="animate-in" style={{
          background: hasCritical ? 'var(--red-dim)' : 'var(--amber-dim)',
          border: `1px solid ${hasCritical ? 'rgba(239, 68, 68, 0.5)' : 'rgba(245, 158, 11, 0.5)'}`,
          borderRadius: 8, padding: '12px 18px', marginBottom: 16,
        }}>
          <div style={{
            fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 700,
            letterSpacing: '0.1em', textTransform: 'uppercase',
            color: hasCritical ? 'var(--red)' : 'var(--amber)',
          }}>
            {hasCritical ? 'Critical' : 'Warning'} — {frame.alerts.length} active alert{frame.alerts.length > 1 ? 's' : ''}
          </div>
          <div className="flex-col gap-2 mt-2">
            {frame.alerts.map(a => (
              <div key={`${a.point}-${a.level}`} className="mono"
                style={{ fontSize: 12, color: a.level === 'critical' ? 'var(--red)' : 'var(--amber)' }}>
                {a.level === 'critical' ? '●' : '▲'} {a.point} · {fmt(a.value)} °C — {a.message}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="animate-in" style={{
          background: 'var(--green-dim)', border: '1px solid rgba(16, 185, 129, 0.3)',
          borderRadius: 8, padding: '10px 18px', marginBottom: 16,
          fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 600,
          letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--green)',
        }}>
          ● All racks nominal — no active alerts
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>

        {/* Rack heat-map */}
        <div className="card card-glow bracket-card animate-in animate-in-1" style={{ gridColumn: '1 / -1' }}>
          <div className="card-header">
            <span className="card-title">Rack Inlet Heat-Map</span>
            <span className="text-xs text-dim mono">22 racks · cap {INLET_CAP_C.toFixed(0)} °C</span>
          </div>
          <div className="card-body">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(76px, 1fr))', gap: 8 }}>
              {RACKS.map(rack => {
                const point = `rack_inlet_c/${rack}`;
                const v = frame.points[point]?.value ?? null;
                const zone = inletZone(v);
                const zs = ZONE_STYLE[zone];
                const pulsing = v != null && v >= INLET_CAP_C;
                return (
                  <div key={rack} title={point} data-zone={zone} style={{
                    background: zs.bg, borderRadius: 6, padding: '8px 4px', textAlign: 'center',
                    border: `1px solid ${pulsing ? 'var(--red)' : zs.border}`,
                    ...(pulsing ? { animation: 'live-pulse-border 1s ease-in-out infinite' } : {}),
                  }}>
                    <div style={{
                      fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
                      letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-secondary)',
                    }}>
                      {rack}
                    </div>
                    <div className="mono" style={{ fontSize: 15, fontWeight: 600, color: zs.color, marginTop: 2 }}>
                      {fmt(v)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Rack detail — the operator's hotspot list, hottest first */}
        <div className="card animate-in animate-in-2" style={{ gridColumn: '1 / -1' }}>
          <div className="card-header">
            <span className="card-title">Rack Detail</span>
            <span className="text-xs text-dim mono">ranked by inlet · margin to {INLET_CAP_C.toFixed(0)} °C cap</span>
          </div>
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Rack</th>
                  <th>Inlet °C</th>
                  <th>Margin °C</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rackDetail.map((r, i) => {
                  const chip = rackChip(r.inlet);
                  const zs = ZONE_STYLE[chip.zone];
                  const m = r.inlet != null ? INLET_CAP_C - r.inlet : null;
                  return (
                    <tr key={r.rack} data-rack={r.rack}>
                      <td className="mono" style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                      <td className="label-cell">{r.rack}</td>
                      <td className="mono" style={{ color: zs.color }}>{fmt(r.inlet)}</td>
                      <td className="mono" style={{ color: m != null && m < 1 ? 'var(--red)' : 'var(--text-secondary)' }}>
                        {m != null ? m.toFixed(1) : '—'}
                      </td>
                      <td>
                        <span className="badge" data-chip={chip.zone} style={{
                          fontSize: 9, color: zs.color, background: zs.bg, border: `1px solid ${zs.border}`,
                        }}>
                          {chip.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* KPI tiles */}
        <div className="card animate-in animate-in-2" style={{ gridColumn: '1 / -1' }}>
          <div className="card-header">
            <span className="card-title">Hall KPIs</span>
            <span className="live-dot">Telemetry</span>
          </div>
          <div className="card-body">
            <div className="metric-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
              <div className="metric-tile">
                <div className="metric-label">Hall Power</div>
                <div>
                  <span className="metric-value" style={{ fontSize: 24 }}>{fmt(pv('hall_power_kw'))}</span>
                  <span className="metric-unit">kW</span>
                </div>
              </div>
              <div className="metric-tile">
                <div className="metric-label">PUE</div>
                <div>
                  <span className="metric-value" style={{ fontSize: 24 }}>{fmt(pv('pue'), 2)}</span>
                </div>
              </div>
              <div className="metric-tile">
                <div className="metric-label">Relative Humidity</div>
                <div>
                  <span className="metric-value" style={{ fontSize: 24 }}>{fmt(pv('rh_pct'))}</span>
                  <span className="metric-unit">%</span>
                </div>
              </div>
              <div className="metric-tile">
                <div className="metric-label">Worst Inlet</div>
                <div>
                  <span className="metric-value" style={{
                    fontSize: 24,
                    color: worst != null ? ZONE_STYLE[inletZone(worst)].color : undefined,
                  }}>
                    {fmt(worst)}
                  </span>
                  <span className="metric-unit">°C</span>
                </div>
                <div className={`metric-delta ${margin != null && margin < 1 ? 'negative' : 'positive'}`}>
                  {margin != null
                    ? `${fmt(margin)} °C to ${INLET_CAP_C.toFixed(0)} °C cap`
                    : 'no rack data'}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Setpoint compliance */}
        <div className="card bracket-card animate-in animate-in-3">
          <div className="card-header">
            <span className="card-title">Setpoint Compliance</span>
            {comp.ok === true && <span className="badge badge-approved">In Tolerance</span>}
            {comp.ok === false && <span className="badge badge-pending">Drift</span>}
            {comp.ok == null && <span className="text-xs text-dim mono">±{COMPLIANCE_TOLERANCE} tolerance</span>}
          </div>
          <div className="card-body">
            {comp.commanded == null ? (
              <div className="empty-state" style={{ padding: '24px 12px' }}>
                <div className="empty-state-icon">◇</div>
                <div className="empty-state-text">No deployed plan</div>
                <p className="text-dim text-sm">Commanded-vs-held compliance appears after a plan is deployed.</p>
              </div>
            ) : (
              AXES.map(ax => {
                const cmd = axisVal(comp.commanded, ax.key);
                const held = axisVal(comp.held, ax.key) ?? frame.points[`held/${ax.key}`]?.value ?? null;
                const delta = axisVal(comp.deltas, ax.key)
                  ?? (cmd != null && held != null ? held - cmd : null);
                const ok = delta == null ? null : Math.abs(delta) <= COMPLIANCE_TOLERANCE;
                return (
                  <div key={ax.key} className="setpoint-row">
                    <span className="setpoint-name">{ax.label}</span>
                    <span className="flex items-center gap-3">
                      <span className="mono" style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                        {`${fmt(cmd, 2)} → ${fmt(held, 2)}`}
                        <span style={{ color: 'var(--text-secondary)', marginLeft: 4 }}>{ax.unit}</span>
                      </span>
                      <span className="mono" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        {delta != null ? `Δ ${delta >= 0 ? '+' : ''}${delta.toFixed(2)}` : 'Δ —'}
                      </span>
                      <span
                        aria-label={`${ax.key} ${ok === false ? 'out of tolerance' : 'in tolerance'}`}
                        title={`commanded vs held · tolerance ±${COMPLIANCE_TOLERANCE}`}
                        style={{
                          fontSize: 14, fontWeight: 700,
                          color: ok === false ? 'var(--amber)' : ok ? 'var(--green)' : 'var(--text-muted)',
                        }}>
                        {ok === false ? '⚠' : ok ? '✓' : '—'}
                      </span>
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Rolling 30-min chart */}
        <div className="card animate-in animate-in-4">
          <div className="card-header">
            <span className="card-title">Rolling Window — {SERIES_WINDOW_MIN} min</span>
            <span className="text-xs text-dim">hall power · worst inlet · 26 °C cap</span>
          </div>
          <div className="card-body">
            {rows.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={rows}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-dim)" vertical={false} />
                  <XAxis dataKey="t" tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                         tickFormatter={(t: number) => fmtClock(t)} minTickGap={40} />
                  <YAxis yAxisId="power" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} width={48} />
                  <YAxis yAxisId="inlet" orientation="right" domain={[20, 30]}
                         tick={{ fill: 'var(--text-muted)', fontSize: 11 }} width={40} />
                  <Tooltip labelFormatter={(t) => fmtClock(Number(t))} />
                  <ReferenceLine yAxisId="inlet" y={INLET_CAP_C} stroke="var(--red)" strokeDasharray="4 4"
                                 label={{ value: '26°C cap', fill: 'var(--red)', fontSize: 10 }} />
                  <Line yAxisId="power" type="monotone" dataKey="power" name="Hall Power (kW)"
                        stroke="rgba(0,200,255,0.9)" dot={false} connectNulls />
                  <Line yAxisId="inlet" type="monotone" dataKey="inlet" name="Worst Inlet (°C)"
                        stroke="rgba(245,158,11,0.9)" dot={false} connectNulls />
                  <Legend />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-dim text-sm">No series data yet — the rolling window fills as telemetry arrives.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
