import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Review from './Review';

vi.mock('../api', () => ({
  listPlans: vi.fn(),
  getPlan: vi.fn(),
  approvePlan: vi.fn(),
  rejectPlan: vi.fn(),
  editSetpoints: vi.fn(),
  deployPlan: vi.fn(),
  getCalibration: vi.fn().mockResolvedValue({
    bias: { inlet_temp_max_c: 0.8, total_hvac_energy_kwh: 1200 },
    sigma: { inlet_temp_max_c: 0.4 },
    n_weeks: 2,
    version: 'weeks-2',
  }),
}));

import { listPlans, getPlan, approvePlan, rejectPlan, deployPlan } from '../api';

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
    robust: {
      robust_feasible: true,
      cvar_energy_kwh: 30500,
      confidence_bands: {
        inlet_temp_max_c: { p50: 25, p90: 25.8, max: 26.2 },
        total_hvac_energy_kwh: { p50: 30000, p90: 31000, max: 31500 },
      },
      n_scenarios: 4,
      calibration_version: 'weeks-3',
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
      expect(screen.getAllByText('Total HVAC Energy').length).toBeGreaterThan(0);
      expect(screen.getByText('PUE Mean')).toBeInTheDocument();
      expect(screen.getAllByText('Peak Inlet Temp').length).toBeGreaterThan(0);
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

  it('renders Deploy button when status is approved', async () => {
    const APPROVED_DETAIL = { ...PLAN_DETAIL, status: 'approved' };
    (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(APPROVED_DETAIL);
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([{ ...PLAN_SUMMARY, status: 'approved' }]);

    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText(/deploy/i)).toBeInTheDocument();
    });
  });

  it('calls deployPlan when Deploy button is clicked', async () => {
    const APPROVED_DETAIL = { ...PLAN_DETAIL, status: 'approved' };
    (deployPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ status: 'deploying' });
    (getPlan as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(APPROVED_DETAIL)
      .mockResolvedValueOnce({ ...PLAN_DETAIL, status: 'deployed' });
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([{ ...PLAN_SUMMARY, status: 'approved' }]);

    render(<Review planId="plan-rev-1" />);
    await waitFor(() => screen.getByText(/deploy/i));
    fireEvent.click(screen.getByText(/deploy/i));
    await waitFor(() => {
      expect(deployPlan).toHaveBeenCalledWith('plan-rev-1');
    });
  });

  it('renders Retry Deploy button when status is deploy_failed', async () => {
    const FAILED_DETAIL = { ...PLAN_DETAIL, status: 'deploy_failed' };
    (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(FAILED_DETAIL);
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([{ ...PLAN_SUMMARY, status: 'deploy_failed' }]);

    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText(/retry deploy/i)).toBeInTheDocument();
    });
  });

  it('renders Realized vs Predicted section when realized data is present', async () => {
    const DEPLOYED_DETAIL = {
      ...PLAN_DETAIL,
      status: 'deployed',
      realized: {
        total_hvac_energy_kwh: 392.1,
        inlet_temp_max_c: 25.8,
        pue_mean: 1.44,
        inlet_violation_steps: 1,
      },
    };
    (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(DEPLOYED_DETAIL);
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([{ ...PLAN_SUMMARY, status: 'deployed' }]);

    render(<Review planId="plan-rev-1" />);
    await waitFor(() => {
      expect(screen.getByText(/realized vs predicted/i)).toBeInTheDocument();
      expect(screen.getByText(/post-deployment actuals/i)).toBeInTheDocument();
    });
  });

  it('renders the Twin Calibration panel with weeks count', async () => {
    render(<Review planId="plan-rev-1" />);
    expect(await screen.findByText(/twin calibration/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/2 weeks/i)).toBeInTheDocument();
    });
  });

  it('renders Confidence Bands panel with scenario count', async () => {
    render(<Review planId="plan-rev-1" />);
    expect(await screen.findByText(/confidence bands/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/4 scenarios/i)).toBeInTheDocument();
    });
  });
});
