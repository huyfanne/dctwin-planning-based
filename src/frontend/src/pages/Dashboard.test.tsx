import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Dashboard from './Dashboard';

vi.mock('../api', () => ({
  listPlans: vi.fn(),
  getPlan: vi.fn(),
}));

import { listPlans, getPlan } from '../api';

const mockPlan = {
  plan_id: 'plan-abc-123',
  week_start: '2026-06-02',
  status: 'pending_approval',
  energy_kwh: 388.5,
  reduction_pct: 8.2,
};

const mockDetail = {
  plan_id: 'plan-abc-123',
  status: 'pending_approval',
  recommendation: {
    status: 'ok',
    setpoints: {
      crah_supply_air_temperature_c: 18.5,
      crah_supply_air_mass_flow_rate_kg_s: 4.2,
      chilled_water_supply_temperature_c: 10.0,
    },
    predicted_kpis: {
      total_hvac_energy_kwh: 388.5,
      pue_mean: 1.42,
      inlet_temp_max_c: 25.3,
      inlet_violation_steps: 0,
      energy_reduction_vs_baseline_pct: 8.2,
    },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Dashboard', () => {
  it('renders loading state initially', () => {
    (listPlans as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<Dashboard onReview={() => {}} />);
    expect(screen.getByText(/loading plan data/i)).toBeInTheDocument();
  });

  it('renders empty state when no plans exist', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    render(<Dashboard onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/no plans found/i)).toBeInTheDocument();
    });
  });

  it('renders latest plan with setpoints and KPIs', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([mockPlan]);
    (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(mockDetail);
    render(<Dashboard onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/week of/i)).toBeInTheDocument();
      expect(screen.getByText('2026-06-02')).toBeInTheDocument();
      // Multiple badges with same status is expected; use getAllByText
      expect(screen.getAllByText('pending_approval').length).toBeGreaterThan(0);
      // Setpoints card
      expect(screen.getByText('CRAH Supply Air Temp')).toBeInTheDocument();
      // KPI labels
      expect(screen.getByText('Total HVAC Energy')).toBeInTheDocument();
      expect(screen.getByText('PUE Mean')).toBeInTheDocument();
    });
  });

  it('renders Open in Review button', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([mockPlan]);
    (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(mockDetail);
    const onReview = vi.fn();
    render(<Dashboard onReview={onReview} />);
    await waitFor(() => {
      const btn = screen.getByText(/open in review/i);
      expect(btn).toBeInTheDocument();
    });
  });

  it('renders error state on API failure', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'));
    render(<Dashboard onReview={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });
});
