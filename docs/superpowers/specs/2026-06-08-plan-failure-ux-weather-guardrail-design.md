# Plan-Failure UX + Weather-Week Guardrail — Design Spec

- **Date:** 2026-06-08
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope:** Backend (`webapp/`, `planner/epw.py`) + a focused frontend change (`NewPlan.tsx`, `api.ts`).

---

## 1. Problem statement

A user created a plan with `week_start = 2026-06-08`, but the configured weather EPW
(`Singapore_Changi_Nov2024-Jan2025.epw`) covers only **Nov 1 – Jan 31**. The planner correctly raised
`ValueError: week 2026-06-08 (+7d) is outside the weather file coverage …` (`planner/week_config.py` →
`week_within_epw`). Three defects made this confusing:

1. **The reason is hidden.** `jobs.py` catches any plan exception and calls `store.set_status(id, "failed")`
   **without storing the message**; `NewPlan.tsx` then shows a **hardcoded** "backend not started with Docker
   (`sg docker`)" string for *every* failure — so a weather-range error reads as a Docker problem.
2. **No guardrail.** `validate_plan_request` checks grid/beam/days/weights but **not** the week against the
   weather coverage, so an out-of-range week passes create and fails later in the background.
3. **No guidance.** New-Plan's `weekStart` field defaults to empty and offers no hint about the valid window,
   so the user has nothing steering them to an in-range week.

**Goal (chosen scope — "Full"):** surface the real failure reason; pre-validate the week at create-time;
and guide New-Plan with a valid default + a coverage hint.

## 2. Goals / non-goals

**Goals**
- Any failed plan shows its **actual reason** in New-Plan (with a generic fallback when none was captured).
- An out-of-coverage week is rejected at **create-time** with a clear `422` naming the valid window — before
  the background job runs.
- New-Plan **defaults to an in-range week** and shows the coverage window, so the default action succeeds.

**Non-goals**
- Showing the failure reason on History/Review (they keep the `failed` badge).
- Changing the weather file, or supporting typical-year / multi-year / year-crossing weeks (still rejected by
  the existing `compute_week_period`).
- A store-schema change for the reason — it rides the existing progress channel.

## 3. Component design

### 3.1 `planner/epw.py` — coverage helpers (Part 2/3 support)

Add two pure helpers next to the existing `epw_data_period` / `week_within_epw`:

```python
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def weather_coverage(weather_file: str) -> dict:
    """Human + machine view of the EPW's covered window (month/day, year-agnostic)."""
    (sm, sd), (em, ed) = epw_data_period(weather_file)
    return {
        "label": f"{_MONTHS[sm]} {sd} – {_MONTHS[em]} {ed}",   # "Nov 1 – Jan 31"
        "start_md": f"{sm:02d}-{sd:02d}",
        "end_md": f"{em:02d}-{ed:02d}",
    }

def epw_first_date(weather_file: str) -> date:
    """First concrete date in the EPW data block (8 header lines, then CSV rows
    'year,month,day,hour,…'). Used to suggest an in-range default week_start."""
    # read past the 8 EPW header lines; parse the first data row's y/m/d
```

### 3.2 `webapp/main.py` `create_plan` — weather pre-validation (Part 2)

After the existing `validate_plan_request` block, add an advisory-but-strict weather check:

```python
# week-vs-weather guardrail: strict only when we can read the configured EPW
try:
    from webapp.jobs import pickle_load
    from planner.epw import week_within_epw, weather_coverage
    wf = pickle_load(p.get("forecaster", "models/forecaster.pkl")).get("weather_file")
except Exception:
    wf = None
if wf:
    week = _date.fromisoformat(p["week_start"]); ndays = _v("days", 7)
    if not week_within_epw(wf, week, ndays):
        cov = weather_coverage(wf)
        raise HTTPException(422, f"week {week} (+{ndays}d) is outside the weather data "
                                 f"coverage ({cov['label']}); pick a week within that window.")
```

A missing/unreadable forecaster leaves `wf = None` → the check is skipped (never blocks creation on the
validation machinery itself, only on a *confirmed* out-of-range week).

### 3.3 `webapp/main.py` — `GET /api/weather` (Part 3)

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

Operator-min (matches the other read endpoints). Always `200` with a graceful null shape when the forecaster
isn't fitted, so the frontend hint simply doesn't render.

### 3.4 `webapp/jobs.py` — persist the failure reason (Part 1)

Extract a small module-level helper (unit-testable without the threaded runner), and call it from the
`except` in `JobRunner._loop` (currently `logger.exception(...); self.store.set_status(id, "failed")`):

```python
def record_failure(store, plan_id: str, exc: Exception) -> None:
    """Persist a failure reason via the progress channel, then mark the plan failed,
    so the SSE frame ({progress, status}) carries progress.error."""
    store.write_progress(plan_id, {"error": str(exc) or exc.__class__.__name__})
    store.set_status(plan_id, "failed")
```

```python
except Exception as e:  # noqa: BLE001
    logger.exception("plan %s failed", plan_id)
    record_failure(self.store, plan_id, e)
```

`write_progress` runs **before** `set_status("failed")`, so by the time the SSE frame reports `failed`,
`progress_frame` (`{progress, status}`) already carries `progress.error`.

### 3.5 Frontend (`api.ts`, `NewPlan.tsx`) — show the reason + the guide (Parts 1/3)

- `api.ts`:
  - `Progress` interface gains `error?: string`.
  - `interface WeatherCoverage { label: string | null; start_md?: string | null; end_md?: string | null;
    file?: string | null; suggested_week_start: string | null; }`
  - `export const getWeather = () => req<WeatherCoverage>("/api/weather");`
- `NewPlan.tsx`:
  - On the failed SSE frame: `setError(frame.progress?.error ?? '<generic fallback>')` (fallback keeps a
    short "see the backend log; the backend may lack Docker access for EnergyPlus" note).
  - On mount: `getWeather()` → if `suggested_week_start` and the field is empty, `setWeekStart(suggested)`;
    store `label` and render a hint under the Week-start input: *"Weather data covers {label}."* (rendered
    only when `label` is non-null).

## 4. Data flow

- **Create (happy path):** New-Plan mounts → `GET /api/weather` → field pre-filled with `suggested_week_start`
  + hint shown → submit → `create_plan` weather check passes → `202` → runs.
- **Create (bad week):** user overrides with an out-of-range week → `create_plan` → `422` with the window →
  `NewPlan.createPlan` catch shows `e.message`. No job runs.
- **Runtime failure (any cause):** job throws → `jobs` writes `{error}` to progress + `failed` → SSE frame
  `{progress:{error}, status:"failed"}` → New-Plan shows `progress.error`.

## 5. Error handling

- Out-of-range week → `422` (create-time) with the coverage label; surfaced inline by New-Plan.
- Forecaster/EPW unreadable at create → guardrail skipped (creation proceeds; a genuine runtime failure then
  surfaces its real reason via Part 1).
- `/api/weather` unreadable → `200` with null fields → no hint, no default change (field stays empty,
  existing "required" validation applies).
- Background failure with an empty `str(e)` → store `e.__class__.__name__` so the UI never shows a blank.

## 6. Testing strategy

**Backend (pytest, mock evaluator — no Docker):**
- `weather_coverage` label + `start_md`/`end_md` for a small fixture EPW; `epw_first_date` returns the first
  data row's date. (Use a tiny inline EPW with a `DATA PERIODS` header + a couple of data rows under tmp.)
- `create_plan`: an out-of-range week → `422` mentioning the window; an in-range week → `202`. Seed the
  forecaster config the test uses (or monkeypatch `pickle_load`) so `weather_file` points at the fixture EPW.
- `GET /api/weather`: returns the label + a `suggested_week_start`; returns the null shape when the forecaster
  is absent.
- `jobs.record_failure(store, id, exc)`: called directly with a seeded store + an exception → `read_progress`
  carries `{"error": …}` and `get_plan_row` status is `failed` (no threading; empty `str(exc)` falls back to
  the class name).

**Frontend (vitest):**
- New-Plan shows `progress.error` from a failed SSE frame (mock `EventSource` per the existing pattern).
- New-Plan calls `getWeather` on mount, pre-fills `weekStart` with `suggested_week_start`, and renders the
  coverage hint.

**Build:** `npm run build` clean (`noUnusedLocals`).

## 7. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **W1** | `epw.py` `weather_coverage` + `epw_first_date` (+ tests) | coverage helpers |
| **W2** | `create_plan` weather pre-validation → 422 (+ tests) | the guardrail |
| **W3** | `GET /api/weather` endpoint (+ test) | coverage exposure |
| **W4** | `jobs.py` persist failure reason (+ test) | reason surfacing (backend) |
| **W5** | `api.ts` (`Progress.error`, `getWeather`) + `NewPlan` reason/hint/default (+ vitest) | the UX |

## 8. Reference file index

- `planner/epw.py` (`epw_data_period`, `week_within_epw`; add `weather_coverage`, `epw_first_date`).
- `webapp/main.py` (`create_plan` synchronous validation; add the weather check + `GET /api/weather`).
- `webapp/jobs.py` (`run_plan_job` except block; `pickle_load`).
- `webapp/store.py` (`write_progress`, `set_status`, `read_progress` — unchanged, reused).
- `frontend/src/api.ts` (`Progress`, add `WeatherCoverage` + `getWeather`).
- `frontend/src/pages/NewPlan.tsx` (failed-frame message; mount fetch → default + hint).
