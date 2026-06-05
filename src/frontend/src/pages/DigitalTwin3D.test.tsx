import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import DigitalTwin3D from './DigitalTwin3D';

// react-three-fiber cannot render under jsdom (no WebGL), so we stub the GL
// boundary: <Canvas> becomes a plain div that still renders its children, and
// useFrame is a no-op. This lets us verify the React/data wiring (HUD + plan
// selector) without touching the GPU.
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: { children: ReactNode }) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
  useThree: () => ({}),
}));

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
  Grid: () => null,
  Environment: () => null,
  Edges: () => null,
  Line: () => null,
  Html: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock('../api', () => ({
  getTopology: vi.fn(),
  listPlans: vi.fn(),
  getPlan: vi.fn(),
}));

import { getTopology, listPlans, getPlan } from '../api';

const TOPO = {
  hall: { name: 'Data Hall 1F 2A', size: [30, 20, 4] },
  crahs: [
    { id: 'crah-1', pos: [10, 0, 2], wall: 'south' },
    { id: 'crah-2', pos: [20, 20, 2], wall: 'north' },
  ],
  rack_rows: [
    { id: 'row-1', pos: [15, 5, 0], aisle: 'cold', nracks: 4 },
    { id: 'row-2', pos: [15, 9, 0], aisle: 'hot', nracks: 4 },
  ],
  plant: { chiller: 1, coolingTower: 1, pumps: 3, pos: [-8, 10, 0] },
  links: [
    { from: 'plant', to: 'crah-1' },
    { from: 'plant', to: 'crah-2' },
  ],
  building: {
    footprint: [42.46, 22.55],
    height: 24.5,
    halls: [
      { code: 'Data Hall GF 1A', level: 'GF', origin: [0, 0, 0], size: [42.46, 22.55, 3.5], z0: 0, controlled: false, ite: 1 },
      { code: 'Data Hall 1F 2A', level: '1F', origin: [0, 0, 7], size: [42.46, 22.55, 3.5], z0: 7, controlled: true, ite: 22 },
      { code: 'Data Hall 2F 3A', level: '2F', origin: [0, 0, 14], size: [42.46, 22.55, 3.5], z0: 14, controlled: false, ite: 1 },
    ],
  },
};

const PLAN_SUMMARY = {
  plan_id: 'plan-twin-1',
  week_start: '2026-06-02',
  status: 'approved',
  energy_kwh: 388.5,
  reduction_pct: 8.2,
};

const PLAN_DETAIL = {
  plan_id: 'plan-twin-1',
  status: 'approved',
  recommendation: {
    status: 'ok',
    setpoints: {
      crah_supply_air_temperature_c: 23.4,
      crah_supply_air_mass_flow_rate_kg_s: 11.5,
      chilled_water_supply_temperature_c: 15.0,
    },
    predicted_kpis: {
      total_hvac_energy_kwh: 388,
      pue_mean: 1.42,
      inlet_temp_max_c: 26.1,
      inlet_violation_steps: 0,
      energy_reduction_vs_baseline_pct: 8.2,
    },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  (getTopology as ReturnType<typeof vi.fn>).mockResolvedValue(TOPO);
  (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([PLAN_SUMMARY]);
  (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(PLAN_DETAIL);
});

describe('DigitalTwin3D', () => {
  it('renders the scene canvas and HUD with the plan setpoints', async () => {
    render(<DigitalTwin3D />);

    await waitFor(() => {
      // GL boundary stub rendered
      expect(screen.getByTestId('canvas')).toBeInTheDocument();
      // HUD shows the supply-air setpoint value
      expect(screen.getByText('23.4')).toBeInTheDocument();
      // and the air-flow setpoint value
      expect(screen.getByText('11.5')).toBeInTheDocument();
    });

    // Setpoint + KPI labels present
    expect(screen.getByText(/supply air/i)).toBeInTheDocument();
    expect(screen.getByText(/air flow/i)).toBeInTheDocument();
    expect(screen.getByText(/chw supply/i)).toBeInTheDocument();
    expect(screen.getByText(/pue mean/i)).toBeInTheDocument();
  });

  it('renders every building hall/level as a labeled box + HUD summary', async () => {
    render(<DigitalTwin3D />);
    await waitFor(() => expect(screen.getByTestId('canvas')).toBeInTheDocument());
    // each context hall in building.halls renders a label (Html -> div stub);
    // GF 1A / 2F 3A are unique to the box labels, 1F 2A also appears in the HUD.
    expect(screen.getByText('Data Hall GF 1A')).toBeInTheDocument();
    expect(screen.getByText('Data Hall 2F 3A')).toBeInTheDocument();
    expect(screen.getAllByText('Data Hall 1F 2A').length).toBeGreaterThanOrEqual(1);
    // controlled hall is badged, and the HUD summarizes the building
    expect(screen.getByText(/CONTROLLED/)).toBeInTheDocument();
    expect(screen.getByText(/3 HALLS \/ 3 LEVELS/)).toBeInTheDocument();
  });

  it('shows the plan selector populated from listPlans', async () => {
    render(<DigitalTwin3D />);
    // selector option text is "<week_start> — <id[:8]> (<status>)"
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /2026-06-02/i })).toBeInTheDocument();
    });
    expect(getTopology).toHaveBeenCalled();
    expect(listPlans).toHaveBeenCalled();
  });

  it('falls back to nominal envelope when there are no plans', async () => {
    (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    render(<DigitalTwin3D />);
    await waitFor(() => {
      expect(screen.getByTestId('canvas')).toBeInTheDocument();
      expect(screen.getByText(/no plan selected/i)).toBeInTheDocument();
    });
  });
});
