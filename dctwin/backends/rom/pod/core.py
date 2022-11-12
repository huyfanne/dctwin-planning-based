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

    def _local_search(
        self,
        used_modes,
        object_mesh_index,
        crac_flow_rate: Dict,
        crac_supply_temperature: Dict,
        server_heat_loads: Dict,
        server_flow_rates: Dict,
        coef_hat: torch.Tensor,
        coef_std: Union[torch.Tensor, None]
    ) -> np.ndarray:

        def make_problem(trust_region=True):
            """Here we solve the rectification problem without trust region constraint to make it always feasible"""
            x = cp.Variable(n)
            y = cp.Parameter(n)

            A = cp.Parameter((num_server, n))
            b = cp.Parameter(num_server)
            c = cp.Parameter(n)
            d = cp.Parameter()

            F = cp.Parameter(n)
            g = cp.Parameter()

            E = cp.Parameter((n, n))
            ub = cp.Parameter(n)
            lb = cp.Parameter(n)

            if trust_region:
                prob = cp.Problem(
                    cp.Minimize(cp.norm(x - y, 2)),
                    constraints=[
                        cp.SOC(c.T @ x + d, A @ x + b), # server energy balance violation
                        E @ x <= ub, # trust region upper bounds
                        E @ x >= lb, # trust region lower bounds
                        F @ x == g # room energy balance
                    ]
                )
                assert prob.is_dcp()
                return prob, [A, b, c, d, E, ub, lb, F, g, y], [x]
            else:
                prob = cp.Problem(
                    cp.Minimize(cp.norm(x - y, 2)),
                    constraints=[
                        cp.SOC(c.T @ x + d, A @ x + b), # server energy balance violation
                        F @ x == g # room energy balance
                    ]
                )
                assert prob.is_dcp()
                return prob, [A, b, c, d, F, g, y], [x]

        phi_return = []
        phi_inlet = []
        phi_outlet = []
        mean_temp_inlet = []
        mean_temp_outlet = []
        mean_temp_return = []
        q_server = []
        m_server = []
        sp_crac = []
        m_crac = []
        used_modes = torch.from_numpy(used_modes).float()
        coef_hat = coef_hat.float()

        for server_name, server_mesh_indices in object_mesh_index["servers"].items():
            q_server.append(server_heat_loads[server_name])
            m_server.append(server_flow_rates[server_name])
            mean_temp_inlet.append(self.mean_obs[server_mesh_indices["inlet"]])
            mean_temp_outlet.append(self.mean_obs[server_mesh_indices["outlet"]])
            phi_inlet.append(used_modes[server_mesh_indices["inlet"], :])
            phi_outlet.append(used_modes[server_mesh_indices["outlet"], :])

        for crac_name, crac_mesh_indices in object_mesh_index["cracs"].items():
            mean_temp_return.append(self.mean_obs[crac_mesh_indices["return"]])
            phi_return.append(used_modes[crac_mesh_indices["return"], :])
            sp_crac.append(crac_supply_temperature[crac_name])
            m_crac.append(crac_flow_rate[crac_name])

        q_server = torch.tensor(q_server, dtype=torch.float32)
        m_server = torch.tensor(m_server, dtype=torch.float32)
        sp_crac = torch.tensor(sp_crac, dtype=torch.float32)
        m_crac = torch.tensor(m_crac, dtype=torch.float32)
        mean_temp_inlet = torch.tensor(mean_temp_inlet, dtype=torch.float32)
        mean_temp_outlet = torch.tensor(mean_temp_outlet, dtype=torch.float32)
        mean_temp_return = torch.tensor(mean_temp_return, dtype=torch.float32)
        phi_inlet = torch.vstack(phi_inlet)
        phi_outlet = torch.vstack(phi_outlet)
        phi_return = torch.vstack(phi_return)

        num_server = phi_inlet.shape[0]
        n = self.num_modes

        # server level energy balance
        A = phi_outlet - phi_inlet
        b = (mean_temp_outlet - mean_temp_inlet) - q_server / (self.c_p * self.rho_air * m_server)
        c = torch.zeros(n)
        d = torch.linalg.norm(A @ coef_hat.T + b)  # use the GP coarse estimation as initialization

        # equality constraint: room energy balance
        F = phi_return * m_crac.view((1, -1))
        g = q_server.sum() / (self.c_p * self.rho_air) - torch.sum((mean_temp_return - sp_crac) * m_crac)

        if coef_std is None:
            # solve the rectification without trust region constraints
            prob, params, vars = make_problem(trust_region=False)
            layer = CvxpyLayer(prob, params, vars)
            coef = layer(
                A, b, c, d, F, g, coef_hat,
            )[0]
            return coef.detach().cpu().numpy()[:, :self.num_modes]
        else:
            # solve the rectification problem with trust region constraints
            beta = 1.0
            for i in range(20):
                upperbound = coef_hat + beta * coef_std
                lowerbound = coef_hat - beta * coef_std
                I = torch.eye(n)
                prob, params, vars = make_problem(trust_region=True)
                layer = CvxpyLayer(prob, params, vars)
                try:
                    coef = layer(
                        A, b, c, d, I, upperbound, lowerbound, F, g, coef_hat,
                    )[0]
                    return coef.detach().cpu().numpy()[:, :self.num_modes]
                except Exception:
                    beta *= 2
            loguru.logger.warning("Local search infeasible. Use GP coarsely estimated POD coefficients instead.")
            return coef_hat.detach().cpu().numpy()


    def _flux_matching(
        self,
        used_modes: np.ndarray,
        object_mesh_index: Dict,
        server_powers: Dict,
        server_flow_rates: Dict,
        crac_setpoints: Dict,
        crac_flow_rates: Dict,
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
        a, b = [], []

        # map the nearest mesh index for local area, i.e., server inlet/outlet and crac return
        server_inlet_index = [object_mesh_index["servers"][each]["inlet"] for each in server_powers.keys()]
        server_outlet_index = [object_mesh_index["servers"][each]["outlet"] for each in server_powers.keys()]
        crac_return_index = [object_mesh_index["cracs"][each]["return"] for each in crac_setpoints.keys()]
        # select boundary conditions within the air loop
        all_server_heat_load = np.asarray([server_powers[each] for each in server_powers.keys()])
        all_server_flow = np.asarray([server_flow_rates[each] for each in server_powers.keys()])
        phi_server_matrix = used_modes[server_outlet_index, :] - used_modes[server_inlet_index, :]
        server_array = all_server_heat_load / (self.c_p * self.rho_air * all_server_flow)
        server_array -= (self.mean_obs[server_outlet_index] - self.mean_obs[server_inlet_index])

        all_crac_setpoint = np.asarray([crac_setpoints[each] for each in crac_setpoints.keys()])
        all_crac_flow = np.asarray([crac_flow_rates[each] for each in crac_setpoints.keys()])
        phi_crac_matrix = np.sum(used_modes[crac_return_index, :] * all_crac_flow.reshape(-1, 1), axis=0).reshape(1, -1)
        crac_array = np.sum(all_server_heat_load) / (self.c_p * self.rho_air)
        crac_array -= np.sum((self.mean_obs[crac_return_index] - all_crac_setpoint) * all_crac_flow, axis=0)
        a.append(np.concatenate([phi_server_matrix, phi_crac_matrix], axis=0))
        b.append(np.concatenate([server_array, np.array([crac_array])], axis=0))

        # assemble all matrices and arrays into a big linear system
        a = np.concatenate(a, axis=0)
        b = np.concatenate(b, axis=0)
        assert a.shape[0] > self.num_modes, "equations are fewer than number of coefficients"
        # solve the least square for optimal coefficients
        self.coefs, _ = np.linalg.lstsq(a, b, rcond=None)[:2]

    def _gp(
        self,
        used_modes: np.ndarray,
        object_mesh_index: Dict,
        server_powers: Dict,
        server_flow_rates: Dict,
        crac_setpoints: Dict,
        crac_flow_rates: Dict,
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
        # compute total heat load and total server flow rate
        q_server_tot = np.sum(list(server_powers.values()))
        m_server_tot = np.sum(list(server_flow_rates.values()))

        # predict POD coefficients with Gaussian Model
        bc = np.concatenate(
            [
                [q_server_tot],
                [m_server_tot],
                np.asarray(list(crac_setpoints.values())).reshape(-1),
                np.asarray(list(crac_flow_rates.values())).reshape(-1)
            ]
        ).reshape(1, -1)
        bc_tensor = torch.FloatTensor(bc)
        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            dist = self.model(bc_tensor)
            prediction = self.likelihood(dist)
            coef = prediction.mean
            coef_std = prediction.stddev * self.model.train_y_std

        # physics-guided local search (rectification) on the coarse estimation from GP models
        if local_search:
            self.coefs = self._local_search(
                used_modes,
                object_mesh_index,
                crac_flow_rates,
                crac_setpoints,
                server_powers,
                server_flow_rates,
                coef,
                coef_std
            )
        else:
            self.coefs = np.asarray(coef)

    def docker_image(self):
        raise NotImplementedError("Docker image is not available for this model.")

    def command(self) -> Union[list, str]:
        raise NotImplementedError("Command is not available for this model.")

    def run(
        self,
        object_mesh_index: Dict,
        pod_method: str = "GP-Flux",
        **boundary_conditions
    ) -> np.ndarray:
        """
        Run certain POD coefficient estimation algorithm to predict the temperature field.

        :param object_mesh_index: the mesh indices of the CRACs and servers
        :param pod_method: the POD coefficient estimation algorithm
        :param boundary_conditions: the boundary conditions for the temperature field calculation. Boundary conditions
            include server power, server flow rate, CRAC setpoint, and CRAC flow rate.
        """
        assert self.modes is not None, "POD modes are not computed or loaded"
        used_modes = self.modes[:, :self.num_modes]
        # POD coefficients calculation for a new test case
        if pod_method == "Flux":
            self._flux_matching(
                used_modes=used_modes,
                object_mesh_index=object_mesh_index,
                **boundary_conditions
            )
        elif pod_method == "GP":
            self._gp(
                used_modes=used_modes,
                object_mesh_index=object_mesh_index,
                local_search=False,
                **boundary_conditions
            )
        elif pod_method == "GP-Flux":
            self._gp(
                used_modes=used_modes,
                object_mesh_index=object_mesh_index,
                **boundary_conditions
            )
        else:
            raise NotImplementedError(f"{pod_method} not implemented")
        # reconstruct temperature field
        reconstruct = self.mean_obs + np.matmul(self.coefs, np.transpose(used_modes))
        return reconstruct.ravel()

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
                    pod.modes = data["modes"]
                    pod.mean_obs = data["mean_obs"]
                    pod.train_bc = data["train_bc"]
                    pod.train_coef = data["train_coef"]
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
