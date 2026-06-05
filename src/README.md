# Digital Twin Dual-Loop Control Framework (dtwin-dualloop)

Heuristic best-first search over 3 weekly setpoints (CRAH supply-air temp, CRAH
airflow, CHWST), scored directly by full-week EnergyPlus 9.5 runs via dctwin
(no MPC, no grey-box surrogate), on the calibrated GDS tropical-DC model.

## Weekly operator workflow

```bash
# 1. (once) fit the statistical forecaster from historical data
python fit_forecaster.py

# 2. Monday: generate the week's recommendation (best-first search over EnergyPlus)
python plan_weekly.py --week-start 2013-11-11

# 3. pre-validate vs the conservative baseline + review the report
python prevalidation.py --recommendation log/recommendation.json

# 4. expert approves (or rejects)
python prevalidation.py --recommendation log/recommendation.json --approve

# 5. deploy (sim-only: runs the plant week, records realized KPIs)
python -c "from deploy import deploy; from planner.oracle import ParallelEnvOracle; \
           deploy('log/recommendation.json', ParallelEnvOracle('configs/dt/dt.prototxt'))"
```

## The four template modes

| Mode | Script | Output |
|---|---|---|
| ai policy test (recommend) | `plan_weekly.py` | `recommendation.json` |
| ai policy train | `fit_forecaster.py` | `models/forecaster.pkl` |
| ai trajectory test | `ai_trajectory_test.py` | `temperature_data_ai.csv` |
| baseline trajectory test | `baseline_policy_test.py` | `temperature_data_baseline.csv` |

## Tests

```bash
python -m pytest                       # fast unit tests (no EnergyPlus)
python -m pytest -m integration        # requires Docker + EnergyPlus 9.5 image
```

See `dctwin/docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md`.
