# New-Plan Planning Decks + Display Fixes — Design Spec

- **Date:** 2026-06-09
- **Stage:** 4th draft
- **Status:** Approved design (autonomous — goal-directed) → ready for implementation plan
- **Scope:** `src/planner/epw.py`, `src/planner/forecaster.py` (read helper), `src/webapp/main.py`, `src/webapp/schemas.py`, `src/frontend/src/api.ts`, `src/frontend/src/pages/NewPlan.tsx`, `History.tsx`, `Review.tsx`, `Dashboard.tsx`.

---

## 1. Problem

Two independent asks for the 4th stage:

**Part 1 — Better next-week planning context on the New Plan page.** Before launching an optimization for a week, the operator should *see the inputs*: the recent and forecast IT load, the recent and forecast weather, and what setpoints ran last week. Currently the page is just a parameter form.

**Part 2 — Three display gaps** the operator reported:
- (2a) Dashboard does not show "Reduction vs Baseline".
- (2b) Review page does not show baseline + delta values.
- (2c) History "Predicted vs Realised — HVAC Energy" graph does not show the Realised line.

## 2. Root causes (verified before design)

- **2a + 2b are a STALE-BACKEND data problem, not a frontend bug.** The live backend process started 2026-06-08 ~13:00; the code that makes `run_weekly_plan` emit a `baseline` block + `energy_reduction_vs_baseline_pct` (`jobs.py` passing `baseline_setpoints` + `energy_scope`) landed in commit `83e83d84` at 15:58. So the running server executes pre-baseline code → every plan it writes is **schema 1.4 with no baseline**. The frontend already renders baseline/reduction *when present* (`Dashboard.tsx:158-209`, `Review.tsx:170-190`) and intentionally hides the comparison when absent. **Fix = restart the backend on current code** (new plans get schema 1.7 + baseline), **plus** a graceful "baseline not available for this plan" state so *old* schema-1.4 plans don't look silently broken.
- **2c is a REAL frontend bug.** The realised value *exists* (deployed plan `gds-2024-12-15-e80285` has `realized_energy_kwh=361829`), but the realised `<Line>` uses `dot={false}` (`History.tsx:122`). A single non-null realised point surrounded by `null`s (only one plan is deployed) draws **no segment and no dot → invisible**. Fix = render visible dots for realised (and predicted), so isolated points show.

## 3. Part 1 design — New Plan planning context

### 3.1 Data sources (confirmed)
| Series | Source | Resolution | Notes |
|---|---|---|---|
| Past IT load (1b) | `his_data` col `1F_Datahall 2A 1F Data Hall 2A IT loads`, sliced `[week_start−7d, week_start)` | 15-min | kW; the controlled hall (1F 2A) |
| Forecast IT load (1d) | `forecaster.forecast(week_start, n_steps)` → per-ITE loading fraction; aggregate hall kW = Σ_ite fraction·capacity_kw (1F 2A cap = 2000 kW over 22 ITEs) | 15-min | same unit (kW) as past, so they combine on one axis |
| Past weather (1c) | EPW slice `[week_start−7d, week_start)`, outdoor dry-bulb °C | hourly | new `epw.weather_timeseries()` |
| Forecast weather (1e) | EPW slice `[week_start, week_start+days)` | hourly | the fixed historical EPW *is* the weather "forecast" (labelled as such) |
| Previous setpoints (1f) | previous-week plan's `recommendation.setpoints`; fallback `as_operated_setpoints(his,…)` | scalar | 3 values |

Units are reconciled **in the backend** (one source of truth): IT-load past is converted to the same kW basis as the forecast (reuse the forecaster's loading→kW capacity mapping). The frontend just plots.

### 3.2 New endpoint — `GET /api/planning-context`
Operator-auth, read-only. Query: `week_start=YYYY-MM-DD`, `days` (default 7), `timesteps_per_hour` (default 4).

Response (`PlanningContext`):
```jsonc
{
  "week_start": "2024-11-08", "days": 7, "timesteps_per_hour": 4,
  "it_load":  { "unit": "kW",
                "past":     [{"t": "2024-11-01T00:00", "kw": 1850.2}, …],   // [] if before data coverage
                "forecast": [{"t": "2024-11-08T00:00", "kw": 1862.0}, …] },
  "weather":  { "unit": "°C",
                "past":     [{"t": "2024-11-01T00:00", "temp_c": 28.3}, …],
                "forecast": [{"t": "2024-11-08T00:00", "temp_c": 29.1}, …] },
  "previous_setpoints": { "source": "previous_plan" | "as_operated" | null,
                          "week_start": "2024-11-01" | null,
                          "setpoints": { "crah_supply_air_temperature_c": 23.0,
                                         "crah_supply_air_mass_flow_rate_kg_s": 6.9,
                                         "chilled_water_supply_temperature_c": 16.07 } | null }
}
```
- Fully guarded: any missing piece returns an empty array / null, never a 500 (the page degrades gracefully — e.g. past IT load is empty for weeks before the history coverage start).
- The endpoint loads the forecaster pickle once per call (same pattern as `GET /api/weather`, `main.py:254-263`). Forecaster build is cheap (no EnergyPlus).

### 3.3 New backend helpers
- `planner/epw.py::weather_timeseries(weather_file, start_date, days, *, field="dry_bulb") -> list[dict]` — parse EPW data rows, return `[{"t": iso, "temp_c": float}]` for `[start_date, start_date+days)`; `[]` if outside coverage. Year-agnostic month/day match (EPW coverage is keyed by md, reuse `_md_in_range`).
- `planner/forecaster.py` (or a small helper in the endpoint): `hall_load_kw_series(his, time_col, load_col, start, days)` for the past series and `forecast_hall_kw(forecast, room2ite_caps)` for the forecast aggregate. Keep them pure + unit-tested.

### 3.4 Frontend — `NewPlan.tsx`
- **1a:** default `week_start` = **`2024-11-08`** (`useState('2024-11-08')`; keep the weather-coverage hint, drop the `suggested_week_start` override so the explicit default wins).
- On mount **and** whenever `week_start` changes (debounced), fetch `getPlanningContext(weekStart, days)` and store it. Charts only render when data is present.
- **Deck A — IT Load (1b+1d combined):** one `LineChart`. Past series + forecast series concatenated on a time axis with a **`ReferenceLine` at `week_start` ("now")**. Two lines: "Past (actual)" + "Forecast". Visible dots off (dense series). Y = kW.
- **Deck B — Weather (1c+1e combined):** same pattern, "Past (actual)" + "Forecast (historical EPW)". Y = °C. `ReferenceLine` at week_start.
- **Deck C — Previous-week setpoints (1f):** a `bracket-card` with the 3 setpoints (reuse the Dashboard setpoint-row style) + a small caption showing the source week (or "as-operated estimate" when no prior plan).
- Layout: the three decks sit **below** the form (a responsive grid `repeat(auto-fit, minmax(320px,1fr))`), shown only when `!planId` (i.e. before a run starts), so the live-progress view is unchanged.
- `api.ts`: `getPlanningContext(weekStart, days)` + the `PlanningContext` types.

## 4. Part 2 design — display fixes

- **2c (History):** realised `<Line dot>` visible (e.g. `dot={{ r: 3 }}`) and predicted likewise; add `connectNulls={false}` so gaps stay gaps but the lone realised point shows as a dot. Keep the existing render guard. (Optional polish: the predicted line currently mixes old facility-scale ~697 MWh plans with hall-scale ~360 MWh, compressing the axis — out of scope; dots fix the reported bug.)
- **2a/2b (graceful states, durable safety net):**
  - `Review.tsx`: when `rec.baseline?.kpis` is absent, render a small inline note in the KPI card — *"Baseline comparison unavailable for this plan (created before the baseline feature — re-run to compute)."* — instead of silently dropping the Baseline/Δ columns.
  - `Dashboard.tsx`: when `reduction_pct`/`energy_reduction_vs_baseline_pct` is null, keep the "—" but add a `title` tooltip with the same explanation.
- **Operational:** restart the backend on current code so **new** plans carry the baseline block (this is the actual fix for 2a/2b data); rebuild the frontend so the new pages + fixes are served.

## 5. Testing

**Backend (pytest, no Docker):**
- `test_epw.py`: `weather_timeseries` returns the right count + values for an in-coverage week; `[]` for out-of-coverage; honours `days`.
- IT-load helpers: past slice length + kW values from a tiny fixture; forecast aggregation = Σ fraction·capacity.
- `test_public_api.py` (or new `test_planning_context.py`): the endpoint returns the four series + previous_setpoints with a stubbed forecaster/EPW; guarded fields are `[]`/`null` not 500; auth required (401 without token).

**Frontend (vitest):**
- `NewPlan.test.tsx`: default week is `2024-11-08`; given a mocked `getPlanningContext`, the IT-load + weather charts and the previous-setpoints card render; charts hidden when context is empty.
- `History.test.tsx`: a plan list with exactly one realised value renders the realised series with dots (assert the realised `<Line>`/dot is present).
- `Review.test.tsx`: a recommendation **without** a baseline shows the "unavailable" note; **with** a baseline shows the comparison.

**Build:** `npm run build` clean (`tsc -b`, `noUnusedLocals`); `pytest -q` green.

## 6. Milestones
| # | Milestone |
|---|---|
| **A** | `epw.weather_timeseries` + IT-load helpers + tests |
| **B** | `GET /api/planning-context` + schema + tests |
| **C** | `api.ts` types + `NewPlan` default week + 3 decks + vitest |
| **D** | History realised dots + Review/Dashboard graceful states + vitest |
| **E** | rebuild frontend, restart backend on current code, verify a fresh plan shows baseline/reduction |
