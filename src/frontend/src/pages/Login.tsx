import { useState, type FormEvent } from 'react';
import { verifyToken, setToken } from '../api';

export default function Login({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const t = value.trim();
    if (!t) return;
    setBusy(true);
    setError(null);
    try {
      if (await verifyToken(t)) {
        setToken(t);
        onAuthed();
      } else {
        setError('Invalid token — check with your operator.');
        setBusy(false);
      }
    } catch {
      setError("Can't reach the backend — is it running?");
      setBusy(false);
    }
  }

  return (
    <div className="login-shell"
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
      <form className="login-card" onSubmit={submit}
        style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: 32, minWidth: 320,
                 border: '1px solid var(--border, #2a2a2a)', borderRadius: 12 }}>
        <div className="app-logo" style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
          <span className="logo-dot" /> DCTwin
        </div>
        <label htmlFor="token-input" style={{ fontSize: 13 }}>Enter your access token</label>
        <input id="token-input" aria-label="access token" type="password" autoFocus value={value}
          onChange={e => setValue(e.target.value)}
          style={{ padding: '8px 10px', borderRadius: 8 }} />
        {error && <div className="error-msg" role="alert" style={{ color: '#ff6b6b', fontSize: 13 }}>{error}</div>}
        <button type="submit" disabled={busy || !value.trim()}>{busy ? 'Checking…' : 'Continue'}</button>
        <div className="text-dim" style={{ fontSize: 12, opacity: 0.7 }}>operator or expert token</div>
      </form>
    </div>
  );
}
