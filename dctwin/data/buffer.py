from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from .batch import Batch, _create_value, _alloc_by_keys_diff


class Buffer:
    """:class:`~tianshou.data.ReplayBuffer` stores data generated from interaction \
    between the policy and environment.

    ReplayBuffer can be considered as a specialized form (or management) of Batch. It
    stores all the data in a batch with circular-queue style.

    For the example usage of ReplayBuffer, please check out Section Buffer in
    :doc:`/tutorials/concepts`.

    :param int size: the maximum size of replay buffer.
    :param int stack_num: the frame-stack sampling argument, should be greater than or
        equal to 1. Default to 1 (no stacking).
    :param bool sample_avail: the parameter indicating sampling only available index
        when using frame-stack sampling method. Default to False.
    """

    _reserved_keys = (
        "zone_air_temperature",
        "sensible_heat_load",
        "supply_air_temperature",
        "supply_air_mass_flow_rate",
        "fan_power",
        "cooling_coil_inlet_air_temperature",
        "cooling_coil_outlet_air_temperature",
        "cooling_coil_air_mass_flow_rate",
        "cooling_coil_inlet_water_temperature",
        "cooling_coil_water_mass_flow_rate",
        "pump_mass_flow_rate",
        "pump_power",
        "chiller_cooling_load",
        "chilled_water_supply_temperature",
        "condenser_water_supply_temperature",
        "chiller_power",
        "cooling_tower_return_water_temperature",
        "cooling_tower_supply_water_temperature",
        "cooling_tower_water_mass_flow_rate",
        "outside_air_wetbulb_temperature",
        "cooling_tower_air_flow_rate_ratio",
        "cooling_tower_fan_power",
        "times",
    )
    _input_keys = (
        "zone_air_temperature",
        "sensible_heat_load",
        "supply_air_temperature",
        "supply_air_mass_flow_rate",
        "fan_power",
        "cooling_coil_inlet_air_temperature",
        "cooling_coil_outlet_air_temperature",
        "cooling_coil_air_mass_flow_rate",
        "cooling_coil_inlet_water_temperature",
        "cooling_coil_water_mass_flow_rate",
        "pump_mass_flow_rate",
        "pump_power",
        "chiller_cooling_load",
        "chilled_water_supply_temperature",
        "condenser_water_supply_temperature",
        "chiller_power",
        "cooling_tower_return_water_temperature",
        "cooling_tower_supply_water_temperature",
        "cooling_tower_water_mass_flow_rate",
        "outside_air_wetbulb_temperature",
        "cooling_tower_air_flow_rate_ratio",
        "cooling_tower_fan_power",
        "times",
    )

    def __init__(
        self,
        size: int = 100,
        stack_num: int = 1,
        sample_avail: bool = False,
    ) -> None:
        self.options: Dict[str, Any] = {
            "stack_num": stack_num,
            "sample_avail": sample_avail,
        }
        super().__init__()
        self.maxsize = int(size)
        assert stack_num > 0, "stack_num should be greater than 0"
        self.stack_num = stack_num
        self._indices = np.arange(size)
        self._sample_avail = sample_avail
        self._meta: Batch = Batch()
        self._ep_rew: Union[float, np.ndarray]
        self.data = {}
        self.reset()

    def __len__(self) -> int:
        """Return len(self)."""
        return self._size

    def __repr__(self) -> str:
        """Return str(self)."""
        return self.__class__.__name__ + self._meta.__repr__()[5:]

    def __getattr__(self, key: str) -> Any:
        """Return self.key."""
        try:
            return self._meta[key]
        except KeyError as exception:
            raise AttributeError from exception

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """Unpickling interface.

        We need it because pickling buffer does not work out-of-the-box
        ("buffer.__getattr__" is customized).
        """
        self.__dict__.update(state)

    def __setattr__(self, key: str, value: Any) -> None:
        """Set self.key = value."""
        assert key not in self._reserved_keys, (
            "key '{}' is reserved and cannot be assigned".format(key)
        )
        super().__setattr__(key, value)

    def reset(
        self,
    ) -> None:
        """Clear all the data in replay buffer and episode statistics."""
        self.last_index = np.array([0])
        self._index = self._size = 0

    def set_batch(self, batch: Batch) -> None:
        """Manually choose the batch you want the ReplayBuffer to manage."""
        assert len(batch) == self.maxsize and set(batch.keys()).issubset(
            self._reserved_keys
        ), "Input batch doesn't meet ReplayBuffer's data form requirement."
        self._meta = batch

    def prev(self, index: Union[int, np.ndarray]) -> np.ndarray:
        """Return the index of previous transition.

        The index won't be modified if it is the beginning of an episode.
        """
        index = (index - 1) % self._size
        end_flag = self.done[index] | (index == self.last_index[0])
        return (index + end_flag) % self._size

    def next(self, index: Union[int, np.ndarray]) -> np.ndarray:
        """Return the index of next transition.

        The index won't be modified if it is the end of an episode.
        """
        end_flag = self.done[index] | (index == self.last_index[0])
        return (index + (1 - end_flag)) % self._size

    def update(self, buffer: "Buffer") -> np.ndarray:
        """Move the data from the given buffer to current buffer.

        Return the updated indices. If update fails, return an empty array.
        """
        if len(buffer) == 0 or self.maxsize == 0:
            return np.array([], int)
        stack_num, buffer.stack_num = buffer.stack_num, 1
        from_indices = buffer.sample_indices(0)  # get all available indices
        buffer.stack_num = stack_num
        if len(from_indices) == 0:
            return np.array([], int)
        to_indices = []
        for _ in range(len(from_indices)):
            to_indices.append(self._index)
            self.last_index[0] = self._index
            self._index = (self._index + 1) % self.maxsize
            self._size = min(self._size + 1, self.maxsize)
        to_indices = np.array(to_indices)
        if self._meta.is_empty():
            self._meta = _create_value(  # type: ignore
                buffer._meta, self.maxsize, stack=False
            )
        self._meta[to_indices] = buffer._meta[from_indices]
        return to_indices

    def _add_index(self) -> int:
        """Maintain the buffer's state after adding one data batch.

        Return (index_to_be_modified, episode_reward, episode_length,
        episode_start_index).
        """
        self.last_index[0] = ptr = self._index
        self._size = min(self._size + 1, self.maxsize)
        self._index = (self._index + 1) % self.maxsize
        return ptr

    def add(
        self,
        batch: Batch,
    ) -> np.ndarray:
        """Add a batch of data into replay buffer.
        :param Batch batch: the input data batch. Its keys must belong to the 4
            input keys
        Return (current_index, episode_reward, episode_length, episode_start_index). If
        the episode is not finished, the return value of episode_length and
        episode_reward is 0.
        """
        # preprocess batch
        new_batch = Batch()
        for key in set(self._input_keys).intersection(batch.keys()):
            new_batch.__dict__[key] = batch[key]
        batch = new_batch
        ptr = np.array([self._add_index()])
        try:
            self._meta[ptr] = batch
        except ValueError:
            if self._meta.is_empty():
                self._meta = _create_value(  # type: ignore
                    batch, self.maxsize, False
                )
            else:  # dynamic key pops up in batch
                _alloc_by_keys_diff(self._meta, batch, self.maxsize, False)
            self._meta[ptr] = batch
        return ptr

    def sample_indices(self, batch_size: int) -> np.ndarray:
        """Get a random sample of index with size = batch_size.

        Return all available indices in the buffer if batch_size is 0; return an empty
        numpy array if batch_size < 0 or no available index can be sampled.
        """
        if self.stack_num == 1 or not self._sample_avail:  # most often case
            if batch_size > 0:
                return np.random.choice(self._size, batch_size)
            elif batch_size == 0:  # construct current available indices
                return np.concatenate(
                    [np.arange(self._index, self._size), np.arange(self._index)]
                )
            else:
                return np.array([], int)
        else:
            if batch_size < 0:
                return np.array([], int)
            all_indices = prev_indices = np.concatenate(
                [np.arange(self._index, self._size), np.arange(self._index)]
            )
            for _ in range(self.stack_num - 2):
                prev_indices = self.prev(prev_indices)
            all_indices = all_indices[prev_indices != self.prev(prev_indices)]
            if batch_size > 0:
                return np.random.choice(all_indices, batch_size)
            else:
                return all_indices

    def sample(self, batch_size: int) -> Tuple[Batch, np.ndarray]:
        """Get a random sample from buffer with size = batch_size.

        Return all the data in the buffer if batch_size is 0.

        :return: Sample data and its corresponding index inside the buffer.
        """
        indices = self.sample_indices(batch_size)
        return self[indices], indices

    def get(
        self,
        index: Union[int, List[int], np.ndarray],
        key: str,
        default_value: Any = None,
        stack_num: Optional[int] = None,
    ) -> Union[Batch, np.ndarray]:
        """Return the stacked result.

        E.g., if you set ``key = "obs", stack_num = 4, index = t``, it returns the
        stacked result as ``[obs[t-3], obs[t-2], obs[t-1], obs[t]]``.

        :param index: the index for getting stacked data.
        :param str key: the key to get, should be one of the reserved_keys.
        :param default_value: if the given key's data is not found and default_value is
            set, return this default_value.
        :param int stack_num: Default to self.stack_num.
        """
        if key not in self._meta and default_value is not None:
            return default_value
        val = self._meta[key]
        if stack_num is None:
            stack_num = self.stack_num
        try:
            if stack_num == 1:  # the most often case
                return val[index]
            stack: List[Any] = []
            if isinstance(index, list):
                indices = np.array(index)
            else:
                indices = index  # type: ignore
            for _ in range(stack_num):
                stack = [val[indices]] + stack
                indices = self.prev(indices)
            if isinstance(val, Batch):
                return Batch.stack(stack, axis=indices.ndim)
            else:
                return np.stack(stack, axis=indices.ndim)
        except IndexError as exception:
            if not (isinstance(val, Batch) and val.is_empty()):
                raise exception  # val != Batch()
            return Batch()

    def __getitem__(self, index: Union[slice, int, List[int], np.ndarray]) -> Batch:
        """Return a data batch: self[index].

        If stack_num is larger than 1, return the stacked obs and obs_next with shape
        (batch, len, ...).
        """
        if isinstance(index, slice):  # change slice to np array
            # buffer[:] will get all available data
            indices = (
                self.sample_indices(0)
                if index == slice(None)
                else self._indices[: len(self)][index]
            )
        else:
            indices = index  # type: ignore
        return Batch(
            zone_air_temperature=self.get(
                indices, key="zone_air_temperature", default_value=Batch()
            ),
            sensible_heat_load=self.get(
                indices, key="sensible_heat_load", default_value=Batch()
            ),
            supply_air_temperature=self.get(
                indices, key="supply_air_temperature", default_value=Batch()
            ),
            supply_air_mass_flow_rate=self.get(
                indices, key="supply_air_mass_flow_rate", default_value=Batch()
            ),
            fan_power=self.get(indices, key="fan_power", default_value=Batch()),
            cooling_coil_inlet_air_temperature=self.get(
                indices, key="cooling_coil_inlet_air_temperature", default_value=Batch()
            ),
            cooling_coil_outlet_air_temperature=self.get(
                indices,
                key="cooling_coil_outlet_air_temperature",
                default_value=Batch(),
            ),
            cooling_coil_air_mass_flow_rate=self.get(
                indices, key="cooling_coil_air_mass_flow_rate", default_value=Batch()
            ),
            cooling_coil_inlet_water_temperature=self.get(
                indices,
                key="cooling_coil_inlet_water_temperature",
                default_value=Batch(),
            ),
            cooling_coil_water_mass_flow_rate=self.get(
                indices, key="cooling_coil_water_mass_flow_rate", default_value=Batch()
            ),
            chiller_cooling_load=self.get(
                indices, key="chiller_cooling_load", default_value=Batch()
            ),
            chilled_water_supply_temperature=self.get(
                indices, key="chilled_water_supply_temperature", default_value=Batch()
            ),
            condenser_water_supply_temperature=self.get(
                indices, key="condenser_water_supply_temperature", default_value=Batch()
            ),
            chiller_power=self.get(indices, key="chiller_power", default_value=Batch()),
            pump_mass_flow_rate=self.get(
                indices, key="pump_mass_flow_rate", default_value=Batch()
            ),
            pump_power=self.get(indices, key="pump_power", default_value=Batch()),
            cooling_tower_return_water_temperature=self.get(
                indices,
                key="cooling_tower_return_water_temperature",
                default_value=Batch(),
            ),
            cooling_tower_water_mass_flow_rate=self.get(
                indices, key="cooling_tower_water_mass_flow_rate", default_value=Batch()
            ),
            cooling_tower_supply_water_temperature=self.get(
                indices,
                key="cooling_tower_supply_water_temperature",
                default_value=Batch(),
            ),
            outside_air_wetbulb_temperature=self.get(
                indices, key="outside_air_wetbulb_temperature", default_value=Batch()
            ),
            cooling_tower_air_flow_rate_ratio=self.get(
                indices, key="cooling_tower_air_flow_rate_ratio", default_value=Batch()
            ),
            cooling_tower_fan_power=self.get(
                indices, key="cooling_tower_fan_power", default_value=Batch()
            ),
            times=self.get(indices, key="times", default_value=Batch()),
        )
