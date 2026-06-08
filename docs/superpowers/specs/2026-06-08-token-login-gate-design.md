# Token Login Gate — Design Spec

- **Date:** 2026-06-08
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope:** Frontend-only (React/Vite/TS in `src/frontend/`). No backend change.

---

## 1. Problem statement

The backend uses **fail-closed bearer-token auth** (operator/expert roles; `TokenAuth`). The frontend
reads its token from `localStorage["token"]` (`api.ts`), but **nothing in the UI ever sets it** —
`setToken()` is exported yet called only in tests. So `TOKEN` is always `""`, every `req()` sends
`Authorization: Bearer ` (empty), and every `/api/*` call returns **401**. The app shell renders (static
assets are unauthenticated) but no data loads, and there is no way to authenticate short of editing
`localStorage` in DevTools.

**Goal:** a minimal login UI so an operator can enter, and later clear/change, their token — making the
app usable. **Chosen approach (locked in brainstorming):** a **blocking login gate with validation** — the
app is replaced by a login card until a token that the backend accepts is entered; a header **Sign out**
clears it.

## 2. Goals / non-goals

**Goals**
- A login card shown whenever no token is stored; the rest of the app does not mount until authed (so the
  on-load 401 storm disappears).
- The entered token is **validated against the backend** before the app is entered; a wrong token is
  reported immediately rather than surfacing as 401s deep in the app.
- A **Sign out** control that clears the token and returns to the gate.

**Non-goals**
- No backend change — validation reuses the existing `GET /api/plans` (operator-minimum).
- No role display in the UI (the backend returns no role; operator-vs-expert stays enforced per action via
  403 where those actions live).
- No user accounts / passwords / hashing — tokens *are* the auth model.
- No change to persistence — the token stays in `localStorage` (already persistent across reloads).

## 3. Decision locked in brainstorming

| Question | Decision |
|---|---|
| How the operator enters the token | **Blocking login gate + validation** (not a header field, not a no-validation gate). |
| Validation probe | `GET /api/plans` (operator-min; 200 = valid, 401 = invalid) via a raw fetch that does **not** mutate the global `TOKEN`. |
| Sign out | Header button → `clearToken()` + return to the gate. |

## 4. Component design

### 4.1 `frontend/src/api.ts` — token helpers + validation

`TOKEN` and `setToken` exist. Add:

```ts
export function getToken(): string { return TOKEN; }
export function clearToken(): void { TOKEN = ""; localStorage.removeItem("token"); }

// Probe the operator-minimum endpoint WITHOUT mutating the global TOKEN, so a bad
// token is never stored. 200 -> valid, 401/403 -> invalid.
export async function verifyToken(token: string): Promise<boolean> {
  const res = await fetch("/api/plans", { headers: { Authorization: `Bearer ${token}` } });
  return res.ok;
}
```

(`verifyToken` may still throw on a network failure — the caller treats a thrown error as "backend
unreachable", distinct from an invalid token.)

### 4.2 `frontend/src/pages/Login.tsx` — the gate card (new)

```tsx
export default function Login({ onAuthed }: { onAuthed: () => void }) { … }
```

- Local state: `value` (input), `error` (string | null), `busy` (bool).
- Markup: a centered card — the `DCTwin` logo/dot, heading "Enter your access token", a
  `type="password"` input (`aria-label="access token"`), a **Continue** submit button (disabled while
  `busy` or empty), an error line when `error`, and the hint "operator or expert token". Wrapped in a
  `<form onSubmit=…>` so Enter submits.
- Submit handler:
  ```
  e.preventDefault(); const t = value.trim(); if (!t) return;
  setBusy(true); setError(null);
  try {
    if (await verifyToken(t)) { setToken(t); onAuthed(); }
    else { setError("Invalid token — check with your operator."); setBusy(false); }
  } catch { setError("Can't reach the backend — is it running?"); setBusy(false); }
  ```
- Styling reuses existing classes/CSS variables (e.g. `app-logo`, `logo-dot`, button styles); no new design
  system.

### 4.3 `frontend/src/App.tsx` — wire the gate + sign out

- `import Login from './pages/Login'` and `import { getToken, clearToken } from './api'`.
- `const [authed, setAuthed] = useState(() => !!getToken());`
- Early return before the shell: `if (!authed) return <Login onAuthed={() => setAuthed(true)} />;`
- In the existing `app-header`, add a **Sign out** button (right of the nav) →
  `onClick={() => { clearToken(); setAuthed(false); }}`.
- The rest of `App.tsx` (nav, page switching, `Suspense` 3D) is unchanged.

## 5. Data flow

1. Load → `App` reads `getToken()`. Empty → render `Login`.
2. Operator types token → submit → `verifyToken` (raw `GET /api/plans` with that bearer).
3. 200 → `setToken` (persists to `localStorage`) → `onAuthed()` → `App` re-renders the shell; pages mount
   and their `/api/*` calls now carry the valid bearer (REST via `req`, SSE via `planStreamUrl`'s
   `?token=`).
4. 401/403 → "Invalid token" shown; nothing stored; stay on the gate.
5. Sign out → `clearToken()` → gate again.

## 6. Error handling

- Empty input → submit is a no-op (button disabled).
- Invalid token (backend 401/403) → inline "Invalid token — check with your operator."; token not stored.
- Backend unreachable (fetch throws) → inline "Can't reach the backend — is it running?".
- An already-stored token that has since become invalid (e.g. backend restarted with different tokens)
  still admits the user to the shell, where the per-page 401 handling applies; **Sign out** lets them
  re-enter. (Re-validating a stored token on load is out of scope — YAGNI.)

## 7. Testing strategy (vitest, TDD)

**`Login.test.tsx`** (new):
- valid token: mock `verifyToken → true`; type + submit; assert `setToken` called with the token **and**
  `onAuthed` called.
- invalid token: mock `verifyToken → false`; submit; assert the error text appears and `onAuthed` is **not**
  called and `setToken` is **not** called.
- (optional) network error: `verifyToken` rejects → the "can't reach the backend" message shows.

**`App.test.tsx`** (update): extend the existing `vi.mock('../api', …)` with `getToken`, `clearToken`,
`verifyToken`. Two cases: `getToken → ""` renders the Login card (assert the "access token" field; assert
the nav is **absent**); `getToken → "op"` renders the nav (existing behaviour). Adjust any existing
assertion that assumed the app renders unconditionally.

**Build:** `npm run build` (`tsc -b && vite build`) stays clean — `noUnusedLocals` is on, so unused imports
fail the build; keep imports tight.

No backend/pytest change.

## 8. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **G1** | `api.ts`: `getToken` / `clearToken` / `verifyToken` (+ unit test of `verifyToken`) | token plumbing |
| **G2** | `pages/Login.tsx` gate card + `Login.test.tsx` (valid / invalid) | the gate |
| **G3** | `App.tsx` wiring + Sign out + `App.test.tsx` update | gating the app |

## 9. Reference file index

- `frontend/src/api.ts` (`TOKEN`, `setToken`, `req`; add `getToken`/`clearToken`/`verifyToken`).
- `frontend/src/App.tsx` (`useState`, `app-header`, nav; add the gate + Sign out).
- `frontend/src/pages/Login.tsx` (new), `frontend/src/pages/Login.test.tsx` (new),
  `frontend/src/App.test.tsx` (update).
- `frontend/src/index.css` / existing classes (`app-logo`, `logo-dot`, button styles) for the card.
