import os
import json

from loguru import logger
from typing import Union

from dctwin.utils import (
    NormalizeConfig,
    ScalarDataItemConfig,
    DCTwinActionConfig,
    DCTwinObservationConfig,
    DCTwinConfig,
)
from .resizers import LinearResizer


class ScalarDataItem:
    def __init__(self, config: ScalarDataItemConfig) -> None:
        self.variable_name = config.variable_name
        if config.HasField("normalize_config"):
            norm_config = config.normalize_config
            assert (
                norm_config.method == NormalizeConfig.Method.LINEAR
            ), "Only linear resizer is implemented at this moment"
            self.resizer = LinearResizer(
                norm_config.lb,
                norm_config.ub,
                norm_config.resized_lb,
                norm_config.resized_ub,
            )
        else:
            self.resizer = None

        self.normed_value = None
        default_value_type = config.WhichOneof("value")
        if default_value_type == "default_normed_value":
            self.set_normed_value(config.default_normed_value)
        elif default_value_type == "default_unnormed_value":
            if config.control_type == DCTwinActionConfig.FIXED:
                logger.info(
                    f"Fixed value {config.default_unnormed_value} is set for {self.variable_name}"
                )
            elif self.resizer is None:
                logger.warning(
                    f"Default unnormed value set for "
                    f"{self.variable_name} but resizer is not specified!"
                )
            self.set_normed_value(config.default_unnormed_value)
        self.default_value = self.normed_value if self.normed_value is not None else 0.0

    def set_unnormed_value(self, unnormed_value) -> None:
        if self.resizer is not None:
            self.normed_value = self.resizer.norm(unnormed_value)
        else:
            self.normed_value = unnormed_value

    def set_normed_value(self, normed_value) -> None:
        self.normed_value = normed_value

    def get_normed_value(self) -> float:
        return self.normed_value

    def get_unnormed_value(self) -> float:
        if hasattr(self, "mask") and self.mask:
            return 0
        elif self.resizer is not None:
            return self.resizer.denorm(self.normed_value)
        else:
            return self.normed_value

    def reset_to_default_value(self) -> None:
        self.normed_value = self.default_value


class Observation(ScalarDataItem):
    def __init__(
        self, config: Union[DCTwinObservationConfig]
    ) -> None:
        super().__init__(config)
        if type(config) == DCTwinObservationConfig:
            self.type = config.DESCRIPTOR.EnumValueName(
                "ObservationType", config.observation_type
            )
        else:
            self.type = None


ActionControlVariable = DCTwinActionConfig.ControlVariable


class Action(ScalarDataItem):
    # noinspection PyBroadException
    def __init__(self, config: DCTwinActionConfig) -> None:
        super().__init__(config)
        self.requires_grad: bool = config.requires_grad
        self.control_variable = config.control_variable
        self.device_unique_key = config.device_unique_key
        # self.debug_name = f"Action {self.variable_name}"
        if not self.requires_grad and self.normed_value is None:
            logger.warning(
                f"{self.device_unique_key} {self.control_variable} set to be fixed but no default value was specified! "
                # f"Using {self.default_value} instead..."
            )
