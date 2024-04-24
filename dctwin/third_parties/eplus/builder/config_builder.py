from typing import Union, OrderedDict, List
from google.protobuf import text_format
from dctwin.utils.dt_engine_pb2 import DTEngineConfig
from loguru import logger

from dclib import Building
from pathlib import Path


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
        key_value: str = None,
        output_variable_name: str = None,
        reporting_frequency: str = None,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        observation_type: int = None,
    ):
        observation = self.model.eplus_env_config.observations.add()
        observation.exposed = exposed
        observation.variable_name = variable_name
        if key_value is not None:
            observation.output_variable_config.key_value = key_value
            observation.output_variable_config.variable_name = output_variable_name
            observation.output_variable_config.reporting_frequency = reporting_frequency
        if normalize_method:
            assert lb is not None and ub is not None, (
                logger.critical(
                    "For normalized observations, the lower bound and upper bound must be provided."
                ),
                exit(1),
            )
            observation.normalize_config.method = normalize_method
            observation.normalize_config.lb = lb
            observation.normalize_config.ub = ub
        if observation_type is not None:
            observation.observation_type = observation_type

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
        masking_variable_name: str = None,
        default_unnormed_value: float = None,
        input_source: Path = None,
    ):
        action = self.model.eplus_env_config.actions.add()
        action.control_type = control_type
        if default_unnormed_value is not None:
            action.default_unnormed_value = default_unnormed_value
        if input_source is not None:
            action.input_source = str(input_source).replace(
                "\\", "/"
            )  # convert to unix style path
        action.variable_name = variable_name.replace("-", "_").replace(
            " ", "_"
        )  # variable name cannot contain dash and space
        action.actuator_config.actuated_component_unique_name = (
            actuated_component_unique_name
        )
        action.actuator_config.actuated_component_type = actuated_component_type
        action.actuator_config.actuated_component_control_type = (
            actuated_component_control_type
        )
        if method != None:
            action.normalize_config.method = method
            action.normalize_config.lb = lb
            action.normalize_config.ub = ub
        if masking_variable_name is not None:
            matches = [
                o
                for o in self.model.eplus_env_config.observations
                if o.variable_name == masking_variable_name
            ]
            assert (
                len(matches) > 0
            ), f"Cannot find observation for {masking_variable_name}"
            action.masking_variable_name = masking_variable_name

    """Public APIs"""

    """Simulation and logging config making functions start here"""

    def make_logging_config(self, log_dir: Path, level: int, verbose: bool):
        self.model.logging_config.log_dir = str(log_dir)
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
        self.model.eplus_env_config.model_file = str(idf_file)
        self.model.eplus_env_config.weather_file = str(weather_file)
        self.model.eplus_env_config.network = network
        self.model.eplus_env_config.host = host
        self.model.eplus_env_config.simulation_time_config.begin_month = begin_month
        self.model.eplus_env_config.simulation_time_config.begin_day_of_month = (
            begin_day_of_month
        )
        self.model.eplus_env_config.simulation_time_config.end_month = end_month
        self.model.eplus_env_config.simulation_time_config.end_day_of_month = (
            end_day_of_month
        )
        self.model.eplus_env_config.simulation_time_config.number_of_timesteps_per_hour = (
            number_of_timesteps_per_hour
        )

    def make_env_params_config(
        self, task_id: str, num_constraints: int = 0, last_episode_idx: int = 0
    ):
        self.model.eplus_env_config.env_params.task_id = task_id
        self.model.eplus_env_config.env_params.num_constraints = num_constraints
        self.model.eplus_env_config.env_params.last_episode_idx = last_episode_idx

    """Observation config making functions start here"""
    def make_weather_observations(
        self,
        variable_names: Union[str, List[str]],
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None
    ):
        for variable_name in variable_names:
            self._make_observation(
                exposed=exposed,
                variable_name=variable_name.lower(),
                key_value="Environment",
                output_variable_name=variable_name,
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            )

    # make plant loop overall observations
    def make_plant_loop_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for chilled_water_loop_name, chilled_water_loop in self.building.constructions.plant.chilled_water_loops.items():
            # observe chilled water loop supply side outlet temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} supply side outlet temperature".lower(),
                key_value=chilled_water_loop_name,
                output_variable_name="Plant Supply Side Outlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "supply side outlet temperature" in variable_names else None
            # observe chilled water loop supply side inlet temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} supply side inlet temperature".lower(),
                key_value=chilled_water_loop_name,
                output_variable_name="Plant Supply Side Inlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "supply side inlet temperature" in variable_names else None
            # observe chilled water loop supply side mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} supply side mass flow rate".lower(),
                key_value=chilled_water_loop_name,
                output_variable_name="Plant Supply Side Inlet Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "supply side mass flow rate" in variable_names else None

    def make_pue_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        self._make_observation(
            exposed=exposed,
            variable_name="hvac power",
            key_value="Whole Building",
            output_variable_name="Facility Total HVAC Electricity Demand Rate",
            reporting_frequency="timestep",
            normalize_method=normalize_method,
            lb=lb,
            ub=ub,
        ) if variable_names is None or "hvac power" in variable_names else None
        self._make_observation(
            exposed=exposed,
            variable_name="total power",
            key_value="Whole Building",
            output_variable_name="Facility Total Electricity Demand Rate",
            reporting_frequency="timestep",
            normalize_method=normalize_method,
            lb=lb,
            ub=ub,
        ) if variable_names is None or "total power" in variable_names else None
        self._make_observation(
            exposed=exposed,
            variable_name="building power",
            key_value="Whole Building",
            output_variable_name="Facility Total Building Electricity Demand Rate",
            reporting_frequency="timestep",
            normalize_method=normalize_method,
            lb=lb,
            ub=ub,
        ) if variable_names is None or "building power" in variable_names else None

    def make_chilled_water_loop_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for chilled_water_loop_name, chilled_water_loop in self.device_key_map[
            "chilled water loops"
        ].items():
            # observe chilled water loop supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} supply temperature".lower(),
                key_value=chilled_water_loop["supply temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "supply temperature" in variable_names else None
            # observe chilled water loop return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} return temperature".lower(),
                key_value=chilled_water_loop["return temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "return temperature" in variable_names else None
            # observe chilled water loop supply flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} supply flow rate".lower(),
                key_value=chilled_water_loop["supply flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "supply flow rate" in variable_names else None
            # observe chilled water loop return flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chilled_water_loop_name} return flow rate".lower(),
                key_value=chilled_water_loop["return flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "return flow rate" in variable_names else None

    def make_condenser_water_loop_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for condenser_water_loop_name, condenser_water_loop in self.device_key_map[
            "condenser water loops"
        ].items():
            # observe condenser water loop supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} supply temperature".lower(),
                key_value=condenser_water_loop["supply temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "supply temperature" in variable_names else None
            # observe condenser water loop return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} return temperature".lower(),
                key_value=condenser_water_loop["return temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "return temperature" in variable_names else None
            # observe condenser water loop supply flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} supply flow rate".lower(),
                key_value=condenser_water_loop["supply flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "supply flow rate" in variable_names else None
            # observe condenser water loop return flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{condenser_water_loop_name} return flow rate".lower(),
                key_value=condenser_water_loop["return flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "return flow rate" in variable_names else None

    def make_acu_fan_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
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
            # observe ACU fan power
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan power consumption".lower(),
                key_value=acu["fan"]["power"].split(":")[0],
                output_variable_name="Fan Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "power" in variable_names else None
            # observe ACU air mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan air mass flow rate".lower(),
                key_value=acu["fan"]["air mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "air mass flow rate" in variable_names else None
            # observe ACU air outlet temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan outlet air temperature".lower(),
                key_value=acu["fan"]["outlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "outlet air temperature" in variable_names else None
            # observe ACU air inlet temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan inlet air temperature".lower(),
                key_value=acu["fan"]["inlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "inlet air temperature" in variable_names else None

    def make_acu_fan_hum_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
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
            # observe ACU air outlet relative humidity
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan outlet air relative humidity".lower(),
                key_value=acu["fan"]["outlet air relative humidity"].split(":")[0],
                output_variable_name="System Node Relative Humidity",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "outlet air relative humidity" in variable_names else None
            # observe ACU air inlet relative humidity
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} fan inlet air relative humidity".lower(),
                key_value=acu["fan"]["inlet air relative humidity"].split(":")[0],
                output_variable_name="System Node Relative Humidity",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "inlet air relative humidity" in variable_names else None

    def make_cooling_coil_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for acu_name, acu in self.device_key_map["acus"].items():
            # observe inlet air temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil inlet air temperature".lower(),
                key_value=acu["cooling coil"]["inlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "inlet air temperature" in variable_names else None
            # observe inlet air mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil air mass flow rate".lower(),
                key_value=acu["cooling coil"]["air mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "air mass flow rate" in variable_names else None
            # observe outlet air temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil outlet air temperature".lower(),
                key_value=acu["cooling coil"]["outlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "outlet air temperature" in variable_names else None
            # observe inlet water temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil inlet water temperature".lower(),
                key_value=acu["cooling coil"]["inlet water temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "inlet water temperature" in variable_names else None
            # observe outlet water temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil outlet water temperature".lower(),
                key_value=acu["cooling coil"]["outlet water temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "outlet water temperature" in variable_names else None
            # observe inlet water mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil water mass flow rate".lower(),
                key_value=acu["cooling coil"]["water mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "water mass flow rate" in variable_names else None
            # observe cooling load
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} cooling coil cooling load".lower(),
                key_value=acu["cooling coil"]["cooling load"].split(":")[0],
                output_variable_name="Cooling Coil Sensible Cooling Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "cooling load" in variable_names else None

    def make_dehumidifier_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for dehumidifier_name, dehumidifier in self.device_key_map["dehumidifiers"].items():
            # observe inlet air temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{dehumidifier_name} inlet air temperature".lower(),
                key_value=dehumidifier["inlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "inlet air temperature" in variable_names else None
            # observe outlet air temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{dehumidifier_name} outlet air temperature".lower(),
                key_value=dehumidifier["outlet air temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "outlet air temperature" in variable_names else None
            # observe air mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{dehumidifier_name} air mass flow rate".lower(),
                key_value=dehumidifier["air mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "air mass flow rate" in variable_names else None
            # observe removed water mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{dehumidifier_name} removed water mass flow rate".lower(),
                key_value=dehumidifier["removed water mass flow rate"].split(":")[0],
                output_variable_name="Zone Dehumidifier Removed Water Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "removed water mass flow rate" in variable_names else None
            # observe dehumidifier power consumption
            self._make_observation(
                exposed=exposed,
                variable_name=f"{dehumidifier_name} power consumption".lower(),
                key_value=dehumidifier["power"].split(":")[0],
                output_variable_name="Zone Dehumidifier Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "power" in variable_names else None

    def make_pump_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for chw_pump_name, chw_pump in self.device_key_map[
            "chilled water pumps"
        ].items():
            # observe chilled water pump mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chw_pump_name} mass flow rate".lower(),
                key_value=chw_pump["mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "mass flow rate" in variable_names else None
            # observe chilled water pump power consumption
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chw_pump_name} power consumption".lower(),
                key_value=chw_pump["power"].split(":")[0],
                output_variable_name="Pump Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "power" in variable_names else None
        for cw_pump_name, cw_pump in self.device_key_map[
            "condenser water pumps"
        ].items():
            # observe condenser water pump mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cw_pump_name} mass flow rate".lower(),
                key_value=cw_pump["mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "mass flow rate" in variable_names else None
            # observe condenser water pump power consumption
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cw_pump_name} power consumption".lower(),
                key_value=cw_pump["power"].split(":")[0],
                output_variable_name="Pump Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "power" in variable_names else None
        if "secondary chilled water pumps" in self.device_key_map:
            for schw_pump_name, schw_pump in self.device_key_map[
                "secondary chilled water pumps"
            ].items():
                # observe secondary chilled water pump mass flow rate
                self._make_observation(
                    exposed=exposed,
                    variable_name=f"{schw_pump_name} mass flow rate".lower(),
                    key_value=schw_pump["mass flow rate"].split(":")[0],
                    output_variable_name="System Node Mass Flow Rate",
                    reporting_frequency="timestep",
                    normalize_method=normalize_method,
                    lb=lb,
                    ub=ub,
                ) if variable_names is None or "mass flow rate" in variable_names else None
                # observe secondary chilled water pump power consumption
                self._make_observation(
                    exposed=exposed,
                    variable_name=f"{schw_pump_name} power consumption".lower(),
                    key_value=schw_pump["power"].split(":")[0],
                    output_variable_name="Pump Electricity Rate",
                    reporting_frequency="timestep",
                    normalize_method=normalize_method,
                    lb=lb,
                    ub=ub,
                ) if variable_names is None or "power" in variable_names else None

    def make_chiller_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
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
            ) if variable_names is None or "cooling load" in variable_names else None
            # observe chiller evaporator mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} evaporator mass flow rate".lower(),
                key_value=chiller["chilled water mass flow rate"].split(":")[0],
                output_variable_name="Chiller Evaporator Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "chilled water mass flow rate" in variable_names else None
            # chilled water supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} chilled water supply temperature".lower(),
                key_value=chiller["chilled water supply temperature"].split(":")[0],
                output_variable_name="Chiller Evaporator Outlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "chilled water supply temperature" in variable_names else None
            # chilled water return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} chilled water return temperature".lower(),
                key_value=chiller["chilled water return temperature"].split(":")[0],
                output_variable_name="Chiller Evaporator Inlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "chilled water return temperature" in variable_names else None
            # chilled water mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} chilled water mass flow rate".lower(),
                key_value=chiller["chilled water mass flow rate"].split(":")[0],
                output_variable_name="Chiller Condenser Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "chilled water mass flow rate" in variable_names else None
            # condenser water supply temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} condenser water supply temperature".lower(),
                key_value=chiller["condenser water supply temperature"].split(":")[0],
                output_variable_name="Chiller Condenser Inlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "condenser water supply temperature" in variable_names else None
            # condenser water return temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} condenser water return temperature".lower(),
                key_value=chiller["condenser water return temperature"].split(":")[0],
                output_variable_name="Chiller Condenser Outlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "condenser water return temperature" in variable_names else None
            self._make_observation(
                exposed=exposed,
                variable_name=f"{chiller_name} condenser water mass flow rate".lower(),
                key_value=chiller["condenser water mass flow rate"].split(":")[0],
                output_variable_name="Chiller Condenser Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "condenser water mass flow rate" in variable_names else None
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
            ) if variable_names is None or "power" in variable_names else None

    def make_hx_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for hx_name, hx in self.device_key_map["heat_exchangers"].items():
            # observe heat exchanger cooling load
            self._make_observation(
                exposed=exposed,
                variable_name=f"{hx_name} cooling load".lower(),
                key_value=hx["cooling load"].split(":")[0],
                output_variable_name="Fluid Heat Exchanger Heat Transfer Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub
            ) if variable_names is None or "cooling load" in variable_names else None
            # observe heat exchanger supply side inlet/outlet temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{hx_name} chilled water supply temperature".lower(),
                key_value=hx["chilled water supply temperature"].split(":")[0],
                output_variable_name="Fluid Heat Exchanger Loop Supply Side Outlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
            ) if variable_names is None or "chilled water supply temperature" in variable_names else None
            self._make_observation(
                exposed=exposed,
                variable_name=f"{hx_name} chilled water return temperature".lower(),
                key_value=hx["chilled water return temperature"].split(":")[0],
                output_variable_name="Fluid Heat Exchanger Loop Supply Side Inlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
            ) if variable_names is None or "chilled water return temperature" in variable_names else None
            self._make_observation(
                exposed=exposed,
                variable_name=f"{hx_name} chilled water mass flow rate".lower(),
                key_value=hx["chilled water mass flow rate"].split(":")[0],
                output_variable_name="Fluid Heat Exchanger Loop Supply Side Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method
            ) if variable_names is None or "chilled water mass flow rate" in variable_names else None
            # observe heat exchanger demand side inlet/outlet temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{hx_name} condenser water supply temperature".lower(),
                key_value=hx["condenser water supply temperature"].split(":")[0],
                output_variable_name="Fluid Heat Exchanger Loop Demand Side Inlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
            ) if variable_names is None or "condenser water supply temperature" in variable_names else None
            self._make_observation(
                exposed=exposed,
                variable_name=f"{hx_name} condenser water return temperature".lower(),
                key_value=hx["condenser water return temperature"].split(":")[0],
                output_variable_name="Fluid Heat Exchanger Loop Demand Side Outlet Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
            ) if variable_names is None or "condenser water return temperature" in variable_names else None
            self._make_observation(
                exposed=exposed,
                variable_name=f"{hx_name} condenser water mass flow rate".lower(),
                key_value=hx["condenser water mass flow rate"].split(":")[0],
                output_variable_name="Fluid Heat Exchanger Loop Demand Side Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method
            ) if variable_names is None or "condenser water mass flow rate" in variable_names else None

    def make_cooling_tower_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for cooling_tower_name, cooling_tower in self.device_key_map[
            "cooling towers"
        ].items():
            # observe cooling tower return water temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} return water temperature".lower(),
                key_value=cooling_tower["return water temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "return water temperature" in variable_names else None
            # observe cooling tower water mass flow rate
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} water mass flow rate".lower(),
                key_value=cooling_tower["water mass flow rate"].split(":")[0],
                output_variable_name="System Node Mass Flow Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "water mass flow rate" in variable_names else None
            # observe cooling tower supply water temperature
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} supply water temperature".lower(),
                key_value=cooling_tower["supply water temperature"].split(":")[0],
                output_variable_name="System Node Temperature",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "supply water temperature" in variable_names else None
            # observe cooling tower air flow rate ratio
            self._make_observation(
                exposed=exposed,
                variable_name=f"{cooling_tower_name} air flow rate ratio".lower(),
                key_value=cooling_tower["air flow rate ratio"].split(":")[0],
                output_variable_name="Cooling Tower Air Flow Rate Ratio",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "air flow rate ratio" in variable_names else None
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
                ub=ub,
            ) if variable_names is None or "power" in variable_names else None

    def make_zone_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
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
                ub=ub,
            ) if variable_names is None or "air temperature" in variable_names else None
            # observe zone air relative humidity
            self._make_observation(
                exposed=exposed,
                variable_name=f"{zone_name} air relative humidity".lower(),
                key_value=zone["air relative humidity"].split(":")[0],
                output_variable_name="Zone Air Relative Humidity",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "air relative humidity" in variable_names else None

    def make_ite_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
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
                ub=ub,
            ) if variable_names is None or "inlet dry-bulb temperature" in variable_names else None
            # observe ITE inlet relative humidity
            self._make_observation(
                exposed=exposed,
                variable_name=f"{ite_name} inlet relative humidity".lower(),
                key_value=ite["inlet relative humidity"].split(":")[0],
                output_variable_name="ITE Air Inlet Relative Humidity",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "inlet relative humidity" in variable_names else None

    def make_electric_load_center_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        variable_names: Union[str, List[str]] = None
    ):
        for (
            load_center_name,
            load_center,
        ) in self.building.constructions.electrical_load_centers.items():
            self._make_observation(
                exposed=exposed,
                variable_name=f"{load_center.uid} produced electricity".lower(),
                key_value=load_center.uid,
                output_variable_name="Electric Load Center Produced Electricity Rate",
                reporting_frequency="timestep",
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
            ) if variable_names is None or "produced electricity" in variable_names else None

    """Action config making functions start here"""

    def make_acu_supply_air_temperature_actions(
        self,
        control_type: int = 2,
        default_unnormed_value: float = None,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        masking: bool = False,
        device_values: dict = {},
        disable: bool = False,
    ):
        for acu_name, acu in self.device_key_map["acus"].items():
            masking_variable_name = (
                f"{acu_name} on off schedule".lower() if masking else None
            )
            variable_name = f"{acu_name} supply air temperature setpoint".lower()
            self._make_actions(
                variable_name=variable_name,
                actuated_component_unique_name=f"{acu_name} air loop supply air temperature schedule".lower(),
                actuated_component_type=3,
                actuated_component_control_type=3,
                control_type=device_values.get(acu_name, {}).get("control_type", control_type),
                default_unnormed_value=device_values.get(acu_name, {}).get("default_unnormed_value", default_unnormed_value),
                method=device_values.get(acu_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(acu_name, {}).get("lb", lb),
                ub=device_values.get(acu_name, {}).get("ub", ub),
                masking_variable_name=device_values.get(acu_name, {}).get("masking_variable_name", masking_variable_name),
            ) if device_values.get(acu_name, {}).get("disable", disable) is False else None

    def make_acu_supply_air_flow_rate_actions(
        self,
        control_type: int = 2,
        default_unnormed_value: float = None,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        masking: bool = False,
        device_values: dict = {},
        disable: bool = False,
    ):
        for acu_name, acu in self.device_key_map["acus"].items():
            masking_variable_name = (
                f"{acu_name} on off schedule".lower() if masking else None
            )
            variable_name = f"{acu_name} supply air mass flow rate".lower()
            self._make_actions(
                variable_name=variable_name,
                actuated_component_unique_name=f"{acu_name} fan".lower(),
                actuated_component_type=0,
                actuated_component_control_type=0,
                control_type=device_values.get(acu_name, {}).get("control_type", control_type),
                default_unnormed_value=device_values.get(acu_name, {}).get("default_unnormed_value", default_unnormed_value),
                method=device_values.get(acu_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(acu_name, {}).get("lb", lb),
                ub=device_values.get(acu_name, {}).get("ub", ub),
                masking_variable_name=device_values.get(acu_name, {}).get("masking_variable_name", masking_variable_name),
            ) if device_values.get(acu_name, {}).get("disable", disable) is False else None

    def make_chilled_water_loop_supply_temperature_actions(
        self,
        control_type: int = 2,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        default_unnormed_value: float = None,
        device_values: dict = {},
        disable: bool = False,
    ):
        for loop_name, loop in self.device_key_map["chilled water loops"].items():
            self._make_actions(
                variable_name=f"{loop_name} supply temperature setpoint".lower(),
                actuated_component_unique_name=f"{loop_name} exit temperature setpoint schedule",
                actuated_component_type=3,
                actuated_component_control_type=3,
                control_type=device_values.get(loop_name, {}).get("control_type", control_type),
                default_unnormed_value=device_values.get(loop_name, {}).get("default_unnormed_value", default_unnormed_value),
                method=device_values.get(loop_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(loop_name, {}).get("lb", lb),
                ub=device_values.get(loop_name, {}).get("ub", ub),
            ) if device_values.get(loop_name, {}).get("disable", disable) is False else None

    def make_condensed_water_loop_supply_temperature_actions(
        self,
        control_type: int = 2,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        default_unnormed_value: float = None,
        device_values: dict = {},
        disable: bool = False,
    ):
        for loop_name, loop in self.device_key_map["condenser water loops"].items():
            self._make_actions(
                variable_name=f"{loop_name} supply temperature setpoint".lower(),
                actuated_component_unique_name=f"{loop_name} exit temperature setpoint schedule",
                actuated_component_type=3,
                actuated_component_control_type=3,
                control_type=device_values.get(loop_name, {}).get("control_type", control_type),
                default_unnormed_value=device_values.get(loop_name, {}).get("default_unnormed_value", default_unnormed_value),
                method=device_values.get(loop_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(loop_name, {}).get("lb", lb),
                ub=device_values.get(loop_name, {}).get("ub", ub),
            ) if device_values.get(loop_name, {}).get("disable", disable) is False else None

    def make_chilled_water_pump_flow_rates_actions(
        self,
        control_type: int = 2,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        default_unnormed_value: float = None,
        device_values: dict = {},
        disable: bool = False,
    ):
        for pump_name, pump in self.device_key_map["chilled water pumps"].items():
            self._make_actions(
                variable_name=f"{pump_name} mass flow rate".lower(),
                actuated_component_unique_name=f"{pump_name}",
                actuated_component_type=2,
                actuated_component_control_type=2,
                control_type=device_values.get(pump_name, {}).get("control_type", control_type),
                default_unnormed_value=device_values.get(pump_name, {}).get("default_unnormed_value", default_unnormed_value),
                method=device_values.get(pump_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(pump_name, {}).get("lb", lb),
                ub=device_values.get(pump_name, {}).get("ub", ub),
            ) if device_values.get(pump_name, {}).get("disable", disable) is False else None

    def make_secondary_chilled_water_pump_flow_rates_actions(
        self,
        control_type: int = 2,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        default_unnormed_value: float = None,
        device_values: dict = {},
        disable: bool = False,
    ):
        for pump_name, pump in self.device_key_map["secondary chilled water pumps"].items():
            self._make_actions(
                variable_name=f"{pump_name} mass flow rate".lower(),
                actuated_component_unique_name=f"{pump_name}",
                actuated_component_type=2,
                actuated_component_control_type=2,
                control_type=device_values.get(pump_name, {}).get("control_type", control_type),
                default_unnormed_value=device_values.get(pump_name, {}).get("default_unnormed_value", default_unnormed_value),
                method=device_values.get(pump_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(pump_name, {}).get("lb", lb),
                ub=device_values.get(pump_name, {}).get("ub", ub),
            ) if device_values.get(pump_name, {}).get("disable", disable) is False else None

    def make_condenser_water_pump_flow_rates_actions(
        self,
        control_type: int = 2,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        default_unnormed_value: float = None,
        device_values: dict = {},
        disable: bool = False,
    ):
        for pump_name, pump in self.device_key_map["condenser water pumps"].items():
            self._make_actions(
                variable_name=f"{pump_name} mass flow rate".lower(),
                actuated_component_unique_name=f"{pump_name}",
                actuated_component_type=2,
                actuated_component_control_type=2,
                control_type=device_values.get(pump_name, {}).get("control_type", control_type),
                default_unnormed_value=device_values.get(pump_name, {}).get("default_unnormed_value", default_unnormed_value),
                method=device_values.get(pump_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(pump_name, {}).get("lb", lb),
                ub=device_values.get(pump_name, {}).get("ub", ub),
            ) if device_values.get(pump_name, {}).get("disable", disable) is False else None

    def make_chilled_water_supply_branch_on_off_actions_prescheduled(
        self,
        schedule_dir: Path = Path("data/schedule/branches"),
        normalize_method: int = 1,
        lb: float = 0.0,
        ub: float = 1.0,
    ):
        chilled_water_loops = self.building["constructions"]["plant"]["chilledWaterLoops"]
        for chilled_water_loop_name, chilled_water_loop in chilled_water_loops.items():
            for branch_name, branch in chilled_water_loop["supplyBranches"].items():
                self._make_actions(
                    variable_name=f"{branch_name} on off".lower(),
                    actuated_component_unique_name=f"{branch_name}",
                    actuated_component_type=4,
                    actuated_component_control_type=4,
                    control_type=5,
                    method=normalize_method,
                    lb=lb,
                    ub=ub,
                    input_source=schedule_dir.joinpath(
                        f"{branch_name}.json"
                    ),
                ) if branch["side"] == "middle" else None

    def make_chilled_water_pump_flow_rates_actions_prescheduled(
        self,
        schedule_dir: Path = Path("data/schedule/pumps"),
        normalize_method: int = 1,
        lb: float = 0.0,
        ub: float = 100.0,
        device_values: dict = {},
        disable: bool = False,
    ):
        for pump_name, pump in self.device_key_map["chilled water pumps"].items():
            self._make_actions(
                variable_name=f"{pump_name} mass flow rate".lower(),
                actuated_component_unique_name=f"{pump_name}",
                actuated_component_type=2,
                actuated_component_control_type=2,
                control_type=5,
                method=device_values.get(pump_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(pump_name, {}).get("lb", lb),
                ub=device_values.get(pump_name, {}).get("ub", ub),
                input_source=schedule_dir.joinpath(f"{pump_name.lower()}.json"),
            ) if device_values.get(pump_name, {}).get("disable", disable) is False else None

    def make_secondary_chilled_water_pump_flow_rates_actions_prescheduled(
        self,
        schedule_dir: Path = Path("data/schedule/pumps"),
        normalize_method: int = 1,
        lb: float = 0.0,
        ub: float = 100.0,
        device_values: dict = {},
        disable: bool = False,
    ):
        for pump_name, pump in self.device_key_map[
            "secondary chilled water pumps"
        ].items():
            self._make_actions(
                variable_name=f"{pump_name} mass flow rate".lower(),
                actuated_component_unique_name=f"{pump_name}",
                actuated_component_type=2,
                actuated_component_control_type=2,
                control_type=5,
                method=device_values.get(pump_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(pump_name, {}).get("lb", lb),
                ub=device_values.get(pump_name, {}).get("ub", ub),
                input_source=schedule_dir.joinpath(f"{pump_name.lower()}.json"),
            ) if device_values.get(pump_name, {}).get("disable", disable) is False else None

    def make_condenser_water_pump_flow_rates_actions_prescheduled(
        self,
        schedule_dir: Path = Path("data/schedule/pumps"),
        normalize_method: int = 1,
        lb: float = 0.0,
        ub: float = 100.0,
        device_values: dict = {},
        disable: bool = False,
    ):
        for pump_name, pump in self.device_key_map["condenser water pumps"].items():
            self._make_actions(
                variable_name=f"{pump_name} mass flow rate".lower(),
                actuated_component_unique_name=f"{pump_name}",
                actuated_component_type=2,
                actuated_component_control_type=2,
                control_type=5,
                method=device_values.get(pump_name, {}).get("normalize_method", normalize_method),
                lb=device_values.get(pump_name, {}).get("lb", lb),
                ub=device_values.get(pump_name, {}).get("ub", ub),
                input_source=schedule_dir.joinpath(f"{pump_name.lower()}.json"),
            ) if device_values.get(pump_name, {}).get("disable", disable) is False else None

    def make_acu_on_off_schedules(
        self,
        schedule_dir: Path = Path("data/schedule/acus/fan_on_off"),
        initial_value: float = 1.0,
        lb: float = 0.0,
        ub: float = 1.0,
    ):
        for acu_name, acu in self.device_key_map["acus"].items():
            fan_name = f"{acu_name} fan"
            action = self.model.eplus_env_config.actions.add()
            action.control_type = 3
            action.variable_name = f"{acu_name} on off schedule".lower()
            action.input_source = str(
                schedule_dir.joinpath(f"{acu_name.lower()}.json")
            ).replace(
                "\\", "/"
            )  # convert to unix style path
            action.schedule_config.initial_value = initial_value
            action.schedule_config.lb = lb
            action.schedule_config.ub = ub
            action.schedule_config.schedule_type = 5
            action.schedule_config.scheduled_fan_name = f"{fan_name.lower()}"

    def make_cpu_loading_schedules(
        self,
        schedule_dir: Path = Path("data/schedule/workloads"),
        initial_value: float = 1.0,
        lb: float = 0.0,
        ub: float = 1.0,
        device_values: dict = {},
    ):
        for ite_name, ite in self.device_key_map["ites"].items():
            action = self.model.eplus_env_config.actions.add()
            action.control_type = 3
            action.variable_name = f"{ite_name} cpu loading schedule".lower()
            action.input_source = str(
                schedule_dir.joinpath(f"{ite_name.lower()}.json")
            ).replace(
                "\\", "/"
            )  # convert to unix style path
            action.schedule_config.initial_value = device_values.get(ite_name, {})\
                .get("initial_value", initial_value)
            action.schedule_config.lb = device_values.get(ite_name, {}).get("lb", lb)
            action.schedule_config.ub = device_values.get(ite_name, {}).get("ub", ub)
            action.schedule_config.schedule_type = 0
            action.schedule_config.scheduled_ite_equipment_name = f"{ite_name.lower()}"

    def make_hx_schedules(
        self,
        schedule_dir: Path = Path("data/schedule/hx"),
        initial_value: float = 1.0,
        lb: float = 0.0,
        ub: float = 1.0,
        device_values: dict = {},
    ):
        for hx_name, hx in self.device_key_map["heat_exchangers"].items():
            action = self.model.eplus_env_config.actions.add()
            action.control_type = 3
            action.variable_name = f"{hx_name} availability schedule".lower()
            action.input_source = str(
                schedule_dir.joinpath(f"{hx_name.lower()}.json")
            ).replace(
                "\\", "/"
            ) # convert to unix style path
            action.schedule_config.initial_value = device_values.get(hx_name, {}).get("initial_value", initial_value)
            action.schedule_config.lb = device_values.get(hx_name, {}).get("lb", lb)
            action.schedule_config.ub = device_values.get(hx_name, {}).get("ub", ub)
            action.schedule_config.schedule_type = 7
            action.schedule_config.scheduled_hx_name = f"{hx_name.lower()}"

    def make_acu_on_off_observations(
        self,
        exposed: bool = True,
        normalize_method: int = 1,
        lb: float = 0.0,
        ub: float = 1.0,
    ):
        """
        Make observations for ACU on/off status
        :param exposed: whether the observation is exposed to the agent
        :param normalize_method: the normalization method
        :param lb: the lower bound of the normalization
        :param ub: the upper bound of the normalization
        :return:
        """
        for acu_name, acu in self.device_key_map["acus"].items():
            # observe ACU on/off status
            self._make_observation(
                exposed=exposed,
                variable_name=f"{acu_name} on off schedule".lower(),
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
                observation_type=2,
            )

    def make_cpu_loading_observations(
        self,
        exposed: bool = True,
        normalize_method: int = 1,
        lb: float = 0.0,
        ub: float = 1.0,
    ):
        """
        Make observations for CPU loading
        :param exposed: whether the observation is exposed to the agent
        :param normalize_method: the normalization method
        :param lb: the lower bound of the normalization
        :param ub: the upper bound of the normalization
        :return:
        """
        for ite_name, ite in self.device_key_map["ites"].items():
            # observe CPU loading
            self._make_observation(
                exposed=exposed,
                variable_name=f"{ite_name} cpu loading schedule".lower(),
                normalize_method=normalize_method,
                lb=lb,
                ub=ub,
                observation_type=2,
            )

    def save(self, path: Path = Path("configs/eplus.prototxt")):
        with open(path, "w") as f:
            f.write(text_format.MessageToString(self.model))

    def get_model(self):
        return self.model