# Close the Fidelity/Safety Gap — Design Spec

- **Date:** 2026-06-07
- **Status:** Approved design — ready for implementation planning
- **Project root:** `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`
- **Scope tier:** the **NOW** items from the 2nd-draft review
  (`dctwin/dctwin/BHUMANS/review_after_2nd_draft.md` §3)
- **Predecessor specs:** `2026-06-04-digital-twin-dual-loop-control-design.md`,
  `2026-06-06-closing-fidelity-loop-design.md`, `2026-06-06-forecast-realism-design.md`

---

## 1. Context & problem statement

The 2nd draft wired up the full outer loop (deploy endpoint, calibration, robust re-rank, perturbed
plant, forecast realism) and the suite is green (172 backend + 57 frontend tests). But turning on the
**perturbed plant** exposed a **demonstrated safety/fidelity failure** that the framework neither catches
nor recovers from.

**The evidence (persisted in `runs/gds-2013-11-11-demo/`):** the planner predicted SAT 20 / flow 7.05 /
CHWST 13 → 28,595 kWh, peak inlet 25.79 °C, **0 violations**, and marked the plan `deployed`. Deployed to
the perturbed plant (`DEFAULT_PLANT`: fan eff ×0.93, coil flow ×0.85), it **realized 370,554 kWh (13×),
peak 29.98 °C, and 666 of 672 steps over the 26 °C hard cap.** A plan that passed the safety filter and the
expert gate ran ~4 °C hot for 99 % of the week.

**Root causes (file-grounded):**

1. **The gate uses the wrong signal.** `run_weekly_plan` sets `status` from `result.feasible` — the
   *nominal* twin — and never from `robust.robust_feasible`, even though the robust re-rank computes it
   (`pipeline.py:54-60`). A nominal-feasible-but-robust-infeasible plan still reaches `pending_approval`
   and is approvable/deployable. The deploy job already runs `DEFAULT_PLANT` and gets 666 violations, then
   marks `deployed` unconditionally (`jobs.py:197-203`). The state machine even allows
   `infeasible_fallback → approved` (`status.py:21`).
2. **Pre-validation can't catch it.** `prevalidation.py:38` reuses the recommendation's `predicted_kpis`
   instead of an independent replay, so the expert reviews the planner's own prediction. The AI replay
   entrypoint replays under `policy="baseline"` (`ai_trajectory_test.py:36`).
3. **Calibration self-poisons.** `fit_calibration` yields σ=0 at n=1 with no prior/clip, and
   `advance_calibration` pairs realized against the *already-calibrated* `predicted_kpis`
   (double-correction). The persisted `data/calibration.json` shows inlet bias +4.19 °C, σ=0, n_weeks=1 —
   which would flip the next plan to all-infeasible.
4. **Webapp safety holes.** `PATCH /setpoints` keeps stale `predicted_kpis` and has no status gate
   (mutable after approval); auth fails open when no tokens are configured.

### Core principle

> **"Feasible" must mean robust-feasible** — non-breaching across the perturbed-plant ensemble AND on the
> actual deploy plant — and the gate is enforced in **one place**, the status state machine, so `approve`,
> `deploy`, and `PATCH` all honor it automatically. The calibration learning loop that should make plans
> safe-by-construction is made trustworthy, and the expert reviews an **independent replay**, not the
> planner's self-report.

## 2. Goals / non-goals

**Goals**
- No plan can be **approved** or **deployed** unless it is demonstrably non-breaching on the plant it will
  run against (robust ensemble at plan time + the exact deploy plant at deploy time).
- When the energy-optimal winner would breach, **auto-substitute** the most efficient robust-feasible beam
  finalist; only block when *no* finalist is safe.
- Pre-validation becomes a **real independent replay** that emits `report.md` + `trajectory_*.csv`.
- Calibration stops self-poisoning (σ-prior + clip; residuals fit against **raw** predictions).
- Close the webapp safety trio (PATCH gating + KPI invalidation; fail-closed auth).
- Prove it with a **realized** (not predicted) acceptance run + a Docker regression test.

**Non-goals (this tier — deferred to NEXT/LATER, named to prevent scope creep)**
- `GET /api/plans/{id}/trajectory` + UI per-step plots + History predicted-vs-realized trend.
- §11 startup fail-fast validation (broadcast dim==45, budget>0, weights≥0).
- Forecast bands carried into the safety margin (schema 1.3) + re-enabling the real-weather pkl.
- Robust scenario error-handling + per-container kill on timeout.
- §6.5 k·σ inner-search inlet pre-tightening (search-time breach avoidance).
- Closing the **forecaster** sub-loop (realized → forecaster refit). The **calibration** sub-loop is the
  feedback path this tier hardens.

## 3. Decisions locked during brainstorming

| Question | Decision |
|---|---|
| Scope | All 5 NOW items in one cohesive spec (they interlock; one acceptance test). |
| Gate placement | **Both** — a plan-time/approval gate **and** a deploy-time backstop. |
| On unsafe winner | **Prefer the safest robust-feasible finalist**, else block (reuses existing scenario evals). |
| Two new statuses | `blocked_unsafe` (plan-time: no finalist safe) and `deploy_blocked` (deploy-time: approved plan breached on the real plant) — kept distinct for diagnostics/UI. |
| Deploy backstop + learning | A deploy-time breach **still records realized + advances calibration** (learning from the worst weeks is the point); it just refuses to label the week `deployed`. |

## 4. Component design

### 4.1 Deploy-safety gate (item 1) — three enforcement points, one source of truth

**4.1a — Plan-time status** (`planner/pipeline.py`).
`robust_select` already prefers a robust-feasible finalist (`pool = [feasible] or all`, `robust.py:78`), so
the energy-optimal-but-unsafe winner is auto-substituted whenever a safer finalist exists. Change
`run_weekly_plan` so that **when the robust re-rank ran, robust feasibility is decisive**:

```
if robust is not None:                         # robust ensemble was evaluated
    best, best_kpi = robust.winner, robust.winner_kpi   # least-bad robust finalist
    status = "pending_approval" if robust.robust_feasible else "blocked_unsafe"
elif result.feasible:                          # no robust pass; fall back to nominal feasibility
    status = "pending_approval"
else:
    status = "infeasible_fallback"             # nominal search found nothing feasible
```

On `blocked_unsafe` the recommendation carries the **robust winner** (the least-bad robust finalist) plus
diagnostics — NOT the fixed coolest-corner fallback (that path stays only for `infeasible_fallback`, when
the nominal search itself found nothing). Surface a `robust_substituted` boolean in the `robust` block (true
when the robust winner ≠ the energy-optimal beam winner) and, on `blocked_unsafe`, per-scenario diagnostics
(which scenarios breached, worst-case inlet).

**4.1b — Approval gate via the state machine** (`webapp/status.py`). Single source of truth:

- `blocked_unsafe`: allowed transitions = `{rejected}` only (NOT approvable).
- `infeasible_fallback`: **remove** the `→ approved` edge (bug fix) — `{rejected}` only.
- `pending_approval`: unchanged (`{approved, rejected}`).
- Add `deploy_blocked`: `{rejected, deploying}` (operator may retry or reject).

`approve` / `deploy` already gate on `can_transition`, so no per-endpoint logic is needed — the safety
property is enforced by the transition table.

**4.1c — Deploy-time backstop** (`webapp/jobs.py::run_deploy_job`). After `deploy()` returns realized KPIs:

```
if realized.inlet_violation_steps > 0:        # ANY breach on the real deploy plant (0-tolerance hard cap)
    status = "deploy_blocked"                 # NOT "deployed"
else:
    status = "deployed"
# in BOTH cases: save_realized + advance_history + advance_calibration + recompute_calibration
```

Tolerance is 0, matching the inlet ≤ 26 °C hard constraint (spec §4.3 / §7.4 of the original design). The
realized data always feeds calibration (learning); only the *status* reflects the breach.

### 4.2 Pre-validation = real independent replay (item 2)

- `prevalidation.py`: replace `_kpi_from_predicted` with an **independent oracle run of the recommended
  setpoints** on the nominal twin; compare to the baseline run (already present). Emit `report.md` +
  `trajectory_*.csv` into `runs/<id>/`.
- **Per-step trajectory capture**: extend `planner/oracle_worker.py` (and the `WeeklyKPI`/oracle return
  path) to optionally retain per-step series (inlet max, HVAC power, PUE) so `trajectory_*.csv` can be
  written. Gated behind a flag so the search path (hundreds of runs) need not pay the cost — only the
  single pre-validation replay does.
- **Automatic invocation**: call `run_prevalidation` as the final step of `run_plan_job` (after
  `save_recommendation`), writing the artifacts under `runs/<id>/`. Every plan gets an independent
  pre-validation before the expert reviews it.
- Fix `ai_trajectory_test.py:36` `policy="baseline"` → `policy="ai"`.

*(Surfacing the trajectory in the UI is a NEXT-tier item; this tier only produces the artifacts + report.)*

### 4.3 Calibration de-poison (item 3)

- **σ-prior + clip** (`planner/calibrator.py::fit_calibration`): a conservative per-KPI prior σ that acts as
  a floor at cold-start and shrinks toward the sample σ as `n` grows (so `n=1 → σ=σ_prior`, never 0).
  Winsorize/clip residuals to a configurable bound so one wild week can't dominate the bias. Constants live
  in `calibrator.py` (e.g. `SIGMA_PRIOR = {energy:…, pue:…, inlet:1.0 °C}`, `RESIDUAL_CLIP`).
- **Raw KPIs for residual fitting** (`planner/pipeline.py`, `planner/recommendation.py`, `webapp/jobs.py`):
  thread the **raw uncalibrated** winner KPI into the recommendation as `predicted_kpis_raw`; bump
  `schema_version` to **1.2**. `advance_calibration` fits residuals against `predicted_kpis_raw`, removing
  the double-correction. The change is additive (existing consumers ignore the new key).

### 4.4 Webapp safety trio (item 5)

- **PATCH status gate** (`webapp/main.py::edit_setpoints`): allowed only when `status == pending_approval`;
  otherwise 409.
- **Invalidate on edit**: on a successful edit, null `predicted_kpis` and the `robust` block and set a
  `needs_revalidation` flag; the approval gate refuses while `needs_revalidation` is set. Re-validation =
  re-running the item-2 pre-validation replay on the edited setpoints (no full re-plan).
- **Fail-closed auth** (`webapp/auth.py::TokenAuth.from_env`): when no tokens are configured, **deny** by
  default; an explicit `DTWIN_INSECURE=1` env var re-enables the open dev mode.

### 4.5 Acceptance — realized, not predicted (item 4)

- **Docker-gated regression test** (`tests/integration/`, marker `integration`): a 1-day window, plan →
  gate → deploy on the perturbed plant. Assert the demonstrated breach **cannot ship**:
  `status ∈ {blocked_unsafe, deploy_blocked}` **OR** the deployed plan's *realized*
  `inlet_violation_steps == 0`.
- **Documented acceptance run**: a representative week with **realized** KPIs, written to `docs/`
  (e.g. `docs/fidelity-acceptance.md`), replacing the predicted-only "11.4 % / 0 violations" claim with a
  realized result.

## 5. Data-contract changes

- `recommendation.json`: `schema_version` → **1.2**; new keys `predicted_kpis_raw` (uncalibrated KPI dict)
  and `robust.robust_substituted` (bool); `robust` may carry `scenario_diagnostics` on `blocked_unsafe`.
  When edited, `predicted_kpis`/`robust` may be `null` with `needs_revalidation: true`.
- Status vocabulary: add `blocked_unsafe`, `deploy_blocked`; remove the `infeasible_fallback → approved`
  edge. All transitions remain centralized in `webapp/status.py`.

## 6. Testing strategy

**Unit (no EnergyPlus):**
- `status`: new transition table — `blocked_unsafe`/`infeasible_fallback` not approvable; `deploy_blocked`
  retry/reject; the previously-allowed `infeasible_fallback → approved` now forbidden.
- `pipeline`: robust-gate status logic (nominal-feasible + robust-feasible → pending; robust-infeasible →
  blocked_unsafe; nominal-infeasible → infeasible_fallback) + `robust_substituted` flag, against a
  MockEvaluator/fake robust fn.
- `calibrator`: σ-prior floor at n=1 (σ>0), shrink toward sample σ as n grows, residual clip bounds a wild
  week, residuals fit against raw predictions (no double-correction).
- `prevalidation`: runs an independent replay (not `_kpi_from_predicted`) and writes `report.md` +
  `trajectory_*.csv`; oracle trajectory capture returns per-step series when enabled.
- `webapp`: PATCH refused unless `pending_approval`; edit nulls KPIs + sets `needs_revalidation` + blocks
  approval; fail-closed auth denies with no tokens, opens only with `DTWIN_INSECURE=1`.

**Integration (Docker-gated, marker `integration`):** the §4.5 regression — the demonstrated 666-violation
deployment cannot occur.

## 7. Implementation milestones

| # | Milestone | Verifies |
|---|---|---|
| **S1** | `status.py` transition table + two new statuses (+ unit tests) | the gate's single source of truth |
| **S2** | `pipeline.py` robust-gate status + `robust_substituted`; `recommendation.py` schema 1.2 + `predicted_kpis_raw` | plan-time gate + raw-KPI plumbing |
| **S3** | `jobs.py` deploy-time backstop (`deploy_blocked`, still learns) | deploy-time net |
| **S4** | `calibrator.py` σ-prior + clip + raw-residual fitting | calibration de-poison |
| **S5** | `prevalidation.py` real replay + `oracle_worker` trajectory capture + auto-run in `run_plan_job` + `ai_trajectory_test` policy fix | independent pre-validation |
| **S6** | webapp safety trio (PATCH gate + invalidation; fail-closed auth) | UI/API safety |
| **S7** | Docker regression test + documented realized acceptance run | the breach cannot ship |

S1–S4 are pure-logic, TDD-able without EnergyPlus. S5–S6 layer on top. S7 is the realized proof.

## 8. Reference file index

- Gate: `planner/pipeline.py:54-60`, `webapp/status.py`, `webapp/jobs.py:197-203`, `planner/robust.py:68-91`.
- Pre-validation: `prevalidation.py:18-55`, `ai_trajectory_test.py:36`, `planner/oracle_worker.py`.
- Calibration: `planner/calibrator.py:62-76`, `webapp/jobs.py:200`, `planner/recommendation.py:25-77`.
- Webapp: `webapp/main.py:102-121`, `webapp/auth.py`.
- Evidence: `runs/gds-2013-11-11-demo/{recommendation,realized}.json`, `data/calibration.json`.
- Review: `dctwin/dctwin/BHUMANS/review_after_2nd_draft.md`.
