from planner.kpi import StepSample, OracleSettings, step_trajectory
from planner.trajectory import write_trajectory_csv


def _smp(power, it, inlet):
    return StepSample(total_power_w=power, it_power_w=it, inlet_temps=[inlet])


def test_step_trajectory_rows():
    samples = [_smp(1200.0, 1000.0, 24.0), _smp(1300.0, 1000.0, 25.0)]
    rows = step_trajectory(samples, hours_per_step=0.25, settings=OracleSettings(warmup_steps=0))
    assert len(rows) == 2
    assert rows[0]["step"] == 0
    assert rows[0]["inlet_temp_max_c"] == 24.0
    assert rows[0]["hvac_power_kw"] == 0.2          # (1200-1000)/1000
    assert abs(rows[1]["pue"] - 1.3) < 1e-9         # 1300/1000


def test_write_trajectory_csv(tmp_path):
    rows = [{"step": 0, "inlet_temp_max_c": 24.0, "hvac_power_kw": 0.2, "pue": 1.2}]
    out = tmp_path / "trajectory_ai.csv"
    write_trajectory_csv(rows, str(out))
    text = out.read_text().splitlines()
    assert text[0] == "step,inlet_temp_max_c,hvac_power_kw,pue"
    assert text[1] == "0,24.0,0.2,1.2"
