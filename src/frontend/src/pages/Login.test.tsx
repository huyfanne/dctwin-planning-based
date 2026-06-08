import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Login from './Login';

vi.mock('../api', () => ({
  verifyToken: vi.fn(),
  setToken: vi.fn(),
}));
import { verifyToken, setToken } from '../api';

beforeEach(() => vi.clearAllMocks());

describe('Login', () => {
  it('authenticates and enters the app on a valid token', async () => {
    (verifyToken as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    const onAuthed = vi.fn();
    render(<Login onAuthed={onAuthed} />);
    fireEvent.change(screen.getByLabelText(/access token/i), { target: { value: 'op-secret' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    await waitFor(() => expect(onAuthed).toHaveBeenCalled());
    expect(setToken).toHaveBeenCalledWith('op-secret');
  });

  it('shows an error and does not enter on an invalid token', async () => {
    (verifyToken as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    const onAuthed = vi.fn();
    render(<Login onAuthed={onAuthed} />);
    fireEvent.change(screen.getByLabelText(/access token/i), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    await waitFor(() => expect(screen.getByText(/invalid token/i)).toBeInTheDocument());
    expect(onAuthed).not.toHaveBeenCalled();
    expect(setToken).not.toHaveBeenCalled();
  });
});
