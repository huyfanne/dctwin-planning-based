import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import DigitalTwin3D, { rowWorstInlets } from './DigitalTwin3D';

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
  getLive: vi.fn(),
}));

import { getTopology, listPlans, getPlan, getLive, type LiveFrame } from '../api';

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
    plant: { chiller: 1, coolingTower: 1, pumps: 3 },
    halls: [
      {
        code: 'Data Hall GF 1A', level: 'GF', origin: [0, 0, 0], size: [42.46, 22.55, 3.5], z0: 0,
        controlled: false, ite: 1,
        infra: { acuTotal: 1, acuControlled: 0, iteObjects: 1, iteUnits: 1000, itPowerKw: 4000, hvac: '1 ACU · scheduled SAT 23°C · water-cooled VAV' },
        crahs: [{ id: 'crah-1', pos: [21, 0, 1.75], wall: 'south' }],
        rackRows: [{ id: 'row-1', pos: [21, 8, 0], aisle: 'cold', nracks: 8 }, { id: 'row-2', pos: [21, 14, 0], aisle: 'hot', nracks: 8 }],
      },
      {
        code: 'Data Hall 1F 2A', level: '1F', origin: [0, 0, 7], size: [42.46, 22.55, 3.5], z0: 7,
        controlled: true, ite: 22,
        infra: { acuTotal: 22, acuControlled: 22, iteObjects: 22, iteUnits: 22000, itPowerKw: 2000, hvac: '22 ACUs · agent-controlled SAT + airflow · water-cooled VAV' },
        crahs: [{ id: 'crah-1', pos: [10, 0, 1.75], wall: 'south' }, { id: 'crah-2', pos: [20, 22, 1.75], wall: 'north' }],
        // 6 rows — the live ite-1..22 mapping spreads 4,4,4,4,3,3 across them.
        rackRows: [
          { id: 'row-1', pos: [21, 3, 0],  aisle: 'cold', nracks: 4 },
          { id: 'row-2', pos: [21, 6, 0],  aisle: 'hot',  nracks: 4 },
          { id: 'row-3', pos: [21, 9, 0],  aisle: 'cold', nracks: 4 },
          { id: 'row-4', pos: [21, 12, 0], aisle: 'hot',  nracks: 4 },
          { id: 'row-5', pos: [21, 15, 0], aisle: 'cold', nracks: 3 },
          { id: 'row-6', pos: [21, 18, 0], aisle: 'hot',  nracks: 3 },
        ],
      },
      {
        code: 'Data Hall 2F 3A', level: '2F', origin: [0, 0, 14], size: [42.46, 22.55, 3.5], z0: 14,
        controlled: false, ite: 1,
        infra: { acuTotal: 1, acuControlled: 0, iteObjects: 1, iteUnits: 1000, itPowerKw: 4000, hvac: '1 ACU · scheduled SAT 23°C · water-cooled VAV' },
        crahs: [{ id: 'crah-1', pos: [21, 0, 1.75], wall: 'south' }],
        rackRows: [{ id: 'row-1', pos: [21, 8, 0], aisle: 'cold', nracks: 8 }, { id: 'row-2', pos: [21, 14, 0], aisle: 'hot', nracks: 8 }],
      },
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

function mkLiveFrame(over: Partial<LiveFrame> = {}): LiveFrame {
  const points: LiveFrame['points'] = {};
  for (let i = 1; i <= 22; i++) points[`rack_inlet_c/ite-${i}`] = { ts: 100, value: 23.5 };
  return {
    ts: 100,
    points,
    alerts: [],
    compliance: { commanded: null, held: null, ok: null, deltas: null },
    simulated: true,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  (getTopology as ReturnType<typeof vi.fn>).mockResolvedValue(TOPO);
  (listPlans as ReturnType<typeof vi.fn>).mockResolvedValue([PLAN_SUMMARY]);
  (getPlan as ReturnType<typeof vi.fn>).mockResolvedValue(PLAN_DETAIL);
  (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(mkLiveFrame());
});

afterEach(() => {
  vi.useRealTimers();
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
    // controlled hall is badged (label + detail panel), HUD summarizes building
    expect(screen.getAllByText(/CONTROLLED/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/3 HALLS \/ 3 LEVELS/)).toBeInTheDocument();
  });

  it('selecting a hall shows that hall’s details', async () => {
    render(<DigitalTwin3D />);
    await waitFor(() => expect(screen.getByTestId('canvas')).toBeInTheDocument());
    // default selection is the controlled hall -> no MONITORED badge yet
    expect(screen.queryByText('MONITORED')).toBeNull();
    // click a context hall's label -> detail panel switches to it
    fireEvent.click(screen.getByText('Data Hall 2F 3A'));
    await waitFor(() => expect(screen.getByText('MONITORED')).toBeInTheDocument());
    // panel shows infrastructure fields
    expect(screen.getByText('Footprint')).toBeInTheDocument();
    expect(screen.getByText('IT power')).toBeInTheDocument();
    expect(screen.getByText('ACUs')).toBeInTheDocument();
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

  // ── live rack-row coloring (#6) ──

  it('rowWorstInlets maps ite-1..22 row-major across 6 rows as 4,4,4,4,3,3', () => {
    const f = mkLiveFrame();
    // value = ite index, so the worst of each group is its last member
    for (let i = 1; i <= 22; i++) f.points[`rack_inlet_c/ite-${i}`] = { ts: 1, value: i };
    expect(rowWorstInlets(f, 6)).toEqual([4, 8, 12, 16, 19, 22]);
  });

  it('rowWorstInlets yields null per row when telemetry points are missing', () => {
    expect(rowWorstInlets(mkLiveFrame({ points: {} }), 6))
      .toEqual([null, null, null, null, null, null]);
  });

  it('colors controlled-hall rack rows from live telemetry and shows legend + caption', async () => {
    const f = mkLiveFrame();
    f.points['rack_inlet_c/ite-6']  = { ts: 100, value: 25.8 };   // row 2 (ites 5-8)  → red
    f.points['rack_inlet_c/ite-20'] = { ts: 100, value: 24.7 };   // row 6 (ites 20-22) → amber
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(f);
    render(<DigitalTwin3D />);
    const legend = await screen.findByTestId('live-rack-legend');
    expect(legend.dataset.rowZones).toBe('green,red,green,green,green,amber');
    expect(screen.getByText(/live telemetry/i)).toBeInTheDocument();
  });

  it('falls back to static plan coloring (no legend) when live telemetry is unavailable', async () => {
    (getLive as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('503: live feed unavailable'));
    render(<DigitalTwin3D />);
    await waitFor(() => expect(screen.getByTestId('canvas')).toBeInTheDocument());
    expect(screen.queryByTestId('live-rack-legend')).toBeNull();
    expect(screen.queryByText(/live telemetry/i)).toBeNull();
  });

  it('polls live telemetry every 5 s and stops on unmount', async () => {
    vi.useFakeTimers();
    const { unmount } = render(<DigitalTwin3D />);
    expect(getLive).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(getLive).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5000);
    expect(getLive).toHaveBeenCalledTimes(3);
    unmount();
    await vi.advanceTimersByTimeAsync(15000);
    expect(getLive).toHaveBeenCalledTimes(3);   // interval cleared
  });
});
