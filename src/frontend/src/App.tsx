import { useState } from 'react';
import { setToken } from './api';
import Dashboard from './pages/Dashboard';
import NewPlan from './pages/NewPlan';
import Review from './pages/Review';
import History from './pages/History';
import DigitalTwin3D from './pages/DigitalTwin3D';

type Page = 'dashboard' | 'newplan' | 'review' | 'history' | 'twin3d';

const NAV: { id: Page; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'newplan',   label: 'New Plan' },
  { id: 'review',    label: 'Review' },
  { id: 'history',   label: 'History' },
  { id: 'twin3d',    label: 'Digital Twin (3D)' },
];

export default function App() {
  const [page, setPage] = useState<Page>('dashboard');
  const [tokenDraft, setTokenDraft] = useState('');
  const [tokenSaved, setTokenSaved] = useState(false);
  // reviewPlanId can be set from History to deep-link to a specific plan
  const [reviewPlanId, setReviewPlanId] = useState<string | undefined>(undefined);

  function handleSetToken() {
    setToken(tokenDraft.trim());
    setTokenSaved(true);
    setTimeout(() => setTokenSaved(false), 1800);
  }

  function openReview(id: string) {
    setReviewPlanId(id);
    setPage('review');
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        {/* Logo */}
        <a className="app-logo" onClick={() => setPage('dashboard')} role="button" style={{ cursor: 'pointer' }}>
          <span className="logo-dot" />
          DCTwin
        </a>

        {/* Nav */}
        <nav className="app-nav">
          {NAV.map(n => (
            <button
              key={n.id}
              className={page === n.id ? 'active' : ''}
              onClick={() => {
                if (n.id !== 'review') setReviewPlanId(undefined);
                setPage(n.id);
              }}
            >
              {n.label}
            </button>
          ))}
        </nav>

        {/* Token input */}
        <div className="token-input-wrap">
          <span className="token-label">API Token</span>
          <input
            type="password"
            className="token-input"
            placeholder="Bearer token…"
            value={tokenDraft}
            onChange={e => setTokenDraft(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSetToken()}
          />
          <button className="token-btn" onClick={handleSetToken}>
            {tokenSaved ? '✓ Saved' : 'Set'}
          </button>
        </div>
      </header>

      <main className="app-content">
        {page === 'dashboard' && <Dashboard onReview={openReview} />}
        {page === 'newplan'   && <NewPlan onDone={id => { setReviewPlanId(id); setPage('review'); }} />}
        {page === 'review'    && <Review planId={reviewPlanId} />}
        {page === 'history'   && <History onReview={openReview} />}
        {page === 'twin3d'    && <DigitalTwin3D />}
      </main>
    </div>
  );
}
