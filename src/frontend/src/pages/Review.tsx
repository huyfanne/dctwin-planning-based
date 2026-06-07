import { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Cell,
  LineChart, Line, ReferenceLine, Legend,
} from 'recharts';
import {
  listPlans, getPlan, approvePlan, rejectPlan, editSetpoints, deployPlan, getCalibration,
  getTrajectory,
  type PlanSummary, type PlanDetail, type CalibrationState, type Trajectory,
} from '../api';

interface Props {
  planId?: string;
}

const KPI_META: { key: string; label: string; unit: string }[] = [
  { key: 'total_hvac_energy_kwh',            label: 'Total HVAC Energy',   unit: 'kWh' },
  { key: 'pue_mean',                          label: 'PUE Mean',             unit: '' },
  { key: 'inlet_temp_max_c',                  label: 'Peak Inlet Temp',      unit: '°C' },
  { key: 'inlet_violation_steps',             label: 'Inlet Violations',     unit: 'steps' },
  { key: 'energy_reduction_vs_baseline_pct',  label: 'Energy Reduction',     unit: '%' },
];

const SETPOINT_LABELS: Record<string, string> = {
  crah_supply_air_temperature_c:       'CRAH Supply Air Temp (°C)',
  crah_supply_air_mass_flow_rate_kg_s: 'CRAH Air Mass Flow (kg/s)',
  chilled_water_supply_temperature_c:  'Chilled Water Supply Temp (°C)',
};

// Pseudo-baseline values for comparison (representative defaults)
const BASELINE_KPIS: Record<string, number> = {
  total_hvac_energy_kwh:            450,
  pue_mean:                         1.6,
  inlet_temp_max_c:                 27,
  inlet_violation_steps:            12,
  energy_reduction_vs_baseline_pct: 0,
};

function statusClass(s: string) {
  if (s.includes('pending')) return 'badge-pending';
  if (s === 'approved')      return 'badge-approved';
  if (s === 'rejected')      return 'badge-rejected';
  if (s === 'deployed')      return 'badge-deployed';
  if (s === 'deploy_failed') return 'badge-rejected';
  return 'badge-running';
}

// Custom tooltip for Recharts
function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload) return null;
  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border-bright)',
      borderRadius: 6,
      padding: '10px 14px',
      fontFamily: 'var(--font-data)',
      fontSize: 12,
    }}>
      <div style={{ color: 'var(--text-label)', marginBottom: 6, fontFamily: 'var(--font-display)', letterSpacing: '0.06em', fontSize: 11, textTransform: 'uppercase' }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color, marginTop: 2 }}>
          {p.name}: {Number(p.value).toFixed(3)}
        </div>
      ))}
    </div>
  );
}

export default function Review({ planId: initialPlanId }: Props) {
  const [plans, setPlans]         = useState<PlanSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>(initialPlanId ?? '');
  const [detail, setDetail]       = useState<PlanDetail | null>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [spDraft, setSpDraft]     = useState<Record<string, string>>({});
  const [saving, setSaving]       = useState(false);
  const [acting, setActing]       = useState(false);
  const [cal, setCal]             = useState<CalibrationState | null>(null);
  const [traj, setTraj]           = useState<Trajectory | null>(null);

  // Load calibration state on mount
  useEffect(() => {
    getCalibration()
      .then(c => setCal(c))
      .catch(() => {});
  }, []);

  // Load plan list on mount
  useEffect(() => {
    listPlans()
      .then(p => {
        const sorted = [...p].sort((a, b) => b.week_start.localeCompare(a.week_start));
        setPlans(sorted);
        if (!initialPlanId && sorted.length > 0) setSelectedId(sorted[0].plan_id);
      })
      .catch(() => {});
  }, [initialPlanId]);

  // Load plan detail when selectedId changes
  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    setError(null);
    setActionMsg(null);
    getPlan(selectedId)
      .then(d => {
        setDetail(d);
        // Initialise setpoint draft
        const sp = d.recommendation?.setpoints ?? {};
        setSpDraft(Object.fromEntries(Object.entries(sp).map(([k, v]) => [k, String(v)])));
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load plan'))
      .finally(() => setLoading(false));
    getTrajectory(selectedId).then(setTraj).catch(() => setTraj(null));
  }, [selectedId]);

  async function handleApprove() {
    if (!selectedId) return;
    setActing(true); setActionMsg(null); setError(null);
    try {
      await approvePlan(selectedId);
      setActionMsg('Plan approved.');
      const d = await getPlan(selectedId);
      setDetail(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Approve failed');
    } finally { setActing(false); }
  }

  async function handleReject() {
    if (!selectedId) return;
    setActing(true); setActionMsg(null); setError(null);
    try {
      await rejectPlan(selectedId);
      setActionMsg('Plan rejected.');
      const d = await getPlan(selectedId);
      setDetail(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Reject failed');
    } finally { setActing(false); }
  }

  async function handleDeploy() {
    if (!selectedId) return;
    setActing(true); setActionMsg(null); setError(null);
    try {
      await deployPlan(selectedId);
      setActionMsg('Deployment triggered.');
      const d = await getPlan(selectedId);
      setDetail(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Deploy failed');
    } finally { setActing(false); }
  }

  async function handleSaveSetpoints() {
    if (!selectedId) return;
    setSaving(true); setError(null);
    try {
      const parsed: Record<string, number> = {};
      for (const [k, v] of Object.entries(spDraft)) {
        const n = parseFloat(v);
        if (isNaN(n)) { setError(`Invalid value for ${k}`); setSaving(false); return; }
        parsed[k] = n;
      }
      await editSetpoints(selectedId, parsed);
      setActionMsg('Setpoints updated.');
      const d = await getPlan(selectedId);
      setDetail(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save setpoints failed');
    } finally { setSaving(false); }
  }

  const rec    = detail?.recommendation;
  const kpi    = rec?.predicted_kpis ?? {};
  const sp     = rec?.setpoints ?? {};
  const robust = rec?.robust;
  const status = detail?.status ?? '';
  const canEdit    = status !== 'rejected' && status !== 'deployed';
  const canAct     = status === 'pending_approval';
  const canDeploy  = status === 'approved' || status === 'deploy_failed';
  const isDeploying = status === 'deploying';

  // Build chart data
  const chartData = KPI_META.filter(m => m.key !== 'energy_reduction_vs_baseline_pct').map(m => ({
    name: m.label.replace(' ', '\n'),
    shortName: m.label.split(' ').slice(0, 2).join(' '),
    Predicted: kpi[m.key] != null ? Number(kpi[m.key]) : null,
    Baseline:  BASELINE_KPIS[m.key] ?? null,
  }));

  return (
    <div className="animate-in">
      <div className="section-header">
        <h2 className="section-title">
          <span className="title-accent">⊙</span> Plan Review
        </h2>

        {/* Plan selector */}
        <div className="flex items-center gap-3">
          <label className="field-label" style={{ whiteSpace: 'nowrap' }}>Select Plan</label>
          <select
            className="field-input"
            style={{ width: 280 }}
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
          >
            {plans.length === 0 && <option value="">No plans</option>}
            {plans.map(p => (
              <option key={p.plan_id} value={p.plan_id}>
                {p.week_start} — {p.plan_id.slice(0, 8)} ({p.status})
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-3" style={{ padding: '32px 0' }}>
          <div className="spinner" />
          <span className="text-dim" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.1em', fontSize: 13 }}>
            LOADING PLAN…
          </span>
        </div>
      )}

      {!loading && !detail && !error && (
        <div className="card" style={{ maxWidth: 480 }}>
          <div className="empty-state">
            <div className="empty-state-icon">⊙</div>
            <div className="empty-state-text">Select a plan to review</div>
          </div>
        </div>
      )}

      {error && <div className="error-msg mt-3">{error}</div>}

      {actionMsg && (
        <div style={{
          background: 'var(--green-dim)', border: '1px solid rgba(16,185,129,0.3)',
          borderRadius: 6, padding: '10px 16px', color: 'var(--green)',
          fontFamily: 'var(--font-data)', fontSize: 12, marginBottom: 16,
        }}>
          {actionMsg}
        </div>
      )}

      {!loading && detail && (
        <div style={{ display: 'grid', gap: 16 }}>

          {/* Status row */}
          <div className="card animate-in animate-in-1">
            <div className="card-body" style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
              <div>
                <div className="metric-label">Plan ID</div>
                <div className="mono" style={{ fontSize: 12, color: 'var(--text-primary)', marginTop: 3 }}>{detail.plan_id}</div>
              </div>
              <div>
                <div className="metric-label">Status</div>
                <div style={{ marginTop: 5 }}>
                  <span className={`badge ${statusClass(status)}`}>{status}</span>
                </div>
              </div>
              {canAct && (
                <div className="flex gap-2" style={{ marginLeft: 'auto' }}>
                  <button className="btn btn-success" onClick={handleApprove} disabled={acting}>
                    {acting ? <span className="spinner" style={{ width: 14, height: 14 }} /> : '✓'} Approve
                  </button>
                  <button className="btn btn-danger" onClick={handleReject} disabled={acting}>
                    {acting ? <span className="spinner" style={{ width: 14, height: 14 }} /> : '✕'} Reject
                  </button>
                </div>
              )}
              {(canDeploy || isDeploying) && (
                <div className="flex gap-2" style={{ marginLeft: 'auto' }}>
                  <button
                    className="btn btn-primary"
                    onClick={handleDeploy}
                    disabled={acting || isDeploying}
                  >
                    {(acting || isDeploying) ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Deploying…</> : status === 'deploy_failed' ? '▶ Retry Deploy' : '▶ Deploy'}
                  </button>
                </div>
              )}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
            {/* KPI table */}
            <div className="card bracket-card animate-in animate-in-2">
              <div className="card-header">
                <span className="card-title">KPI Comparison</span>
                <span className="text-xs text-dim">Predicted vs Baseline</span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Predicted</th>
                    <th>Baseline</th>
                    <th>Delta</th>
                  </tr>
                </thead>
                <tbody>
                  {KPI_META.map(m => {
                    const pred = kpi[m.key];
                    const base = BASELINE_KPIS[m.key];
                    const delta = pred != null && base != null ? Number(pred) - base : null;
                    const lower_is_better = m.key !== 'energy_reduction_vs_baseline_pct';
                    const deltaColor = delta == null
                      ? 'var(--text-muted)'
                      : (lower_is_better ? delta < 0 : delta > 0)
                      ? 'var(--green)' : 'var(--red)';
                    return (
                      <tr key={m.key}>
                        <td className="label-cell">{m.label}</td>
                        <td style={{ color: 'var(--cyan)' }}>
                          {pred != null ? `${Number(pred).toFixed(3)}${m.unit}` : '—'}
                        </td>
                        <td style={{ color: 'var(--text-secondary)' }}>
                          {`${base}${m.unit}`}
                        </td>
                        <td style={{ color: deltaColor, fontWeight: 600 }}>
                          {delta != null ? `${delta > 0 ? '+' : ''}${delta.toFixed(3)}` : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Setpoint editor */}
            <div className="card bracket-card animate-in animate-in-3">
              <div className="card-header">
                <span className="card-title">Setpoints</span>
                {canEdit && <span className="text-xs text-dim">Expert edit</span>}
              </div>
              <div className="card-body">
                {Object.keys(sp).length === 0 ? (
                  <p className="text-dim text-sm">No setpoints available.</p>
                ) : (
                  <div className="flex-col gap-0">
                    {Object.entries(SETPOINT_LABELS).map(([key, lbl]) => {
                      if (!(key in sp) && !(key in spDraft)) return null;
                      return (
                        <div key={key} className="setpoint-row">
                          <span className="setpoint-name">{lbl}</span>
                          {canEdit ? (
                            <input
                              type="number"
                              step="0.1"
                              className="setpoint-input"
                              value={spDraft[key] ?? ''}
                              onChange={e => setSpDraft(prev => ({ ...prev, [key]: e.target.value }))}
                            />
                          ) : (
                            <span className="mono" style={{ fontSize: 16, fontWeight: 600, color: 'var(--cyan)' }}>
                              {sp[key] != null ? Number(sp[key]).toFixed(2) : '—'}
                            </span>
                          )}
                        </div>
                      );
                    })}
                    {canEdit && (
                      <div className="mt-3">
                        <button
                          className="btn btn-ghost"
                          style={{ width: '100%', justifyContent: 'center' }}
                          onClick={handleSaveSetpoints}
                          disabled={saving}
                        >
                          {saving ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Saving…</> : '↑ Save Setpoints'}
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Confidence Bands */}
          {robust?.confidence_bands && (
            <div className="card bracket-card animate-in animate-in-4">
              <div className="card-header">
                <span className="card-title">Confidence Bands</span>
                <span className="text-xs text-dim">
                  {robust.n_scenarios} scenarios · {robust.robust_feasible ? '✓ robust-feasible' : '⚠ not robust-feasible'}
                </span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>KPI</th>
                    <th>p50</th>
                    <th>p90</th>
                    <th>max</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(robust.confidence_bands).map(([key, band]) => (
                    <tr key={key}>
                      <td className="label-cell">{key}</td>
                      <td style={{ color: 'var(--cyan)' }}>
                        {band?.p50 != null ? band.p50.toFixed(1) : '—'}
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {band?.p90 != null ? band.p90.toFixed(1) : '—'}
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {band?.max != null ? band.max.toFixed(1) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Realized vs Predicted */}
          {detail.realized && (
            <div className="card bracket-card animate-in animate-in-4">
              <div className="card-header">
                <span className="card-title">Realized vs Predicted</span>
                <span className="text-xs text-dim">Post-deployment actuals</span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Realized</th>
                    <th>Predicted</th>
                    <th>Delta</th>
                  </tr>
                </thead>
                <tbody>
                  {KPI_META.filter(m => m.key !== 'energy_reduction_vs_baseline_pct').map(m => {
                    const realized = detail.realized ? (detail.realized as Record<string, number | undefined>)[m.key] : undefined;
                    const predicted = kpi[m.key];
                    const delta = realized != null && predicted != null ? Number(realized) - Number(predicted) : null;
                    const lower_is_better = true;
                    const deltaColor = delta == null
                      ? 'var(--text-muted)'
                      : (lower_is_better ? delta <= 0 : delta >= 0)
                      ? 'var(--green)' : 'var(--red)';
                    return (
                      <tr key={m.key}>
                        <td className="label-cell">{m.label}</td>
                        <td style={{ color: 'var(--cyan)' }}>
                          {realized != null ? `${Number(realized).toFixed(3)}${m.unit}` : '—'}
                        </td>
                        <td style={{ color: 'var(--text-secondary)' }}>
                          {predicted != null ? `${Number(predicted).toFixed(3)}${m.unit}` : '—'}
                        </td>
                        <td style={{ color: deltaColor, fontWeight: 600 }}>
                          {delta != null ? `${delta > 0 ? '+' : ''}${delta.toFixed(3)}` : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Twin Calibration */}
          {cal && (
            <div className="card bracket-card animate-in animate-in-4">
              <div className="card-header">
                <span className="card-title">Twin Calibration</span>
                <span className="text-xs text-dim">{cal.version}</span>
              </div>
              <div className="card-body">
                <div className="metric-label" style={{ marginBottom: 8 }}>
                  {cal.n_weeks} weeks of realized history
                </div>
                {cal.n_weeks === 0 ? (
                  <p className="text-dim text-sm">No calibration yet — run more deployed weeks to accumulate data.</p>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Bias</th>
                        <th>σ</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td className="label-cell">Peak Inlet Temp</td>
                        <td style={{ color: 'var(--cyan)' }}>
                          {cal.bias.inlet_temp_max_c?.toFixed(2) ?? '—'} °C
                        </td>
                        <td style={{ color: 'var(--text-secondary)' }}>
                          {cal.sigma.inlet_temp_max_c?.toFixed(2) ?? '—'} °C
                        </td>
                      </tr>
                      <tr>
                        <td className="label-cell">Total HVAC Energy</td>
                        <td style={{ color: 'var(--cyan)' }}>
                          {cal.bias.total_hvac_energy_kwh?.toFixed(1) ?? '—'} kWh
                        </td>
                        <td style={{ color: 'var(--text-secondary)' }}>
                          {cal.sigma.total_hvac_energy_kwh?.toFixed(1) ?? '—'} kWh
                        </td>
                      </tr>
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

          {/* Bar chart */}
          <div className="card animate-in animate-in-4">
            <div className="card-header">
              <span className="card-title">KPI Chart — Predicted vs Baseline</span>
            </div>
            <div className="card-body">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chartData} barGap={4} barCategoryGap="28%">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-dim)" vertical={false} />
                  <XAxis
                    dataKey="shortName"
                    tick={{ fill: 'var(--text-secondary)', fontFamily: 'var(--font-display)', fontSize: 11, letterSpacing: '0.06em' }}
                    axisLine={{ stroke: 'var(--border-bright)' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: 'var(--text-muted)', fontFamily: 'var(--font-data)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    width={55}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="Predicted" name="Predicted" radius={[3, 3, 0, 0]}>
                    {chartData.map((_, i) => (
                      <Cell key={i} fill="rgba(0,200,255,0.7)" />
                    ))}
                  </Bar>
                  <Bar dataKey="Baseline" name="Baseline" radius={[3, 3, 0, 0]}>
                    {chartData.map((_, i) => (
                      <Cell key={i} fill="rgba(100,116,139,0.45)" />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="flex gap-4 mt-2" style={{ justifyContent: 'center' }}>
                <div className="flex items-center gap-2">
                  <div style={{ width: 12, height: 12, borderRadius: 2, background: 'rgba(0,200,255,0.7)' }} />
                  <span className="text-xs text-label" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.08em' }}>Predicted</span>
                </div>
                <div className="flex items-center gap-2">
                  <div style={{ width: 12, height: 12, borderRadius: 2, background: 'rgba(100,116,139,0.45)' }} />
                  <span className="text-xs text-label" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.08em' }}>Baseline</span>
                </div>
              </div>
            </div>
          </div>

          {traj && (traj.nominal.length > 0 || traj.worst.length > 0) && (
            <div className="card animate-in animate-in-4">
              <div className="card-header">
                <span className="card-title">Inlet Trajectory</span>
                <span className="text-xs text-dim">nominal vs worst-case scenario · 26 °C cap</span>
              </div>
              <div className="card-body">
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={(traj.nominal.length ? traj.nominal : traj.worst).map((r, i) => ({
                    step: r.step,
                    nominal: traj.nominal[i]?.inlet_temp_max_c ?? null,
                    worst: traj.worst[i]?.inlet_temp_max_c ?? null,
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-dim)" vertical={false} />
                    <XAxis dataKey="step" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} />
                    <YAxis domain={[20, 32]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} width={40} />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine y={26} stroke="var(--red)" strokeDasharray="4 4" label="26°C cap" />
                    <Line type="monotone" dataKey="nominal" name="Nominal" stroke="rgba(0,200,255,0.9)" dot={false} />
                    <Line type="monotone" dataKey="worst" name="Worst scenario" stroke="rgba(239,68,68,0.9)" dot={false} />
                    <Legend />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  );
}
