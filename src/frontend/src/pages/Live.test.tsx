import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import Live from './Live';

vi.mock('../api', () => ({
  getLive: vi.fn(),
  getLiveSeries: vi.fn(),
  liveStreamUrl: () => '/api/live/stream?token=t',
}));

import { getLive, getLiveSeries, type LiveFrame } from '../api';

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(url: string) { this.url = url; MockEventSource.instances.push(this); }
  close() { this.closed = true; }
  emit(frame: object) { this.onmessage?.({ data: JSON.stringify(frame) }); }
  fail() { this.onerror?.(); }
}

function mkFrame(over: Partial<LiveFrame> = {}): LiveFrame {
  const points: LiveFrame['points'] = {};
  for (let i = 1; i <= 22; i++) points[`rack_inlet_c/ite-${i}`] = { ts: 100, value: 23.5 };
  Object.assign(points, {
    hall_power_kw:    { ts: 100, value: 612.4 },
    pue:              { ts: 100, value: 1.38 },
    rh_pct:           { ts: 100, value: 52.1 },
    'held/sat_c':     { ts: 100, value: 23.1 },
    'held/flow_kg_s': { ts: 100, value: 8.38 },
    'held/chwst_c':   { ts: 100, value: 16.8 },
  });
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
  (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(mkFrame());
  (getLiveSeries as ReturnType<typeof vi.fn>).mockResolvedValue({ series: {} });
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: unknown }).EventSource = MockEventSource;
});

describe('Live', () => {
  it('renders the 22-rack heat-map with inlet temps and point-name tooltips', async () => {
    render(<Live />);
    await waitFor(() => expect(screen.getByTitle('rack_inlet_c/ite-1')).toBeInTheDocument());
    expect(screen.getByTitle('rack_inlet_c/ite-22')).toBeInTheDocument();
    // 22 tiles at 23.5 (the worst-inlet KPI tile repeats the value, so >= 22)
    expect(screen.getAllByText('23.5').length).toBeGreaterThanOrEqual(22);
    expect(screen.getByTitle('rack_inlet_c/ite-1').dataset.zone).toBe('green');
  });

  it('colors tiles by inlet zone and pulses the border at >= 26 °C', async () => {
    const f = mkFrame();
    f.points['rack_inlet_c/ite-2'] = { ts: 100, value: 24.9 };   // amber: >= 24.5
    f.points['rack_inlet_c/ite-3'] = { ts: 100, value: 25.7 };   // red: >= 25.5
    f.points['rack_inlet_c/ite-4'] = { ts: 100, value: 26.3 };   // red + pulsing: >= 26
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(f);
    render(<Live />);
    await waitFor(() => expect(screen.getByTitle('rack_inlet_c/ite-2')).toBeInTheDocument());
    expect(screen.getByTitle('rack_inlet_c/ite-2').dataset.zone).toBe('amber');
    expect(screen.getByTitle('rack_inlet_c/ite-3').dataset.zone).toBe('red');
    expect(screen.getByTitle('rack_inlet_c/ite-3').style.animation).toBe('');
    const hot = screen.getByTitle('rack_inlet_c/ite-4');
    expect(hot.dataset.zone).toBe('red');
    expect(hot.style.animation).toContain('live-pulse-border');
  });

  it('shows the quiet green nominal line when there are no alerts', async () => {
    render(<Live />);
    expect(await screen.findByText(/all racks nominal/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the alert banner with warn and critical alerts', async () => {
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(mkFrame({
      alerts: [
        { level: 'warn',     point: 'rack_inlet_c/ite-2', value: 25.2, message: 'inlet margin < 1 °C' },
        { level: 'critical', point: 'rack_inlet_c/ite-4', value: 26.3, message: 'inlet above 26 °C cap' },
      ],
    }));
    render(<Live />);
    const banner = await screen.findByRole('alert');
    expect(banner).toBeInTheDocument();
    expect(screen.getByText(/critical/i)).toBeInTheDocument();
    expect(screen.getByText(/inlet margin < 1/)).toBeInTheDocument();
    expect(screen.getByText(/inlet above 26 °C cap/)).toBeInTheDocument();
    expect(screen.queryByText(/all racks nominal/i)).not.toBeInTheDocument();
  });

  it('renders the KPI tiles: hall power, PUE, RH, worst inlet + margin to cap', async () => {
    const f = mkFrame();
    f.points['rack_inlet_c/ite-7'] = { ts: 100, value: 24.9 };   // worst rack
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(f);
    render(<Live />);
    expect(await screen.findByText('612.4')).toBeInTheDocument();   // hall power
    expect(screen.getByText('1.38')).toBeInTheDocument();           // PUE
    expect(screen.getByText('52.1')).toBeInTheDocument();           // RH
    expect(screen.getAllByText('24.9').length).toBeGreaterThanOrEqual(2);  // tile + worst-inlet KPI
    expect(screen.getByText(/1\.1 °C to 26 °C cap/)).toBeInTheDocument(); // margin
  });

  it('shows the compliance empty state when no plan is deployed', async () => {
    render(<Live />);
    expect(await screen.findByText(/no deployed plan/i)).toBeInTheDocument();
  });

  it('renders commanded vs held with per-axis check marks and deltas', async () => {
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(mkFrame({
      compliance: {
        commanded: { sat_c: 23, flow_kg_s: 8.4, chwst_c: 16 },
        held:      { sat_c: 23.1, flow_kg_s: 8.38, chwst_c: 16.8 },
        ok: false,
        deltas:    { sat_c: 0.1, flow_kg_s: -0.02, chwst_c: 0.8 },
      },
    }));
    render(<Live />);
    expect(await screen.findByText('23.00 → 23.10')).toBeInTheDocument();
    expect(screen.getByText('Δ +0.80')).toBeInTheDocument();
    expect(screen.getAllByText('✓').length).toBe(2);     // sat + flow within ±0.5
    expect(screen.getAllByText('⚠').length).toBe(1);     // chwst drifted by 0.8
    expect(screen.getByText(/drift/i)).toBeInTheDocument();
    expect(screen.queryByText(/no deployed plan/i)).not.toBeInTheDocument();
  });

  it('shows the SIMULATED FEED badge when the data is simulated', async () => {
    render(<Live />);
    expect(await screen.findByText(/simulated feed/i)).toBeInTheDocument();
  });

  it('hides the SIMULATED FEED badge for real telemetry', async () => {
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(mkFrame({ simulated: false }));
    render(<Live />);
    await screen.findByText('612.4');
    expect(screen.queryByText(/simulated feed/i)).not.toBeInTheDocument();
  });

  it('updates the page from SSE frames', async () => {
    render(<Live />);
    await screen.findByText('612.4');
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const f2 = mkFrame();
    f2.points.hall_power_kw = { ts: 101, value: 701.6 };
    MockEventSource.instances[0].emit(f2);
    await waitFor(() => expect(screen.getByText('701.6')).toBeInTheDocument());
  });

  it('falls back to 5 s polling after repeated stream failures', async () => {
    render(<Live />);
    await screen.findByText('612.4');
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const before = (getLive as ReturnType<typeof vi.fn>).mock.calls.length;
    const es = MockEventSource.instances[0];
    for (let i = 0; i < 7; i++) es.fail();               // exceed the retry budget
    await waitFor(() =>
      expect((getLive as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(before));
    expect(await screen.findByText(/poll fallback/i)).toBeInTheDocument();
  });

  it('fetches the 30-min series and renders the rolling chart card', async () => {
    (getLiveSeries as ReturnType<typeof vi.fn>).mockResolvedValue({
      series: {
        hall_power_kw: [{ t: 1000, v: 600.0 }, { t: 1060, v: 610.0 }],
        pue:           [{ t: 1000, v: 1.40 }],
        worst_inlet_c: [{ t: 1000, v: 24.2 }, { t: 1060, v: 24.4 }],
      },
    });
    render(<Live />);
    await waitFor(() => expect(getLiveSeries).toHaveBeenCalledWith(30));
    expect(await screen.findByText(/rolling window/i)).toBeInTheDocument();
    expect(screen.queryByText(/no series data yet/i)).not.toBeInTheDocument();
  });

  // Rack-detail table rows (tbody <tr data-rack=…>), in rendered (ranked) order.
  function detailRows(): HTMLElement[] {
    return screen.getAllByRole('row').filter(r => (r as HTMLElement).dataset.rack) as HTMLElement[];
  }

  it('renders the rack-detail table ranked by inlet descending with margin + status chips', async () => {
    const f = mkFrame();
    f.points['rack_inlet_c/ite-5']  = { ts: 100, value: 25.7 };   // red  → Hot
    f.points['rack_inlet_c/ite-12'] = { ts: 100, value: 24.9 };   // amber → Warm
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(f);
    render(<Live />);
    await screen.findByText(/rack detail/i);
    const rows = detailRows();
    expect(rows.length).toBe(22);
    // hottest first, then the warm one, then the 23.5 pack
    expect(rows[0].dataset.rack).toBe('ite-5');
    expect(rows[1].dataset.rack).toBe('ite-12');
    expect(within(rows[0]).getByText('25.7')).toBeInTheDocument();
    expect(within(rows[0]).getByText('0.3')).toBeInTheDocument();     // 26 − 25.7 margin
    expect(within(rows[0]).getByText('Hot')).toBeInTheDocument();
    expect((within(rows[0]).getByText('Hot') as HTMLElement).dataset.chip).toBe('red');
    expect(within(rows[1]).getByText('1.1')).toBeInTheDocument();     // 26 − 24.9
    expect(within(rows[1]).getByText('Warm')).toBeInTheDocument();
    expect(within(rows[2]).getByText('2.5')).toBeInTheDocument();     // 26 − 23.5
    expect(within(rows[2]).getByText('Nominal')).toBeInTheDocument();
  });

  it('flags over-cap racks first and puts missing-data racks last in the rack detail', async () => {
    const f = mkFrame();
    f.points['rack_inlet_c/ite-9'] = { ts: 100, value: 26.2 };
    delete f.points['rack_inlet_c/ite-3'];
    (getLive as ReturnType<typeof vi.fn>).mockResolvedValue(f);
    render(<Live />);
    await screen.findByText(/rack detail/i);
    const rows = detailRows();
    expect(rows[0].dataset.rack).toBe('ite-9');
    expect(within(rows[0]).getByText('Over Cap')).toBeInTheDocument();
    expect(within(rows[0]).getByText('-0.2')).toBeInTheDocument();    // negative margin
    const last = rows[rows.length - 1];
    expect(last.dataset.rack).toBe('ite-3');
    expect(within(last).getByText('No Data')).toBeInTheDocument();
    expect(within(last).getAllByText('—').length).toBeGreaterThanOrEqual(1);
  });

  it('shows an error when the initial fetch fails and no stream frame arrives', async () => {
    (getLive as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('503: live feed unavailable'));
    render(<Live />);
    expect(await screen.findByText(/live feed unavailable/i)).toBeInTheDocument();
  });
});
