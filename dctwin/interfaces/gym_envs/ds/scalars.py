import os
import json

from loguru import logger
from typing import Union

from dctwin.utils import (
    NormalizeConfig,
    ScalarDataItemConfig,
    EPlusObservationConfig,
    EPlusActionConfig,
    CFDObservationConfig,
)
from .resizers import LinearResizer


def validator(method) -> callable:
    def validated_call(self):
        if (
            self.control_type != ActionControlType.PRE_SCHEDULED
            and self.control_type != ActionControlType.ACTUATOR_PRE_SCHEDULED
        ):
            logger.error(
                f"{self.debug_name} is not pre_scheduled but schedule related call "
                f"is made to it! Ignoring..."
            )
        else:
            return method(self)

    return validated_call


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
            if config.control_type == ActionControlType.FIXED:
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
        if self.resizer is not None:
            return self.resizer.denorm(self.normed_value)
        else:
            return self.normed_value

    def reset_to_default_value(self) -> None:
        self.normed_value = self.default_value


class Observation(ScalarDataItem):
    def __init__(
        self, config: Union[EPlusObservationConfig, CFDObservationConfig]
    ) -> None:
        super().__init__(config)
        self.exposed = config.exposed
        if type(config) == EPlusObservationConfig:
            self.type = config.DESCRIPTOR.EnumValueName(
                "ObservationType", config.observation_type
            )
        else:
            self.type = None


ActionControlType = EPlusActionConfig.ControlType


class Action(ScalarDataItem):
    # noinspection PyBroadException
    def __init__(self, config: EPlusActionConfig) -> None:
        super().__init__(config)
        self.control_type = config.control_type

        self.debug_name = f"Action {self.variable_name}"
        if self.control_type == ActionControlType.FIXED and self.normed_value is None:
            logger.warning(
                f"{self.debug_name} set to be fixed but no default value was specified! "
                f"Using {self.default_value} instead..."
            )
        elif (
            self.control_type == ActionControlType.PRE_SCHEDULED
            or self.control_type == ActionControlType.ACTUATOR_PRE_SCHEDULED
        ):
            try:
                self.input_source = config.input_source
                assert (
                    len(self.input_source) > 0
                ), f"{self.debug_name} is pre_scheduled but input source was not specified!"
                if not os.path.isabs(self.input_source):
                    self.input_source = os.path.abspath(self.input_source)
                with open(self.input_source, "r") as f:
                    self.schedule = json.load(f)
                    assert isinstance(self.schedule, list), (
                        f"{self.debug_name}: " f"input source has to be a json list!"
                    )
                    assert (
                        len(self.schedule) != 0
                    ), f"{self.debug_name} has an input source of length 0!"
                    self.schedule_idx = 0
            except Exception:
                logger.exception("Failed to load input source!")
        elif config.HasField("input_source"):
            logger.warning(
                f"{self.debug_name} is not pre_scheduled but input source was specified. "
                f"The source will be ignored."
            )

    @validator
    def __iter__(self):
        return self

    @validator
    def __next__(self) -> float:
        """
        get the next pre-scheduled value

        Q: Why it's not set directly?
        A: Because you don't know if the input source is normed or unnormed;
        if force it to be normed, what if the user wants to use unnormed interface?
        """
        v = self.schedule[self.schedule_idx]
        self.schedule_idx = (self.schedule_idx + 1) % len(self.schedule)
        return v

    @validator
    def peek(self) -> float:
        """
        peek the next scheduled value
        """
        return self.schedule[self.schedule_idx]

    def reset(self) -> None:
        """reset value using default value, and reset input source idx (if any)"""
        self.reset_to_default_value()
        if hasattr(self, "schedule_idx"):
            self.schedule_idx = 0


Reward = ScalarDataItem
