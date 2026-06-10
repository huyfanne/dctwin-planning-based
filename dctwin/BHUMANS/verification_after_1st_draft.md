# Verification: Templates, Protocol & Search Algorithm — After 1st Draft

**Date:** 2026-06-06
**Scope:** Three follow-up verification questions on the Digital Twin Dual-Loop Control Framework,
grounded in the actual repos (template framework, dctwin, our `src/`).
**Method:** 3-agent file-grounded investigation (template conformance, protocol, search) +
direct file verification for the protocol. Evidence is given as `file:line`.

---

## 1. Did we follow the standard dcwiz templates? — Yes, with deliberate, documented deviations (~70% structural conformance)

**Proofs we conform (we subclass the real template base classes in `dcwiz-ai-engine-deploy-master`):**

| What | Proof |
|---|---|
| RecommendTemplate subclassed | `src/plan_weekly.py:22` → `class WeeklyPlanTemplate(RecommendTemplate)`; import at `:11` `from dcwiz_policy_template import RecommendTemplate` (base: `dcwiz-ai-engine-deploy-master/dcwiz_policy_template/dcwiz_policy_template/recommend_template.py:10`) |
| TrajectoryPolicyTemplate subclassed (×2) | `src/ai_trajectory_test.py:14` `class AITrajectoryReplay(TrajectoryPolicyTemplate)`; `src/baseline_policy_test.py:12` `class BaselineTrajectory(TrajectoryPolicyTemplate)` |
| Required `initialize()` overridden | `plan_weekly.py:30`, `ai_trajectory_test.py:17`, `baseline_policy_test.py:15` (abstract in `recommend_template.py:11-23`) |
| Invoked through the template `__call__()` | `plan_weekly.py:102-111` `WeeklyPlanTemplate()(...)`, etc. |
| The four entry modes | recommend (`plan_weekly.py`), ai-trajectory-test, baseline-policy-test, train (`fit_forecaster.py`) — same four as `examples/sample_template/` |
| Standard layout mirrored | `src/{configs/dt/dt.prototxt, configs/policy/, data/, models/}` matches `sample_template/{configs,data,models}` |

**Deviations (intentional, documented):**
- `plan_weekly.py:68-87` **overrides `run()`** with the oracle beam-search instead of a reactive dcbrain
  policy — the docstring (`:23-27`) says exactly why: *"the base `RecommendTemplate.run()` expects a
  reactive dcbrain policy; the oracle owns the weekly run period."*
- Does **not** implement the abstract `log_recommendations()` (`recommend_template.py:60-72`); uses
  `planner.recommendation.write_recommendation()` instead.
- Uses `week_start` rather than the template's `recommendation_timestamp` for the run period.
- **No `hooks.py`** — the sample template consolidates logic in one `hooks.py`; we split it into the
  `planner/` package (cleaner, but structurally different).

**Verdict:** we genuinely sit on the official template framework (real subclasses, the four modes, the
config/data/model layout) but deliberately replace the *reactive-policy* behavior with a *planning*
behavior — which is the whole point of this project.

---

## 2. The dctwin ↔ planner communication protocol

**Important correction first:** the `dcbrain` repo is **not actually wired in**. The only `dcbrain`
token in our code is a *comment* (`plan_weekly.py:26`); there is no `import dcbrain`. Our planner is
**net-new, in-project (`src/planner/`)**, designed to be upstreamable to dcbrain later. So the real
connection is **dctwin (EnergyPlus twin) ↔ our in-project planner**, via a layered stack:

| Layer | Mechanism | Proof |
|---|---|---|
| **A. Planner ↔ Twin seam** | the `Evaluator` protocol: `evaluate(candidates: Setpoints[], forecast) → WeeklyKPI[]`. Planner depends only on this interface; `ParallelEnvOracle` implements it (real E+), `MockEvaluator` for tests. | `src/planner/types.py:64-71` |
| **B. 3 → 45 broadcast** | the planner's 3 global setpoints expand to the 45-dim normalized action vector (22 SAT + 22 FLOW + 1 CHWST). | `src/planner/broadcast.py:46` `expand()`, `:59` `gds_action_spec()` |
| **C. Gym env contract** | `dctwin.make_env(env_proto_config, reward_fn) → gym.Env`; then `env.reset()`, `env.step(action)` (5-tuple), `inspect_current_observation(name)` to read live obs. | `dctwin/registration.py:9`; driven in `src/planner/oracle_worker.py:45-49,31` |
| **D. BCVTB TCP socket** (the actual transport) | host Python binds a TCP socket (`0.0.0.0:<rand>`, 3600 s timeout), writes `socket.cfg(host,port)` into the case dir, launches the EnergyPlus container; E+'s ExternalInterface connects **back** to the host. Per step: `send_action()` writes a space-delimited float string; `receive_status()` reads the obs vector. | `dctwin/third_parties/eplus/core.py:87-98` (socket), `:101-108` (socket.cfg), `:265-270` (`send_action` → `_conn.send`), `:283-294` (`recv`/`receive_status`) |
| — host reachability fix | we override `backend._host = "172.17.0.1"` (docker0 gateway) so the container can dial back. | `src/planner/oracle_worker.py:88` |
| **E. Env contract definition** | `dt.prototxt` (`DTEngineConfig`): model_file, weather_file, simulation time, the 45 actions + observations — defines *what* crosses the socket. | `src/configs/dt/dt.prototxt`, schema `dctwin/utils/protos/dt_engine.proto` |
| **F. Inner → outer loop contract** | `recommendation.json` (versioned): setpoints + predicted_kpis + status. | `src/planner/recommendation.py:42-` |

**In one sentence:** planner → `Evaluator.evaluate` → 3→45 broadcast → `env.step(action)` →
**BCVTB TCP socket** → EnergyPlus-in-Docker → observations back over the socket → aggregated to
`WeeklyKPI` → scored. The transport is the **EnergyPlus BCVTB / ExternalInterface co-simulation
protocol** (a simple space-delimited float line protocol over TCP), *not* a dcbrain API.

---

## 3. Physical background of the search — and is it the best?

**Algorithm** (`src/planner/beam_search.py`): best-first **coarse-to-fine beam search** over the 3-D
continuous cube **SAT [20,26] °C × airflow [4.8,13.8] kg/s × CHWST [13,19] °C** (`types.py:77-81`).
Coarse grid g=5 → 125 candidates, keep top-B=5 (`:80-93`); then L=3 refinement levels, 8 local
neighbors at a **step that halves each level** (`:95-102,123`); early-stop when relative improvement
< ε=1e-3, budget `max_evals=400` (`:20-21`).

**Physical basis — why local coarse-to-fine fits:** the three knobs act on a **smooth, low-dimensional
thermodynamic surface** with two competing physical effects:
- **Energy** is a convex-ish *bowl*: raising SAT and CHWST shrinks the chiller's thermal lift (less
  compressor energy), and lowering airflow cuts fan power (≈ flow³) — but overdoing any of them drives
  inlet temps up and costs cooling back. So there's an interior optimum (`mock_evaluator.py:34-39`
  models it as a separable quadratic bowl).
- **Inlet temperature** (the hard safety constraint) is **monotone**: ↑ with SAT and CHWST, ↓ with
  airflow (`mock_evaluator.py:40-45`). So the feasible region is a monotone "cool-enough corner" of the
  cube.

A smooth + low-D + monotone-constraint surface is *exactly* the regime where a coarse grid locates the
right basin and local refinement polishes it — there's little reason to expect many disconnected
optima. And because **each evaluation is a full-week EnergyPlus run (minutes)**, the binding
requirement is **sample-efficiency (few hundred evals)** — which beam search satisfies while staying
transparent, parallelizable, deterministic, and equipped with a safe fallback.

**Is it the best? — A sound, defensible v1 choice, but *not* the most sample-efficient.** Honest
comparison:

| Method | Verdict for this problem |
|---|---|
| **Beam / coarse-to-fine (ours)** | Great fit: simple, transparent, parallel, safe-fallback, matches smooth low-D physics. Not provably global; local. |
| **Grid search** | Strictly worse (no refinement). |
| **Bayesian optimization (GP + expected-improvement)** | **The strongest upgrade** — usually finds the optimum in *fewer* expensive E+ runs and gives uncertainty bounds (which directly serves "high-fidelity"). More complex/opaque. |
| **CMA-ES / iCEM (the old OptimizationMPC)** | Robust on non-convex, but needs more evals than BO — overkill for a smooth 3-D surface. |
| **Gradient / MPC** | Needs a differentiable surrogate; we deliberately use EnergyPlus directly (no surrogate) → no gradients. |

**Bottom line:** for the current **3-variable, smooth, expensive-black-box, weekly** problem, beam
search is near-best among *simple* methods and the right call for v1. It is **not the most
sample-efficient** — if you push for higher fidelity or richer actions, the natural next step is
**Bayesian optimization** (fewer EnergyPlus runs + uncertainty estimates), optionally with random
restarts to guard against model artifacts. Note too that with only 3 constant setpoints the space is
tiny — beam search is almost more than enough; the moment you enrich the action space (time-of-day
blocks, per-hall setpoints) the dimensionality grows and BO/CMA-ES start to clearly earn their keep.

---

## 4. "Candidate Control Sequences" (Option 1..N) — why it looks missing, and how to add it

There are two senses of "candidate control sequences" in the diagram:

- **(a) Competing options ranked by the search.** Option 1..N = the candidates the planner evaluates
  and ranks; the surviving frontier is the beam. **This IS implemented** — each `Setpoints` candidate
  is scored by an EnergyPlus run and ranked by the objective, and the top-B beam is exactly "the best
  Options kept" (`src/planner/beam_search.py:80-93,104-123`; `_top_b` at `:127`). So the *tree of
  competing options* exists.
- **(b) Time-varying sequences.** Each Option being a *trajectory* of actions across the week
  (different setpoints per hour/day), not a single constant value. **This is NOT implemented** — our
  candidate is a constant weekly trio (3 scalars held for all ~672 steps; `run_episode` steps with the
  same action every step, `src/planner/oracle_worker.py:49`).

**Why (b) was deferred (deliberate v1 non-goal, spec §2):** each candidate is a full-week EnergyPlus
run (minutes). A constant trio = 3 search dimensions. Time-varying explodes it: day/night = 6 dims,
per-day = 21 dims, hourly = 504 dims → many more E+ runs. v1 kept it tractable and matched operations
(operator applies one weekly setpoint). The `recommendation.json` schema was deliberately left
extensible for this (spec §15).

**Yes, we can implement it — recommended: a piecewise-constant time-block schedule.** Touch-points:

| Step | Change |
|---|---|
| Candidate type | `Setpoints` (3 scalars) → `Schedule` = `K × 3` (K time-blocks). `src/planner/types.py` |
| Search space | K copies of the 3-D cube (`SearchSpace` → K-block). `src/planner/types.py:35-45` |
| Broadcast / episode | apply block-b's setpoints during block-b's steps — `run_episode` steps with the per-step action from the schedule (or via dctwin `make_env(schedule_fn=...)`). `src/planner/oracle_worker.py:41-49`, `dctwin/registration.py:9` |
| Search | beam search still works at K=2 (6-D); as K grows (per-day 21-D, hourly 504-D) switch to **Bayesian optimization / CMA-ES** (see Q3). |
| Output | `recommendation.json` setpoints → a per-block schedule (schema already allows it). `src/planner/recommendation.py` |

Start with **K=2 (day/night)** or **peak/off-peak** (tariff-aware) — the biggest savings for the least
added dimensionality — then generalize. This also moves the implementation closer to the diagram's
literal "control sequences."

---

## 5. Operational constraints in the objective — already partly there, easy to extend

**What exists today** (`src/planner/objective.py:33-53`, metrics computed in `src/planner/kpi.py`):
- **Hard constraint (feasibility gate):** ITE inlet ≤ 26 °C — `is_feasible()` returns False if
  `inlet_violation_steps > inlet_tol_steps` (tol=0) → score = +∞, candidate dropped from the beam.
- **Soft constraints (penalty terms):** `score = energy + λ_T·inlet_excess + λ_R·rh_excursion +
  λ_Z·zone_band` — inlet-margin, humidity (RH 30–60 %), and zone-temperature excursions are penalized
  but not gated.

So we already implement "Operational Constraints" via the standard **hard-reject + soft-penalty**
pattern; the diagram's third objective is honored.

**Yes — more operational constraints are straightforward to add**, via one seam: compute the metric in
`aggregate_kpi` (from EnergyPlus observations), add it to `WeeklyKPI`, then either gate it in
`is_feasible` (hard) or add a `λ·term` in `score` (soft).

| Constraint to add | Mechanism |
|---|---|
| RH bounds as a HARD limit | flip `rh_hard=True` (the flag already exists, default False) |
| Chiller / cooling-tower capacity, N+1 redundancy headroom | read equipment load via `inspect_current_observation`; hard-reject if over capacity |
| Setpoint ramp limit (for time-block schedules) | bound `\|block_{b+1} − block_b\| ≤ Δmax` — hard or soft |
| PUE / energy-budget cap | hard-reject if PUE > threshold |
| Per-ACU airflow / CHWST equipment min–max | partly via search-space bounds; add as explicit hard checks |

**Best practice (the design already follows it):** hard gates for *safety-critical / true equipment
limits* (inlet temp, RH bounds, capacity), soft penalties for *preferences* (margins, smoothness,
ramp). Caveat: every added hard constraint shrinks the feasible set and raises the chance of
`infeasible_fallback`, so (i) reserve hard gates for genuine limits, and (ii) pair them with the
**per-candidate failure diagnostics** from the review's P3 so an infeasible result tells the expert
*which* constraint bound. Constraints on equipment state also require wiring those observations into
the monitor set first (`src/planner/monitor.py`).
