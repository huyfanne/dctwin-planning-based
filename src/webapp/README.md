# Digital Twin Dual-Loop — Web App

FastAPI backend + React (Vite/TS) frontend for the weekly planner: trigger plans
with live progress, review KPIs/plots, the expert approve/deploy gate, and an
interactive **3D view of the 1F 2A hall with animated airflow**.

## Backend (FastAPI)

The backend shares the dctwin venv so it can run real plans (EnergyPlus via Docker).

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
# tokens define the two roles (operator can create plans; expert can approve/deploy)
export OPERATOR_TOKEN=op-secret EXPERT_TOKEN=ex-secret
# Docker access for the worker's EnergyPlus runs: launch under the docker group
sg docker -c "PYTHONPATH=$PWD OPERATOR_TOKEN=$OPERATOR_TOKEN EXPERT_TOKEN=$EXPERT_TOKEN \
  /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m uvicorn webapp.main:app --host 0.0.0.0 --port 8000"
```

Requires `models/`, `configs/`, `data/` assets present in `src/` and the fitted
forecaster (`python fit_forecaster.py`). The model assets are gitignored — copy
them from `mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup`.

### API
`POST /api/plans` (operator) · `GET /api/plans` · `GET /api/plans/{id}` ·
`GET /api/plans/{id}/progress` · `PATCH /api/plans/{id}/setpoints` (expert) ·
`POST /api/plans/{id}/approve|reject` (expert) · `GET /api/topology` (1F-2A hall layout).
Auth: `Authorization: Bearer <token>`.

## Frontend (React + Vite)

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend
npm install
npm run dev        # http://localhost:5173, proxies /api -> :8000
# if the backend is on another port (e.g. 8000 is occupied), point the proxy at it:
VITE_API_TARGET=http://localhost:8011 npm run dev
```

Note: the backend python is at `dctwin/.venv-dtwin/bin/python` (the parent of
`src/`), so use that absolute path — `.venv-dtwin/...` is not under `src/`. No
Docker is needed just to view/serve; wrap uvicorn in `sg docker -c "..."` only to
*trigger* a plan run (which launches EnergyPlus).

Paste an operator or expert token into the header field. Five views: **Dashboard**,
**New Plan** (live search progress), **Review & Approve**, **History**, and
**Digital Twin (3D)** (3D hall + airflow driven by the selected plan's setpoints).

## Tests

```bash
# backend (no Docker needed; integration tests are deselected by default)
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -q
# frontend
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src/frontend && npm run test -- --run
# EnergyPlus integration (Docker + EP 9.5 image)
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src && sg docker -c "PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python -m pytest -m integration -q"
```

See `dctwin/docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` §14.
