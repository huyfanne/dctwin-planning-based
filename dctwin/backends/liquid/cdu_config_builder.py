from typing import Union, OrderedDict, List
from google.protobuf import text_format
from dctwin.utils.dt_engine_pb2 import DTEngineConfig
from loguru import logger

from dclib import Building
from pathlib import Path


class CDUConfigBuilder:
    def __init__(
        self,
        building: Building
    ):
        self.building = building
        self.model = DTEngineConfig()

    """Private utility functions"""

    def _make_observation(
        self,
        exposed: bool,
        variable_name: str,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        observation_type: int = None,
    ):
        observation = self.model.cdu_env_config.observations.add()
        observation.exposed = exposed
        observation.variable_name = variable_name
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
        control_type: int,
        method: int,
        lb: float,
        ub: float,
        default_unnormed_value: float = None,
    ):
        action = self.model.cdu_env_config.actions.add()
        action.control_type = control_type
        if default_unnormed_value is not None:
            action.default_unnormed_value = default_unnormed_value
        action.variable_name = variable_name.replace("-", "_").replace(
            " ", "_"
        )  # variable name cannot contain dash and space
        if method != None:
            action.normalize_config.method = method
            action.normalize_config.lb = lb
            action.normalize_config.ub = ub

    """Public APIs"""

    """Simulation and logging config making functions start here"""

    def make_logging_config(self, log_dir: Path, level: int, verbose: bool):
        self.model.logging_config.log_dir = str(log_dir)
        self.model.logging_config.level = level
        self.model.logging_config.verbose = verbose


    """Observation config making functions start here"""

    def make_cdu_observations(
        self,
        exposed: bool = True,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
    ):
        for zone_name, zone in self.building.constructions.zones.items():
            if zone.constructions.cdus is not None:
                for cdu_name, cdu in zone.constructions.cdus.items():
                    self._make_observation(
                        exposed=exposed,
                        variable_name=f"{cdu.uid} cooling water supply temperature".lower(),
                        normalize_method=normalize_method,
                        lb=lb,
                        ub=ub,
                    )
                    self._make_observation(
                        exposed=exposed,
                        variable_name=f"{cdu.uid} cooling water return temperature".lower(),
                        normalize_method=normalize_method,
                        lb=lb,
                        ub=ub,
                    )
                    self._make_observation(
                        exposed=exposed,
                        variable_name=f"{cdu.uid} chilled water supply temperature".lower(),
                        normalize_method=normalize_method,
                        lb=lb,
                        ub=ub,
                    )
                    self._make_observation(
                        exposed=exposed,
                        variable_name=f"{cdu.uid} chilled water return temperature".lower(),
                        normalize_method=normalize_method,
                        lb=lb,
                        ub=ub,
                    )
                    self._make_observation(
                        exposed=exposed,
                        variable_name=f"{cdu.uid} chilled water mass flow rate".lower(),
                        normalize_method=normalize_method,
                        lb=lb,
                        ub=ub,
                    )
                    self._make_observation(
                        exposed=exposed,
                        variable_name=f"{cdu.uid} electrical power".lower(),
                        normalize_method=normalize_method,
                        lb=lb,
                        ub=ub,
                    )
        # aggregated
        self._make_observation(
            exposed=exposed,
            variable_name="Total CDU Power".lower(),
            normalize_method=normalize_method,
            lb=lb,
            ub=ub,
        )
        self._make_observation(
            exposed=exposed,
            variable_name="Total CDU Cooling Water Flow Rate".lower(),
            normalize_method=normalize_method,
            lb=lb,
            ub=ub,
        )
        self._make_observation(
            exposed=exposed,
            variable_name="Total CDU Chilled Water Flow Rate".lower(),
            normalize_method=normalize_method,
            lb=lb,
            ub=ub,
        )

    """Action config making functions start here"""

    def make_cdu_cooling_water_supply_temperature_actions(
        self,
        control_type: int = 2,
        default_unnormed_value: float = None,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        device_values: dict = {},
        disable: bool = False,
    ):
        for zone_name, zone in self.building.constructions.zones.items():
            if zone.constructions.cdus is not None:
                for cdu_name, cdu in zone.constructions.cdus.items():
                    self._make_actions(
                        variable_name=f"{cdu.uid} cooling water supply temperature".lower(),
                        control_type=device_values.get(f"{cdu.uid}", {}).get("control_type", control_type),
                        method=device_values.get(f"{cdu.uid}", {}).get("normalize_method", normalize_method),
                        lb=device_values.get(f"{cdu.uid}", {}).get("lb", lb),
                        ub=device_values.get(f"{cdu.uid}", {}).get("ub", ub),
                        default_unnormed_value=device_values.get(f"{cdu.uid}", {}).get("default_unnormed_value", default_unnormed_value),
                    )  if device_values.get(f"{cdu.uid}", {}).get("disable", disable) == False else None

    def make_cdu_cooling_water_supply_flow_rate_actions(
        self,
        control_type: int = 2,
        default_unnormed_value: float = None,
        normalize_method: int = None,
        lb: float = None,
        ub: float = None,
        device_values: dict = {},
        disable: bool = False,
    ):
        for zone_name, zone in self.building.constructions.zones.items():
            if zone.constructions.cdus is not None:
                for cdu_name, cdu in zone.constructions.cdus.items():
                    self._make_actions(
                        variable_name=f"{cdu.uid} cooling water supply flow rate".lower(),
                        control_type=device_values.get(f"{cdu.uid}", {}).get("control_type", control_type),
                        method=device_values.get(f"{cdu.uid}", {}).get("normalize_method", normalize_method),
                        lb=device_values.get(f"{cdu.uid}", {}).get("lb", lb),
                        ub=device_values.get(f"{cdu.uid}", {}).get("ub", ub),
                        default_unnormed_value=device_values.get(f"{cdu.uid}", {}).get("default_unnormed_value", default_unnormed_value),
                    ) if device_values.get(f"{cdu.uid}", {}).get("disable", disable) == False else None

    def save(self, path: Path = Path("configs/cdu.prototxt")):
        with open(path, "w") as f:
            f.write(text_format.MessageToString(self.model))

    def get_model(self):
        return self.model