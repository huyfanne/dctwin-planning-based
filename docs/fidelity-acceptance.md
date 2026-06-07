# Fidelity/Safety Gate — Realized Acceptance

This records the realized (not predicted-only) acceptance run for the
fidelity/safety gate. It replaces the earlier predicted-only "11.4% energy /
0 violations" claim — which was measured on the twin, not on the plant the
plan would actually run against — with a result that exercises the full
plan → robust re-rank → (approve → deploy → backstop) loop on the perturbed
EnergyPlus plant.

## Command

```bash
cd /mnt/lv/home/hoanghuy/newcode/dctwin/src
sg docker -c "PYTHONPATH=$PWD /mnt/lv/home/hoanghuy/newcode/dctwin/.venv-dtwin/bin/python \
  -m pytest tests/integration/test_fidelity_gate.py -m integration -v"
```

Result: `1 passed` (≈7m51s — real EnergyPlus 9.5 runs via the
`ghcr.io/cap-dcwiz/energyplus-9-5-0` Docker image).

## Run metadata

- Date: 2026-06-07
- Git SHA: `6d153280` (`6d15328099911898d3f9c30f0d1b2cc0b340a614`)
- Branch: `feat/close-fidelity-safety-gap`
- Plan params: `week_start=2013-11-11`, `days=1`, `grid=3`, `beam_width=2`,
  `levels=1`, `n_workers=2`, `n_scenarios=2`

## Realized outcome — the breach cannot ship

The plan ended in **`blocked_unsafe`** — gated at plan time by the robust
re-rank, before it could ever reach `pending_approval`/`approved`/`deployed`.
On the perturbed plant the winning candidate breaches and no finalist is safe,
so the breach is blocked at the earliest possible point in the loop.

The robust-evaluated winner KPIs at the gate:

| KPI | Calibrated | Raw (pre-calibration) |
|---|---|---|
| `inlet_violation_steps` | **666** | **666** |
| `inlet_temp_max_c` | 37.88 °C | 33.69 °C |
| `total_hvac_energy_kwh` | 696704.19 | 354745.37 |
| `pue_mean` | 1.1838 | 1.1779 |

The 666 inlet-violation steps are exactly the breach the design called out:
the plan that the predicted-only pipeline would have shipped as "safe" is
instead recognized as breaching on the plant and is `blocked_unsafe`. Because
the gate fires at plan time, the deploy-time backstop is not reached in this
run; the acceptance test asserts the alternative branches too — had the plan
reached deploy, the realized week would either be clean (`deployed`) or the
backstop would set `deploy_blocked` — never silently `deployed` with a breach.

## Acceptance criterion (spec §4.5)

A plan that breaches on the perturbed plant must end **either** gated
(`blocked_unsafe` / `deploy_blocked`) **or** with a realized 0-violation deploy
— never `deployed` with a breach. This run satisfies it: the demonstrated
666-violation deployment cannot ship.
