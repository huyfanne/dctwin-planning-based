import { useState, useEffect, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine, Legend } from 'recharts';
import { createPlan, planStreamUrl, getWeather, cancelPlan, getPlanningContext, type Progress, type PlanningContext } from '../api';

const PREV_SETPOINT_LABELS: Record<string, string> = {
  crah_supply_air_temperature_c:       'CRAH Supply Air Temp',
  crah_supply_air_mass_flow_rate_kg_s: 'CRAH Air Mass Flow',
  chilled_water_supply_temperature_c:  'Chilled Water Supply Temp',
};

// One deck combining a PAST (actual) and FORECAST series on a shared time axis, with a
// dashed "now" divider at the week boundary. Used for both IT load and weather.
function SeriesDeck({ title, subtitle, unit, past, forecast, boundary, color }: {
  title: string; subtitle: string; unit: string;
  past: { t: string; v: number }[]; forecast: { t: string; v: number }[];
  boundary: string; color: string;
}) {
  const data = [
    ...past.map(p => ({ t: p.t, past: p.v })),
    ...forecast.map(p => ({ t: p.t, forecast: p.v })),
  ];
  const interval = Math.max(0, Math.floor(data.length / 7) - 1);
  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
        <span className="text-xs text-dim">{subtitle}</span>
      </div>
      <div className="card-body">
        {data.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-dim)" vertical={false} />
              <XAxis dataKey="t" tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                     interval={interval} tickFormatter={(t: string) => String(t).slice(5, 10)} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} width={48} />
              <Tooltip />
              <ReferenceLine x={boundary} stroke="var(--cyan)" strokeDasharray="4 4"
                             label={{ value: 'now', fill: 'var(--cyan)', fontSize: 10, position: 'top' }} />
              <Line type="monotone" dataKey="past" name={`Past (actual, ${unit})`} stroke={color} dot={false} connectNulls={false} />
              <Line type="monotone" dataKey="forecast" name={`Forecast (${unit})`} stroke="rgba(245,158,11,0.9)" strokeDasharray="5 3" dot={false} connectNulls={false} />
              <Legend />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-dim text-sm">No data available for this week.</p>
        )}
      </div>
    </div>
  );
}

function PrevSetpointsDeck({ prev }: { prev: PlanningContext['previous_setpoints'] }) {
  const caption = prev
    ? (prev.source === 'previous_plan' ? `plan · week of ${prev.week_start}` : 'as-operated estimate')
    : '—';
  return (
    <div className="card bracket-card animate-in">
      <div className="card-header">
        <span className="card-title">Previous Week Setpoints</span>
        <span className="text-xs text-dim">{caption}</span>
      </div>
      <div className="card-body">
        {prev && prev.setpoints ? (
          Object.entries(PREV_SETPOINT_LABELS).map(([k, lbl]) => (
            <div key={k} className="setpoint-row">
              <span className="setpoint-name">{lbl}</span>
              <span className="mono" style={{ fontSize: 18, fontWeight: 600, color: 'var(--cyan)', fontFamily: 'var(--font-data)' }}>
                {prev.setpoints[k] != null ? Number(prev.setpoints[k]).toFixed(2) : '—'}
              </span>
            </div>
          ))
        ) : (
          <p className="text-dim text-sm">No previous-week setpoints available.</p>
        )}
      </div>
    </div>
  );
}

// A long plan can outlive a single SSE connection (the server closes the stream after a
// while, or a proxy drops an idle one). Reconnect quietly a few times before declaring the
// backend down, so a healthy long run doesn't show a false "backend stopped" error.
const MAX_STREAM_RETRIES = 5;
const STREAM_RECONNECT_MS = 2000;

interface Props {
  onDone: (planId: string) => void;
}

export default function NewPlan({ onDone }: Props) {
  // Default to 2024-11-08 so the "past week" (Nov 1-7) sits inside the data coverage.
  const [weekStart, setWeekStart]   = useState('2024-11-08');
  const [days, setDays]             = useState('7');
  const [grid, setGrid]             = useState('5');
  const [beamWidth, setBeamWidth]   = useState('3');
  const [levels, setLevels]         = useState('3');
  const [nWorkers, setNWorkers]     = useState('4');
  const [timeBlock, setTimeBlock]   = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [planId, setPlanId]         = useState<string | null>(null);
  const [progress, setProgress]     = useState<Progress | null>(null);
  const [done, setDone]             = useState(false);
  const [status, setStatus]         = useState<string>('queued');
  const [error, setError]           = useState<string | null>(null);
  const [coverage, setCoverage]     = useState<string | null>(null);
  const [cancelled, setCancelled]   = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [ctx, setCtx]               = useState<PlanningContext | null>(null);
  const [ctxLoading, setCtxLoading] = useState(false);

  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    getWeather().then(w => setCoverage(w.label)).catch(() => {});
  }, []);

  // Fetch the planning context (past/forecast IT load + weather + previous setpoints)
  // when the week (or days) changes, debounced, until a run starts.
  useEffect(() => {
    if (planId) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(weekStart)) { setCtx(null); return; }
    let live = true;
    setCtxLoading(true);
    const id = setTimeout(() => {
      getPlanningContext(weekStart, Number(days) || 7)
        .then(c => { if (live) setCtx(c); })
        .catch(() => { if (live) setCtx(null); })
        .finally(() => { if (live) setCtxLoading(false); });
    }, 300);
    return () => { live = false; clearTimeout(id); };
  }, [weekStart, days, planId]);

  useEffect(() => {
    if (!planId || done || error || cancelled) return;
    let retries = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const open = () => {
      if (stopped) return;
      const es = new EventSource(planStreamUrl(planId));
      esRef.current = es;
      es.onmessage = (e) => {
        retries = 0;                                  // a frame arrived → the connection is healthy
        const frame = JSON.parse(e.data) as { progress: Progress; status: string };
        if (frame.progress) setProgress(frame.progress);
        setStatus(frame.status);
        if (frame.status === 'failed') {
          setError(frame.progress?.error ?? 'Plan run failed on the server — see the backend log (the backend may lack Docker access for EnergyPlus).');
          stopped = true; es.close();
        } else if (frame.status === 'cancelled') {
          setCancelled(true); stopped = true; es.close();
        } else if (frame.status && !['queued', 'running', 'deploying'].includes(frame.status)) {
          setDone(true); stopped = true; es.close();
        }
      };
      es.onerror = () => {
        es.close();
        if (stopped) return;
        retries += 1;
        if (retries > MAX_STREAM_RETRIES) {
          stopped = true;
          setError('Lost connection to the progress stream. The backend may have stopped — see the backend log.');
        } else {
          timer = setTimeout(open, STREAM_RECONNECT_MS);   // quietly reconnect; the plan keeps running server-side
        }
      };
    };

    open();
    return () => { stopped = true; if (timer) clearTimeout(timer); esRef.current?.close(); };
  }, [planId, done, error, cancelled]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!weekStart) { setError('Week start date is required.'); return; }
    setSubmitting(true);
    try {
      const res = await createPlan({
        week_start: weekStart,
        days:       Number(days),
        grid:       Number(grid),
        beam_width: Number(beamWidth),
        levels:     Number(levels),
        n_workers:  Number(nWorkers),
        time_block: timeBlock,
      });
      setPlanId(res.plan_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create plan');
      setSubmitting(false);
    }
  }

  const maxLevel = Number(levels) || 3;
  const currLevel = progress?.level ?? 0;
  const pct = Math.min(100, Math.round((currLevel / maxLevel) * 100));
  const evals = progress?.evals ?? 0;
  const bestScore = progress?.best_score;

  return (
    <div className="animate-in">
      <div className="section-header">
        <h2 className="section-title">
          <span className="title-accent">+</span> New Optimization Plan
        </h2>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: planId ? '1fr 1fr' : '1fr', maxWidth: planId ? '900px' : '520px', gap: 20 }}>

        {/* Form */}
        <div className="card bracket-card">
          <div className="card-header">
            <span className="card-title">Plan Parameters</span>
            {planId && <span className="badge badge-running">Optimizing</span>}
          </div>
          <form onSubmit={handleSubmit}>
            <div className="card-body flex-col gap-3">
              <div className="field">
                <label className="field-label" htmlFor="week-start">Week Start *</label>
                <input
                  id="week-start"
                  type="date"
                  className="field-input"
                  value={weekStart}
                  onChange={e => setWeekStart(e.target.value)}
                  disabled={!!planId}
                  required
                />
                {coverage && <div className="field-hint" style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>Weather data covers {coverage}.</div>}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div className="field">
                  <label className="field-label" htmlFor="days">Days</label>
                  <input
                    id="days"
                    type="number"
                    className="field-input"
                    value={days}
                    min={1}
                    max={30}
                    onChange={e => setDays(e.target.value)}
                    disabled={!!planId}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="grid">Grid Size</label>
                  <input
                    id="grid"
                    type="number"
                    className="field-input"
                    value={grid}
                    min={2}
                    max={20}
                    onChange={e => setGrid(e.target.value)}
                    disabled={!!planId}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="beam-width">Beam Width</label>
                  <input
                    id="beam-width"
                    type="number"
                    className="field-input"
                    value={beamWidth}
                    min={1}
                    max={20}
                    onChange={e => setBeamWidth(e.target.value)}
                    disabled={!!planId}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="levels">Levels</label>
                  <input
                    id="levels"
                    type="number"
                    className="field-input"
                    value={levels}
                    min={1}
                    max={10}
                    onChange={e => setLevels(e.target.value)}
                    disabled={!!planId}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="n-workers">Workers</label>
                  <input
                    id="n-workers"
                    type="number"
                    className="field-input"
                    value={nWorkers}
                    min={1}
                    max={32}
                    onChange={e => setNWorkers(e.target.value)}
                    disabled={!!planId}
                  />
                </div>
              </div>

              <div className="field">
                <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input type="checkbox" checked={timeBlock} disabled={!!planId}
                         onChange={e => setTimeBlock(e.target.checked)} />
                  Day/night setpoints (time-block)
                </label>
              </div>

              {error && <div className="error-msg">{error}</div>}

              {!planId && (
                <div className="mt-2">
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={submitting}
                    style={{ width: '100%', justifyContent: 'center' }}
                  >
                    {submitting ? <><span className="spinner" style={{ width: 16, height: 16 }} /> Submitting…</> : '▶ Launch Optimization'}
                  </button>
                </div>
              )}
            </div>
          </form>
        </div>

        {/* Live Progress */}
        {planId && (
          <div className="card bracket-card animate-in">
            <div className="card-header">
              <span className="card-title">Live Progress</span>
              {error ? <span className="badge" style={{ color: 'var(--amber, #f5a623)', borderColor: 'var(--amber, #f5a623)' }}>Failed</span>
                : cancelled ? <span className="badge badge-rejected">Cancelled</span>
                : done ? <span className="badge badge-approved">Complete</span>
                : <span className="live-dot">Running</span>}
            </div>
            <div className="card-body flex-col gap-4">
              {/* Plan ID */}
              <div>
                <div className="metric-label">Plan ID</div>
                <div className="mono" style={{ fontSize: 12, color: 'var(--cyan)', marginTop: 4 }}>{planId}</div>
              </div>

              {/* Progress bar */}
              <div className="flex-col gap-2">
                <div className="flex justify-between" style={{ marginBottom: 4 }}>
                  <span className="metric-label">Level {currLevel} / {maxLevel}</span>
                  <span className="mono" style={{ fontSize: 12, color: 'var(--text-label)' }}>{pct}%</span>
                </div>
                <div className="progress-wrap">
                  <div className="progress-bar" style={{ width: `${pct}%` }} />
                </div>
              </div>

              {/* Stats */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div className="metric-tile">
                  <div className="metric-label">Evaluations</div>
                  <div>
                    <span className="metric-value" style={{ fontSize: 28 }}>{evals}</span>
                  </div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">Best Score</div>
                  <div>
                    <span className="metric-value" style={{ fontSize: 24, color: 'var(--green)' }}>
                      {bestScore != null ? Number(bestScore).toFixed(4) : '—'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Action */}
              {!done && !error && !cancelled && (
                <button className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center' }}
                  disabled={cancelling}
                  onClick={async () => { setCancelling(true); try { await cancelPlan(planId!); } catch { /* stream reflects it */ } }}>
                  {cancelling ? 'Cancelling…' : 'Cancel Plan'}
                </button>
              )}
              {cancelled && (
                <>
                  <div className="error-msg">Plan cancelled.</div>
                  <button className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center' }}
                    onClick={() => {
                      esRef.current?.close();
                      setPlanId(null); setProgress(null); setDone(false); setCancelled(false);
                      setCancelling(false); setError(null); setStatus('queued'); setSubmitting(false);
                    }}>
                    ← Start New Plan
                  </button>
                </>
              )}
              {done && (
                <button
                  className="btn btn-primary"
                  style={{ width: '100%', justifyContent: 'center' }}
                  onClick={() => onDone(planId)}
                >
                  Review Results →
                </button>
              )}

              {error && (
                <>
                  <div className="error-msg">{error}</div>
                  <button
                    className="btn btn-ghost"
                    style={{ width: '100%', justifyContent: 'center' }}
                    onClick={() => {
                      esRef.current?.close();
                      setPlanId(null); setProgress(null); setDone(false);
                      setError(null); setStatus('queued'); setSubmitting(false);
                    }}
                  >
                    ← Start New Plan
                  </button>
                </>
              )}

              {!done && !error && !cancelled && (
                <p className="text-dim text-sm" style={{ fontFamily: 'var(--font-data)', textAlign: 'center', marginTop: 4 }}>
                  Status: {status} · live stream
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Planning-context decks — shown before a run starts */}
      {!planId && (ctx || ctxLoading) && (
        <div style={{ marginTop: 24 }}>
          <div className="section-header" style={{ marginBottom: 12 }}>
            <h3 className="section-title" style={{ fontSize: 16 }}>
              <span className="title-accent">~</span> Planning Context — week of {weekStart}
              {ctxLoading && <span className="spinner" style={{ width: 14, height: 14, marginLeft: 10, display: 'inline-block' }} />}
            </h3>
          </div>
          {ctx ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
              <SeriesDeck
                title="IT Load — past & forecast" subtitle={`1F 2A · ${ctx.it_load.unit}`} unit={ctx.it_load.unit}
                past={ctx.it_load.past.map(p => ({ t: p.t, v: p.kw }))}
                forecast={ctx.it_load.forecast.map(p => ({ t: p.t, v: p.kw }))}
                boundary={ctx.it_load.forecast[0]?.t ?? `${weekStart}T00:00`} color="rgba(0,200,255,0.9)" />
              <SeriesDeck
                title="Weather — past & forecast" subtitle={`outdoor · ${ctx.weather.unit}`} unit={ctx.weather.unit}
                past={ctx.weather.past.map(p => ({ t: p.t, v: p.temp_c }))}
                forecast={ctx.weather.forecast.map(p => ({ t: p.t, v: p.temp_c }))}
                boundary={ctx.weather.forecast[0]?.t ?? `${weekStart}T00:00`} color="rgba(0,200,255,0.9)" />
              <PrevSetpointsDeck prev={ctx.previous_setpoints} />
            </div>
          ) : (
            <p className="text-dim text-sm">Loading planning context…</p>
          )}
        </div>
      )}
    </div>
  );
}
