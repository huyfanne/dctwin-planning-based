import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Review from './Review';

vi.mock('../api', () => ({
  listPlans: vi.fn(),
  getPlan: vi.fn(),
  approvePlan: vi.fn(),
  rejectPlan: vi.fn(),
  editSetpoints: vi.fn(),
}));

import { listPlans, getPlan, approvePlan, rejectPlan } from '../api';

const PLAN_SUMMARY = {
  plan_id: 'plan-rev-1',
  week_start: '2026-06-02',
  status: 'pending_approval',
  energy_kwh: 388.5,
  reduction_pct: 8.2,
};

const PLAN_DETAIL = {
  plan_id: 'plan-rev-1',
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
  (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([PLAN_SUMMARY]);
  (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(PLAN_DETAIL);
});

describe('Review', () => {
  it('renders the plan selector and loads plan detail', async () => {
    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText(/kpi comparison/i)).toBeInTheDocument();
      // "Setpoints" appears as card title and also in "Save Setpoints" button
      expect(screen.getAllByText(/setpoints/i).length).toBeGreaterThan(0);
      expect(screen.getByText('pending_approval')).toBeInTheDocument();
    });
  });

  it('renders KPI table with metric rows', async () => {
    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText('Total HVAC Energy')).toBeInTheDocument();
      expect(screen.getByText('PUE Mean')).toBeInTheDocument();
      expect(screen.getByText('Peak Inlet Temp')).toBeInTheDocument();
    });
  });

  it('renders Approve and Reject buttons for pending plan', async () => {
    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText(/approve/i)).toBeInTheDocument();
      expect(screen.getByText(/reject/i)).toBeInTheDocument();
    });
  });

  it('calls approvePlan on Approve button click', async () => {
    (approvePlan as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (getPlan as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(PLAN_DETAIL)
      .mockResolvedValueOnce({ ...PLAN_DETAIL, status: 'approved' });

    render(<Review planId="plan-rev-1" />);
    await waitFor(() => screen.getByText(/approve/i));
    fireEvent.click(screen.getByText(/approve/i));
    await waitFor(() => {
      expect(approvePlan).toHaveBeenCalledWith('plan-rev-1');
    });
  });

  it('calls rejectPlan on Reject button click', async () => {
    (rejectPlan as ReturnType<typeof vi.fn>).mockResolvedValue({});
    (getPlan as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(PLAN_DETAIL)
      .mockResolvedValueOnce({ ...PLAN_DETAIL, status: 'rejected' });

    render(<Review planId="plan-rev-1" />);
    await waitFor(() => screen.getByText(/reject/i));
    fireEvent.click(screen.getByText(/reject/i));
    await waitFor(() => {
      expect(rejectPlan).toHaveBeenCalledWith('plan-rev-1');
    });
  });

  it('renders the Recharts KPI chart', async () => {
    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText(/kpi chart/i)).toBeInTheDocument();
    });
  });

  it('renders setpoint inputs for editable plan', async () => {
    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText('CRAH Supply Air Temp (°C)')).toBeInTheDocument();
    });
  });
});
