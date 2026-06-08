"""Spot-check the recirc recouple: does the 1F-2A inlet now TRACK the SAT setpoint?

Runs two real EnergyPlus candidates (SAT 20 vs SAT 26, same flow/CHWST) and reports the
ITE-1 inlet max + hall inlet max for each. Pre-fix baseline (recirc=1.0): ITE-1 ~23.3 C
bit-invariant. If recoupled (recirc=0.1), SAT=20 should give a markedly LOWER ITE-1 inlet
than SAT=26 (the inlet now follows the cooled supply). Run under `sg docker`.
"""
import glob
import os
import sys
from pathlib import Path

SRC = Path("/mnt/lv/home/hoanghuy/newcode/dctwin/src")
os.chdir(SRC)
sys.path.insert(0, str(SRC))

from datetime import date                         # noqa: E402

from planner.kpi import OracleSettings            # noqa: E402
from planner.oracle_worker import EvalTask, evaluate_one  # noqa: E402
from planner.week_config import write_week_config  # noqa: E402

# Fresh config with the ACU masking LIFTED (the fix under test) — 2 days for speed.
WC = write_week_config("configs/dt/dt.prototxt", date(2024, 12, 1),
                       "runs/_recouple_check/week.prototxt", days=2)


def _ite1_steadystate(log_dir: Path):
    """ITE-1 inlet, mean over the 2nd half of the run (steady state — excludes the
    startup-warmup transient, which is SAT-independent and otherwise dominates the max)."""
    csvs = glob.glob(str(log_dir / "**" / "eplusout.csv"), recursive=True)
    if not csvs:
        return None
    with open(csvs[0]) as f:
        header = f.readline().split(",")
        i1 = next((k for k, h in enumerate(header)
                   if "DATA HALL 1F 2A ITE-1:" in h.upper() and "AIR INLET DRY-BULB" in h.upper()), None)
        if i1 is None:
            return None
        vals = []
        for line in f:
            try:
                vals.append(float(line.split(",")[i1]))
            except (ValueError, IndexError):
                pass
    if not vals:
        return None
    half = vals[len(vals) // 2:]
    return sum(half) / len(half)


def run(sat: float, tag: str):
    ld = SRC / "runs" / "_recouple_check" / tag
    ld.mkdir(parents=True, exist_ok=True)
    task = EvalTask(candidate=(sat, 9.3, 16.0), week_config_path=WC, log_dir=str(ld),
                    hours_per_step=0.25, settings_kwargs=OracleSettings().__dict__,
                    monitored_hall="1f 2a", timeout_s=300.0)
    kpi = evaluate_one(task)
    ite1 = _ite1_steadystate(ld)
    print(f"SAT={sat:>4}: kpi.inlet_temp_max={kpi.inlet_temp_max:.2f}  "
          f"energy_kwh={kpi.total_hvac_energy_kwh:.0f}  ITE-1_inlet_steadystate={ite1:.2f}",
          flush=True)
    return ite1


if __name__ == "__main__":
    a = run(20.0, "sat20")
    b = run(26.0, "sat26")
    if a is not None and b is not None:
        print(f"\nITE-1 steady-state inlet: SAT20={a:.2f}  SAT26={b:.2f}  delta={b - a:+.2f} C", flush=True)
        print("RECOUPLED (inlet tracks SAT)" if (b - a) > 1.0 else
              "STILL DECOUPLED (inlet did not move with SAT)", flush=True)
