import torch.nn as nn
import torch

from scipy.optimize import curve_fit


class CubicCurve(nn.Module):

    def __init__(self, init_params: torch.Tensor, requires_grad: bool = True):

        assert len(init_params) == 4, "CubicCurve takes 4 parameters."

        super(CubicCurve, self).__init__()
        self.learnable = requires_grad
        self.params = nn.Parameter(init_params, requires_grad=requires_grad)
        if requires_grad is True:
            self.opt = torch.optim.Adam(self.parameters(), lr=0.01)

    def forward(self, x: torch.Tensor):
        return self.params[0] * x ** 3 + self.params[1] * x ** 2 + self.params[2] * x + self.params[3]

    def learn(self, x: torch.Tensor, y: torch.Tensor):
        assert self.learnable, "The parameters are not learnable."
        coef = curve_fit(
            lambda x, a, b, c, d: a * (x**3) + b * (x**2) + c * x + d,
            x.view(-1).detach().numpy(), y.view(-1).detach().numpy()
        )[0]
        self.params.data = torch.tensor(coef, dtype=torch.float32)
