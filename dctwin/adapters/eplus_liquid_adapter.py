import csv
from typing import Tuple, Union, List, Callable, Dict
from pathlib import Path

import numpy as np
from dclib import Building

from dctwin.utils import config
from dctwin.backends import LiquidCoolingManager
from dctwin.backends import EplusBackend


class EplusLiquidAdapter:
    """
    A class to manage the co-simulation data hall liquid cooling (CDU) simulation and the chiller plant simulation.
    """
    def __init__(
        self,
        building: Building,
        eplus_backend: EplusBackend,
        map_cdu_inputs_fn: Callable,
    ) -> None:
        self.building = building
        self._init_room_liquid_cooling_managers()
        self.eplus_manager = eplus_backend
        self._map_cdu_inputs_fn = map_cdu_inputs_fn
        self.episode_idx, self.step_idx = 1, 1

    def _init_room_liquid_cooling_managers(self) -> None:
        self.liquid_managers = {}
        for room_name, room in self.building.constructions.zones.items():
            self.liquid_managers[room_name] = LiquidCoolingManager(
                room=room,
            )

    def _pre_process(self, episode_idx: int = 0) -> None:
        """create case directory and backup model files"""
        config.cdu.case_dir = Path(config.LOG_DIR).joinpath(
            "cdu_output", f"episode-{episode_idx}"
        )
        Path(config.cdu.case_dir).mkdir(exist_ok=True, parents=True)
        # init log file for cdu simulation results
        filename = Path(config.cfd.case_dir).joinpath("cdu_log.csv")
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
        config.cdu.log_handler.writeheader()
        config.cfd.file_handler.flush()

    def _post_processing(
        self,
        cdu_sim_results: Dict[str, Dict[str, Dict[str, float]]],
    ):
        # store simulation results to the building model
        for manager_name, manager in self.liquid_managers.items():
            for cdu_name, cdu in manager.cdus.items():
                cdu.config.cooling.operating.supply_side_supply_temperature = cdu_sim_results[manager_name][
                    cdu_name
                ]["cdu_cooling_water_supply_temperatures"]
                cdu.config.cooling.operating.supply_side_return_temperature = cdu_sim_results[manager_name][
                    cdu_name
                ]["cdu_cooling_water_return_temperatures"]
                cdu.config.cooling.operating.demand_side_supply_temperature = cdu_sim_results[manager_name][
                    cdu_name
                ]["cdu_chilled_water_supply_temperatures"]
                cdu.config.cooling.operating.demand_side_return_temperature = cdu_sim_results[manager_name][
                    cdu_name
                ]["cdu_chilled_water_return_temperatures"]
                cdu.config.cooling.operating.demand_side_mass_flow_rate = cdu_sim_results[manager_name][
                    cdu_name
                ]["cdu_chilled_water_mass_flow_rates"]
                cdu.config.constructions.pump.power.operating.pump_power = cdu_sim_results[manager_name][
                    cdu_name
                ]["cdu_electrical_powers"]
        # log CDU simulation results
        cdu_log_dict = {}
        cdu_log_dict.update({"timestamp": config.eplus_cdu.timestamp})
        total_cdu_power = 0
        total_cdu_chilled_water_flow_rate = 0
        total_cdu_cooling_water_flow_rate = 0
        for manager_name, manager in self.liquid_managers.items():
            for cdu_name, cdu in manager.cdus.items():
                cdu_log_dict.update(
                    {f"{cdu_name} Cooling Water Supply T (C)": round(
                        cdu.config.cooling.operating.supply_side_supply_temperature, 3)
                    }
                )
                cdu_log_dict.update(
                    {f"{cdu_name} Cooling Water Supply M (kg/s)": round(
                        cdu.config.cooling.operating.supply_side_mass_flow_rate, 3)
                    }
                )
                cdu_log_dict.update(
                    {f"{cdu_name} Cooling Water Return T (C)": round(
                        cdu.config.cooling.operating.demand_side_return_temperature, 3)
                    }
                )
                cdu_log_dict.update(
                    {f"{cdu_name} Chilled Water Supply T (C)": round(
                        cdu.config.cooling.operating.demand_side_supply_temperature, 3)
                    }
                )
                cdu_log_dict.update(
                    {f"{cdu_name} Chilled Water Supply M (kg/s)": round(
                        cdu.config.cooling.operating.demand_side_mass_flow_rate, 3)
                    }
                )
                cdu_log_dict.update(
                    {f"{cdu_name} Chilled Water Return T (C)": round(
                        cdu.config.cooling.operating.demand_side_return_temperature, 3)
                    }
                )
                cdu_log_dict.update({f"{cdu_name} Electricity Demand Rate (W)": round(
                    cdu.config.constructions.pump.power.operating.pump_power, 3)}
                )
                # update total CDU power, cooling water mass flow rate and chilled water mass flow rate
                total_cdu_power += cdu.config.constructions.pump.power.operating.pump_power
                total_cdu_chilled_water_flow_rate += cdu.config.cooling.operating.demand_side_mass_flow_rate
                total_cdu_cooling_water_flow_rate += cdu.config.cooling.operating.supply_side_mass_flow_rate
        # log aggregated
        cdu_log_dict.update({"Total CDU Power (w)": round(total_cdu_power, 3)})
        cdu_log_dict.update({"Total CDU Cooling Water M (kg/s)": round(total_cdu_cooling_water_flow_rate, 3)})
        cdu_log_dict.update({"Total CDU Chilled Water M (kg/s)": round(total_cdu_chilled_water_flow_rate, 3)})

    def run(self, episode_idx) -> tuple[float | None, float | None]:
        self.episode_idx = episode_idx
        eplus_obs, done = self.eplus_manager.run(episode_idx)
        return eplus_obs, done

    def send_action(self, parsed_actions: Dict[str, float | np.ndarray]):
        self.step_idx += 1
        (
            server_powers,
            server_mass_flow_rates,
            server_liquid_cooling_percentages,
            cdu_cooling_water_supply_temperature_sps,
            cdu_chilled_water_supply_temperatures,
        ) = self._map_cdu_inputs_fn(self, parsed_actions)
        # run CFD/POD simulation
        cdu_sim_results = {}
        for manager_name, manager in self.liquid_managers.items():
            (
                cdu_electrical_powers,
                cdu_chilled_water_return_temperatures,
                cdu_cooling_water_supply_temperatures,
                cdu_return_temperatures,
                cdu_chilled_water_mass_flow_rates,
                cdu_hx_infos
            ) = manager.sim(
                server_powers=server_powers,
                server_mass_flow_rates=server_mass_flow_rates,
                server_liquid_cooling_percentages=server_liquid_cooling_percentages,
                cooling_water_supply_temperature_sps=cdu_cooling_water_supply_temperature_sps,
                chilled_water_supply_temperatures=cdu_chilled_water_supply_temperatures,
            )
            cdu_sim_results[manager_name] = {
                "cdu_electrical_powers": cdu_electrical_powers,
                "cdu_chilled_water_return_temperatures": cdu_chilled_water_return_temperatures,
                "cdu_cooling_water_supply_temperatures": cdu_cooling_water_supply_temperatures,
                "cdu_return_temperatures": cdu_return_temperatures,
                "cdu_chilled_water_mass_flow_rates": cdu_chilled_water_mass_flow_rates,
                "cdu_hx_infos": cdu_hx_infos,
            }
        # post-processing CFD/POD simulation result to obtain return temperature
        self._post_processing(
            cdu_sim_results=cdu_sim_results
        )
        # reformat action dictionary to numpy array that can be accepted by Eplus
        send_actions = []
        for value in parsed_actions.values():
            send_actions.append(value)
        # send raw action array to Eplus to proceed the energy simulation
        self.eplus_manager.send_action(send_actions)

    def receive_status(self) -> Tuple[Union[List[float], None], bool]:
        eplus_obs, done = self.eplus_manager.receive_status()
        return eplus_obs, done
