import pickle
from typing import Dict, Union

import numpy as np
import cvxpy as cp
from pathlib import Path
import gpytorch
import torch

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
        used_mode: np.ndarray,
        object_mesh_index: Dict,
        crac_flow_rate: np.ndarray,
        crac_supply_temperature: np.ndarray,
        server_heat_loads: Dict,
        server_flow_rates: Dict,
        coef_hat: np.ndarray,
        coef_std: Union[np.ndarray, None]
    ) -> np.ndarray:
        """
        Implement local search of the coarse estimation of the POD coefficients based on the paper:
        *  Zhiwei Cao, Ruihang Wang, Xin Zhou and Yonggang Wen, "Reducio: Model Reduction for Data Center Predictive
           Digital Twins via Physics-Guided Machine Learning," the 9th ACM International Conference on Systems for
           Energy-Efficient Buildings, Cities, and Transportation (BuildSys '22), 9-10 November, 2022, Boston MA, USA.

        :param used_mode: the POD modes used for the local search
        :param object_mesh_index: the mesh index of the servers and cracs
        :param crac_flow_rate: the flow rate of the cracs
        :param crac_supply_temperature: the supply temperature of the cracs
        :param server_heat_loads: the heat loads of the servers
        :param server_flow_rates: the flow rates of the servers
        :param coef_hat: the coarse estimation of the POD coefficients
        :param coef_std: the standard deviation of the POD coefficients
        :return: the refined POD coefficients
        """
        phi_return = []
        phi_inlet = []
        phi_outlet = []
        mean_temp_inlet = []
        mean_temp_outlet = []
        mean_temp_return = []
        q_server = []
        m_server = []

        for server_name, server_mesh_indices in object_mesh_index["servers"].items():
            q_server.append(server_heat_loads[server_name])
            m_server.append(server_flow_rates[server_name])
            mean_temp_inlet.append(self.mean_obs[server_mesh_indices["inlet"]])
            mean_temp_outlet.append(self.mean_obs[server_mesh_indices["outlet"]])
            phi_inlet.append(used_mode[server_mesh_indices["inlet"], :])
            phi_outlet.append(used_mode[server_mesh_indices["outlet"], :])

        for crac_name, crac_mesh_indices in object_mesh_index["cracs"].items():
            mean_temp_return.append(self.mean_obs[crac_mesh_indices["return"]])
            phi_return.append(used_mode[crac_mesh_indices["return"], :])

        q_server = np.array(q_server)
        m_server = np.array(m_server)
        mean_temp_inlet = np.array(mean_temp_inlet)
        mean_temp_outlet = np.array(mean_temp_outlet)
        mean_temp_return = np.array(mean_temp_return)
        phi_inlet = np.vstack(phi_inlet)
        phi_outlet = np.vstack(phi_outlet)
        phi_return = np.vstack(phi_return)

        # Physics-guided local search main loop
        beta = 1.0
        for _ in range(20):
            # step1: transform qcqp into socp
            num_server = phi_inlet.shape[0]
            n = self.num_modes + 1
            f = np.zeros(self.num_modes + 1)
            f[-1] = 1.0  # put the auxiliary variable as the last variable
            A1 = np.zeros((num_server, n))
            A1[:, :self.num_modes] = phi_outlet - phi_inlet
            b1 = -(q_server / (self.c_p * self.rho_air * m_server) - (mean_temp_outlet - mean_temp_inlet))
            c1 = np.zeros(n)
            d1 = beta * np.linalg.norm(A1 @ np.concatenate([coef_hat, [0.0]]) - b1,
                                       ord=2)  # use the GP coarse estimation as initialization
            A2 = np.zeros((self.num_modes, n))
            A2[:, :self.num_modes] = np.identity(self.num_modes)
            b2 = -coef_hat
            c2 = np.zeros(n)
            c2[-1] = 1.0
            d2 = 0
            F = np.zeros(n)
            F[:self.num_modes] = np.sum(phi_return * crac_flow_rate.reshape((-1, 1)), axis=0)
            Q = q_server.sum()
            g = Q / (self.c_p * self.rho_air) - np.sum((mean_temp_return - crac_supply_temperature) * crac_flow_rate)

            # step2: Define and solve the reformulated SOCP problem.
            a = cp.Variable(n)
            if coef_std is not None:
                upperbound = np.zeros(n)
                upperbound[:self.num_modes] = coef_hat + beta * coef_std
                lowerbound = np.zeros(n)
                lowerbound[:self.num_modes] = coef_hat - beta * coef_std
                identity = np.identity(n)
                identity[-1, -1] = 0
                constraints = [
                    cp.SOC(c1.T @ a + d1, A1 @ a + b1),
                    cp.SOC(c2.T @ a + d2, A2 @ a + b2),
                    identity @ a <= upperbound,
                    identity @ a >= lowerbound,
                    F @ a == g
                ]
            else:
                constraints = [
                    cp.SOC(c1.T @ a + d1, A1 @ a + b1),
                    cp.SOC(c2.T @ a + d2, A2 @ a + b2),
                    F @ a == g
                ]
            prob = cp.Problem(objective=cp.Minimize(f.T @ a), constraints=constraints)
            prob.solve(verbose=False)

            # step3: Check the solution is feasible or not
            if prob.status != "infeasible":
                return a.value[:self.num_modes]
            else:
                beta *= 1.1

        return coef_hat

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
        crac_flow_rate = np.asarray(list(crac_flow_rates.values())).reshape(-1)
        crac_supply_temperature = np.asarray(list(crac_setpoints.values())).reshape(-1)
        bc = np.concatenate([[q_server_tot], [m_server_tot], crac_supply_temperature, crac_flow_rate]).reshape(1, -1)
        bc_tensor = torch.FloatTensor(bc)
        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            dist = self.model(self.model.normalize_input(bc_tensor))
            prediction = self.likelihood(dist)
            coef_tensor = prediction.mean
            coef_tensor = self.model.train_y_std * coef_tensor + self.model.train_y_mean
            coef_std_tensor = prediction.stddev
            coef_std_tensor = self.model.train_y_std * coef_std_tensor + self.model.train_y_mean
        coef = coef_tensor.detach().cpu().numpy().ravel()
        coef_std = coef_std_tensor.detach().cpu().numpy().ravel()
        # loguru.logger.info(f"GP prediction: {[round(val, 3) for val in coef]}")
        if local_search:
            # physics-guided local search (rectification) on the coarse estimation from GP models
            self.coefs = self._local_search(
                used_modes, object_mesh_index, crac_flow_rate, crac_supply_temperature,
                server_powers, server_flow_rates, coef, coef_std)
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
        reconstruct = self.mean_obs + np.dot(self.coefs, np.transpose(used_modes))
        return reconstruct

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
