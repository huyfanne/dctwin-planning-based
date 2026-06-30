# CLAUDE.md

Guidance for Claude Code working in this repo. Keep it accurate — update it when the facts below change.

## What this is

The **Digital Twin Dual-Loop Control Framework**: a planning-based optimizer that recommends **weekly data-center cooling setpoints**, with **EnergyPlus 9.5 (via Docker) as the in-the-loop oracle**. It searches 3 global setpoints — CRAH supply-air temp (SAT, 20–26 °C), CRAH airflow (4.8–13.8 kg/s), CHWST (13–19 °C) — broadcast to 45 actuators for the controlled 1F 2A hall, under a hard inlet ≤ 26 °C safety cap.

## Project Context & AI Rules

### Core System Directives
- NEVER read entire folders or multiple raw files blindly.
- ALWAYS reference the knowledge graph before modifying core architecture.
- Session Memory: Utilize Graphify artifacts to recall context from previous sessions.

### Graphify Integration Commands
- Read structural overview: View `/graphify-out/GRAPH_REPORT.md`
- Inspect raw map schema: Reference `/graphify-out/graph.json`
- Re-index structural mutations: Run `/graphify . --update`

### Depth lives elsewhere — read these before large changes:
- `src/README.md`, `src/webapp/README.md` — how to run the planner + web app.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — the design specs + TDD implementation plans for every shipped tier (NOW, NEXT, LATER A/B/C). Each feature has a dated spec+plan pair.
- `graphify-out/GRAPH_REPORT.md` + `graph.html` — the AST knowledge graph (1045 nodes) of `src/`.

## Environment & commands

- **Python interpreter (non-standard venv):** `/mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python`. There is no `python`/`python3` on PATH that has the deps.
- **Sandbox quirk:** a leading `cd` is stripped from shell commands. Always use `env -C <dir> …` or `git -C <repo> …` instead of `cd`.
- The Python package roots are under `src/` (`from planner…`, `from webapp…`); run from `src/` (or set `PYTHONPATH=…/src`).

**Run unit tests** (fast; EnergyPlus is mocked — see below):
```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -q
```
`pyproject.toml` sets `addopts = "-q -m 'not integration'"`, so Docker tests are deselected by default. The pytest summary line is often buried under warnings — rely on the exit code + the `N passed` count.

**Run the Docker-gated integration tests** (real EnergyPlus; slow, flaky on BCVTB — wrap in a hard timeout):
```bash
sg docker -c "env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src PYTHONPATH=\$PWD \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -m integration -q"
```

**Frontend** (`src/frontend`):
```bash
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm test          # vitest (runs once in non-TTY; use `npx vitest run` to force one-shot)
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run build      # tsc -b && vite build — type-checks .test.tsx too (noUnusedLocals is ON)
env -C /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend npm run dev        # dev server
```

**Run the web app** — one command clears plan state, builds the UI, and serves the **whole app from the backend at a single origin** `http://localhost:8000` (UI at `/`, API at `/api/*`). Ctrl-C stops it. Flags: `--dev` (hot-reload via the Vite dev server at `:5173` + backend proxy), `--backend-only`, `--keep-runs`, `-y`, `--help`:
```bash
scripts/clear-and-run.sh            # → http://localhost:8000  (single origin)
scripts/clear-and-run.sh --dev      # → http://localhost:5173  (hot reload)
```
Then open the printed URL and enter the operator/expert token. `webapp/main.py` mounts `frontend/dist` at `/` when it's built (so **build the frontend** — `npm --prefix src/frontend run build` — or `/` shows a "not built" hint, not the UI). To start the backend by hand (full command in `src/webapp/README.md`):
```bash
sg docker -c "PYTHONPATH=\$PWD OPERATOR_TOKEN=op EXPERT_TOKEN=ex \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m uvicorn webapp.main:app --port 8000"
```

**CLI entry scripts** (in `src/`): `plan_weekly.py` (run a weekly plan headless), `fit_forecaster.py` (fit the persistence/statistical forecaster — required before plans), `prevalidation.py` (deploy pre-validation gate), `deploy.py` (apply an approved plan).

**Model assets are gitignored.** `src/{models,configs,data}/` must be present; copy the GDS model from `mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup`.

## Architecture

**Inner planning loop** (`src/planner/`): `forecaster` (weather/IT-load persistence forecast) → `beam_search` (coarse-to-fine best-first search over the 3 setpoints) → `oracle`/`oracle_worker` (each candidate scored by a **full-week EnergyPlus run**, parallelized across processes) → `objective`/`robust` (safety: hard-reject inlet > cap, k·σ pre-tighten, robust-feasibility deploy gate) → `recommendation` (the JSON artifact). `broadcast` expands 3 global setpoints → 45 actuators. `mock_evaluator` is the **fast analytic stand-in for EnergyPlus used by all unit tests** — never invoke real EnergyPlus from a unit test.

**Time-block (day/night) extension:** `schedule` (`TimeBlock`/`WeeklySchedule`) + `schedule_search` (`refine_schedule`, a warm-start local search seeded at the constant optimum). Opt-in via `PlanRequest.time_block`.

**Outer deployment loop:** `prevalidation` → expert approve/deploy → `calibrator`/`recalibrator` (bias/σ residuals with a σ fading-floor `max(sample, prior/n)` and inlet residual clipping) → re-plan.

**Web app** (`src/webapp/`): `main` (FastAPI app + routes incl. the SSE `…/stream` endpoint), `jobs` (the threaded `JobRunner` that runs plans + writes `progress.json`), `store` (SQLite index + run artifacts), `auth` (`TokenAuth`, operator/expert roles, fail-closed), `status` (the plan status state machine), `schemas`. Frontend is React 19 + Vite + TS in `src/frontend/`.

## Key conventions & gotchas

- **Process-based parallelism, not threads.** The dctwin/EnergyPlus config is a **process-global singleton**, so the oracle fans out across *processes*. Don't assume thread-safety for config-dependent state.
- **`recommendation.json` is schema-versioned** (currently `1.0`→`1.7`; `1.5` adds the time-block `schedule` block, `1.7` adds the as-operated `baseline` block + `energy_scope`). Bump the version when you change the artifact shape, and keep older readers working.
- **Energy objective is hall-scoped** (`energy_scope: "hall_controllable_v1"`): `kpi.total_hvac_energy_kwh` sums the 1F-2A ACU fans + chiller/CHW plant (`monitor.hvac_power_names`), NOT facility total−IT; it falls back to facility (total−IT) only when those component powers aren't discovered (mock/legacy). The baseline is the **as-operated** setpoints (`planner/baseline.py`, medians from `his_data`) evaluated once. Live forecaster is **seasonal** (week-aligned); the 1F-2A IT load is ~flat in the data, so weather dominates week-to-week.
- **Hard safety invariant:** inlet temperature ≤ 26 °C at every step. `objective.is_feasible` rejects violations; the robust gate adds margin; deploy has a backstop. Don't weaken these to make a search "succeed."
- **TDD + don't weaken tests.** Plans are written test-first; implementers must make the code pass, never relax an assertion. The frontend build (`tsc -b`) type-checks test files with `noUnusedLocals` — drop imports you stop using or the build fails (TS6133).

## Repo / workflow conventions

- **Branch per sub-project**, merge to `main` with `git merge --no-ff`. Feature flow is **brainstorm → spec (`docs/superpowers/specs/`) → plan (`docs/superpowers/plans/`) → adversarial verification → subagent build → merge → graphify update**.
- **Do NOT push to `origin` without an explicit go-ahead.** `main` is ~177 commits ahead of `origin` and intentionally local-only.
- End commit messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Knowledge graph:** after merging code changes, regenerate `graphify-out/` (incremental AST extract of `src/`, excluding `frontend/.vite/`). It's a navigation aid for the next session, not a build artifact.

# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
