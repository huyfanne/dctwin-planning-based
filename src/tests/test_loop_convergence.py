"""Prove the calibration learning loop converges over N weeks with NO EnergyPlus.

Twin = MockEvaluator(MockSurface(inlet_base=20)) — energy-optimum inlet ~24.7 C (near the
26 C cap). Plant = the same surface shifted +2 C (MockSurface(inlet_base=22)) — a fixed +2 C
realized inlet bias. (+2 C is below the NOW-tier RESIDUAL_CLIP of 3 C, so calibration can
LEARN it fully; the twin opt at ~24.7 C means +2 C breaches week 1.) Each week: plan on the
twin (with the k*sigma pre-tighten + the learned calibration) -> 'deploy' on the plant ->
learn (advance_calibration on RAW predicted vs realized -> recompute_calibration) -> re-plan.
"""
from datetime import date

from planner.pipeline import run_weekly_plan, PlanRequest
from planner.mock_evaluator import MockEvaluator, MockSurface
from planner.calibrator import Calibration, recompute_calibration
from planner.history import advance_calibration
from planner.types import Setpoints


class _FakeForecaster:
    method = "persistence"
    def forecast(self, week_start, n_steps):
        class _F:
            week_start = date(2013, 11, 11)
            method = "persistence"
            def materialize(self, root): pass
        return _F()


def _sp(rec):
    s = rec["setpoints"]
    return Setpoints(s["crah_supply_air_temperature_c"],
                     s["crah_supply_air_mass_flow_rate_kg_s"],
                     s["chilled_water_supply_temperature_c"])


def test_multi_week_loop_converges(tmp_path):
    twin = MockEvaluator(MockSurface(inlet_base=20.0))       # predicts inlet x (opt ~24.7 C)
    plant = MockEvaluator(MockSurface(inlet_base=22.0))      # realizes inlet x + 2
    histp = str(tmp_path / "calibration_history.json")
    calp = str(tmp_path / "calibration.json")
    cal = Calibration.identity()

    sigmas, biases, realized_violations, statuses = [], [], [], []
    for wk in range(4):
        rec = run_weekly_plan(
            PlanRequest(week_start=date(2013, 11, 4 + wk), days=1, grid=4, beam_width=3, levels=2),
            evaluator=twin, forecaster=_FakeForecaster(), calibration=cal)
        rk = plant.evaluate([_sp(rec)])[0]                    # 'deploy' on the plant
        realized = {"total_hvac_energy_kwh": rk.total_hvac_energy_kwh,
                    "pue_mean": rk.pue_mean, "inlet_temp_max_c": rk.inlet_temp_max}
        # learn from RAW predicted (uncalibrated) vs realized
        advance_calibration(rec["predicted_kpis_raw"], realized, date(2013, 11, 4 + wk), histp)
        cal = recompute_calibration(histp, calp)
        sigmas.append(cal.sigma["inlet_temp_max_c"])
        biases.append(cal.bias["inlet_temp_max_c"])
        realized_violations.append(rk.inlet_violation_steps)
        statuses.append(rec["status"])

    assert realized_violations[0] > 0                         # week 1 breaches (nothing learned yet)
    assert all(v == 0 for v in realized_violations[1:])       # feasible once the bias is learned
    # spec §4.3: the plan does not regress to a blocked/fallback status after convergence
    assert all(s not in ("blocked_unsafe", "infeasible_fallback") for s in statuses[1:])
    assert sigmas == sorted(sigmas, reverse=True)             # sigma non-increasing (converges)
    assert abs(biases[-1] - biases[-2]) < 1e-6                # bias stabilized (fixed +2 C)
    assert abs(biases[-1] - 2.0) < 0.5                        # learned ~the true +2 C plant bias
