import torch.nn as nn
import torch
from scipy.optimize import curve_fit


class QuadraticCurve(nn.Module):
    """
    Implement the learnable Quadratic Curve model.
    """

    def __init__(self, init_params: torch.Tensor, requires_grad: bool = False):

        assert len(init_params) == 3, "QuadraticCurve takes 3 parameters."

        super(QuadraticCurve, self).__init__()
        self.learnable = requires_grad
        self.params = nn.Parameter(init_params, requires_grad=requires_grad)

    def forward(self, x: torch.Tensor):
        return self.params[0] + self.params[1] * x + self.params[2] * x**2

    def learn(self, x: torch.Tensor, y: torch.Tensor):
        assert self.learnable, "The parameters are not learnable."
        coef = curve_fit(
            lambda x, a, b, c: a + b * x + c * x**2,
            x.view(-1).detach().numpy(), y.view(-1).detach().numpy()
        )[0]
        self.params.data = torch.tensor(coef, dtype=torch.float32, requires_grad=self.learnable)
