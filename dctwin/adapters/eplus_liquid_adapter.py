import shutil
import csv
from typing import Tuple, Union, List, Callable
from pathlib import Path

from dclib import Building

from dctwin.utils import config
from dctwin.backends import LiquidCoolingManager
from dctwin.backends import EplusBackend


class EplusLiquidAdapter:
    """
    A class to manage the co-simulation data hall liquid cooling simulation and the chiller plant simulation.
    """
    def __init__(
        self,
        building: Building,
        eplus_backend: EplusBackend,
        map_cdu_inputs_fn: Callable,
    ) -> None:
        self.liquid_managers = {}
        for room_name, room in building.constructions.zones.items():
            self.liquid_managers[room_name] = LiquidCoolingManager(
                room=room,
            )
        self.eplus_manager = eplus_backend
        self._map_cdu_inputs_fn = map_cdu_inputs_fn
        self.episode_idx, self.step_idx = 1, 1

    def _pre_process(self, episode_idx: int = 0) -> None:
        """create case directory and backup model files"""
        config.cfd.case_dir = Path(config.LOG_DIR).joinpath(
            "cdu_output", f"episode-{episode_idx}"
        )
        Path(config.cfd.case_dir).mkdir(exist_ok=True, parents=True)
        room_path = Path(config.cfd.case_dir).joinpath(config.cfd.geometry_file.name)
        idf2room_path = Path(config.cfd.case_dir).joinpath(
            config.eplus_cfd.idf2room_map.name
        )
        shutil.copy(config.cfd.geometry_file, room_path)
        shutil.copy(config.eplus_cfd.idf2room_map, idf2room_path)
        # init log file for cfd results
        filename = Path(config.cfd.case_dir).joinpath("cfd_log.csv")
        config.cfd.file_handler = open(filename, "wt", newline="")
        cdu_cooling_water_supply_temperature_cols = []
        cdu_cooling_water_mass_flow_rate_cols = []
        cdu_cooling_water_return_temperature_cols = []
        cdu_chilled_water_supply_temperature_cols = []
        cdu_chilled_water_mass_flow_rate_cols = []
        cdu_chilled_water_return_temperature_cols = []
        cdu_power_cols = []
        for room_name, liquid_manager in self.liquid_managers.items():
            for cdu_name in liquid_manager.room.constructions.cdus.keys():
                cdu_cooling_water_supply_temperature_cols.append(f"{cdu_name} Cooling Water Supply T (C)")
                cdu_cooling_water_mass_flow_rate_cols.append(f"{cdu_name} Cooling Water Supply M (kg/s)")
                cdu_cooling_water_return_temperature_cols.append(f"{cdu_name} Cooling Water Return T (C)")
                cdu_chilled_water_supply_temperature_cols.append(f"{cdu_name} Chilled Water Supply T (C)")
                cdu_chilled_water_mass_flow_rate_cols.append(f"{cdu_name} Chilled Water Supply M (kg/s)")
                cdu_chilled_water_return_temperature_cols.append(f"{cdu_name} Chilled Water Return T (C)")
                cdu_power_cols.append(f"{cdu_name} Electricity Demand Rate (W)")
        config.cfd.log_handler = csv.DictWriter(
            config.cfd.file_handler,
            fieldnames=(
                ["timestamp"]
                + cdu_cooling_water_supply_temperature_cols
                + cdu_cooling_water_mass_flow_rate_cols
                + cdu_cooling_water_return_temperature_cols
                + cdu_chilled_water_supply_temperature_cols
                + cdu_chilled_water_mass_flow_rate_cols
                + cdu_chilled_water_return_temperature_cols
                + cdu_power_cols
                + ["Total CDU Power (w)"]
                + ["Total CDU Cooling Water M (kg/s)"]
                + ["Total CDU Chilled Water M (kg/s)"]
            )
        )
        config.cfd.log_handler.writeheader()
        config.cfd.file_handler.flush()

    def _post_processing(self):
        total_cdu_chilled_water_flow_rate = 0
        cdu_chilled_water_flow_rate = {}
        cdu_power = {}
        for room_name, liquid_manager in self.liquid_managers.items():
            for cdu_name, cdu in liquid_manager.cdus.items():
                cdu_chilled_water_flow_rate[cdu_name] = cdu.config.cooling.operating.supply_side_mass_flow_rate
                cdu_power[cdu_name] = cdu.config.constructions.pump.power.operating.pump_power
                total_cdu_chilled_water_flow_rate += cdu.config.cooling.operating.supply_side_supply_temperature
        # log CDU simulation results
        return total_cdu_chilled_water_flow_rate, cdu_power, cdu_chilled_water_flow_rate

    def send_action(self, parsed_actions):
        self.step_idx += 1
        # boundary_conditions = self.map_boundary_conditions(parsed_actions)
        cdu_inputs = self._map_cdu_inputs_fn(self, parsed_actions)
        # run CFD/POD simulation
        for room_name, liquid_manager in self.liquid_managers.items():
            liquid_manager.sim()
        # post-processing CFD/POD simulation result to obtain return temperature
        total_cdu_chilled_water_flow_rate, cdu_power, cdu_chilled_water_flow_rate = self._post_processing()
        # add two approach temperatures (a.k.a. return temperature actually) to the end of the raw action array
        send_actions = []
        for value in parsed_actions.values():
            send_actions.append(value)
        # send raw action array to Eplus to proceed the energy simulation
        self.eplus_manager.send_action(send_actions)

    def receive_status(self) -> Tuple[Union[List[float], None], bool]:
        # get energy status from Eplus as observation
        eplus_obs, done = self.eplus_manager.receive_status()
        # combine co-sim sensor observation with Eplus observation
        obs = eplus_obs + self.cfd_sensor_obs
        return obs, done
