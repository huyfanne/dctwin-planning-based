import { useState, useEffect, useRef } from 'react';
import { createPlan, planStreamUrl, getWeather, type Progress } from '../api';

interface Props {
  onDone: (planId: string) => void;
}

export default function NewPlan({ onDone }: Props) {
  const [weekStart, setWeekStart]   = useState('');
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

  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    getWeather().then(w => {
      setCoverage(w.label);
      if (w.suggested_week_start) setWeekStart(prev => prev || w.suggested_week_start!);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!planId || done || error) return;
    const es = new EventSource(planStreamUrl(planId));
    esRef.current = es;
    es.onmessage = (e) => {
      const frame = JSON.parse(e.data) as { progress: Progress; status: string };
      if (frame.progress) setProgress(frame.progress);
      setStatus(frame.status);
      if (frame.status === 'failed') {
        setError(frame.progress?.error ?? 'Plan run failed on the server — see the backend log (the backend may lack Docker access for EnergyPlus).');
        es.close();
      } else if (frame.status && !['queued', 'running', 'deploying'].includes(frame.status)) {
        setDone(true);
        es.close();
      }
    };
    es.onerror = () => {
      es.close();
      setError('Lost connection to the progress stream. The backend may have stopped — see the backend log.');
    };
    return () => { es.close(); };
  }, [planId, done, error]);

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
              {error
                ? <span className="badge" style={{ color: 'var(--amber, #f5a623)', borderColor: 'var(--amber, #f5a623)' }}>Failed</span>
                : done
                ? <span className="badge badge-approved">Complete</span>
                : <span className="live-dot">Running</span>
              }
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

              {!done && !error && (
                <p className="text-dim text-sm" style={{ fontFamily: 'var(--font-data)', textAlign: 'center', marginTop: 4 }}>
                  Status: {status} · live stream
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
