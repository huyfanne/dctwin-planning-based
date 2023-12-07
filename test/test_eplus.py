from pathlib import Path
import numpy as np

from dclib import Building
from dctwin.utils.builder import IDFBuilder, ConfigBuilder
from dctwin.registraion import make_env

if __name__ == "__main__":
    # Build IDF file
    building = Building.load("models/building/building.json")
    manager = IDFBuilder(
        building=building,
    )
    manager.make()
    manager.save(
        idf_save_dir=Path("models/idf"),
        device_key_map_save_dir=Path("models/building"),
    )

    # Build config file
    config = ConfigBuilder(
        building=building,
        device_key_map=manager.device_key_map,
    )
    config.make_eplus_env_config(
        idf_file=Path("models/idf/building.idf"),
        weather_file=Path("data/weather/SGP_Singapore.486980_IWEC.epw"),
        network="host",
        host="host.docker.internal"
    )
    config.make_cpu_loading_schedules(
        schedule_dir=Path("data/schedule/workloads")
    )
    config.make_acu_supply_air_temperature_actions()
    config.make_acu_supply_air_flow_rate_actions()
    config.make_chilled_water_loop_supply_temperature_actions()
    config.make_chilled_water_loop_observations(exposed=False)
    config.make_acu_fan_observations(exposed=False)
    config.make_cooling_coil_observations(exposed=False)
    config.make_pump_observations(exposed=False)
    config.make_chiller_observations(exposed=False)
    config.make_cooling_tower_observations(exposed=False)
    config.make_zone_observations(exposed=False)
    config.make_ite_observations(exposed=False)
    config.save(path="configs/test_eplus.prototxt")

    # Run simulation
    engine_config = "configs/test_eplus.prototxt"
    env = make_env(
        env_proto_config=engine_config,
        reward_fn=lambda x: 0.0,
    )
    env.reset()
    acu_setpoint_sp = 18.0
    acu_supply_flow = 15.0
    water_supply_sp = 7.0
    act = np.array([acu_setpoint_sp, acu_supply_flow, water_supply_sp])
    done = False
    while not done:
        obs, rew, done, truncated, info = env.step(act)
