import pickle
from typing import Tuple

import gpytorch
import torch
import numpy as np
from scipy import linalg
from pathlib import Path

from tqdm import tqdm

from loguru import logger

from dctwin.models import Room

from .utils import (
    read_temperature_fields,
    read_boundary_conditions,
)

from dctwin.backends.rom.pod.models import BatchIndependentMultiTaskGPModel


class PODBuilder:
    """
    A class method to build POD model from the CFD simulation data

    :param room: Room object model (see dctwin.models.room)
    :param num_modes: number of POD modes to be used to reconstruct the temperature field
    :param max_iter: maximum number of iterations for the training process of the GP model
    :param tol: tolerance for the training process of the GP model
    :param lr: learning rate for the training process of the GP model
    """

    def __init__(
        self,
        room: Room,
        num_modes: int = 0,
        max_iter: int = 1000,
        tol: float = 1e-9,
        lr: float = 0.001,
    ) -> None:
        self.num_modes = num_modes
        self.room = room
        self.max_iter = max_iter
        self.tol = tol
        self.lr = lr
        self.temperatures = None
        self.mesh_points = None
        self.mean_temperature = None
        self.correlation_matrix = None
        self.pod_modes, self.eigen_values = None, None

    def _calc_mean_temperature_field(self) -> np.ndarray:
        return np.mean(self.temperatures, axis=0)

    def _build_correlation_matrix(self) -> np.ndarray:
        num_observation = self.temperatures.shape[0]
        residual_temperature_fields = self.temperatures - self.mean_temperature
        correlation_matrix = np.dot(
            residual_temperature_fields, np.transpose(residual_temperature_fields)
        ) / (num_observation - 1)
        return correlation_matrix

    def _calc_pod_modes(self) -> Tuple[np.ndarray, np.ndarray]:
        # first_step: solve eigenvalue problem for the correlation matrix
        eigen_values, eigen_vectors = linalg.eig(self.correlation_matrix)
        # second step: calculate spatial mode (n_point, n_observation)
        phi = np.dot(
            np.transpose(self.temperatures - self.mean_temperature), eigen_vectors
        )
        sqrt_diagonals = np.sqrt(np.diag(np.dot(np.transpose(phi), phi)))
        # normalize so that the POD mode has unit length
        phi /= sqrt_diagonals
        return phi, np.real(eigen_values)

    def _compute_coef(self) -> np.ndarray:
        coefs = []
        available_modes = self.pod_modes.shape[1]
        for temperature in self.temperatures:
            coef = []
            temperature -= (
                self.mean_temperature
            )  # subtract reference temperature field is necessary
            for mode_idx in range(available_modes):
                coef.append(np.vdot(temperature, self.pod_modes[:, mode_idx]))
            coefs.append(coef)
        coefs = np.array(coefs)
        return coefs

    def _build_estimator(self) -> None:
        # prepare data
        self.train_bc = torch.FloatTensor(read_boundary_conditions(self.room))
        self.train_coef = torch.FloatTensor(self._compute_coef())
        self.likelihood = gpytorch.likelihoods.MultitaskGaussianLikelihood(
            num_tasks=self.num_modes
        )
        self.model = BatchIndependentMultiTaskGPModel(
            train_x=self.train_bc,
            train_y=self.train_coef,
            likelihood=self.likelihood,
            num_modes=self.num_modes,
        )
        # specify the GP model and the likelihood model in the training mode (require gradient)
        self.model.train()
        self.likelihood.train()
        # Use the adam optimizer
        optimizer = torch.optim.Adam(
            self.model.parameters(), lr=self.lr
        )  # Includes GaussianLikelihood parameters
        # "Loss" for GPs - the marginal log likelihood
        mll = gpytorch.mlls.ExactMarginalLogLikelihood(self.likelihood, self.model)
        # train the multi-output GP model with Adam Optimizer (Stochastic Gradient Descend)
        pbar = tqdm(range(self.max_iter))
        prev_loss = torch.inf
        _iter = 0
        normalized_targets = self.model.get_normalized_target()
        for _ in pbar:
            optimizer.zero_grad()
            dist = self.model(self.train_bc)
            loss = -mll(dist, normalized_targets)
            if torch.abs(loss - prev_loss) <= self.tol:
                break
            else:
                prev_loss = loss
            loss.backward()
            pbar.set_description(
                "Iter = {:d}, Loss = {:.3f}".format(_iter, loss.item())
            )
            _iter += 1
            optimizer.step()

        for param_name, param in self.model.named_parameters():
            logger.info(f"Parameter name: {param_name:42} value = {param}")

    def run(self, end_time: str = "500") -> None:
        logger.info("Reading temperature fields")
        self.temperatures = read_temperature_fields(end_time)
        logger.info(
            f"Read {self.temperatures.shape[0]} temperature fields with dim = {self.temperatures.shape[1]}"
        )
        logger.info("Calculating mean temperature field")
        self.mean_temperature = self._calc_mean_temperature_field()
        logger.info("Building correlation matrix and solve eigenvalue problem")
        self.correlation_matrix = self._build_correlation_matrix()
        logger.info("Calculating POD modes")
        self.pod_modes, self.eigen_values = self._calc_pod_modes()
        logger.info("Building GP predictors for POD coefficients")
        self._build_estimator()

    def save(self, save_path: Path) -> None:
        if not save_path.exists():
            save_path.mkdir(parents=True, exist_ok=True)
        data_dict = {
            "mean_obs": torch.from_numpy(self.mean_temperature),
            "modes": torch.from_numpy(self.pod_modes),
            "train_bc": self.train_bc,
            "train_coef": self.train_coef,
        }
        torch.save(self.model.state_dict(), save_path.joinpath("model.pth"))
        torch.save(self.likelihood.state_dict(), save_path.joinpath("likelihood.pth"))
        with open(save_path.joinpath("pod_data.pkl"), "wb") as f:
            pickle.dump(data_dict, f)
