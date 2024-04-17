"""
Implementation of various performance curves for facilities
"""
import abc

import torch.nn as nn
import torch
from scipy.optimize import curve_fit


class Curve(nn.Module, abc.ABC):
    """
    Base class for performance curves. It takes two parameters:
    :param init_params: torch.Tensor, initial parameters (a, b, c)
    :param requires_grad: bool, whether the parameters are learnable
    """

    def __init__(
        self,
        init_params: torch.Tensor,
        requires_grad: bool = False,
    ) -> None:
        super().__init__()
        self.params = nn.Parameter(init_params, requires_grad=requires_grad)
        self.learnable = requires_grad

    @abc.abstractmethod
    def forward(
        self,
        **kwargs,
    ) -> torch.Tensor:
        """
        Forward pass of the curve.
        It takes a tensor of inputs and returns a tensor of outputs.
        :param kwargs: torch.Tensor of a single input or a batch of inputs
        :return: torch.Tensor of a single output or a batch of outputs
        """
        pass

    @abc.abstractmethod
    def learn(
        self,
        **kwargs,
    ) -> None:
        """
        Learn the parameters of the curve.
        :param kwargs: torch.Tensor of inputs and outputs
        :return: None
        """
        pass


class QuadraticCurve(Curve):
    """
    Quadratic curve in the form of
    y = a + bx + cx^2
    :param init_params: torch.Tensor, initial parameters (a, b, c)
    :param requires_grad: bool, whether the parameters are learnable
    """

    def __init__(
        self,
        init_params: torch.Tensor,
        requires_grad: bool = False,
    ) -> None:

        assert len(init_params) == 3, "QuadraticCurve should take 3 parameters."
        super().__init__(init_params=init_params, requires_grad=requires_grad)

    def forward(
        self,
        x: torch.Tensor,
    ) -> torch.Tensor:
        return self.params[0] + self.params[1] * x + self.params[2] * x**2

    def learn(
        self,
        x: torch.Tensor,
        y: torch.Tensor,
    ) -> None:
        coefs = curve_fit(
            lambda x, a, b, c: a + b * x + c * x**2,
            x.view(-1).detach().numpy(), y.view(-1).detach().numpy()
        )[0]
        self.params.data = torch.tensor(coefs, dtype=torch.float32, requires_grad=self.learnable)


class BiQuadraticCurve(Curve):
    """
    BiQuadratic curve in the form of:
    y = a + bx + cx^2 + dy + ey^2 + fxy
    """
    def __init__(
        self,
        init_params: torch.Tensor,
        requires_grad: bool = True,
    ) -> None:
        assert len(init_params) == 6, "BiQuadraticCurve should take 6 parameters."
        super().__init__(init_params=init_params, requires_grad=requires_grad)

    def forward(
        self,
        x: torch.Tensor,
        y: torch.Tensor,
    ) -> torch.Tensor:
        return self.params[0] + \
               self.params[1] * x + self.params[2] * x**2 + \
               self.params[3] * y + self.params[4] * y**2 + \
               self.params[5] * x * y

    def learn(
        self,
        x: torch.Tensor,
        y: torch.Tensor,
    ) -> None:
        assert self.learnable, "The parameters are not learnable."
        coefs = curve_fit(
            lambda x, a, b, c, d, e, f: a * x ** 2 + b * y ** 2 + c * x * y + d * x + e * y + f,
            x.view(-1).detach().numpy(), y.view(-1).detach().numpy()
        )[0]
        self.params.data = torch.tensor(coefs, dtype=torch.float32)


class CubicCurve(Curve):

    """
    Cubic curve in the form of:
    y = a + bx + cx^2 + dx^3
    :param init_params: torch.Tensor, initial parameters (a, b, c, d)
    :param requires_grad: bool, whether the parameters are learnable
    """

    def __init__(
        self,
        init_params: torch.Tensor,
        requires_grad: bool = True,
    ) -> None:

        assert len(init_params) == 4, "CubicCurve should take 4 parameters."
        super(CubicCurve, self).__init__(init_params=init_params, requires_grad=requires_grad)

    def forward(
        self,
        x: torch.Tensor,
    ) -> torch.Tensor:
        return self.params[0] + self.params[1] * x + self.params[2] * x**2 + self.params[3] * x**3

    def learn(
        self,
        x: torch.Tensor,
        y: torch.Tensor,
    ) -> None:
        coefs = curve_fit(
            lambda x, a, b, c, d: a * (x**3) + b * (x**2) + c * x + d,
            x.view(-1).detach().numpy(), y.view(-1).detach().numpy()
        )[0]
        self.params.data = torch.tensor(coefs, dtype=torch.float32)
