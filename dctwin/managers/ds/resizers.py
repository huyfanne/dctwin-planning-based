from typing import Union
import numpy as np


class Resizer:
    def norm(self, value: Union[int, float]):
        raise NotImplementedError

    def denorm(self, value: Union[int, float]):
        raise NotImplementedError


class LinearResizer(Resizer):
    def __init__(
        self,
        lb: Union[str, int, float],
        ub: Union[str, int, float],
        resized_lb: Union[str, int, float],
        resized_ub: Union[str, int, float],
    ) -> None:
        super().__init__()
        self.lb = float(lb)
        self.ub = float(ub)
        self.resized_lb = float(resized_lb)
        self.resized_ub = float(resized_ub)

    def norm(self, value: Union[int, float]) -> float:
        return self._map(value, self.lb, self.ub, self.resized_lb, self.resized_ub)

    def denorm(self, value: Union[int, float]) -> float:
        return self._map(value, self.resized_lb, self.resized_ub, self.lb, self.ub)

    @staticmethod
    def _map(value, original_lb, original_ub, new_lb, new_ub):
        if np.max(value) > original_ub or np.min(value) < original_lb:
            value = np.clip(value, original_lb, original_ub)
        return new_lb + (value - original_lb) / (original_ub - original_lb) * (
            new_ub - new_lb
        )
