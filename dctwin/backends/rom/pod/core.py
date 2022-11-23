import pickle
from typing import Dict, Union

import loguru
import numpy as np
import cvxpy as cp
from pathlib import Path
import gpytorch
import torch
from cvxpylayers.torch import CvxpyLayer


from dctwin.backends.core import Backend
from dctwin.utils import config

from .models import BatchIndependentMultiTaskGPModel


class PODBackend(Backend):
    """
    Backend for the POD model. It is a wrapper of the POD model.
    It accepts the boundary conditions and predict the
    temperature field with the POD modes and the GP models.
    """
    rho_air = 1.19  # air density kg/m^3
    c_p = 1006  # air heat capacity J/(kg*C)

    def __init__(self) -> None:
        super().__init__()
        self.train_bc = None
        self.train_coef = None
        self.likelihood = None
        self.model = None
        self.mean_obs = None
        self.modes = None
        self.num_modes = config.cfd.num_modes

    def _prepare_mode_data(self, object_mesh_index: Dict):
        used_modes = self.modes[:, :self.num_modes]
        phi_return = []
        phi_inlet = []
        phi_outlet = []
        mean_temp_inlet = []
        mean_temp_outlet = []
        mean_temp_return = []
        for server_name, server_mesh_indices in object_mesh_index["servers"].items():
            mean_temp_inlet.append(self.mean_obs[server_mesh_indices["inlet"]])
            mean_temp_outlet.append(self.mean_obs[server_mesh_indices["outlet"]])
            phi_inlet.append(used_modes[server_mesh_indices["inlet"], :])
            phi_outlet.append(used_modes[server_mesh_indices["outlet"], :])

        for crac_name, crac_mesh_indices in object_mesh_index["cracs"].items():
            mean_temp_return.append(self.mean_obs[crac_mesh_indices["return"]])
            phi_return.append(used_modes[crac_mesh_indices["return"], :])

        mean_temp_inlet = torch.tensor(mean_temp_inlet, dtype=torch.float32, requires_grad=False)
        mean_temp_outlet = torch.tensor(mean_temp_outlet, dtype=torch.float32, requires_grad=False)
        mean_temp_return = torch.tensor(mean_temp_return, dtype=torch.float32, requires_grad=False)
        phi_inlet = torch.vstack(phi_inlet)
        phi_outlet = torch.vstack(phi_outlet)
        phi_return = torch.vstack(phi_return)
        return {
            "mean_temp_inlet": mean_temp_inlet,
            "mean_temp_outlet": mean_temp_outlet,
            "mean_temp_return": mean_temp_return,
            "phi_inlet": phi_inlet,
            "phi_outlet": phi_outlet,
            "phi_return": phi_return,
        }
    def _local_search(
        self,
        crac_volume_flow_rate: torch.Tensor,
        crac_setpoints: torch.Tensor,
        server_powers: torch.Tensor,
        server_volume_flow_rates: torch.Tensor,
        coef_hat: torch.Tensor,
        coef_std: Union[torch.Tensor, None],
        mean_temp_inlet: torch.Tensor,
        mean_temp_outlet: torch.Tensor,
        mean_temp_return: torch.Tensor,
        phi_inlet: torch.Tensor,
        phi_outlet: torch.Tensor,
        phi_return: torch.Tensor,
    ) -> torch.Tensor:

        def make_problem(trust_region=True):
            """Here we solve the rectification problem without trust region constraint to make it always feasible"""
            x = cp.Variable(num_modes)
            y = cp.Parameter(num_modes)

            A = cp.Parameter((num_server, num_modes))
            b = cp.Parameter(num_server)
            c = cp.Parameter(num_modes)
            d = cp.Parameter()

            F = cp.Parameter(num_modes)
            g = cp.Parameter()

            E = cp.Parameter((num_modes, num_modes))
            ub = cp.Parameter(num_modes)
            lb = cp.Parameter(num_modes)

            if trust_region:
                prob = cp.Problem(
                    cp.Minimize(cp.norm(x - y, 2)),
                    constraints=[
                        cp.SOC(c.T @ x + d, A @ x + b),  # server energy balance violation
                        E @ x <= ub,  # trust region upper bounds
                        E @ x >= lb,  # trust region lower bounds
                        F @ x == g  # room energy balance
                    ]
                )
                assert prob.is_dcp()
                return prob, [A, b, c, d, E, ub, lb, F, g, y], [x]
            else:
                prob = cp.Problem(
                    cp.Minimize(cp.norm(x - y, 2)),
                    constraints=[
                        cp.SOC(c.T @ x + d, A @ x + b),  # server energy balance violation
                        F @ x == g  # room energy balance
                    ]
                )
                assert prob.is_dcp()
                return prob, [A, b, c, d, F, g, y], [x]

        # setup problem dimensions
        num_server = phi_inlet.shape[0]
        num_modes = self.num_modes

        # server energy balance violation as a second order cone constraint
        A = phi_outlet - phi_inlet
        b = (mean_temp_outlet - mean_temp_inlet) - server_powers / (self.c_p * self.rho_air * server_volume_flow_rates)
        c = torch.zeros(num_modes)
        d = torch.linalg.norm(A @ coef_hat.T + b)  # use the GP coarse estimation as initialization

        # equality constraint: exact room energy balance
        F = phi_return * crac_setpoints.view((1, -1))
        g = server_powers.sum() / (self.c_p * self.rho_air) - \
            torch.sum((mean_temp_return - crac_setpoints) * crac_volume_flow_rate)

        if coef_std is None:
            # solve the rectification without trust region constraints
            problem, parameters, variables = make_problem(trust_region=False)
            layer = CvxpyLayer(problem, parameters, variables)
            coef = layer(
                A, b, c, d, F, g, coef_hat,
            )[0]
            return coef
        else:
            # solve the rectification problem with trust region constraints
            beta = 1.0
            problem, parameters, variables = make_problem(trust_region=True)
            layer = CvxpyLayer(problem, parameters, variables)
            I = torch.eye(num_modes)
            for i in range(5):
                upperbound = coef_hat + beta * coef_std
                lowerbound = coef_hat - beta * coef_std
                try:
                    coef = layer(
                        A, b, c, d, I, upperbound, lowerbound, F, g, coef_hat,
                    )[0]
                    return coef
                except Exception:
                    # Here solver error means the trust region is too small
                    beta *= 1.1
            # loguru.logger.warning("Local search infeasible. Use GP coarsely estimated POD coefficients instead.")
            return coef_hat

    def _flux_matching(
        self,
        server_powers: torch.Tensor,
        server_volume_flow_rates: torch.Tensor,
        crac_setpoints: torch.Tensor,
        crac_volume_flow_rates: torch.Tensor,
        mean_temp_inlet: torch.Tensor,
        mean_temp_outlet: torch.Tensor,
        mean_temp_return: torch.Tensor,
        phi_inlet: torch.Tensor,
        phi_outlet: torch.Tensor,
        phi_return: torch.Tensor,
    ) -> None:
        """
        Implement flux matching based on the paper
        "Proper Orthogonal Decomposition for Reduced Order Thermal Modeling of Air Cooled Data Centers"

        :param used_modes: the POD modes used for prediction
        :param object_mesh_index: the mesh indices of the CRACs and servers
        :param server_powers: the power of the servers
        :param server_flow_rates: the flow rate of the servers
        :param crac_setpoints: the setpoint of the CRACs
        :param crac_flow_rates: the flow rate of the CRACs
        """
        # select boundary conditions within the air loop
        phi_server_matrix = phi_outlet - phi_inlet
        server_array = server_powers / (self.c_p * self.rho_air * server_volume_flow_rates)
        server_array -= (mean_temp_outlet - mean_temp_inlet)

        phi_crac_matrix = torch.sum(phi_return * crac_volume_flow_rates.view(-1, 1)).view(1, -1)
        crac_array = torch.sum(server_powers.sum()) / (self.c_p * self.rho_air)
        crac_array -= np.sum((mean_temp_return - crac_setpoints) * crac_volume_flow_rates, axis=0)

        # assemble all matrices and arrays into a big linear system
        a = torch.cat([phi_server_matrix, phi_crac_matrix], dim=0)
        b = torch.cat([server_array, crac_array], dim=0)
        assert a.shape[0] > self.num_modes, "equations are fewer than number of coefficients"
        # solve the least square for optimal coefficients
        self.coefs, _ = torch.linalg.lstsq(a, b)[:2]

    def _gp(
        self,
        server_powers: torch.Tensor,
        server_volume_flow_rates: torch.Tensor,
        crac_setpoints: torch.Tensor,
        crac_volume_flow_rate: torch.Tensor,
        mean_temp_inlet: torch.Tensor,
        mean_temp_outlet: torch.Tensor,
        mean_temp_return: torch.Tensor,
        phi_inlet: torch.Tensor,
        phi_outlet: torch.Tensor,
        phi_return: torch.Tensor,
        local_search: bool = True,
    ) -> None:
        """
        Implement POD coefficient estimation based on Gaussian Process Regression.

        :param used_modes: the POD modes used for prediction
        :param object_mesh_index: the mesh indices of the CRACs and servers
        :param server_powers: the power of the servers
        :param server_flow_rates: the flow rate of the servers
        :param crac_setpoints: the setpoint of the CRACs
        :param crac_flow_rates: the flow rate of the CRACs
        :param local_search: whether to use local search to find the POD coefficients
        """

        # build the input tensor to the GP model
        inputs = torch.cat(
            [
                server_powers.sum().view(1, -1),
                server_volume_flow_rates.sum().view(1, -1),
                crac_setpoints.view(1, -1),
                crac_volume_flow_rate.view(1, -1)
            ],
            dim=1
        )
        # predict POD coefficients with Gaussian Model
        with gpytorch.settings.fast_pred_var():
            dist = self.model(inputs)
            prediction = self.likelihood(dist)
            coef = prediction.mean
            coef_std = prediction.stddev * self.model.train_y_std

        # physics-guided local search (rectification) on the coarse estimation from GP models
        if local_search:
            self.coefs = self._local_search(
                server_powers=server_powers,
                server_volume_flow_rates=server_volume_flow_rates,
                crac_volume_flow_rate=crac_volume_flow_rate,
                crac_setpoints=crac_setpoints,
                coef_hat=coef,
                coef_std=coef_std,
                mean_temp_inlet=mean_temp_inlet,
                mean_temp_outlet=mean_temp_outlet,
                mean_temp_return=mean_temp_return,
                phi_inlet=phi_inlet,
                phi_outlet=phi_outlet,
                phi_return=phi_return,
            )
        else:
            self.coefs = coef

    def docker_image(self):
        raise NotImplementedError("Docker image is not available for this model.")

    def command(self) -> Union[list, str]:
        raise NotImplementedError("Command is not available for this model.")

    @classmethod
    def load(cls):
        """
        Load the POD modes, mean temperature filed, offline trained GP models from the saved file.
        """
        try:
            pod = cls()
            # load pod modes, mean temperature field,
            # training boundary conditions and training labels (POD coefficients)
            with open(Path(config.cfd.pod_dir).joinpath("pod_data.pkl"), "rb") as f:
                data = pickle.load(f)
                assert isinstance(data, dict), "data.pkl should be a dictionary!"
                try:
                    pod.modes = data["modes"].float()
                    pod.mean_obs = data["mean_obs"].float()
                    pod.train_bc = data["train_bc"].float()
                    pod.train_coef = data["train_coef"].float()
                except KeyError:
                    raise KeyError(
                        f"Key not found in the saved data file. "
                        f"Keys in the saved data file include: "
                        f"{data.keys()}"
                    )
            pod.likelihood = gpytorch.likelihoods.MultitaskGaussianLikelihood(num_tasks=pod.num_modes)
            pod.model = BatchIndependentMultiTaskGPModel(
                train_x=pod.train_bc,
                train_y=pod.train_coef,
                likelihood=pod.likelihood,
                num_modes=pod.num_modes
            )
            # load optimized parameters of the multi-output GP model
            pod.model.load_state_dict(torch.load(Path(config.cfd.pod_dir).joinpath("model.pth")))
            pod.likelihood.load_state_dict(torch.load(Path(config.cfd.pod_dir).joinpath("likelihood.pth")))
            # switch to evaluation mode
            pod.model.eval()
            pod.likelihood.eval()
        except FileNotFoundError:
            pod = None
        return pod

    def run(
        self,
        object_mesh_index: Dict,
        server_powers: torch.Tensor,
        server_volume_flow_rates: torch.Tensor,
        crac_setpoints: torch.Tensor,
        crac_volume_flow_rates: torch.Tensor,
        pod_method: str = "GP-Flux",
    ) -> np.ndarray:
        """
        Run certain POD coefficient estimation algorithm to predict the temperature field.
        :param object_mesh_index: the mesh indices of the CRACs and servers
        :param pod_method: the POD coefficient estimation algorithm
        :param boundary_conditions: the boundary conditions for the temperature field calculation. Boundary conditions
            include server power, server flow rate, CRAC setpoint, and CRAC flow rate.
        """
        assert self.modes is not None, "POD modes are not computed or loaded"
        mode_data = self._prepare_mode_data(object_mesh_index)
        # POD coefficients calculation for a new test case
        if pod_method == "Flux":
            self._flux_matching(
                server_powers=server_powers,
                server_volume_flow_rates=server_volume_flow_rates,
                crac_setpoints=crac_setpoints,
                crac_volume_flow_rates=crac_volume_flow_rates,
                **mode_data
            )
        elif pod_method == "GP":
            self._gp(
                server_powers=server_powers,
                server_volume_flow_rates=server_volume_flow_rates,
                crac_setpoints=crac_setpoints,
                crac_volume_flow_rate=crac_volume_flow_rates,
                local_search=False,
                **mode_data
            )
        elif pod_method == "GP-Flux":
            self._gp(
                server_powers=server_powers,
                server_volume_flow_rates=server_volume_flow_rates,
                crac_setpoints=crac_setpoints,
                crac_volume_flow_rate=crac_volume_flow_rates,
                local_search=True,
                **mode_data
            )
        else:
            raise NotImplementedError(f"{pod_method} not implemented")
        # reconstruct temperature field
        reconstruct = self.mean_obs + torch.matmul(self.coefs, self.modes[:, :self.num_modes].T)
        return reconstruct