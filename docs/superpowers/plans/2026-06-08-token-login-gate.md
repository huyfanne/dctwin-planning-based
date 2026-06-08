# Token Login Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a blocking token-login gate to the React frontend so the operator can enter (and clear) a bearer token, fixing the 401s caused by `localStorage["token"]` never being set in the UI.

**Architecture:** `api.ts` gains `getToken`/`clearToken`/`verifyToken` (validation via a raw `GET /api/plans` that doesn't mutate the stored token). A new `pages/Login.tsx` card validates the entered token before storing it. `App.tsx` renders `Login` until authed and adds a header **Sign out**. Frontend-only; no backend change.

**Tech Stack:** React 19 + Vite + TS, vitest + @testing-library/react. Build = `tsc -b && vite build` (`noUnusedLocals` ON — unused imports fail the build).

**Spec:** `docs/superpowers/specs/2026-06-08-token-login-gate-design.md`

**Conventions for every task:**
- Frontend dir: `/mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend`. The sandbox strips a leading `cd` — prefix with `env -C <dir>`.
- Run one test file: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- <name>` (vitest runs once in non-TTY).
- Full check: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `npm run build`.
- Branch `feat/token-login-gate` (already created); do NOT switch branches. Commit after each task (repo policy appends a `Co-Authored-By` trailer — keep it).

---

## File map

| File | Change | Task |
|---|---|---|
| `frontend/src/api.ts` | add `getToken`, `clearToken`, `verifyToken` | G1 |
| `frontend/src/api.test.ts` | add token-helper + `verifyToken` tests | G1 |
| `frontend/src/pages/Login.tsx` | new — the gate card | G2 |
| `frontend/src/pages/Login.test.tsx` | new — valid/invalid | G2 |
| `frontend/src/App.tsx` | gate wiring + Sign out | G3 |
| `frontend/src/App.test.tsx` | extend `./api` mock + gate/sign-out tests | G3 |

---

## Task G1: `api.ts` token helpers + `verifyToken`

**Files:**
- Modify: `frontend/src/api.ts`
- Test: `frontend/src/api.test.ts`

- [ ] **Step 1: Write the failing tests**

In `frontend/src/api.test.ts`, change the import line to add the three new symbols:

```ts
import { listPlans, createPlan, approvePlan, setToken, getToken, clearToken, verifyToken } from "./api";
```

Append a new describe block at the end of the file:

```ts
describe("token helpers", () => {
  it("getToken / setToken / clearToken round-trip via localStorage", () => {
    setToken("abc");
    expect(getToken()).toBe("abc");
    expect(localStorage.getItem("token")).toBe("abc");
    clearToken();
    expect(getToken()).toBe("");
    expect(localStorage.getItem("token")).toBeNull();
  });

  it("verifyToken probes /api/plans with the given token and returns true on 200, without mutating the stored token", async () => {
    setToken("orig");
    (fetch as any).mockResolvedValue({ ok: true, json: async () => [] });
    const ok = await verifyToken("probe-tok");
    expect(ok).toBe(true);
    const [url, opts] = (fetch as any).mock.calls[0];
    expect(url).toBe("/api/plans");
    expect(opts.headers.Authorization).toBe("Bearer probe-tok");
    expect(getToken()).toBe("orig");          // verifyToken must NOT store the probed token
  });

  it("verifyToken returns false on 401", async () => {
    (fetch as any).mockResolvedValue({ ok: false, status: 401, json: async () => ({}) });
    expect(await verifyToken("bad")).toBe(false);
  });
});
```

(The file's existing `beforeEach` already does `setToken("op-tok"); vi.stubGlobal("fetch", vi.fn());`, so `fetch` is mocked.)

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- api`
Expected: FAIL — `getToken`/`clearToken`/`verifyToken` are not exported (`undefined`/import errors).

- [ ] **Step 3: Implement the helpers**

In `frontend/src/api.ts`, immediately after the existing `setToken` line (`export function setToken(t: string) { … }`), add:

```ts
export function getToken(): string { return TOKEN; }
export function clearToken(): void { TOKEN = ""; localStorage.removeItem("token"); }

// Validate a token WITHOUT mutating the stored TOKEN: raw GET /api/plans (operator-min;
// an expert token satisfies it too). 200 -> valid, 401/403 -> invalid. May throw on a
// network failure (caller treats that as "backend unreachable").
export async function verifyToken(token: string): Promise<boolean> {
  const res = await fetch("/api/plans", { headers: { Authorization: `Bearer ${token}` } });
  return res.ok;
}
```

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- api`
Expected: PASS (3 new + existing api tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/api.ts src/frontend/src/api.test.ts
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): api.ts getToken/clearToken/verifyToken for the login gate"
```

---

## Task G2: `Login.tsx` gate card

**Files:**
- Create: `frontend/src/pages/Login.tsx`
- Test: `frontend/src/pages/Login.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/Login.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- Login`
Expected: FAIL — `./Login` does not exist (cannot resolve import).

- [ ] **Step 3: Implement the component**

Create `frontend/src/pages/Login.tsx`:

```tsx
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
```

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- Login`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/pages/Login.tsx src/frontend/src/pages/Login.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): Login gate card with token validation"
```

---

## Task G3: wire the gate into `App.tsx` + Sign out

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Update the test (failing)**

Replace the entire contents of `frontend/src/App.test.tsx` with (note the extended `./api` mock — without `getToken` the gated `App` would throw on every test):

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';

vi.mock('./api', () => ({
  setToken: vi.fn(),
  getToken: vi.fn(),
  clearToken: vi.fn(),
  verifyToken: vi.fn(),
  listPlans: vi.fn().mockResolvedValue([]),
  getPlan: vi.fn().mockResolvedValue(null),
  createPlan: vi.fn(),
  getProgress: vi.fn(),
  approvePlan: vi.fn(),
  rejectPlan: vi.fn(),
  editSetpoints: vi.fn(),
}));

import { getToken, clearToken } from './api';

vi.mock('./pages/Dashboard', () => ({ default: () => <div>DashboardPage</div> }));
vi.mock('./pages/NewPlan',   () => ({ default: () => <div>NewPlanPage</div> }));
vi.mock('./pages/Review',    () => ({ default: () => <div>ReviewPage</div> }));
vi.mock('./pages/History',   () => ({ default: () => <div>HistoryPage</div> }));
vi.mock('./pages/DigitalTwin3D', () => ({ default: () => <div>DigitalTwin3DPage</div> }));

const mockGetToken = getToken as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  mockGetToken.mockReturnValue('op');          // default: already authed
});

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

  it('shows the login gate when no token is stored', () => {
    mockGetToken.mockReturnValue('');
    render(<App />);
    expect(screen.getByLabelText(/access token/i)).toBeInTheDocument();
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument();   // nav hidden behind the gate
  });

  it('signs out: clears the token and returns to the gate', () => {
    render(<App />);                                                    // authed (getToken -> 'op')
    fireEvent.click(screen.getByText('Sign out'));
    expect(clearToken).toHaveBeenCalled();
    expect(screen.getByLabelText(/access token/i)).toBeInTheDocument();
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it, verify it fails**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- App`
Expected: FAIL — the two new tests (`shows the login gate…`, `signs out…`) fail because `App` has no gate yet (it renders the nav unconditionally; there is no `Sign out`).

- [ ] **Step 3: Implement the gate in `App.tsx`**

In `frontend/src/App.tsx`:

(a) After the existing page imports (the line `import History from './pages/History';`), add:

```tsx
import Login from './pages/Login';
import { getToken, clearToken } from './api';
```

(b) Add the `authed` state as the **first hook**, but place the guard `return` **after all three `useState` calls** — an early return *between* `useState` calls violates the Rules of Hooks (authed render = 3 hooks, unauthed = 1), and React 19 throws "Rendered fewer hooks than expected" when Sign out toggles `authed`. The top of the function body must read exactly:

```tsx
export default function App() {
  const [authed, setAuthed] = useState(() => !!getToken());
  const [page, setPage] = useState<Page>('dashboard');
  // reviewPlanId can be set from History to deep-link to a specific plan
  const [reviewPlanId, setReviewPlanId] = useState<string | undefined>(undefined);

  if (!authed) return <Login onAuthed={() => setAuthed(true)} />;
```

(i.e. add the `authed` line above the existing two `useState` lines, and put the guard `if (!authed) …` below all of them, before `function openReview(…)`.)

(c) In the header, add a **Sign out** button right after the closing `</nav>` (replace the existing `</nav>\n\n      </header>` region):

```tsx
        </nav>

        <button className="signout" onClick={() => { clearToken(); setAuthed(false); }}
          style={{ marginLeft: 'auto' }}>Sign out</button>
      </header>
```

(The `marginLeft: 'auto'` pushes Sign out to the right edge of the flex header; the `signout` class is harmless if no CSS rule exists yet.)

- [ ] **Step 4: Run tests + build, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`
Expected: all vitest pass (incl. the 2 new App tests, Login, api); `tsc -b && vite build` clean (no TS6133 unused-import errors — `useState` is already imported in `App.tsx`).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/App.tsx src/frontend/src/App.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): gate the app behind token login + header Sign out"
```

---

## Final verification

- [ ] Full frontend suite green: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test`.
- [ ] Build clean: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`.
- [ ] Python suite untouched/green (no backend change): `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -q`.
- [ ] Manual sanity (optional): build + serve, open the app → login card; wrong token → "Invalid token"; `op-secret` → app loads; Sign out → back to card.
