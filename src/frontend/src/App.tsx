import { lazy, Suspense, useState } from 'react';
import Dashboard from './pages/Dashboard';
import Live from './pages/Live';
import NewPlan from './pages/NewPlan';
import Review from './pages/Review';
import History from './pages/History';
import Login from './pages/Login';
import { getToken, clearToken } from './api';
// Lazy-load the 3D twin so the heavy three.js bundle is only fetched on demand.
const DigitalTwin3D = lazy(() => import('./pages/DigitalTwin3D'));

type Page = 'dashboard' | 'live' | 'newplan' | 'review' | 'history' | 'twin3d';

const NAV: { id: Page; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'live',      label: 'Live' },
  { id: 'newplan',   label: 'New Plan' },
  { id: 'review',    label: 'Review' },
  { id: 'history',   label: 'History' },
  { id: 'twin3d',    label: 'Digital Twin (3D)' },
];

export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken());
  const [page, setPage] = useState<Page>('dashboard');
  // reviewPlanId can be set from History to deep-link to a specific plan
  const [reviewPlanId, setReviewPlanId] = useState<string | undefined>(undefined);

  if (!authed) return <Login onAuthed={() => setAuthed(true)} />;

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

        <button className="signout" onClick={() => { clearToken(); setAuthed(false); }}
          style={{ marginLeft: 'auto' }}>Sign out</button>
      </header>

      <main className="app-content">
        {page === 'dashboard' && <Dashboard onReview={openReview} />}
        {page === 'live'      && <Live />}
        {page === 'newplan'   && <NewPlan onDone={id => { setReviewPlanId(id); setPage('review'); }} />}
        {page === 'review'    && <Review planId={reviewPlanId} />}
        {page === 'history'   && <History onReview={openReview} />}
        {page === 'twin3d'    && (
          <Suspense fallback={
            <div className="flex items-center gap-3" style={{ padding: '48px 0' }}>
              <div className="spinner" />
              <span className="text-dim" style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.1em', fontSize: 13 }}>
                LOADING 3D ENGINE…
              </span>
            </div>
          }>
            <DigitalTwin3D />
          </Suspense>
        )}
      </main>
    </div>
  );
}
