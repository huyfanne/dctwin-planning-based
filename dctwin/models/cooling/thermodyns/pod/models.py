import torch
import gpytorch


class BatchIndependentMultiTaskGPModel(gpytorch.models.ExactGP):
    """
    Define the Batch Independent Multi Task GP model according to the following tutorials:
    https://docs.gpytorch.ai/en/stable/examples/03_Multitask_Exact_GPs/Batch_Independent_Multioutput_GP.html
    """

    def __init__(
        self,
        train_x: torch.Tensor,
        train_y: torch.Tensor,
        likelihood: gpytorch.likelihoods.Likelihood,
        num_modes: int,
    ):
        super().__init__(train_x, train_y[:, :num_modes], likelihood)
        self.num_samples, self.num_features = train_x.size()
        self.num_modes = num_modes
        self.train_x_mean = torch.nn.Parameter(train_x.mean(dim=0), requires_grad=False)
        self.train_x_std = torch.nn.Parameter(train_x.std(dim=0), requires_grad=False)
        self.train_y_mean = torch.nn.Parameter(
            train_y[:, :num_modes].mean(dim=0), requires_grad=False
        )
        self.train_y_std = torch.nn.Parameter(
            train_y[:, :num_modes].std(dim=0), requires_grad=False
        )
        self.mean_module = gpytorch.means.ConstantMean(
            batch_shape=torch.Size([num_modes])
        )
        self.covar_module = gpytorch.kernels.ScaleKernel(
            gpytorch.kernels.RBFKernel(batch_shape=torch.Size([num_modes])),
            batch_shape=torch.Size([num_modes]),
        )

    def get_normalized_target(self):
        return (self.train_targets - self.train_y_mean) / (self.train_y_std + 1e-6)

    def forward(
        self, x: torch.Tensor
    ) -> gpytorch.distributions.MultitaskMultivariateNormal:
        x = (x - self.train_x_mean) / (
            self.train_x_std + 1e-6
        )  # here the input is normalized
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        dist = gpytorch.distributions.MultitaskMultivariateNormal.from_batch_mvn(
            gpytorch.distributions.MultivariateNormal(mean_x, covar_x)
        )
        return dist
