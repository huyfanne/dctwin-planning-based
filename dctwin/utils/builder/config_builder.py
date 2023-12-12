from typing import Union, OrderedDict
from google.protobuf import text_format
from dctwin.utils.dt_engine_pb2 import DTEngineConfig
from loguru import logger

from dclib import Building
from pathlib import Path

from dclib.cooling.plant.plant import ChilledWaterLoops, CondenserWaterLoops


class ConfigBuilder:

    def __init__(
        self,
        building: Building,
        device_key_map: dict,
    ):
        self.building = building
        self.device_key_map = device_key_map
        self.model = DTEngineConfig()

    """Private utility functions"""
    def _make_observation(
        self,
        exposed: bool,
        variable_name: str,
        key_value: str,
        output_variable_name:str,
        reporting_frequency: str,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        observation = self.model.eplus_env_config.observations.add()
        observation.exposed = exposed
        observation.variable_name = variable_name
        observation.output_variable_config.key_value = key_value
        observation.output_variable_config.variable_name = output_variable_name
        observation.output_variable_config.reporting_frequency = reporting_frequency
        if normalize_method:
            assert lb is not None and ub is not None, (
                logger.critical("For normalized observations, the lower bound and upper bound must be provided."),
                exit(1)
            )
            observation.normalize_config.method = normalize_method
            observation.normalize_config.lb = lb
            observation.normalize_config.ub = ub

    def _make_actions(
        self,
        variable_name: str,
        actuated_component_unique_name: str,
        actuated_component_type: int,
        actuated_component_control_type: int,
        control_type: int,
        method: int,
        lb: float,
        ub: float,
        masking_variable_name: str = "",
        default_unnormed_value: float = None
    ):
        if masking_variable_name != "":
            matches = [o for o in self.model.eplus_env_config.observations \
                    if o.variable_name == masking_variable_name]
            assert len(matches) > 0, f"Cannot find observation for {masking_variable_name}"
        action = self.model.eplus_env_config.actions.add()
        action.control_type = control_type
        if default_unnormed_value is not None:
            action.default_unnormed_value = default_unnormed_value
        action.variable_name = variable_name
        if masking_variable_name != "":
            action.masking_variable_name = masking_variable_name
        action.actuator_config.actuated_component_unique_name = actuated_component_unique_name
        action.actuator_config.actuated_component_type = actuated_component_type
        action.actuator_config.actuated_component_control_type = actuated_component_control_type
        if method != None:
            action.normalize_config.method = method
            action.normalize_config.lb = lb
            action.normalize_config.ub = ub

    """Public APIs"""

    """Simulation and logging config making functions start here"""
    def make_logging_config(
        self, log_dir: Path, level: int, verbose: bool
    ):
        self.model.logging_config.log_dir = str(log_dir.absolute())
        self.model.logging_config.level = level
        self.model.logging_config.verbose = verbose

    def make_eplus_env_config(
        self,
        idf_file: Path,
        weather_file: Path,
        begin_month: int = 9,
        begin_day_of_month: int = 1,
        end_month: int = 9,
        end_day_of_month: int = 1,
        number_of_timesteps_per_hour: int = 4,
        network: str = "host",
        host: str = "localhost",
    ):
        self.model.eplus_env_config.model_file = str(idf_file.absolute())
        self.model.eplus_env_config.weather_file = str(weather_file.absolute())
        self.model.eplus_env_config.network = network
        self.model.eplus_env_config.host = host
        self.model.eplus_env_config.simulation_time_config.begin_month = begin_month
        self.model.eplus_env_config.simulation_time_config.begin_day_of_month = begin_day_of_month
        self.model.eplus_env_config.simulation_time_config.end_month = end_month
        self.model.eplus_env_config.simulation_time_config.end_day_of_month = end_day_of_month
        self.model.eplus_env_config.simulation_time_config.number_of_timesteps_per_hour = number_of_timesteps_per_hour

    def make_env_params_config(
        self,
        task_id: str,
        num_constraints: int = 0,
        last_episode_idx: int = 0
    ):
        self.model.eplus_env_config.env_params.task_id = task_id
        self.model.eplus_env_config.env_params.num_constraints = num_constraints
        self.model.eplus_env_config.env_params.last_episode_idx = last_episode_idx

    """Observation config making functions start here"""
    def make_chilled_water_loop_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
    ):
        for chilled_water_loop_name, chilled_water_loop in self.device_key_map["chilled water loops"].items():
            # observe chilled water loop supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} supply temperature".lower(),
                key_value=chilled_water_loop["supply temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe chilled water loop return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} return temperature".lower(),
                key_value=chilled_water_loop["return temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe chilled water loop supply flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} supply flow rate".lower(),
                key_value=chilled_water_loop["supply flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe chilled water loop return flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} return flow rate".lower(),
                key_value=chilled_water_loop["return flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_condenser_water_loop_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
    ):
        for condenser_water_loop_name, condenser_water_loop in self.device_key_map["condenser water loops"].items():
            # observe condenser water loop supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} supply temperature".lower(),
                key_value=condenser_water_loop["supply temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe condenser water loop return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} return temperature".lower(),
                key_value=condenser_water_loop["return temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe condenser water loop supply flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} supply flow rate".lower(),
                key_value=condenser_water_loop["supply flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe condenser water loop return flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} return flow rate".lower(),
                key_value=condenser_water_loop["return flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_acu_fan_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        """
        Make observations for ACU fans
        :param exposed: whether the observation is exposed to the agent
        :param normalize_method: the normalization method
        :param lb: the lower bound of the normalization
        :param ub: the upper bound of the normalization
        :return:
        """
        for acu_name, acu in self.device_key_map["acus"].items():
            # observe ACU air mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan air mass flow rate".lower(),
                key_value=acu["fan"]["air mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe ACU fan power
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan power consumption".lower(),
                key_value=acu["fan"]["power"].split(":")[0],
                output_variable_name="Fan Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_cooling_coil_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for acu_name, acu in self.device_key_map["acus"].items():
            # observe inlet air temperautre
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil inlet air temperature".lower(),
                key_value=acu["cooling coil"]["inlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe inlet air mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil air mass flow rate".lower(),
                key_value=acu["cooling coil"]["air mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe outlet air temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil outlet air temperature".lower(),
                key_value=acu["cooling coil"]["outlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe inlet water temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil inlet water temperature".lower(),
                key_value=acu["cooling coil"]["inlet water temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe inlet water mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil water mass flow rate".lower(),
                key_value=acu["cooling coil"]["water mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_pump_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for chw_pump_name, chw_pump in self.device_key_map["chilled water pumps"].items():
            # observe chilled water pump mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chw_pump_name} mass flow rate".lower(),
                key_value=chw_pump["mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe chilled water pump power consumption
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chw_pump_name} power consumption".lower(),
                key_value=chw_pump["power"].split(":")[0],
                output_variable_name="Pump Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
        for cw_pump_name, cw_pump in self.device_key_map["condenser water pumps"].items():
            # observe condenser water pump mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cw_pump_name} mass flow rate".lower(),
                key_value=cw_pump["mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe condenser water pump power consumption
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cw_pump_name} power consumption".lower(),
                key_value=cw_pump["power"].split(":")[0],
                output_variable_name="Pump Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_chiller_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for chiller_name, chiller in self.device_key_map["chillers"].items():
            # observe chiller cooling load
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} cooling load".lower(),
                key_value=chiller["cooling load"].split(":")[0],
                output_variable_name="Chiller Evaporator Cooling Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # chilled water supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} chilled water supply temperature".lower(),
                key_value=chiller["chilled water supply temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # condenser water supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} condenser water supply temperature".lower(),
                key_value=chiller["condensing water supply temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # chilled water return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} chilled water return temperature".lower(),
                key_value=chiller["chilled water return temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # condenser water return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} condenser water return temperature".lower(),
                key_value=chiller["condensing water return temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe chiller power consumption
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} power consumption".lower(),
                key_value=chiller["power"].split(":")[0],
                output_variable_name="Chiller Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_cooling_tower_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for cooling_tower_name, cooling_tower in self.device_key_map["cooling towers"].items():
            # observe cooling tower return water temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} return water temperature".lower(),
                key_value=cooling_tower["return water temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe cooling tower water mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} water mass flow rate".lower(),
                key_value=cooling_tower["water mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe cooling tower supply water temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} supply water temperature".lower(),
                key_value=cooling_tower["supply water temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe cooling tower air flow rate ratio
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} air flow rate ratio".lower(),
                key_value=cooling_tower["air flow rate ratio"].split(":")[0],
                output_variable_name="Cooling Tower Air Flow Rate Ratio",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # # observe cooling tower outside air wetbulb temperature
            # self._make_observation(
            #     exposed=exposed,
            #     variable_name=f"{cooling_tower_name} outside air wetbulb temperature".lower(),
            #     key_value="Environment",
            #     output_variable_name="Site Outdoor Air Wetbulb Temperature",
            #     reporting_frequency="timestep",
            #     normalize_method=normalize_method,
            #     lb=lb,
            #     ub=ub
            # )
            # observe cooling tower fan power consumption
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} fan power consumption".lower(),
                key_value=cooling_tower["power"].split(":")[0],
                output_variable_name="Cooling Tower Fan Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_zone_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for zone_name, zone in self.device_key_map["zones"].items():
            # observe zone air temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{zone_name} air temperature".lower(),
                key_value=zone["air temperature"].split(":")[0],
                output_variable_name="Zone Air Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )
            # observe zone air relative humidity
            self._make_observation(
                exposed=exposed,
                variable_name=f"{zone_name} air relative humidity".lower(),
                key_value=zone["air relative humidity"].split(":")[0],
                output_variable_name="Zone Air Relative Humidity",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_ite_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for ite_name, ite in self.device_key_map["ites"].items():
            # observe ITE inlet dry-bulb temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{ite_name} inlet dry-bulb temperature".lower(),
                key_value=ite["inlet dry-bulb temperature"].split(":")[0],
                output_variable_name="ITE Air Inlet Dry-Bulb Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_electric_load_center_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for load_center_name, load_center in self.building.constructions.electrical_load_centers.items():
            self._make_observation(
                exposed=exposed,
                variable_name=f"{load_center.uid} produced electricity".lower(),
                key_value=load_center.uid,
                output_variable_name="Electric Load Center Produced Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    """Action config making functions start here"""
    def make_acu_supply_air_temperature_actions(
        self,
        control_type: int = 2,
        default_unnormed_value: float = None,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for acu_name, acu in self.device_key_map["acus"].items():
            variable_name = f"{acu_name} supply air temperature setpoint".lower()
            variable_name = variable_name.replace(" ", "_")
            self._make_actions(
                variable_name=variable_name,
                actuated_component_unique_name=f"{acu_name} air loop supply air temperature schedule",
                actuated_component_type=3,
                actuated_component_control_type=3,
                control_type=control_type,
                default_unnormed_value=default_unnormed_value,
                method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_acu_supply_air_flow_rate_actions(
        self,
        control_type: int = 2,
        default_unnormed_value: float = None,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for acu_name, acu in self.device_key_map["acus"].items():
            variable_name = f"{acu_name} supply air mass flow rate".lower()
            variable_name = variable_name.replace(" ", "_")
            self._make_actions(
                variable_name=variable_name,
                actuated_component_unique_name=f"{acu_name} fan",
                actuated_component_type=0,
                actuated_component_control_type=0,
                control_type=control_type,
                default_unnormed_value=default_unnormed_value,
                method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_chilled_water_loop_supply_temperature_actions(
        self,
        control_type: int = 2,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        default_unnormed_value: float = None
    ):
        for loop_name, loop in self.device_key_map["chilled water loops"].items():
            variable_name = f"{loop_name} supply temperature setpoint".lower()
            variable_name = variable_name.replace(" ", "_")
            self._make_actions(
                variable_name=variable_name,
                actuated_component_unique_name=f"{loop_name} supply outlet node",
                actuated_component_type=1,
                actuated_component_control_type=1,
                control_type=control_type,
                default_unnormed_value=default_unnormed_value,
                method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_condensed_water_loop_supply_temperature_actions(
        self,
        control_type: int = 2,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        default_unnormed_value: float = None
    ):
        for loop_name, loop in self.device_key_map["condenser water loops"].items():
            variable_name = f"{loop_name} supply temperature setpoint".lower()
            variable_name = variable_name.replace(" ", "_")
            self._make_actions(
                variable_name=variable_name,
                actuated_component_unique_name=f"{loop_name} supply outlet node",
                actuated_component_type=1,
                actuated_component_control_type=1,
                control_type=control_type,
                default_unnormed_value=default_unnormed_value,
                method=normalize_method,
                lb=lb,
                ub=ub
            )

    def make_cpu_loading_schedules(
        self,
        schedule_dir: Path,
        initial_value: float = 1.0,
        lb: float = 0.0,
        ub: float = 1.0
    ):
        for ite_name, ite in self.device_key_map["ites"].items():
            action = self.model.eplus_env_config.actions.add()
            action.control_type = 3
            action.variable_name = f"{ite_name} cpu loading schedule"
            action.input_source = str(schedule_dir.joinpath(f"{ite_name.lower()}.json").absolute())
            action.schedule_config.initial_value = initial_value
            action.schedule_config.lb = lb
            action.schedule_config.ub = ub
            action.schedule_config.schedule_type = 0
            action.schedule_config.scheduled_ite_equipment_name = f"{ite_name.lower()}"        

    def save(self, path: Path = Path('configs/eplus.prototxt')):
        with open(path, 'w') as f:
            f.write(text_format.MessageToString(self.model))
