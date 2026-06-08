import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import NewPlan from './NewPlan';

vi.mock('../api', () => ({
  createPlan: vi.fn(),
  getProgress: vi.fn(),
  getPlan: vi.fn(),
  getWeather: vi.fn(),
  planStreamUrl: (id: string) => `/api/plans/${id}/stream?token=t`,
}));

import { createPlan, getWeather } from '../api';

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

beforeEach(() => {
  vi.clearAllMocks();
  (getWeather as ReturnType<typeof vi.fn>).mockResolvedValue({ label: null, suggested_week_start: null });
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: unknown }).EventSource = MockEventSource;
});

describe('NewPlan', () => {
  it('renders the form with required fields', () => {
    render(<NewPlan onDone={() => {}} />);
    expect(screen.getByLabelText(/week start/i)).toBeInTheDocument();
    expect(screen.getByText(/launch optimization/i)).toBeInTheDocument();
  });

  it('shows validation error when week start is missing and form is submitted programmatically', async () => {
    render(<NewPlan onDone={() => {}} />);
    // Submit the form directly to bypass HTML5 required validation in jsdom
    const form = document.querySelector('form')!;
    fireEvent.submit(form);
    await waitFor(() => {
      expect(screen.getByText(/week start date is required/i)).toBeInTheDocument();
    });
  });

  it('creates plan and shows progress panel on submit', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p-new-1', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(screen.getByText('p-new-1')).toBeInTheDocument());
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: { level: 1, evals: 42, best_score: 0.9 }, status: 'running' });
    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument());   // evals tile (42 avoids the grid=5 default)
  });

  it('renders plan params fields with defaults', () => {
    render(<NewPlan onDone={() => {}} />);
    expect(screen.getByLabelText(/days/i)).toHaveValue(7);
    expect(screen.getByLabelText(/grid size/i)).toHaveValue(5);
    expect(screen.getByLabelText(/beam width/i)).toHaveValue(3);
    expect(screen.getByLabelText(/levels/i)).toHaveValue(3);
    expect(screen.getByLabelText(/workers/i)).toHaveValue(4);
  });

  it('shows API error if createPlan fails', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Server error'));
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => {
      expect(screen.getByText(/server error/i)).toBeInTheDocument();
    });
  });

  it('sends time_block when the day/night toggle is on', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p1', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2013-11-11' } });
    fireEvent.click(screen.getByLabelText(/day\/night setpoints/i));
    fireEvent.click(screen.getByRole('button', { name: /launch/i }));
    await waitFor(() => expect(createPlan).toHaveBeenCalledWith(expect.objectContaining({ time_block: true })));
  });

  it('marks done on a terminal frame', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p2', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: { level: 3, evals: 40 }, status: 'pending_approval' });
    await waitFor(() => expect(screen.getByText(/review results/i)).toBeInTheDocument());
  });

  it('does not error on a single transient stream drop (reconnects quietly)', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p3', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].fail();                 // one drop → quiet reconnect, no scary error
    await waitFor(() => expect(screen.getByText('p3')).toBeInTheDocument());
    expect(screen.queryByText(/lost connection/i)).not.toBeInTheDocument();
  });

  it('shows an error only after repeated stream failures', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'p3', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];
    for (let i = 0; i < 7; i++) es.fail();               // exceed the retry budget (shared closure counter)
    // {error} renders in BOTH the form card and the live-progress card, so use getAllByText.
    await waitFor(() => expect(screen.getAllByText(/lost connection|backend/i).length).toBeGreaterThan(0));
  });

  it('shows the real failure reason from the stream', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'pf', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2024-11-11' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: { error: 'week 2026-06-08 is outside coverage' }, status: 'failed' });
    // {error} renders in BOTH the form card and the live-progress card once planId is set,
    // so use getAllByText (single-match getByText throws on the duplicate — see the sibling
    // 'shows an error when the stream errors' test).
    await waitFor(() => expect(screen.getAllByText(/outside coverage/i).length).toBeGreaterThan(0));
  });

  it('prefills week start and shows the coverage hint', async () => {
    (getWeather as ReturnType<typeof vi.fn>).mockResolvedValue({ label: 'Nov 1 – Jan 31', suggested_week_start: '2024-11-01' });
    render(<NewPlan onDone={() => {}} />);
    await waitFor(() => expect(screen.getByText(/weather data covers/i)).toBeInTheDocument());
    expect((screen.getByLabelText(/week start/i) as HTMLInputElement).value).toBe('2024-11-01');
  });
});
