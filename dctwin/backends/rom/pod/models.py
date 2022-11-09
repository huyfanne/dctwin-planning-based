import gpytorch
import torch


class BatchIndependentMultiTaskGPModel(gpytorch.models.ExactGP):
    """
    Define the vector output GP model according to the tutorial:
    https://docs.gpytorch.ai/en/stable/examples/03_Multitask_Exact_GPs/Multitask_GP_Regression.html
    """
    def __init__(
        self,
        train_x: torch.Tensor,
        train_y: torch.Tensor,
        likelihood: gpytorch.likelihoods.Likelihood,
        num_modes: int
    ) -> None:
        self.num_samples, self.num_features = train_x.size()
        self.num_modes = num_modes
        train_target = (train_y[:, :num_modes] - train_y[:, :num_modes].mean(dim=0)) / train_y[:, :num_modes].std(dim=0)
        train_input = (train_x[:, :num_modes] - train_x[:, :num_modes].mean(dim=0)) / train_x[:, :num_modes].std(dim=0)
        super().__init__(train_input, train_target, likelihood)
        self.train_x_mean = torch.nn.Parameter(train_x[:, :num_modes].mean(dim=0), requires_grad=False)
        self.train_x_std = torch.nn.Parameter(train_x[:, :num_modes].std(dim=0), requires_grad=False)
        self.train_y_mean = torch.nn.Parameter(train_y[:, :num_modes].mean(dim=0), requires_grad=False)
        self.train_y_std = torch.nn.Parameter(train_y[:, :num_modes].std(dim=0), requires_grad=False)
        self.mean_module = gpytorch.means.ConstantMean(batch_shape=torch.Size([num_modes]))
        self.covar_module = gpytorch.kernels.ScaleKernel(
            gpytorch.kernels.RBFKernel(batch_shape=torch.Size([num_modes])),
            batch_shape=torch.Size([num_modes])
        )

    def get_normalized_input(self):
        return self.train_inputs[0]

    def get_normalized_target(self):
        return self.train_targets

    def forward(self, x: torch.Tensor):
        """
        Forward pass of the multi-output GP model.
        Note: the input x is not normalized and it should be normalized
        to make the prediction result stable.
        """
        # x = (x - self.train_x_mean) / self.train_x_std
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        dist = gpytorch.distributions.MultitaskMultivariateNormal.from_batch_mvn(
            gpytorch.distributions.MultivariateNormal(mean_x, covar_x)
        )
        return dist
