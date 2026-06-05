import { useEffect, useState } from 'react';
import { listPlans, type PlanSummary } from '../api';

interface Props {
  onReview: (id: string) => void;
}

function statusClass(s: string) {
  if (s.includes('pending')) return 'badge-pending';
  if (s === 'approved')      return 'badge-approved';
  if (s === 'rejected')      return 'badge-rejected';
  if (s === 'deployed')      return 'badge-deployed';
  return 'badge-running';
}

type SortKey = 'week_start' | 'status' | 'energy_kwh' | 'reduction_pct';
type SortDir = 'asc' | 'desc';

export default function History({ onReview }: Props) {
  const [plans, setPlans]     = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('week_start');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [filter, setFilter]   = useState('');

  useEffect(() => {
    listPlans()
      .then(p => setPlans(p))
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load history'))
      .finally(() => setLoading(false));
  }, []);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  const filtered = plans.filter(p => {
    if (!filter) return true;
    const q = filter.toLowerCase();
    return (
      p.plan_id.toLowerCase().includes(q) ||
      p.week_start.includes(q) ||
      p.status.includes(q)
    );
  });

  const sorted = [...filtered].sort((a, b) => {
    let va: string | number | null = a[sortKey];
    let vb: string | number | null = b[sortKey];
    if (va == null) va = sortDir === 'asc' ? Infinity : -Infinity;
    if (vb == null) vb = sortDir === 'asc' ? Infinity : -Infinity;
    if (typeof va === 'string' && typeof vb === 'string') {
      return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
    }
    return sortDir === 'asc' ? (va as number) - (vb as number) : (vb as number) - (va as number);
  });

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <span style={{ opacity: 0.3 }}>↕</span>;
    return <span style={{ color: 'var(--cyan)' }}>{sortDir === 'asc' ? '↑' : '↓'}</span>;
  }

  return (
    <div className="animate-in">
      <div className="section-header">
        <h2 className="section-title">
          <span className="title-accent">≡</span> Plan History
        </h2>
        <div className="flex items-center gap-3">
          <input
            type="search"
            className="field-input"
            placeholder="Filter plans…"
            style={{ width: 220 }}
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
          <span className="text-dim text-xs" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            {sorted.length} record{sorted.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-3" style={{ padding: '32px 0' }}>
          <div className="spinner" />
          <span className="text-dim" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.1em', fontSize: 13 }}>
            LOADING HISTORY…
          </span>
        </div>
      )}

      {error && <div className="error-msg mt-3">{error}</div>}

      {!loading && !error && (
        <div className="card bracket-card animate-in animate-in-1">
          {sorted.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">≡</div>
              <div className="empty-state-text">
                {filter ? 'No plans match your filter' : 'No plans found'}
              </div>
              {!filter && (
                <p className="text-dim text-sm">Create a plan to see history.</p>
              )}
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th
                      style={{ cursor: 'pointer', userSelect: 'none' }}
                      onClick={() => toggleSort('week_start')}
                    >
                      Week Start <SortIcon col="week_start" />
                    </th>
                    <th>Plan ID</th>
                    <th
                      style={{ cursor: 'pointer', userSelect: 'none' }}
                      onClick={() => toggleSort('status')}
                    >
                      Status <SortIcon col="status" />
                    </th>
                    <th
                      style={{ cursor: 'pointer', userSelect: 'none', textAlign: 'right' }}
                      onClick={() => toggleSort('energy_kwh')}
                    >
                      Energy (kWh) <SortIcon col="energy_kwh" />
                    </th>
                    <th
                      style={{ cursor: 'pointer', userSelect: 'none', textAlign: 'right' }}
                      onClick={() => toggleSort('reduction_pct')}
                    >
                      Reduction % <SortIcon col="reduction_pct" />
                    </th>
                    <th style={{ textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((p, i) => (
                    <tr key={p.plan_id} className="animate-in" style={{ animationDelay: `${0.04 * i}s` }}>
                      <td style={{ fontFamily: 'var(--font-data)', color: 'var(--text-primary)' }}>
                        {p.week_start}
                      </td>
                      <td style={{ fontFamily: 'var(--font-data)', fontSize: 11, color: 'var(--text-secondary)' }}>
                        {p.plan_id}
                      </td>
                      <td>
                        <span className={`badge ${statusClass(p.status)}`}>{p.status}</span>
                      </td>
                      <td style={{ textAlign: 'right', color: 'var(--text-primary)' }}>
                        {p.energy_kwh != null ? Number(p.energy_kwh).toFixed(1) : '—'}
                      </td>
                      <td style={{
                        textAlign: 'right',
                        color: p.reduction_pct != null && p.reduction_pct > 0 ? 'var(--green)' : 'var(--text-primary)',
                        fontWeight: p.reduction_pct != null && p.reduction_pct > 0 ? 600 : 400,
                      }}>
                        {p.reduction_pct != null
                          ? `${p.reduction_pct > 0 ? '−' : '+'}${Math.abs(p.reduction_pct).toFixed(1)}%`
                          : '—'}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="btn btn-ghost"
                          style={{ fontSize: 11, padding: '4px 12px' }}
                          onClick={() => onReview(p.plan_id)}
                        >
                          Review →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
