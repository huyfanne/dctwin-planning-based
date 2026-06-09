# recirc Sensitivity Sweep — Results (real EnergyPlus)

Fixed setpoint; week_start=2024-11-11. Energy is the hall-scoped controllable HVAC
(1F-2A fans + chiller/CHW plant). The recirculation fraction is the `Coefficient1 Constant`
of each 1F-2A ITE `recirculation function of loading and supply temperature` curve,
patched by `scripts/recouple_ite_recirc.py`.

## Sweep A — mid setpoint (SAT 23, flow 9.3 kg/s, CHWST 16), days=3

| recirc | inlet max (°C) | inlet violations | HVAC energy (kWh) | feasible |
|---|---|---|---|---|
| 0.05 | 23.854 | 0 | 279815.3 | True |
| 0.10 | 23.854 | 0 | 279815.3 | True |
| 0.15 | 23.854 | 0 | 279815.3 | True |
| 0.20 | 23.854 | 0 | 279815.3 | True |

## Sweep B — low flow (SAT 23, flow 4.8 kg/s, CHWST 16), days=3

| recirc | inlet max (°C) | inlet violations | HVAC energy (kWh) | feasible |
|---|---|---|---|---|
| 0.05 | 23.00 | 0 | 262626 | True |
| 0.10 | 23.00 | 0 | 262626 | True |
| 0.20 | 23.00 | 0 | 262626 | True |
| 0.30 | 23.00 | 0 | 262626 | True |
| 0.50 | 23.00 | 0 | 262626 | True |

## Finding: the recirc fraction is currently INERT

Across **both** flows and recirc from **0.05 to 0.50**, the binding inlet temperature and the
HVAC energy are **bit-identical**. The patch lands (the run log confirms `Coefficient1
Constant = 0.05…0.50`) and the curve is referenced by the `AdjustedSupply` ITE objects, yet
the simulated inlet never moves. So the inlet is driven by **supply-air temperature (SAT) plus
a flow-dependent fan-heat term**, NOT by recirculation: at flow 4.8 the inlet equals SAT
(23.0 °C); at flow 9.3 it is 23.85 °C (added fan heat at higher airflow). The zone-air
reference the ITE blends against sits at ≈ the supply temperature, so the recirculation term
mixes two near-equal temperatures and contributes nothing.

### Consequences
1. **Calibrating recirc=0.10 is currently moot** — the parameter has no effect on the inlet
   or the energy, so there is nothing to tune until the recirculation path is made live.
2. **The model effectively assumes near-perfect containment.** A real hall with imperfect
   hot/cold-aisle separation would show rack inlets running hotter than supply, especially at
   low airflow / high load. The model does not currently impose that penalty, so the inlet
   safety margin should be treated as **optimistic**.
3. The hard inlet cap (≤ 26 °C) and the robust deploy margin remain the safety backstop and
   are unaffected by this; they read the correct signal (see the monitor-safety review).

### Recommended next step (NOT a blind recalibration)
Make recirculation a *live* lever before calibrating: investigate why the `AdjustedSupply`
recirculation curve does not raise the inlet (the zone-air reference node / connection wiring),
so the fraction actually blends in warmer return air. Only then does fitting it to **measured
per-rack inlet temperatures** (which do not exist in `his_data` today — power/PDU/supply-temp
telemetry only) become meaningful. Until measured inlets exist and the path is live, keep 0.10
as a documented placeholder and rely on the hard cap + robust margin.
