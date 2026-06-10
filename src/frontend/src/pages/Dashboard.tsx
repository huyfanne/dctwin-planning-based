import { useEffect, useState } from 'react';
import { listPlans, getPlan, type PlanDetail, type PlanSummary } from '../api';

interface Props {
  onReview: (id: string) => void;
}

const SETPOINT_LABELS: Record<string, string> = {
  crah_supply_air_temperature_c:        'CRAH Supply Air Temp',
  crah_supply_air_mass_flow_rate_kg_s:  'CRAH Air Mass Flow',
  chilled_water_supply_temperature_c:   'Chilled Water Supply Temp',
};

const KPI_LABELS: Record<string, { label: string; unit: string; accent?: string }> = {
  total_hvac_energy_kwh:           { label: 'Total HVAC Energy',    unit: 'kWh' },
  pue_mean:                        { label: 'PUE Mean',              unit: '' },
  inlet_temp_max_c:                { label: 'Peak Inlet Temp',       unit: '°C' },
  inlet_violation_steps:           { label: 'Inlet Violations',      unit: 'steps' },
  energy_reduction_vs_baseline_pct:{ label: 'Energy Reduction',      unit: '%', accent: 'green' },
};

function statusClass(s: string) {
  if (s.includes('pending')) return 'badge-pending';
  if (s === 'approved')      return 'badge-approved';
  if (s === 'rejected')      return 'badge-rejected';
  if (s === 'deployed')      return 'badge-deployed';
  return 'badge-running';
}

export default function Dashboard({ onReview }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [latest, setLatest]   = useState<(PlanSummary & { detail?: PlanDetail }) | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const plans = await listPlans();
        if (plans.length === 0) {
          setLatest(null);
          setLoading(false);
          return;
        }
        // Sort by week_start descending, pick most recent
        const sorted = [...plans].sort((a, b) => b.week_start.localeCompare(a.week_start));
        const top = sorted[0];
        let detail: PlanDetail | undefined;
        try { detail = await getPlan(top.plan_id); } catch {}
        setLatest({ ...top, detail });
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to load plans');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-3 mt-6" style={{ padding: '48px 0' }}>
        <div className="spinner" />
        <span className="text-dim" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.1em', fontSize: 13 }}>
          LOADING PLAN DATA…
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mt-4">
        <div className="error-msg">{error}</div>
      </div>
    );
  }

  if (!latest) {
    return (
      <div className="animate-in">
        <div className="section-header">
          <h2 className="section-title">
            <span className="title-accent">↗</span> Dashboard
          </h2>
        </div>
        <div className="card" style={{ maxWidth: 540 }}>
          <div className="empty-state">
            <div className="empty-state-icon">◎</div>
            <div className="empty-state-text">No plans found</div>
            <p className="text-dim text-sm">Create a new optimization plan to begin.</p>
          </div>
        </div>
      </div>
    );
  }

  const rec = latest.detail?.recommendation;
  const sp  = rec?.setpoints ?? {};
  const kpi = rec?.predicted_kpis ?? {};

  return (
    <div className="animate-in">
      {/* Header */}
      <div className="section-header">
        <div>
          <h2 className="section-title">
            <span className="title-accent">↗</span> Dashboard
          </h2>
          <p className="text-dim text-sm mt-2" style={{ fontFamily: 'var(--font-data)' }}>
            Latest plan — week of <strong style={{ color: 'var(--text-primary)' }}>{latest.week_start}</strong>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`badge ${statusClass(latest.status)}`}>{latest.status}</span>
          <button className="btn btn-ghost" onClick={() => onReview(latest.plan_id)}>
            Open in Review →
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>

        {/* Setpoints card */}
        <div className="card card-glow bracket-card animate-in animate-in-1">
          <div className="card-header">
            <span className="card-title">Setpoints</span>
            <span className="text-xs text-dim mono">CRAH / Chiller targets</span>
          </div>
          <div className="card-body">
            {Object.keys(SETPOINT_LABELS).length === 0 || Object.keys(sp).length === 0 ? (
              <p className="text-dim text-sm">No setpoints available.</p>
            ) : (
              Object.entries(SETPOINT_LABELS).map(([key, lbl]) => (
                <div key={key} className="setpoint-row">
                  <span className="setpoint-name">{lbl}</span>
                  <span className="mono" style={{
                    fontSize: 18, fontWeight: 600, color: 'var(--cyan)',
                    fontFamily: 'var(--font-data)',
                  }}>
                    {sp[key] != null ? Number(sp[key]).toFixed(2) : '—'}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* KPIs card */}
        <div className="card bracket-card animate-in animate-in-2">
          <div className="card-header">
            <span className="card-title">Predicted KPIs</span>
            <span className="live-dot">AI Forecast</span>
          </div>
          <div className="card-body">
            <div className="metric-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
              {Object.entries(KPI_LABELS).map(([key, cfg]) => {
                const val = kpi[key];
                const isReduction = key === 'energy_reduction_vs_baseline_pct';
                return (
                  <div key={key} className="metric-tile animate-in" style={{ animationDelay: `${0.05 * Object.keys(KPI_LABELS).indexOf(key)}s` }}>
                    <div className="metric-label">{cfg.label}</div>
                    <div>
                      <span className="metric-value" style={{
                        fontSize: 22,
                        color: isReduction && val != null && (val as number) > 0
                          ? 'var(--green)'
                          : key === 'inlet_violation_steps' && val != null && (val as number) > 0
                          ? 'var(--amber)'
                          : undefined
                      }}>
                        {val != null ? Number(val).toFixed(2) : '—'}
                      </span>
                      {cfg.unit && <span className="metric-unit">{cfg.unit}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Summary strip */}
        <div className="card animate-in animate-in-3" style={{ gridColumn: '1 / -1' }}>
          <div className="card-body" style={{ display: 'flex', gap: 32, flexWrap: 'wrap', alignItems: 'center' }}>
            <div>
              <div className="metric-label">Plan ID</div>
              <div className="mono" style={{ fontSize: 13, color: 'var(--text-primary)', marginTop: 3 }}>
                {latest.plan_id}
              </div>
            </div>
            <div>
              <div className="metric-label">Energy (kWh)</div>
              <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', marginTop: 3 }}>
                {latest.energy_kwh != null ? Number(latest.energy_kwh).toFixed(1) : '—'}
              </div>
            </div>
            <div>
              <div className="metric-label">Reduction vs Baseline</div>
              <div className="mono" style={{
                fontSize: 18,
                fontWeight: 600,
                color: latest.reduction_pct != null && latest.reduction_pct > 0 ? 'var(--green)' : 'var(--text-primary)',
                marginTop: 3,
              }}
              title={latest.reduction_pct == null
                ? 'No baseline recorded for this plan (created before the baseline feature) — re-run the plan to compute the reduction.'
                : undefined}>
                {latest.reduction_pct != null ? `${latest.reduction_pct > 0 ? '−' : ''}${Math.abs(latest.reduction_pct).toFixed(1)}%` : '—'}
              </div>
            </div>
            <div style={{ marginLeft: 'auto' }}>
              <span className={`badge ${statusClass(latest.status)}`} style={{ fontSize: 13, padding: '5px 14px' }}>
                {latest.status}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
