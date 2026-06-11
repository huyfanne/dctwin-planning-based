---
name: run-dctwin
description: Build, start, smoke-test, screenshot, and drive the DCTwin webapp (FastAPI backend + React UI + EnergyPlus-in-Docker planning oracle). Use when asked to run the app, start/restart the backend, take a screenshot, run a real optimization plan, check status, or recover a hung/wedged plan.
---

# Run DCTwin (webapp + planner)

DCTwin recommends weekly data-center cooling setpoints; every candidate is scored by a
real EnergyPlus 9.5 run in Docker. The app is a **single-origin web server**: FastAPI
serves the built React SPA at `/` and the API at `/api/*`. Agents drive it through
**`.claude/skills/run-dctwin/driver.sh`** (curl + playwright) — not by opening a window.

All paths below are relative to the **repo root**. The Python venv is
`.venv-dtwin/bin/python` (nothing useful is on PATH). Two sandbox quirks shape every
command: a leading `cd` is stripped (use `env -C`), and Docker needs the group wrapper
(`sg docker -c "…"`).

## Prerequisites (already present on this box — listed for a clean machine)

- Python venv at `.venv-dtwin/` with the project deps; package roots live in `src/`.
- Docker with the `ierg4910/eplus95:latest` image; the user in the `docker` group
  (commands go through `sg docker -c`).
- Node ≥ 20 for the frontend (`src/frontend`), playwright chromium for screenshots
  (`env -C src/frontend npx playwright install chromium` if `~/.cache/ms-playwright` is empty).
- **Gitignored model assets must exist**: `src/{models,configs,data}/` (copy from
  `mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup`), including the fitted
  `src/models/forecaster.pkl` (else: `env -C src ../.venv-dtwin/bin/python fit_forecaster.py`).

## Build (frontend → served by the backend)

```bash
npm --prefix src/frontend run build      # tsc -b && vite build → src/frontend/dist
```

If `dist/` is missing the backend still runs, but `/` shows a "not built" hint page.

## Run + drive (agent path — use the driver)

```bash
.claude/skills/run-dctwin/driver.sh start        # kill old backend, start fresh, wait healthy
.claude/skills/run-dctwin/driver.sh smoke        # end-to-end: UI, auth, all read APIs,
                                                 #   weather guardrail, create→running→cancel→delete
                                                 #   a REAL plan (needs Docker; ~2 min)
.claude/skills/run-dctwin/driver.sh smoke --api-only   # no-Docker variant
.claude/skills/run-dctwin/driver.sh screenshot   # headless login + dashboard PNGs → src/log/screens/
.claude/skills/run-dctwin/driver.sh plan         # run a tiny REAL plan to completion (~6-8 min)
.claude/skills/run-dctwin/driver.sh status       # backend pid, active plans, E+ containers
.claude/skills/run-dctwin/driver.sh unstick <id> # recover a wedged running plan
.claude/skills/run-dctwin/driver.sh stop
```

- URL: **http://localhost:8001** (override `PORT=…`; default tokens `op-secret` operator /
  `ex-secret` expert — override `OPERATOR_TOKEN`/`EXPERT_TOKEN`).
- Backend log: `src/log/backend.out`. Per-plan artifacts: `src/runs/<plan_id>/`
  (`progress.json`, `recommendation.json`, `realized.json`).
- Direct API examples the driver wraps:

```bash
curl -s -H "Authorization: Bearer op-secret" http://localhost:8001/api/plans
curl -s -X POST http://localhost:8001/api/plans -H "Authorization: Bearer op-secret" \
  -H "Content-Type: application/json" \
  -d '{"week_start":"2024-11-08","days":2,"grid":2,"beam_width":2,"levels":1,"n_workers":6}'
```

Use `week_start` **2024-11-08** (or any week inside the EPW coverage Nov 1 – Jan 31);
anything outside is rejected 422 by the weather guardrail. A 2-day/grid-2 plan ≈ 6–8 min;
a full 7-day/grid-5 plan ≈ 1–2 h.

## Run (human path)

```bash
scripts/clear-and-run.sh        # clears plan state, builds UI, serves on :8000/:8001 (auto-bumps)
scripts/clear-and-run.sh --dev  # Vite hot reload on :5173
```

Foreground; Ctrl-C stops it. Fine in a terminal, useless for agents.

## Direct invocation (no webapp)

Most planner PRs can be exercised without the server — the unit suite mocks EnergyPlus:

```bash
env -C src ../.venv-dtwin/bin/python -m pytest -q          # ~300 tests, ~1 min, no Docker
env -C src/frontend npx vitest run                          # frontend tests
sg docker -c "env -C src PYTHONPATH=\$PWD ../.venv-dtwin/bin/python -m pytest -m integration -q"  # real E+, slow
```

Headless weekly plan without the webapp: `src/plan_weekly.py` (same venv/env pattern).

## Gotchas (each one cost real debugging time)

- **Port 8000 is often squatted** by an unrelated long-running `dev-mock-server` container
  on this host — that's why everything defaults to **8001**. `lsof` can't see the squatter
  (root-owned); `ss -ltnp` can.
- **A leading `cd` is silently stripped** from sandboxed shell commands → always `env -C <dir>`.
- **The oracle is process-parallel, not thread-parallel** (EnergyPlus config is a
  process-global singleton). The backend fans out a `ProcessPoolExecutor`; its workers
  show up as python children of the uvicorn process.
- **Wedged plan** (progress frozen, no E+ containers in `docker ps`): the API cancel alone
  can't fire if no candidate completes. `driver.sh unstick <id>` kills the pool workers →
  the executor fails the stuck futures → candidates become infeasible and the plan
  resumes/cancels. The oracle's stall watchdog (1.5× per-candidate timeout) bounds new
  occurrences to minutes, but only in backends started after commit `2aaff601`.
- **Restarting the backend kills any running plan** (it's an in-process thread; orphans
  are marked `failed` on restart). Check `driver.sh status` first.
- **Auth is fail-closed**: no/blank tokens → every request 401. The SSE stream
  authenticates via `?token=` query param, not header.
- **Old plans (schema < 1.7) show "—" for baseline/reduction** in the UI — they predate
  the as-operated baseline; re-run the plan to get the comparison.
- **`pytest` summary drowns in warnings** — and `pyproject.toml` addopts already include `-q`,
  so passing `-q` yourself makes it double-quiet and the final `N passed` line VANISHES.
  Trust the exit code and the `.. [100%]` dots line, not the tail of the output.

## Troubleshooting (errors actually hit)

| Symptom | Fix |
|---|---|
| `[Errno 98] address already in use` at start | `driver.sh stop` (kills + `fuser -k`); the squatter on :8000 → use 8001 |
| `/` returns the "not built" hint page | `npm --prefix src/frontend run build`, restart |
| Plan fails instantly, progress error mentions Docker | backend not started via `sg docker` — use `driver.sh start` |
| Create plan → 422 "outside weather coverage" | pick a week in Nov 1 – Jan 31 (e.g. 2024-11-08) |
| Plan stuck `running`, 0 E+ containers, progress stale | `driver.sh unstick <plan_id>` |
| Stale `running` rows after a crash/restart | restart backend — `reconcile_orphans` marks them failed |
| Screenshot: `waitForSelector('text=Dashboard')` timeout | wrong token, or frontend dist stale — rebuild |
