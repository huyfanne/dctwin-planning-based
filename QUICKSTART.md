# QUICKSTART — from clone to your first optimization plan

This is the **Digital Twin Dual-Loop Control Framework**: a planning-based optimizer that
recommends weekly data-center cooling setpoints (CRAH supply-air temp, CRAH airflow, chilled-water
supply temp), scoring every candidate with a full-week **EnergyPlus 9.5** simulation and never
letting any server inlet exceed **26 °C**. This guide takes you from a fresh clone to a running
web app and a launched optimization plan.

> Full reference docs are in [`docs/`](docs/): user guide, code-handoff guide, template-compliance
> summary, and a plain-language book chapter.

---

## ⚠️ 0. Two things you need from the maintainer first

A fresh clone of this **public** repo is **not runnable on its own** — two pieces are deliberately
excluded and must be obtained from the maintainer (Hoang-Huy Nguyen):

1. **Model / config / data assets** — the git-ignored folders `src/models/`, `src/configs/`,
   `src/data/` (the GDS digital-twin: `building.idf`, device maps, `dt.prototxt`, the historical
   telemetry CSV, EPW weather, calibration files). **Without them, no plan can run.**
2. **Access to two private `cap-dcwiz` resources:** the EnergyPlus Docker image
   (`ghcr.io/cap-dcwiz/energyplus-9-5-0`) and the `dclib` git dependency. If you don't have
   `cap-dcwiz` access, ask the maintainer to grant it or to send you the image tarball.

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| git | any | clone the repo |
| **Docker** (user in the `docker` group) | engine | runs the EnergyPlus oracle (required to run a plan) |
| **Python** | **3.13** (to match `requirements.lock.txt`) | planner + web backend |
| **Node.js** | ≥18 (22 works) | builds the React UI |

On Linux, add yourself to the docker group once, then re-login:
```bash
sudo usermod -aG docker "$USER"
```
> The one-command launcher (`scripts/clear-and-run.sh`) uses `sg docker` and is **Linux-only**.
> On macOS/Windows, use the manual backend command in **Step 6b**.

---

## 2. Clone and pull the EnergyPlus image
```bash
git clone git@github.com:huyfanne/dctwin-planning-based.git
cd dctwin-planning-based
export REPO="$PWD"

docker pull ghcr.io/cap-dcwiz/energyplus-9-5-0:latest
# If this is denied (private): `docker login ghcr.io` with a token that can read cap-dcwiz packages,
# or load a tarball the maintainer sends: `docker load -i energyplus-9-5-0.tar`
```

## 3. Drop in the assets you received
Place the three folders **under `src/`** (this exact layout matters):
```bash
cp -r /path/to/assets/{models,configs,data} "$REPO/src/"
# sanity check:
ls "$REPO/src/models/idf/building.idf" "$REPO/src/configs/dt/dt.prototxt" "$REPO/src/data/weather/"*.epw
```

## 4. Create the Python environment **at `.venv-dtwin`**
The launcher hardcodes the interpreter path `.venv-dtwin/bin/python`, so use that exact name at the repo root:
```bash
cd "$REPO"
python3.13 -m venv .venv-dtwin
source .venv-dtwin/bin/activate
python -m pip install --upgrade pip

# exact, one-shot install of all third-party deps (engine + web):
pip install -r requirements.lock.txt

# install this repo's dctwin engine package (deps already satisfied above):
pip install -e . --no-deps
```

**If `pip install -r` fails:**
- on the `dclib` line → you lack `cap-dcwiz` access (see Step 0.2); or swap `git+https` → `git+ssh://git@` in that line if your SSH key has access.
- on a heavy optional dep (e.g. `mayavi`/`vtk`) → it's only for CFD viz, not the planning webapp: delete that line from `requirements.lock.txt` and re-run.
- **Fallback (any Python 3.11–3.14, no lockfile):** `pip install poetry && poetry config virtualenvs.create false --local && poetry install --only main && pip install fastapi uvicorn pandas`, then `pip install -e . --no-deps`.

Smoke test (no Docker needed — EnergyPlus is mocked in unit tests):
```bash
cd "$REPO/src" && PYTHONPATH="$PWD" ../.venv-dtwin/bin/python -m pytest -q
```

## 5. Ensure a fitted forecaster exists
A plan needs `src/models/forecaster.pkl`. If it wasn't in the assets, fit it (needs `data/` + `configs/`):
```bash
cd "$REPO/src"
PYTHONPATH="$PWD" ../.venv-dtwin/bin/python fit_forecaster.py     # → models/forecaster.pkl
```

## 6. Start the web app

**6a — One command (Linux, in the `docker` group):**
```bash
cd "$REPO"
scripts/clear-and-run.sh        # builds the UI, serves everything at http://localhost:8000
```
It prints the login tokens — **operator `op-secret`, expert `ex-secret`** (override with
`OPERATOR_TOKEN=… EXPERT_TOKEN=…`). It offers to wipe `runs/` (say `y` on a fresh setup). Ctrl-C stops it.
(`--dev` gives hot-reload at `:5173`; a busy `:8000` auto-bumps to the next free port.)

**6b — Manual (macOS/Windows, or if `sg` is unavailable):**
```bash
cd "$REPO/src/frontend" && npm install && npm run build      # build the UI so "/" serves it
cd "$REPO/src"
PYTHONPATH="$PWD" OPERATOR_TOKEN=op-secret EXPERT_TOKEN=ex-secret DTWIN_SIM_TELEMETRY=1 \
  ../.venv-dtwin/bin/python -m uvicorn webapp.main:app --host 0.0.0.0 --port 8000
```
> Skipping the frontend build makes `http://localhost:8000/` show a "not built" hint; the API at `/api/*` still works.

## 7. Log in
Open **http://localhost:8000** and paste a token in the login field:
- **`op-secret`** (operator) — create/run/monitor plans → enough for this walkthrough.
- **`ex-secret`** (expert) — also approve/deploy.

## 8. Start a new optimization plan
1. Open the **New Plan** tab.
2. Use these safe, verified values:
   - **Week start:** `2024-11-08` — must fall inside the data/weather coverage shown in the panel (Nov 2024–Jan 2025); don't pick a week that crosses a year boundary.
   - **Days** `7` · **Grid size** `5` · **Beam width** `3` · **Levels** `3` · **Workers** e.g. `4` (≤ CPU cores). Leave day/night off for a first run.
3. Click **Launch Optimization**. Each candidate is a **full-week EnergyPlus run in Docker**, fanned
   out across `Workers` processes — expect **several minutes to tens of minutes**.
4. Watch the **live progress** on the page (search level, evaluations, best score).

## 9. See the result
When it finishes, open the **Review** tab: the chosen setpoints, predicted energy & PUE vs the
as-operated baseline, robust confidence bands, and the inlet-temperature trajectory against the
26 °C cap. **Dashboard** is the one-screen summary; **History** tracks predicted-vs-realized once
weeks are deployed. (Approving/deploying is expert-only and runs in shadow mode — not needed to
"start a plan".)

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: fastapi` / `uvicorn` | Step 4 didn't complete, or the wrong venv is active (`source .venv-dtwin/bin/activate`). |
| `interpreter not found: .../.venv-dtwin/bin/python` | The venv isn't at exactly `.venv-dtwin` (Step 4). Recreate it there, or edit `PY=` atop `scripts/clear-and-run.sh`. |
| Plan fails instantly on `building.idf` / `dt.prototxt` / `forecaster.pkl` | Assets (Step 3) or forecaster (Step 5) missing/misplaced — they live under `src/models`, `src/configs`, `src/data`. |
| `permission denied` / `Cannot connect to the Docker daemon` | User not in `docker` group, or the EnergyPlus image wasn't pulled (Steps 1–2). |
| BCVTB/socket errors when a plan runs | On Linux the oracle uses the Docker0 gateway `172.17.0.1`; Docker Desktop (macOS/Windows) needs `host.docker.internal`. |
| `sg: command not found` (macOS/Windows) | Use the manual command in **Step 6b**. |
| Port 8000 busy | The launcher auto-bumps to the next free port (it prints which), or set `BACKEND_PORT=8001`. |
| `pip install -r` fails on `dclib` | You need `cap-dcwiz` read access (Step 0.2). |
