import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import NewPlan from './NewPlan';

vi.mock('../api', () => ({
  createPlan: vi.fn(),
  getProgress: vi.fn(),
  getPlan: vi.fn(),
}));

import { createPlan, getProgress } from '../api';

beforeEach(() => {
  vi.clearAllMocks();
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
    (getProgress as ReturnType<typeof vi.fn>).mockResolvedValue({ level: 1, evals: 5, best_score: 0.9 });

    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2026-06-09' } });
    fireEvent.click(screen.getByText(/launch optimization/i));

    await waitFor(() => {
      expect(createPlan).toHaveBeenCalledWith(expect.objectContaining({ week_start: '2026-06-09' }));
      expect(screen.getByText('p-new-1')).toBeInTheDocument();
    });
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
});
