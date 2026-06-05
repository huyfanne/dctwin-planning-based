import { useEffect, useMemo, useState } from 'react';
import {
  getTopology, listPlans, getPlan,
  type Topology, type PlanSummary, type PlanDetail,
} from '../api';
import HallScene from '../three/HallScene';
import SceneBoundary from '../three/SceneBoundary';
import { particleSpeed, tempColor } from '../three/airflow';

const SAT_KEY = 'crah_supply_air_temperature_c';
const FLOW_KEY = 'crah_supply_air_mass_flow_rate_kg_s';
const CHWST_KEY = 'chilled_water_supply_temperature_c';

// Fallback anchors when a plan/KPI is missing, so the scene always renders.
const DEFAULT_SAT = 22;
const DEFAULT_FLOW = 9.3;
const DEFAULT_INLET_MAX = 27;

function num(v: number | null | undefined, fallback: number): number {
  return typeof v === 'number' && isFinite(v) ? v : fallback;
}

interface HudStatProps {
  label: string;
  value: string;
  unit?: string;
  accent?: string;
  sub?: string;
}

function HudStat({ label, value, unit, accent = 'var(--cyan)', sub }: HudStatProps) {
  return (
    <div
      style={{
        background: 'rgba(13,19,32,0.78)',
        border: `1px solid var(--border-bright)`,
        borderRadius: 6,
        padding: '8px 12px',
        minWidth: 96,
        backdropFilter: 'blur(6px)',
      }}
    >
      <div className="metric-label" style={{ fontSize: 9 }}>{label}</div>
      <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: accent, lineHeight: 1.05 }}>
        {value}
        {unit && <span style={{ fontSize: 11, color: 'var(--text-secondary)', marginLeft: 3 }}>{unit}</span>}
      </div>
      {sub && <div className="mono" style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function DigitalTwin3D() {
  const [topo, setTopo] = useState<Topology | null>(null);
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [detail, setDetail] = useState<PlanDetail | null>(null);
  const [showLabels, setShowLabels] = useState(false);
  const [topoErr, setTopoErr] = useState<string | null>(null);
  const [loadingTopo, setLoadingTopo] = useState(true);
  const [loadingPlan, setLoadingPlan] = useState(false);

  // Load topology + plan list on mount.
  useEffect(() => {
    let alive = true;
    getTopology()
      .then((t) => { if (alive) setTopo(t); })
      .catch((e) => { if (alive) setTopoErr(e instanceof Error ? e.message : 'Failed to load topology'); })
      .finally(() => { if (alive) setLoadingTopo(false); });

    listPlans()
      .then((p) => {
        if (!alive) return;
        const sorted = [...p].sort((a, b) => b.week_start.localeCompare(a.week_start));
        setPlans(sorted);
        if (sorted.length > 0) setSelectedId(sorted[0].plan_id);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Load plan detail when selection changes.
  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    let alive = true;
    setLoadingPlan(true);
    getPlan(selectedId)
      .then((d) => { if (alive) setDetail(d); })
      .catch(() => { if (alive) setDetail(null); })
      .finally(() => { if (alive) setLoadingPlan(false); });
    return () => { alive = false; };
  }, [selectedId]);

  const rec = detail?.recommendation;
  const sp = rec?.setpoints ?? {};
  const kpi = rec?.predicted_kpis ?? {};

  const sat = num(sp[SAT_KEY], DEFAULT_SAT);
  const flow = num(sp[FLOW_KEY], DEFAULT_FLOW);
  const chwst = num(sp[CHWST_KEY], 16);
  const inletMax = num(kpi.inlet_temp_max_c, DEFAULT_INLET_MAX);
  // Ensure a non-degenerate color span even if inletMax <= sat.
  const inletAnchor = inletMax > sat + 1 ? inletMax : sat + 5;

  const speedPct = useMemo(() => Math.round(particleSpeed(flow) * 100), [flow]);

  if (loadingTopo) {
    return (
      <div className="animate-in">
        <div className="section-header">
          <h2 className="section-title"><span className="title-accent">◈</span> Digital Twin (3D)</h2>
        </div>
        <div className="flex items-center gap-3" style={{ padding: '48px 0' }}>
          <div className="spinner" />
          <span className="text-dim" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.1em', fontSize: 13 }}>
            BUILDING HALL TOPOLOGY…
          </span>
        </div>
      </div>
    );
  }

  if (topoErr || !topo) {
    return (
      <div className="animate-in">
        <div className="section-header">
          <h2 className="section-title"><span className="title-accent">◈</span> Digital Twin (3D)</h2>
        </div>
        <div className="error-msg">{topoErr ?? 'No hall topology available.'}</div>
      </div>
    );
  }

  const hasPlan = !!rec;

  return (
    <div className="animate-in">
      <div className="section-header">
        <h2 className="section-title">
          <span className="title-accent">◈</span> Digital Twin (3D)
          <span className="text-dim" style={{ fontSize: 12, fontFamily: 'var(--font-data)', letterSpacing: 0, textTransform: 'none', marginLeft: 8 }}>
            {topo.hall.name}
          </span>
        </h2>

        <div className="flex items-center gap-3">
          <button
            className="btn btn-ghost"
            style={{ padding: '7px 14px', fontSize: 11 }}
            onClick={() => setShowLabels((s) => !s)}
          >
            {showLabels ? '◉ Labels On' : '○ Labels Off'}
          </button>
          <label className="field-label" style={{ whiteSpace: 'nowrap' }}>Plan</label>
          <select
            className="field-input"
            style={{ width: 260 }}
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {plans.length === 0 && <option value="">No plans (showing nominal)</option>}
            {plans.map((p) => (
              <option key={p.plan_id} value={p.plan_id}>
                {p.week_start} — {p.plan_id.slice(0, 8)} ({p.status})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 3D viewport with HUD overlay */}
      <div
        className="card bracket-card card-glow"
        style={{ position: 'relative', height: 'calc(100vh - 180px)', minHeight: 520, overflow: 'hidden', padding: 0 }}
      >
        {/* The GL scene */}
        <div style={{ position: 'absolute', inset: 0 }}>
          <SceneBoundary>
            <HallScene
              topo={topo}
              sat={sat}
              flow={flow}
              inletMax={inletAnchor}
              showLabels={showLabels}
            />
          </SceneBoundary>
        </div>

        {/* Top-left: live + setpoints */}
        <div style={{ position: 'absolute', top: 14, left: 14, display: 'flex', flexDirection: 'column', gap: 10, pointerEvents: 'none' }}>
          <div className="flex items-center gap-3">
            <span className="live-dot">Twin Live</span>
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {topo.crahs.length} CRAH · {topo.rack_rows.length} ROWS
            </span>
          </div>
          <div className="flex gap-2" style={{ flexWrap: 'wrap', maxWidth: 360 }}>
            <HudStat label="Supply Air" value={sat.toFixed(1)} unit="°C" accent={tempColor(sat, sat, inletAnchor)} />
            <HudStat label="Air Flow" value={flow.toFixed(1)} unit="kg/s" sub={`${speedPct}% jet speed`} />
            <HudStat label="CHW Supply" value={chwst.toFixed(1)} unit="°C" accent="var(--violet)" />
          </div>
        </div>

        {/* Top-right: predicted KPIs */}
        <div style={{ position: 'absolute', top: 14, right: 14, display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end', pointerEvents: 'none' }}>
          <span className="metric-label" style={{ fontSize: 9 }}>Predicted KPIs</span>
          <HudStat label="HVAC Energy" value={num(kpi.total_hvac_energy_kwh, 0).toFixed(0)} unit="kWh" accent="var(--green)" />
          <HudStat label="PUE Mean" value={num(kpi.pue_mean, 0).toFixed(2)} />
          <HudStat
            label="Peak Inlet"
            value={num(kpi.inlet_temp_max_c, inletAnchor).toFixed(1)}
            unit="°C"
            accent={tempColor(inletMax, sat, inletAnchor)}
          />
          <HudStat
            label="Violations"
            value={num(kpi.inlet_violation_steps, 0).toFixed(0)}
            unit="steps"
            accent={num(kpi.inlet_violation_steps, 0) > 0 ? 'var(--red)' : 'var(--green)'}
          />
        </div>

        {/* Bottom-left: thermal legend + plan context */}
        <div style={{ position: 'absolute', bottom: 14, left: 14, pointerEvents: 'none' }}>
          <div className="metric-label" style={{ fontSize: 9, marginBottom: 5 }}>Cold Aisle → Hot Aisle</div>
          <div style={{
            width: 200, height: 8, borderRadius: 4,
            background: `linear-gradient(90deg, ${tempColor(sat, sat, inletAnchor)}, ${tempColor((sat + inletAnchor) / 2, sat, inletAnchor)}, ${tempColor(inletAnchor, sat, inletAnchor)})`,
            border: '1px solid var(--border-bright)',
          }} />
          <div className="flex justify-between mono" style={{ width: 200, fontSize: 9, color: 'var(--text-secondary)', marginTop: 3 }}>
            <span>{sat.toFixed(0)}°C</span>
            <span>{inletAnchor.toFixed(0)}°C</span>
          </div>
        </div>

        {/* Bottom-right: status chip */}
        <div style={{ position: 'absolute', bottom: 14, right: 14, pointerEvents: 'none' }}>
          {loadingPlan ? (
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-secondary)' }}>loading plan…</span>
          ) : hasPlan ? (
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-secondary)' }}>
              animating recommended setpoints · drag to orbit
            </span>
          ) : (
            <span className="mono" style={{ fontSize: 10, color: 'var(--amber)' }}>
              no plan selected — showing nominal envelope
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
