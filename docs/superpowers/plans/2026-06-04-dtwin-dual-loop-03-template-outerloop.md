# Digital Twin Dual-Loop — Plan 3: Template Integration + Outer Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the planner + oracle into the dcwiz template's four entry modes, emit the versioned `recommendation.json`, and build the outer loop — pre-validation report, expert-approval gate, and sim-only deployment — culminating in an acceptance test.

**Architecture:** A `WeeklyPlanTemplate(RecommendTemplate)` overrides `run()` to invoke the `BeamPlanner` (the base `run()` assumes a reactive dcbrain policy). Pre-validation replays the recommended setpoints through `TrajectoryPolicyTemplate` (baseline mode) and compares KPIs against a baseline. All decision logic (recommendation building, fallback selection, validation metrics, the approval/deploy gate) lives in small pure modules that are TDD'd; the EnergyPlus-driven entrypoints are covered by `@pytest.mark.integration` tests.

**Tech Stack:** Python 3.10+, numpy, pandas, pytest, `dctwin`, `dcwiz_policy_template`, Docker + EnergyPlus 9.5. Builds on Plans 1 + 2.

**Prerequisite:** Plans 1 and 2 complete and green.

**Reference spec:** `dctwin/docs/superpowers/specs/2026-06-04-digital-twin-dual-loop-control-design.md` (§6 layout, §8 template integration + recommendation schema, §9 outer loop, §13 milestones M5–M7).

### Verified template API facts (use these exactly)

- `from dcwiz_policy_template import RecommendTemplate, TrajectoryPolicyTemplate` (`__init__.py:1-2`).
- `RecommendTemplate.__call__(*args, **kwargs)`: if `recommendation_timestamp` in kwargs → `configure_run_period(...)` (writes a **1-day** temp prototxt) → `initialize(*args, **kwargs)` → `run(*args, **kwargs)` → `finally _cleanup` (`recommend_template.py:130-142`). Base `run()` calls `self.policy.policy(data)` — **we override `run()`**.
- We will NOT pass `recommendation_timestamp` (avoids the base 1-day override); the **oracle owns the weekly run period** via `forecast.week_start` (Plan 2 Task 7).
- `TrajectoryPolicyTemplate.__call__(policy, *args, **kwargs)` with `policy="baseline"` runs `run_baseline()`, stepping `self.env.step(self.act)` to the episode end and writing a per-step CSV (`trajectory_policy_template.py:119-205,629-676`). Subclass `initialize()` must set `self.env` and `self.act`.
- Sample subclass pattern: `initialize(self, dt_engine_config, ...)` sets `self.env = dctwin.make_env(...)` (`examples/sample_template/baseline_policy_test.py:32-60`).

**Note on commits:** branch `feat/dtwin-dual-loop-framework`; append `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` to each commit body.

---

## File Structure

Paths relative to `/mnt/lv/home/hoanghuy/newcode/dctwin/src/`.

| File | Responsibility |
|---|---|
| `configs/`, `models/`, `data/` | copied GDS model assets (M0 scaffold) |
| `.gitignore` | ignore generated `log/`, EnergyPlus outputs |
| `planner/recommendation.py` | build/write `recommendation.json`; `safest_fallback`; `energy_reduction_pct` |
| `planner/validation.py` | `validation_metrics`, `render_report` (pure) |
| `plan_weekly.py` | `WeeklyPlanTemplate(RecommendTemplate)` — the Monday entrypoint |
| `ai_trajectory_test.py` | replay recommended setpoints → `temperature_data_ai.csv` |
| `baseline_policy_test.py` | conservative baseline → `temperature_data_baseline.csv` |
| `prevalidation.py` | KPI comparison report + `--approve` gate |
| `deploy.py` | sim-only deploy (status gate + realized-KPI run) + BMS stub |
| `tests/test_recommendation.py` | schema, fallback, reduction math |
| `tests/test_validation.py` | report metrics + rendering |
| `tests/test_deploy_gate.py` | refuses unapproved; runs when approved (fake oracle) |
| `tests/integration/test_plan_weekly.py` | tiny end-to-end plan + acceptance (`@pytest.mark.integration`) |

---

## Task 1: M0 scaffold — copy model assets + .gitignore

**Files:**
- Create: `configs/`, `models/`, `data/` (copied)
- Create: `.gitignore`

- [ ] **Step 1: Copy the GDS model assets into the project (idempotent)**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
SRC=/mnt/lv/home/hoanghuy/mycode/Tropical_DC_Files/GDS_Nov_Supply_Return32_CHWT_Backup
cp -rn "$SRC/configs" "$SRC/models" "$SRC/data" .
find . -name ".DS_Store" -delete
ls configs/dt/dt.prototxt models/idf/building.idf data/his_data_processed.csv
```

Expected: all three paths listed (assets present).

- [ ] **Step 2: Write `.gitignore`**

`.gitignore`:

```gitignore
log/
**/eplus_output/
*.eso
*.end
*.rdd
*.mdd
*.eio
*.audit
__pycache__/
.venv/
.pytest_cache/
models/forecaster.pkl
```

- [ ] **Step 3: Verify the model loads through dctwin (quick integration smoke)**

Run:

```bash
python -c "from dctwin.utils import read_engine_config; c=read_engine_config('configs/dt/dt.prototxt'); print(c.WhichOneof('EnvConfig'))"
```

Expected: prints `eplus_env_config`.

- [ ] **Step 4: Commit (assets + gitignore; the policy.pth RL artifact is intentionally NOT copied)**

```bash
git add src/configs src/models src/data src/.gitignore
git commit -m "chore(dtwin): scaffold project with GDS model assets (M0)"
```

---

## Task 2: Recommendation builder (`recommendation.py`)

Pure functions producing the versioned `recommendation.json` and selecting a safe fallback.

**Files:**
- Create: `planner/recommendation.py`
- Test: `tests/test_recommendation.py`

- [ ] **Step 1: Write the failing test**

`tests/test_recommendation.py`:

```python
import json
from datetime import date

from planner.recommendation import (
    build_recommendation, write_recommendation, safest_fallback, energy_reduction_pct,
)
from planner.types import Setpoints, WeeklyKPI


def _kpi(energy, viol=0, inlet=24.0):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=1.2, inlet_temp_max=inlet,
                     inlet_violation_steps=viol, rh_violation_steps=0, feasible=True)


def test_energy_reduction_pct():
    assert energy_reduction_pct(plan_kwh=80.0, baseline_kwh=100.0) == 20.0
    assert energy_reduction_pct(plan_kwh=100.0, baseline_kwh=0.0) == 0.0


def test_safest_fallback_prefers_fewest_violations_then_energy():
    kpis = [_kpi(50.0, viol=5), _kpi(90.0, viol=0), _kpi(70.0, viol=0)]
    assert safest_fallback(kpis) == 2   # 0 violations, lowest energy among those


def test_build_recommendation_schema():
    rec = build_recommendation(
        setpoints=Setpoints(24.0, 6.2, 18.0),
        kpi=_kpi(80.0),
        week_start=date(2013, 11, 11), days=7,
        forecast_method="persistence",
        search_meta={"evals": 245, "beam_width": 5, "levels": 3},
        baseline_energy_kwh=100.0,
        status="pending_approval",
    )
    assert rec["schema_version"] == "1.0"
    assert rec["week_start"] == "2013-11-11"
    assert rec["week_end"] == "2013-11-17"
    assert rec["setpoints"] == {
        "crah_supply_air_temperature_c": 24.0,
        "crah_supply_air_mass_flow_rate_kg_s": 6.2,
        "chilled_water_supply_temperature_c": 18.0,
    }
    assert rec["predicted_kpis"]["total_hvac_energy_kwh"] == 80.0
    assert rec["predicted_kpis"]["energy_reduction_vs_baseline_pct"] == 20.0
    assert rec["search"]["evals"] == 245
    assert rec["status"] == "pending_approval"


def test_build_recommendation_without_baseline_sets_null_reduction():
    rec = build_recommendation(Setpoints(24.0, 6.2, 18.0), _kpi(80.0),
                               date(2013, 11, 11), 7, "persistence",
                               {"evals": 1, "beam_width": 1, "levels": 0},
                               baseline_energy_kwh=None, status="pending_approval")
    assert rec["predicted_kpis"]["energy_reduction_vs_baseline_pct"] is None


def test_write_and_read_roundtrip(tmp_path):
    rec = build_recommendation(Setpoints(24.0, 6.2, 18.0), _kpi(80.0),
                               date(2013, 11, 11), 7, "persistence",
                               {"evals": 1, "beam_width": 1, "levels": 0},
                               baseline_energy_kwh=100.0, status="pending_approval")
    p = tmp_path / "recommendation.json"
    write_recommendation(str(p), rec)
    assert json.loads(p.read_text())["setpoints"]["crah_supply_air_temperature_c"] == 24.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_recommendation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.recommendation'`.

- [ ] **Step 3: Write the implementation**

`planner/recommendation.py`:

```python
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Sequence

from planner.types import Setpoints, WeeklyKPI


def energy_reduction_pct(plan_kwh: float, baseline_kwh: float) -> float:
    if not baseline_kwh:
        return 0.0
    return (baseline_kwh - plan_kwh) / baseline_kwh * 100.0


def safest_fallback(kpis: Sequence[WeeklyKPI]) -> int:
    """Index of the safest candidate: fewest inlet violations, then least energy."""
    return min(
        range(len(kpis)),
        key=lambda i: (kpis[i].inlet_violation_steps, kpis[i].total_hvac_energy_kwh),
    )


def build_recommendation(
    setpoints: Setpoints,
    kpi: WeeklyKPI,
    week_start: date,
    days: int,
    forecast_method: str,
    search_meta: dict,
    baseline_energy_kwh: Optional[float] = None,
    status: str = "pending_approval",
) -> dict:
    week_end = week_start + timedelta(days=days - 1)
    reduction = (
        energy_reduction_pct(kpi.total_hvac_energy_kwh, baseline_energy_kwh)
        if baseline_energy_kwh is not None
        else None
    )
    return {
        "schema_version": "1.0",
        "plan_id": f"gds-{week_start.isoformat()}",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "cadence": "weekly",
        "setpoints": {
            "crah_supply_air_temperature_c": round(setpoints.sat_c, 2),
            "crah_supply_air_mass_flow_rate_kg_s": round(setpoints.flow_kg_s, 2),
            "chilled_water_supply_temperature_c": round(setpoints.chwst_c, 2),
        },
        "predicted_kpis": {
            "total_hvac_energy_kwh": kpi.total_hvac_energy_kwh,
            "pue_mean": kpi.pue_mean,
            "inlet_temp_max_c": kpi.inlet_temp_max,
            "inlet_violation_steps": kpi.inlet_violation_steps,
            "energy_reduction_vs_baseline_pct": reduction,
        },
        "forecast": {"method": forecast_method, "weather": "TMY-window"},
        "search": dict(search_meta),
        "status": status,
    }


def write_recommendation(path: str, recommendation: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(recommendation, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_recommendation.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/recommendation.py src/tests/test_recommendation.py
git commit -m "feat(dtwin): recommendation.json builder + safe fallback"
```

---

## Task 3: Validation report (`validation.py`)

Pure comparison of plan vs baseline KPIs + markdown rendering.

**Files:**
- Create: `planner/validation.py`
- Test: `tests/test_validation.py`

- [ ] **Step 1: Write the failing test**

`tests/test_validation.py`:

```python
from planner.validation import validation_metrics, render_report
from planner.types import WeeklyKPI


def _kpi(energy, viol=0, inlet=24.0, pue=1.2):
    return WeeklyKPI(total_hvac_energy_kwh=energy, pue_mean=pue, inlet_temp_max=inlet,
                     inlet_violation_steps=viol, rh_violation_steps=0, feasible=True)


def test_validation_metrics():
    m = validation_metrics(ai=_kpi(80.0, viol=0, inlet=25.5), baseline=_kpi(100.0, viol=0))
    assert m["energy_reduction_pct"] == 20.0
    assert m["ai_energy_kwh"] == 80.0
    assert m["baseline_energy_kwh"] == 100.0
    assert m["ai_inlet_violations"] == 0
    assert m["passes"] is True   # reduction > 0 and 0 violations


def test_validation_fails_on_violations():
    m = validation_metrics(ai=_kpi(80.0, viol=3), baseline=_kpi(100.0))
    assert m["passes"] is False


def test_validation_fails_when_no_savings():
    m = validation_metrics(ai=_kpi(110.0, viol=0), baseline=_kpi(100.0))
    assert m["passes"] is False


def test_render_report_contains_key_numbers():
    m = validation_metrics(ai=_kpi(80.0), baseline=_kpi(100.0))
    text = render_report(m, plan_id="gds-2013-11-11")
    assert "gds-2013-11-11" in text
    assert "20.0" in text
    assert "PASS" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner.validation'`.

- [ ] **Step 3: Write the implementation**

`planner/validation.py`:

```python
from __future__ import annotations

from planner.recommendation import energy_reduction_pct
from planner.types import WeeklyKPI


def validation_metrics(ai: WeeklyKPI, baseline: WeeklyKPI) -> dict:
    reduction = energy_reduction_pct(ai.total_hvac_energy_kwh, baseline.total_hvac_energy_kwh)
    passes = (ai.inlet_violation_steps == 0) and (reduction > 0.0)
    return {
        "ai_energy_kwh": ai.total_hvac_energy_kwh,
        "baseline_energy_kwh": baseline.total_hvac_energy_kwh,
        "energy_reduction_pct": reduction,
        "ai_pue_mean": ai.pue_mean,
        "baseline_pue_mean": baseline.pue_mean,
        "ai_inlet_max_c": ai.inlet_temp_max,
        "ai_inlet_violations": ai.inlet_violation_steps,
        "passes": passes,
    }


def render_report(metrics: dict, plan_id: str) -> str:
    verdict = "PASS" if metrics["passes"] else "FAIL"
    return (
        f"# Pre-validation report — {plan_id}\n\n"
        f"**Verdict: {verdict}**\n\n"
        f"| Metric | Plan | Baseline |\n"
        f"|---|---|---|\n"
        f"| HVAC energy (kWh) | {metrics['ai_energy_kwh']:.1f} | {metrics['baseline_energy_kwh']:.1f} |\n"
        f"| PUE (mean) | {metrics['ai_pue_mean']:.3f} | {metrics['baseline_pue_mean']:.3f} |\n"
        f"| Energy reduction | {metrics['energy_reduction_pct']:.1f}% | — |\n"
        f"| Peak inlet (°C) | {metrics['ai_inlet_max_c']:.2f} | — |\n"
        f"| Inlet violations (steps) | {metrics['ai_inlet_violations']} | — |\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validation.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/planner/validation.py src/tests/test_validation.py
git commit -m "feat(dtwin): pre-validation metrics + markdown report"
```

---

## Task 4: Deploy gate (`deploy.py`)

Sim-only deployment: refuse unless approved, then run the plant (one oracle eval of the approved setpoints) and record realized KPIs. The status-gate logic is pure and unit-tested with a fake oracle; the real run is integration.

**Files:**
- Create: `deploy.py`
- Test: `tests/test_deploy_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_deploy_gate.py`:

```python
import json
from datetime import date

import pytest

from deploy import deploy
from planner.types import Setpoints, WeeklyKPI


class _FakeOracle:
    def __init__(self):
        self.calls = 0
    def evaluate(self, candidates, forecast=None):
        self.calls += 1
        return [WeeklyKPI(total_hvac_energy_kwh=77.0, pue_mean=1.19, inlet_temp_max=25.0,
                          inlet_violation_steps=0, rh_violation_steps=0, feasible=True)]


def _rec(status):
    return {
        "schema_version": "1.0", "plan_id": "gds-x", "week_start": "2013-11-11",
        "week_end": "2013-11-17", "cadence": "weekly",
        "setpoints": {"crah_supply_air_temperature_c": 24.0,
                      "crah_supply_air_mass_flow_rate_kg_s": 6.2,
                      "chilled_water_supply_temperature_c": 18.0},
        "predicted_kpis": {}, "forecast": {}, "search": {}, "status": status,
    }


def test_deploy_refuses_when_not_approved(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps(_rec("pending_approval")))
    with pytest.raises(PermissionError):
        deploy(str(p), oracle=_FakeOracle())


def test_deploy_runs_and_records_realized_when_approved(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps(_rec("approved")))
    orc = _FakeOracle()
    deploy(str(p), oracle=orc)
    out = json.loads(p.read_text())
    assert orc.calls == 1
    assert out["status"] == "deployed"
    assert out["realized_kpis"]["total_hvac_energy_kwh"] == 77.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_deploy_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'deploy'`.

- [ ] **Step 3: Write the implementation**

`deploy.py`:

```python
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from planner.types import Setpoints


def _setpoints_from_rec(rec: dict) -> Setpoints:
    s = rec["setpoints"]
    return Setpoints(
        sat_c=s["crah_supply_air_temperature_c"],
        flow_kg_s=s["crah_supply_air_mass_flow_rate_kg_s"],
        chwst_c=s["chilled_water_supply_temperature_c"],
    )


class _NullForecast:
    """Forecast token for deploy: workloads already materialized; carry week_start."""
    def __init__(self, week_start: date):
        self.week_start = week_start
    def materialize(self, project_root):  # already on disk from planning
        pass


def deploy(recommendation_path: str, oracle, forecast=None) -> dict:
    """Sim-only deployment: require approval, run the plant week, record realized KPIs.

    The physical-BMS adapter is intentionally a stub here (sim-only ground truth).
    To target a real BMS later, implement a `BmsAdapter.apply(setpoints, week)` and
    call it in place of the oracle plant-run below; the contract is the same dict.
    """
    rec = json.loads(Path(recommendation_path).read_text())
    if rec.get("status") != "approved":
        raise PermissionError(
            f"recommendation status is {rec.get('status')!r}; expert approval required"
        )

    setpoints = _setpoints_from_rec(rec)
    if forecast is None:
        forecast = _NullForecast(date.fromisoformat(rec["week_start"]))

    realized = oracle.evaluate([setpoints], forecast=forecast)[0]
    rec["realized_kpis"] = {
        "total_hvac_energy_kwh": realized.total_hvac_energy_kwh,
        "pue_mean": realized.pue_mean,
        "inlet_temp_max_c": realized.inlet_temp_max,
        "inlet_violation_steps": realized.inlet_violation_steps,
    }
    rec["status"] = "deployed"
    Path(recommendation_path).write_text(json.dumps(rec, indent=2))
    return rec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_deploy_gate.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/deploy.py src/tests/test_deploy_gate.py
git commit -m "feat(dtwin): sim-only deploy gate (approval-required) + BMS stub"
```

---

## Task 5: `prevalidation.py` — report + approval gate CLI

Pure approval helper is unit-tested (reusing Task 2/3 modules); the oracle-driven baseline run is integration (exercised in Task 8).

**Files:**
- Create: `prevalidation.py`
- Test: `tests/test_prevalidation_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_prevalidation_gate.py`:

```python
import json

from prevalidation import set_status


def test_set_status_approves(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps({"status": "pending_approval"}))
    set_status(str(p), "approved")
    assert json.loads(p.read_text())["status"] == "approved"


def test_set_status_reject(tmp_path):
    p = tmp_path / "recommendation.json"
    p.write_text(json.dumps({"status": "pending_approval"}))
    set_status(str(p), "rejected")
    assert json.loads(p.read_text())["status"] == "rejected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prevalidation_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prevalidation'`.

- [ ] **Step 3: Write the implementation**

`prevalidation.py`:

```python
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from planner.kpi import OracleSettings
from planner.oracle import ParallelEnvOracle, OracleConfig
from planner.types import Setpoints, WeeklyKPI
from planner.validation import validation_metrics, render_report


def set_status(recommendation_path: str, status: str) -> None:
    rec = json.loads(Path(recommendation_path).read_text())
    rec["status"] = status
    Path(recommendation_path).write_text(json.dumps(rec, indent=2))


def _kpi_from_predicted(rec: dict) -> WeeklyKPI:
    k = rec["predicted_kpis"]
    return WeeklyKPI(
        total_hvac_energy_kwh=k["total_hvac_energy_kwh"], pue_mean=k["pue_mean"],
        inlet_temp_max=k["inlet_temp_max_c"], inlet_violation_steps=k["inlet_violation_steps"],
        rh_violation_steps=0, feasible=True,
    )


class _Forecast:
    def __init__(self, week_start: date):
        self.week_start = week_start
    def materialize(self, root):
        pass


def run_prevalidation(recommendation_path: str, dt_engine_config: str,
                      baseline: Setpoints, project_root: str = ".") -> dict:
    """Compare the recommended plan (predicted KPIs) against a baseline run."""
    rec = json.loads(Path(recommendation_path).read_text())
    ai_kpi = _kpi_from_predicted(rec)

    orc = ParallelEnvOracle(base_prototxt=dt_engine_config, project_root=project_root,
                            config=OracleConfig(n_workers=1, use_process_pool=False,
                                                log_root="log/prevalidation"))
    week_start = date.fromisoformat(rec["week_start"])
    baseline_kpi = orc.evaluate([baseline], forecast=_Forecast(week_start))[0]

    metrics = validation_metrics(ai_kpi, baseline_kpi)
    report = render_report(metrics, plan_id=rec["plan_id"])
    Path("log/prevalidation").mkdir(parents=True, exist_ok=True)
    Path("log/prevalidation/report.md").write_text(report)
    print(report)
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-validation + expert approval gate")
    parser.add_argument("--recommendation", default="log/recommendation.json")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    parser.add_argument("--approve", action="store_true", help="mark plan approved")
    parser.add_argument("--reject", action="store_true", help="mark plan rejected")
    args = parser.parse_args()

    if args.approve:
        set_status(args.recommendation, "approved")
        print("approved")
    elif args.reject:
        set_status(args.recommendation, "rejected")
        print("rejected")
    else:
        # conservative baseline: coolest SAT/CHW, max flow
        from planner.types import DEFAULT_SEARCH_SPACE as S
        baseline = Setpoints(S.sat.lb, S.flow.ub, S.chwst.lb)
        run_prevalidation(args.recommendation, args.dt, baseline)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_prevalidation_gate.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/prevalidation.py src/tests/test_prevalidation_gate.py
git commit -m "feat(dtwin): prevalidation report + expert approval gate CLI"
```

---

## Task 6: `plan_weekly.py` — the WeeklyPlanTemplate entrypoint

Overrides `RecommendTemplate.run()` to run the planner and write `recommendation.json`. The pure pieces are already tested (Tasks 2–3); this wires them to the real oracle/forecaster, covered by the Task 8 integration test.

**Files:**
- Create: `plan_weekly.py`

- [ ] **Step 1: Write the implementation** (no separate unit test — the wiring is integration-tested in Task 8; pure logic is tested in Tasks 2, 9-Plan2)

`plan_weekly.py`:

```python
from __future__ import annotations

import argparse
import json
import pickle
from datetime import date
from pathlib import Path

import pandas as pd

from dcwiz_policy_template import RecommendTemplate
from dctwin.utils import config as dt_config

from planner.beam_search import BeamConfig, BeamPlanner
from planner.forecaster import StatisticalForecaster
from planner.objective import ObjectiveWeights
from planner.oracle import OracleConfig, ParallelEnvOracle
from planner.recommendation import build_recommendation, write_recommendation
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints


class WeeklyPlanTemplate(RecommendTemplate):
    """One-shot weekly planner: heuristic search over 3 setpoints, EnergyPlus-scored.

    Overrides run() because the base RecommendTemplate.run() expects a reactive
    dcbrain policy. The oracle owns the weekly run period (via forecast.week_start),
    so we do NOT pass recommendation_timestamp to __call__.
    """

    def initialize(self, *args, **kwargs):
        self.dt_engine_config = kwargs.get("dt_engine_config", "configs/dt/dt.prototxt")
        self.week_start = kwargs["week_start"]
        if isinstance(self.week_start, str):
            self.week_start = date.fromisoformat(self.week_start)
        self.days = int(kwargs.get("days", 7))
        self.timesteps_per_hour = int(kwargs.get("timesteps_per_hour", 4))
        self.baseline_energy_kwh = kwargs.get("baseline_energy_kwh")

        # forecaster from the fitted config (fit_forecaster.py output)
        fc_cfg = pickle.loads(Path(kwargs.get("forecaster_config", "models/forecaster.pkl")).read_bytes())
        his = pd.read_csv(fc_cfg["his_csv"])
        room2ite = json.loads(Path(fc_cfg["room2ite_path"]).read_text())
        self.forecaster = StatisticalForecaster(
            his, room2ite, fc_cfg["his_col_for_room"], method=fc_cfg["method"]
        )

        self.space = DEFAULT_SEARCH_SPACE
        self.oracle = ParallelEnvOracle(
            base_prototxt=self.dt_engine_config,
            project_root=".",
            config=OracleConfig(
                n_workers=int(kwargs.get("n_workers", 8)),
                timesteps_per_hour=self.timesteps_per_hour,
                log_root="log/plan",
            ),
        )
        self.beam = BeamConfig(
            grid=int(kwargs.get("grid", 5)),
            beam_width=int(kwargs.get("beam_width", 5)),
            levels=int(kwargs.get("levels", 3)),
        )
        self.planner = BeamPlanner(self.space, self.oracle, ObjectiveWeights(), self.beam)
        # satisfy base-class attribute presence (we override run, so these are unused)
        self.policy = self.planner
        self.obs = None
        self.data_file = kwargs.get("recommendation_out", "log/recommendation.json")

    def run(self, *args, **kwargs):
        n_steps = self.days * 24 * self.timesteps_per_hour
        forecast = self.forecaster.forecast(self.week_start, n_steps)

        result = self.planner.plan(forecast)
        if result.feasible:
            best, kpi, status = result.best, result.best_kpi, "pending_approval"
        else:
            self.logger.warning("No feasible plan found; using safest fallback setpoints")
            fb = Setpoints(self.space.sat.lb, self.space.flow.ub, self.space.chwst.lb)
            kpi = self.oracle.evaluate([fb], forecast)[0]
            best, status = fb, "infeasible_fallback"

        rec = build_recommendation(
            setpoints=best, kpi=kpi, week_start=self.week_start, days=self.days,
            forecast_method=forecast.method,
            search_meta={"evals": result.evals, "beam_width": self.beam.beam_width,
                         "levels": self.beam.levels},
            baseline_energy_kwh=self.baseline_energy_kwh, status=status,
        )
        out = Path(dt_config.config.LOG_DIR) / "recommendation.json"
        write_recommendation(str(out), rec)
        # also write to the conventional location for downstream tools
        write_recommendation("log/recommendation.json", rec)
        self.logger.info(f"Weekly recommendation written to {out} (status={status})")
        return rec


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the weekly Digital-Twin planner")
    parser.add_argument("--week-start", required=True, help="YYYY-MM-DD (Monday)")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    parser.add_argument("--forecaster", default="models/forecaster.pkl")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--grid", type=int, default=5)
    parser.add_argument("--beam-width", type=int, default=5)
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--n-workers", type=int, default=8)
    args = parser.parse_args()

    WeeklyPlanTemplate()(
        dt_engine_config=args.dt,
        forecaster_config=args.forecaster,
        week_start=args.week_start,
        days=args.days,
        grid=args.grid,
        beam_width=args.beam_width,
        levels=args.levels,
        n_workers=args.n_workers,
    )
    print("Weekly plan complete")
```

- [ ] **Step 2: Verify it imports and the suite is still green** (no E+ run here)

Run: `python -m pytest && python -c "import ast; ast.parse(open('plan_weekly.py').read()); print('plan_weekly.py parses')"`
Expected: all unit tests pass; prints `plan_weekly.py parses`.

- [ ] **Step 3: Commit**

```bash
git add src/plan_weekly.py
git commit -m "feat(dtwin): WeeklyPlanTemplate entrypoint (RecommendTemplate)"
```

---

## Task 7: Trajectory replay + baseline entrypoints

Both use `TrajectoryPolicyTemplate` baseline-mode with a fixed broadcast action. EnergyPlus-driven → exercised by Task 8.

**Files:**
- Create: `ai_trajectory_test.py`
- Create: `baseline_policy_test.py`

- [ ] **Step 1: Write `ai_trajectory_test.py`**

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

import dctwin
from dcwiz_policy_template import TrajectoryPolicyTemplate

from planner.env_actions import mapper_from_env
from planner.types import Setpoints


class AITrajectoryReplay(TrajectoryPolicyTemplate):
    """Replay the recommended weekly setpoints (held constant) over the full week."""

    def initialize(self, *args, **kwargs):
        dt_engine_config = kwargs.get("dt_engine_config", "configs/dt/dt.prototxt")
        recommendation = kwargs.get("recommendation", "log/recommendation.json")
        self.env = dctwin.make_env(env_proto_config=dt_engine_config, reward_fn=lambda x: 0)

        rec = json.loads(Path(recommendation).read_text())["setpoints"]
        setpoints = Setpoints(
            sat_c=rec["crah_supply_air_temperature_c"],
            flow_kg_s=rec["crah_supply_air_mass_flow_rate_kg_s"],
            chwst_c=rec["chilled_water_supply_temperature_c"],
        )
        self.act = mapper_from_env(self.env).expand(setpoints)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay recommended setpoints (pre-validation)")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    parser.add_argument("--recommendation", default="log/recommendation.json")
    args = parser.parse_args()
    AITrajectoryReplay()(policy="baseline", dt_engine_config=args.dt,
                         recommendation=args.recommendation)
    print("AI trajectory replay complete")
```

- [ ] **Step 2: Write `baseline_policy_test.py`**

```python
from __future__ import annotations

import argparse

import dctwin
from dcwiz_policy_template import TrajectoryPolicyTemplate

from planner.env_actions import mapper_from_env
from planner.types import DEFAULT_SEARCH_SPACE, Setpoints


class BaselineTrajectory(TrajectoryPolicyTemplate):
    """Conservative baseline: coolest SAT/CHW, maximum airflow (safe, energy-heavy)."""

    def initialize(self, *args, **kwargs):
        dt_engine_config = kwargs.get("dt_engine_config", "configs/dt/dt.prototxt")
        self.env = dctwin.make_env(env_proto_config=dt_engine_config, reward_fn=lambda x: 0)
        s = DEFAULT_SEARCH_SPACE
        baseline = Setpoints(sat_c=s.sat.lb, flow_kg_s=s.flow.ub, chwst_c=s.chwst.lb)
        self.act = mapper_from_env(self.env).expand(baseline)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the conservative baseline trajectory")
    parser.add_argument("--dt", default="configs/dt/dt.prototxt")
    args = parser.parse_args()
    BaselineTrajectory()(policy="baseline", dt_engine_config=args.dt)
    print("Baseline trajectory complete")
```

- [ ] **Step 3: Verify both parse + suite green**

Run:

```bash
python -m pytest && python -c "import ast; [ast.parse(open(f).read()) for f in ('ai_trajectory_test.py','baseline_policy_test.py')]; print('entrypoints parse')"
```

Expected: tests pass; prints `entrypoints parse`.

- [ ] **Step 4: Commit**

```bash
git add src/ai_trajectory_test.py src/baseline_policy_test.py
git commit -m "feat(dtwin): trajectory replay + conservative baseline entrypoints"
```

---

## Task 8: End-to-end integration + acceptance (M7)

Runs a tiny full plan on a short window, then the acceptance check (0 violations + energy reduction). Requires Docker + EnergyPlus image + assets from Task 1.

**Files:**
- Create: `tests/integration/test_plan_weekly.py`

- [ ] **Step 1: Ensure the forecaster is fitted (needed by plan_weekly)**

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
python fit_forecaster.py
ls models/forecaster.pkl
```

Expected: `models/forecaster.pkl` exists; stdout reports rooms mapped.

- [ ] **Step 2: Write the integration test**

`tests/integration/test_plan_weekly.py`:

```python
import json
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DT = "configs/dt/dt.prototxt"
FC = "models/forecaster.pkl"


@pytest.mark.skipif(not (Path(DT).exists() and Path(FC).exists()),
                    reason="model assets / fitted forecaster not present")
def test_tiny_weekly_plan_then_baseline_acceptance(tmp_path, monkeypatch):
    # shrink the planning window to 1 day and the search to a 2^3 grid for speed
    from planner import week_config
    orig = week_config.compute_week_period
    monkeypatch.setattr(week_config, "compute_week_period",
                        lambda ws, days=7: orig(ws, days=1))

    from plan_weekly import WeeklyPlanTemplate
    WeeklyPlanTemplate()(
        dt_engine_config=DT, forecaster_config=FC,
        week_start=date(2013, 11, 11), days=1,
        grid=2, beam_width=2, levels=0, n_workers=2,
    )

    rec = json.loads(Path("log/recommendation.json").read_text())
    assert rec["status"] in ("pending_approval", "infeasible_fallback")
    assert set(rec["setpoints"]) == {
        "crah_supply_air_temperature_c",
        "crah_supply_air_mass_flow_rate_kg_s",
        "chilled_water_supply_temperature_c",
    }

    # ACCEPTANCE: recommended plan must be feasible (0 inlet violations) and
    # use less HVAC energy than the conservative baseline.
    from planner.oracle import ParallelEnvOracle, OracleConfig
    from planner.types import DEFAULT_SEARCH_SPACE as S, Setpoints

    class _F:
        week_start = date(2013, 11, 11)
        def materialize(self, root): pass

    orc = ParallelEnvOracle(base_prototxt=DT,
                            config=OracleConfig(n_workers=2, use_process_pool=True,
                                                log_root=str(tmp_path / "acc")))
    rec_sp = rec["setpoints"]
    plan_sp = Setpoints(rec_sp["crah_supply_air_temperature_c"],
                        rec_sp["crah_supply_air_mass_flow_rate_kg_s"],
                        rec_sp["chilled_water_supply_temperature_c"])
    baseline_sp = Setpoints(S.sat.lb, S.flow.ub, S.chwst.lb)
    plan_kpi, base_kpi = orc.evaluate([plan_sp, baseline_sp], forecast=_F())

    assert plan_kpi.feasible and base_kpi.feasible
    assert plan_kpi.inlet_violation_steps == 0
    assert plan_kpi.total_hvac_energy_kwh < base_kpi.total_hvac_energy_kwh
```

- [ ] **Step 3: Run the integration test (Docker + EP image required)**

Run: `python -m pytest tests/integration/test_plan_weekly.py -v -m integration`
Expected: PASS (1 passed) — several minutes (multiple full-day E+ runs).

- [ ] **Step 4: Commit**

```bash
git add src/tests/integration/test_plan_weekly.py
git commit -m "test(dtwin): end-to-end weekly plan + acceptance (M7)"
```

---

## Task 9: Project README

Document the four entry modes + the weekly operator workflow.

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add src/README.md
git commit -m "docs(dtwin): project README with weekly operator workflow"
```

---

## Self-Review

**Spec coverage (Plan 3 = spec §6 layout, §8 template integration, §9 outer loop, §13 M0/M5–M7):**
- M0 scaffold (assets + gitignore) → Task 1. ✅
- §8.1 four modes: ai policy test=`plan_weekly.py` (Task 6), ai policy train=`fit_forecaster.py` (Plan 2 Task 10), ai trajectory test=`ai_trajectory_test.py` + baseline=`baseline_policy_test.py` (Task 7). ✅
- §8.2 `recommendation.json` versioned schema + status transitions → Task 2 (build), Task 5 (approve), Task 4 (deploy). ✅
- §9 pre-validation report (Task 3 + Task 5), expert approval gate (Task 5), sim-only deploy + realized KPIs + BMS stub (Task 4). ✅
- §11 infeasible-fallback in the weekly run → Task 6 `run()`. ✅
- §13 M7 acceptance (0 violations + energy reduction) → Task 8. ✅

**Placeholder scan:** No TBD/TODO/"add later" — every step has full code + exact command + expected output. ✅

**Type consistency:** `Setpoints(sat_c, flow_kg_s, chwst_c)`, `WeeklyKPI` fields, `ParallelEnvOracle(base_prototxt, config=OracleConfig, project_root)`, `OracleConfig(n_workers, use_process_pool, log_root, timesteps_per_hour)`, `BeamPlanner(space, evaluator, weights, config).plan(forecast)`, `StatisticalForecaster(his, room2ite, his_col_for_room, method).forecast(week_start, n_steps)`, `Forecast.week_start`/`.materialize(project_root)`/`.method`, `build_recommendation(...)`, `validation_metrics(ai, baseline)` are used identically across Plans 1–3. The recommendation dict keys (`setpoints.*`, `predicted_kpis.*`, `status`) match between `build_recommendation` (Task 2), `deploy` (Task 4), `prevalidation` (Task 5), and `ai_trajectory_test` (Task 7). ✅

---

## Execution Handoff

Plans 1–3 are complete (26 tasks total). Together they build the full Digital Twin Dual-Loop Control Framework: a TDD planner core, an EnergyPlus-backed parallel oracle, a statistical forecaster, the four dcwiz template entry modes, and the pre-validation / expert-approval / sim-only deployment outer loop, with an end-to-end acceptance test.
