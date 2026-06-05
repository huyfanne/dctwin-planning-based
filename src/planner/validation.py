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
