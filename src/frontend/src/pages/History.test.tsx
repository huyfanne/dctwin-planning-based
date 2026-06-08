import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import History from './History';

vi.mock('../api', () => ({
  listPlans: vi.fn(),
  cancelPlan: vi.fn(),
}));

import { listPlans, cancelPlan } from '../api';

const PLANS = [
  { plan_id: 'plan-001', week_start: '2026-06-02', status: 'approved',   energy_kwh: 388.5, reduction_pct: 8.2 },
  { plan_id: 'plan-002', week_start: '2026-05-26', status: 'deployed',   energy_kwh: 402.1, reduction_pct: 4.7 },
  { plan_id: 'plan-003', week_start: '2026-05-19', status: 'rejected',   energy_kwh: null,  reduction_pct: null },
  { plan_id: 'plan-004', week_start: '2026-06-09', status: 'pending_approval', energy_kwh: 375.0, reduction_pct: 11.5 },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('History', () => {
  it('renders loading state initially', () => {
    (listPlans as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<History onReview={() => {}} />);
    expect(screen.getByText(/loading history/i)).toBeInTheDocument();
  });

  it('renders table rows for each plan', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue(PLANS);
    render(<History onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText('plan-001')).toBeInTheDocument();
      expect(screen.getByText('plan-002')).toBeInTheDocument();
      expect(screen.getByText('2026-06-02')).toBeInTheDocument();
    });
  });

  it('renders status badges', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue(PLANS);
    render(<History onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText('approved')).toBeInTheDocument();
      expect(screen.getByText('deployed')).toBeInTheDocument();
      expect(screen.getByText('rejected')).toBeInTheDocument();
    });
  });

  it('calls onReview with plan_id when Review button clicked', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([PLANS[0]]);
    const onReview = vi.fn();
    render(<History onReview={onReview} />);
    await waitFor(() => screen.getByText(/review →/i));
    fireEvent.click(screen.getByText(/review →/i));
    expect(onReview).toHaveBeenCalledWith('plan-001');
  });

  it('filters plans by search input', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue(PLANS);
    render(<History onReview={() => {}} />);
    await waitFor(() => screen.getByText('plan-001'));
    fireEvent.change(screen.getByPlaceholderText(/filter plans/i), { target: { value: 'deployed' } });
    await waitFor(() => {
      expect(screen.queryByText('plan-001')).not.toBeInTheDocument();
      expect(screen.getByText('plan-002')).toBeInTheDocument();
    });
  });

  it('shows empty state when no plans', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    render(<History onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/no plans found/i)).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Unauthorized'));
    render(<History onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/unauthorized/i)).toBeInTheDocument();
    });
  });

  it('shows record count', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue(PLANS);
    render(<History onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/4 records/i)).toBeInTheDocument();
    });
  });

  it('renders the predicted-vs-realized trend', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([
      { plan_id: 'p1', week_start: '2026-06-02', status: 'deployed', energy_kwh: 100, reduction_pct: 10, realized_energy_kwh: 120 },
    ]);
    render(<History onReview={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Predicted vs Realized/i)).toBeInTheDocument());
  });

  it('shows Cancel on a running plan and calls cancelPlan', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([
      { plan_id: 'r1', week_start: '2024-11-11', status: 'running', energy_kwh: null, reduction_pct: null },
    ]);
    render(<History onReview={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: /cancel/i }));
    await waitFor(() => expect(cancelPlan).toHaveBeenCalledWith('r1'));
  });
});
