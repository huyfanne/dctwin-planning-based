import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';

vi.mock('./api', () => ({
  setToken: vi.fn(),
  listPlans: vi.fn().mockResolvedValue([]),
  getPlan: vi.fn().mockResolvedValue(null),
  createPlan: vi.fn(),
  getProgress: vi.fn(),
  approvePlan: vi.fn(),
  rejectPlan: vi.fn(),
  editSetpoints: vi.fn(),
}));

vi.mock('./pages/Dashboard', () => ({ default: () => <div>DashboardPage</div> }));
vi.mock('./pages/NewPlan',   () => ({ default: () => <div>NewPlanPage</div> }));
vi.mock('./pages/Review',    () => ({ default: () => <div>ReviewPage</div> }));
vi.mock('./pages/History',   () => ({ default: () => <div>HistoryPage</div> }));
vi.mock('./pages/DigitalTwin3D', () => ({ default: () => <div>DigitalTwin3DPage</div> }));

describe('App', () => {
  it('renders the nav with all 5 items', () => {
    render(<App />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('New Plan')).toBeInTheDocument();
    expect(screen.getByText('Review')).toBeInTheDocument();
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Digital Twin (3D)')).toBeInTheDocument();
  });

  it('renders the DCTwin logo', () => {
    render(<App />);
    expect(screen.getByText('DCTwin')).toBeInTheDocument();
  });

  it('shows Dashboard page by default', () => {
    render(<App />);
    expect(screen.getByText('DashboardPage')).toBeInTheDocument();
  });

  it('switches to NewPlan page on nav click', () => {
    render(<App />);
    fireEvent.click(screen.getByText('New Plan'));
    expect(screen.getByText('NewPlanPage')).toBeInTheDocument();
  });

  it('switches to History page on nav click', () => {
    render(<App />);
    fireEvent.click(screen.getByText('History'));
    expect(screen.getByText('HistoryPage')).toBeInTheDocument();
  });

  it('renders API token input', () => {
    render(<App />);
    expect(screen.getByPlaceholderText(/bearer token/i)).toBeInTheDocument();
    expect(screen.getByText('Set')).toBeInTheDocument();
  });
});
