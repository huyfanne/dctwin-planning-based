import torch.nn as nn
import torch
from scipy.optimize import curve_fit


class BiQuadraticCurve(nn.Module):

    def __init__(self, init_params: torch.Tensor, requires_grad: bool = True):

        assert len(init_params) == 6, "BiQuadraticCurve takes 6 parameters."

        super(BiQuadraticCurve, self).__init__()
        self.learnable = requires_grad
        self.params = nn.Parameter(init_params, requires_grad=requires_grad)
        if requires_grad is True:
            self.opt = torch.optim.Adam(self.parameters(), lr=0.01)

    def forward(self, x: torch.Tensor, y: torch.Tensor):
        return self.params[0] + self.params[1] * x + self.params[2] * x**2 + self.params[3] * y+ \
               self.params[4] * y**2 + self.params[5] * x * y

    def learn(self, x: torch.Tensor, y: torch.Tensor, z: torch.Tensor):
        assert self.learnable, "The parameters are not learnable."
        coef = curve_fit(
            lambda x, a, b, c, d, e, f: a * x ** 2 + b * y ** 2 + c * x * y + d * x + e * y + f,
            x.view(-1).detach().numpy(), y.view(-1).detach().numpy()
        )[0]
        self.params.data = torch.tensor(coef, dtype=torch.float32)