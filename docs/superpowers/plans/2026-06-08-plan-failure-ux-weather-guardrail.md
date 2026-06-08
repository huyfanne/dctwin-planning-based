# Plan-Failure UX + Weather-Week Guardrail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a failed plan show its real reason, reject out-of-coverage weeks at create-time with a clear 422, and guide New-Plan with an in-range default week + a coverage hint.

**Architecture:** New `planner/epw.py` coverage helpers; a weather guardrail + `GET /api/weather` in `webapp/main.py`; a `record_failure` helper in `webapp/jobs.py`; and a `NewPlan`/`api.ts` change to surface the reason and the hint. Backend reuses the existing progress channel for the failure reason (no store-schema change).

**Tech Stack:** Python 3.13 (venv `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin`), FastAPI/pytest `TestClient`; React 19 + Vite + vitest. No Docker (mock evaluator).

**Spec:** `docs/superpowers/specs/2026-06-08-plan-failure-ux-weather-guardrail-design.md`

**Conventions for every task:**
- `PY=/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`. The sandbox strips a leading `cd` — use `env -C <dir>`.
- Backend tests: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest <path> -v`. Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- <name>` and `npm run build`.
- Branch `feat/weather-guardrail` (already created); do NOT switch branches. Commit after each task (repo appends a `Co-Authored-By` trailer — keep it).

---

## File map

| File | Change | Task |
|---|---|---|
| `planner/epw.py` | add `weather_coverage`, `epw_first_date` | W1 |
| `tests/test_epw.py` | tests for the helpers | W1 |
| `webapp/main.py` | `create_plan` weather 422 + `GET /api/weather` | W2, W3 |
| `tests/test_api.py` | 422 + endpoint tests | W2, W3 |
| `webapp/jobs.py` | `record_failure` helper + use it in `_loop` | W4 |
| `tests/test_jobs.py` | `record_failure` tests | W4 |
| `frontend/src/api.ts` | `Progress.error`, `WeatherCoverage`, `getWeather` | W5 |
| `frontend/src/pages/NewPlan.tsx` | real reason + hint + default | W5 |
| `frontend/src/pages/NewPlan.test.tsx` | mock `getWeather` + 2 tests | W5 |

A reusable test fixture (a minimal EPW) is defined inline in both `test_epw.py` and `test_api.py`:

```python
def _make_epw(p):
    """A minimal EPW: 8 header lines (DATA PERIODS covering Nov 1 – Jan 31) + one data row."""
    lines = ["LOCATION,X", "DESIGN CONDITIONS,0", "TYPICAL/EXTREME PERIODS,0",
             "GROUND TEMPERATURES,0", "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
             "COMMENTS 1,", "COMMENTS 2,",
             "DATA PERIODS,1,1,Data,Friday, 11/ 1, 1/31", "2024,11,1,1,0"]
    p.write_text("\n".join(lines) + "\n")
    return str(p)
```

---

## Task W1: `epw.py` coverage helpers

**Files:**
- Modify: `planner/epw.py`
- Test: `tests/test_epw.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_epw.py` (add `from datetime import date` if not already imported):

```python
def _make_epw(p):
    lines = ["LOCATION,X", "DESIGN CONDITIONS,0", "TYPICAL/EXTREME PERIODS,0",
             "GROUND TEMPERATURES,0", "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
             "COMMENTS 1,", "COMMENTS 2,",
             "DATA PERIODS,1,1,Data,Friday, 11/ 1, 1/31", "2024,11,1,1,0"]
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_weather_coverage_label_and_md(tmp_path):
    from planner.epw import weather_coverage
    cov = weather_coverage(_make_epw(tmp_path / "w.epw"))
    assert cov["label"] == "Nov 1 – Jan 31"
    assert cov["start_md"] == "11-01"
    assert cov["end_md"] == "01-31"


def test_epw_first_date(tmp_path):
    from datetime import date
    from planner.epw import epw_first_date
    assert epw_first_date(_make_epw(tmp_path / "w.epw")) == date(2024, 11, 1)
```

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_epw.py -k "weather_coverage or epw_first_date" -v`
Expected: FAIL — `cannot import name 'weather_coverage'` / `'epw_first_date'`.

- [ ] **Step 3: Implement the helpers**

In `planner/epw.py`, add after `epw_data_period` (keep `date`/`Path` imports already at the top):

```python
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def weather_coverage(weather_file: str) -> dict:
    """Human + machine view of the EPW's covered window (month/day, year-agnostic)."""
    (sm, sd), (em, ed) = epw_data_period(weather_file)
    return {
        "label": f"{_MONTHS[sm]} {sd} – {_MONTHS[em]} {ed}",
        "start_md": f"{sm:02d}-{sd:02d}",
        "end_md": f"{em:02d}-{ed:02d}",
    }


def epw_first_date(weather_file: str) -> date:
    """First concrete date in the EPW data block (8 header lines, then CSV rows
    'year,month,day,hour,…'). Used to suggest an in-range default week_start."""
    rows = Path(weather_file).read_text().splitlines()
    f = rows[8].split(",")
    return date(int(f[0]), int(f[1]), int(f[2]))
```

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_epw.py -v`
Expected: PASS (2 new + existing epw tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/planner/epw.py src/tests/test_epw.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): epw weather_coverage + epw_first_date helpers"
```

---

## Task W2: `create_plan` weather guardrail (422)

**Files:**
- Modify: `webapp/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py` (reuses the `client` fixture + `_op()`):

```python
def _make_epw(p):
    lines = ["LOCATION,X", "DESIGN CONDITIONS,0", "TYPICAL/EXTREME PERIODS,0",
             "GROUND TEMPERATURES,0", "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
             "COMMENTS 1,", "COMMENTS 2,",
             "DATA PERIODS,1,1,Data,Friday, 11/ 1, 1/31", "2024,11,1,1,0"]
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_create_rejects_week_outside_weather_coverage(client, tmp_path, monkeypatch):
    epw = _make_epw(tmp_path / "w.epw")
    monkeypatch.setattr("webapp.jobs.pickle_load", lambda path: {"weather_file": epw})
    r = client.post("/api/plans", json={"week_start": "2026-06-08"}, headers=_op())
    assert r.status_code == 422
    assert "coverage" in r.json()["detail"].lower()


def test_create_accepts_week_inside_weather_coverage(client, tmp_path, monkeypatch):
    epw = _make_epw(tmp_path / "w.epw")
    monkeypatch.setattr("webapp.jobs.pickle_load", lambda path: {"weather_file": epw})
    r = client.post("/api/plans", json={"week_start": "2024-11-11"}, headers=_op())
    assert r.status_code == 202
```

(`create_plan` does `from webapp.jobs import pickle_load` lazily, so monkeypatching `webapp.jobs.pickle_load` takes effect at request time.)

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -k "weather_coverage" -v`
Expected: FAIL — the out-of-range post returns `202` (no guardrail yet), so the `== 422` assertion fails.

- [ ] **Step 3: Add the guardrail to `create_plan`**

In `webapp/main.py` `create_plan`, insert between the `except ValueError … raise HTTPException(422, str(e))` block and the `plan_id = f"gds-…"` line:

```python
        # week-vs-weather guardrail (strict only when the configured EPW is readable)
        try:
            from webapp.jobs import pickle_load
            from planner.epw import week_within_epw, weather_coverage
            _wf = pickle_load(p.get("forecaster", "models/forecaster.pkl")).get("weather_file")
        except Exception:
            _wf = None
        if _wf:
            _week = _date.fromisoformat(p["week_start"])
            _days = _v("days", 7)
            if not week_within_epw(_wf, _week, _days):
                _cov = weather_coverage(_wf)
                raise HTTPException(422, f"week {_week} (+{_days}d) is outside the weather data "
                                         f"coverage ({_cov['label']}); pick a week within that window.")
```

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -v`
Expected: PASS (the 2 new + all existing api tests; existing tests have no forecaster pkl so `_wf` is None and they are unaffected).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/main.py src/tests/test_api.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): reject out-of-coverage week at create with a clear 422"
```

---

## Task W3: `GET /api/weather` endpoint

**Files:**
- Modify: `webapp/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py` (reuses `_make_epw` from W2):

```python
def test_weather_endpoint_returns_coverage(client, tmp_path, monkeypatch):
    epw = _make_epw(tmp_path / "w.epw")
    monkeypatch.setattr("webapp.jobs.pickle_load", lambda path: {"weather_file": epw})
    body = client.get("/api/weather", headers=_op()).json()
    assert body["label"] == "Nov 1 – Jan 31"
    assert body["suggested_week_start"] == "2024-11-01"


def test_weather_endpoint_null_when_no_forecaster(client, monkeypatch):
    def _raise(path): raise FileNotFoundError()
    monkeypatch.setattr("webapp.jobs.pickle_load", _raise)
    body = client.get("/api/weather", headers=_op()).json()
    assert body["suggested_week_start"] is None and body["label"] is None
```

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -k "weather_endpoint" -v`
Expected: FAIL — `GET /api/weather` is undefined → 404, so `.json()["label"]` is wrong.

- [ ] **Step 3: Add the endpoint**

In `webapp/main.py`, add right after the `@app.get("/api/calibration")` route (and before the static-frontend mount at the end of `create_app`):

```python
    @app.get("/api/weather")
    def get_weather(role: str = Depends(operator)):
        try:
            from webapp.jobs import pickle_load
            from planner.epw import weather_coverage, epw_first_date
            wf = pickle_load("models/forecaster.pkl").get("weather_file")
            cov = weather_coverage(wf)
            return {**cov, "file": wf, "suggested_week_start": epw_first_date(wf).isoformat()}
        except Exception:
            return {"label": None, "start_md": None, "end_md": None,
                    "file": None, "suggested_week_start": None}
```

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_api.py -k "weather" -v`
Expected: PASS (the 2 endpoint tests + the 2 W2 guardrail tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/main.py src/tests/test_api.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): GET /api/weather exposes coverage + suggested week_start"
```

---

## Task W4: `jobs.record_failure` persists the reason

**Files:**
- Modify: `webapp/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jobs.py`:

```python
def test_record_failure_stores_reason_and_status(tmp_path):
    from webapp.jobs import record_failure
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p1", "2024-11-11", {})
    record_failure(store, "p1", ValueError("boom"))
    assert store.read_progress("p1") == {"error": "boom"}
    assert store.get_plan_row("p1")["status"] == "failed"


def test_record_failure_falls_back_to_class_name(tmp_path):
    from webapp.jobs import record_failure
    from webapp.store import PlanStore
    store = PlanStore(runs_dir=str(tmp_path / "runs"), db_path=str(tmp_path / "i.db"))
    store.create_plan("p2", "2024-11-11", {})
    record_failure(store, "p2", RuntimeError())          # str(exc) == ""
    assert store.read_progress("p2") == {"error": "RuntimeError"}
```

- [ ] **Step 2: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_jobs.py -k record_failure -v`
Expected: FAIL — `cannot import name 'record_failure'`.

- [ ] **Step 3: Implement + wire it in**

In `webapp/jobs.py`, add a module-level helper (next to `pickle_load`):

```python
def record_failure(store, plan_id: str, exc: Exception) -> None:
    """Persist a failure reason via the progress channel, then mark the plan failed,
    so the SSE frame ({progress, status}) carries progress.error."""
    store.write_progress(plan_id, {"error": str(exc) or exc.__class__.__name__})
    store.set_status(plan_id, "failed")
```

Then change the `_loop` except block (currently `except Exception:` … `logger.exception("plan %s failed", plan_id)` … `self.store.set_status(plan_id, "failed")`) to capture and record the exception:

```python
            except Exception as e:  # noqa: BLE001
                logger.exception("plan %s failed", plan_id)
                record_failure(self.store, plan_id, e)
```

- [ ] **Step 4: Run them, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest tests/test_jobs.py -v`
Expected: PASS (2 new + existing jobs tests).

- [ ] **Step 5: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/webapp/jobs.py src/tests/test_jobs.py
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): record_failure persists the plan failure reason for the UI"
```

---

## Task W5: New-Plan shows the reason + coverage hint/default

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/NewPlan.tsx`
- Test: `frontend/src/pages/NewPlan.test.tsx`

- [ ] **Step 1: Add the API surface to `api.ts`**

In `frontend/src/api.ts`:

(a) Add `error?: string;` to the `Progress` interface (currently `export interface Progress { level?: number; evals?: number; best_score?: number; }`):

```ts
export interface Progress { level?: number; evals?: number; best_score?: number; error?: string; }
```

(b) Add after the `getCalibration` export:

```ts
export interface WeatherCoverage {
  label: string | null;
  start_md?: string | null;
  end_md?: string | null;
  file?: string | null;
  suggested_week_start: string | null;
}
export const getWeather = () => req<WeatherCoverage>("/api/weather");
```

- [ ] **Step 2: Update the NewPlan tests (failing)**

In `frontend/src/pages/NewPlan.test.tsx`:

(a) Add `getWeather: vi.fn(),` to the `vi.mock('../api', …)` factory object (alongside `createPlan`/`getProgress`/`getPlan`/`planStreamUrl`).

(b) Change the import line to `import { createPlan, getWeather } from '../api';`.

(c) In the `beforeEach`, after `vi.clearAllMocks();`, add a safe default so every test's mount fetch resolves:

```ts
  (getWeather as ReturnType<typeof vi.fn>).mockResolvedValue({ label: null, suggested_week_start: null });
```

(d) Add two tests inside `describe('NewPlan', …)`:

```tsx
  it('shows the real failure reason from the stream', async () => {
    (createPlan as ReturnType<typeof vi.fn>).mockResolvedValue({ plan_id: 'pf', status: 'queued' });
    render(<NewPlan onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText(/week start/i), { target: { value: '2024-11-11' } });
    fireEvent.click(screen.getByText(/launch optimization/i));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit({ progress: { error: 'week 2026-06-08 is outside coverage' }, status: 'failed' });
    await waitFor(() => expect(screen.getByText(/outside coverage/i)).toBeInTheDocument());
  });

  it('prefills week start and shows the coverage hint', async () => {
    (getWeather as ReturnType<typeof vi.fn>).mockResolvedValue({ label: 'Nov 1 – Jan 31', suggested_week_start: '2024-11-01' });
    render(<NewPlan onDone={() => {}} />);
    await waitFor(() => expect(screen.getByText(/weather data covers/i)).toBeInTheDocument());
    expect((screen.getByLabelText(/week start/i) as HTMLInputElement).value).toBe('2024-11-01');
  });
```

- [ ] **Step 3: Run them, verify they fail**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test -- NewPlan`
Expected: FAIL — the failure test still shows the hardcoded Docker message (not "outside coverage"); the prefill test finds no hint and an empty week-start (NewPlan doesn't fetch weather yet).

- [ ] **Step 4: Implement in `NewPlan.tsx`**

(a) Change the import (line 2) to: `import { createPlan, planStreamUrl, getWeather, type Progress } from '../api';`

(b) Add a coverage state next to the others (after the `error` state): `const [coverage, setCoverage] = useState<string | null>(null);`

(c) Add a mount effect (place it just above the existing SSE `useEffect`):

```tsx
  useEffect(() => {
    getWeather().then(w => {
      setCoverage(w.label);
      if (w.suggested_week_start) setWeekStart(prev => prev || w.suggested_week_start!);
    }).catch(() => {});
  }, []);
```

(d) In the SSE `onmessage` handler, replace the hardcoded failed-status message:

```tsx
      if (frame.status === 'failed') {
        setError(frame.progress?.error ?? 'Plan run failed on the server — see the backend log (the backend may lack Docker access for EnergyPlus).');
        es.close();
```

(e) Render the coverage hint right after the Week-start `<input … id="week-start" … />` (before its closing wrapper):

```tsx
                {coverage && <div className="field-hint" style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>Weather data covers {coverage}.</div>}
```

- [ ] **Step 5: Run tests + build, verify pass**

Run: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test` then `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build`
Expected: all vitest pass (incl. the 2 new NewPlan tests); `tsc -b && vite build` clean (no TS6133 — `getWeather`/`Progress` are used; `useEffect` already imported).

- [ ] **Step 6: Commit**

```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git add src/frontend/src/api.ts src/frontend/src/pages/NewPlan.tsx src/frontend/src/pages/NewPlan.test.tsx
env -C /mnt/lv/home/hoanghuy/newcode/dctwin git commit -m "feat(dtwin): New-Plan shows the real failure reason + weather coverage hint/default"
```

---

## Final verification

- [ ] Full unit suite green: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src $PY -m pytest -q`.
- [ ] Frontend: `env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test && npm run build`.
- [ ] Manual sanity (optional): serve, open New-Plan → field pre-filled with an in-range date + "Weather data covers Nov 1 – Jan 31"; submit a June week → inline 422; submit an in-range week → runs.
