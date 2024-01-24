import pickle
from typing import Dict, Union, Optional
from loguru import logger
import numpy as np
import cvxpy as cp
from pathlib import Path
import gpytorch
import torch
from cvxpylayers.torch import CvxpyLayer


from dctwin.backends.core import Backend
from dctwin.backends.core_k8s import BackendK8s
from dctwin.models import Room
from dctwin.utils import config

from .models import BatchIndependentMultiTaskGPModel


class PODBackendMixin:
    """
    Backend for the POD model. It is a wrapper of the POD model.
    It accepts the boundary conditions and predict the
    temperature field with the POD modes and the GP models.
    """

    rho_air = 1.19  # air density kg/m^3
    c_p = 1006  # air heat capacity J/(kg*C)

    def __init__(self, room: Room, object_mesh_index: Dict) -> None:
        super().__init__()
        self.train_bc = None
        self.train_coef = None
        self.likelihood = None
        self.model = None
        self.mean_obs = None
        self.modes = None
        self.room = room
        self.num_modes = config.cfd.num_modes
        self.object_mesh_index = object_mesh_index
        self.server_inlet, self.server_outlet = [], []
        self.acu_supply, self.acu_return = [], []
        self.sensor_index = []
        self._get_object_index()

    def _get_object_index(self) -> None:

        for rack_name, rack in self.room.constructions.racks.items():
            for server_name, _ in rack.constructions.servers.items():
                self.server_inlet.append(
                    self.object_mesh_index["servers"][server_name]["inlet"]
                )
                self.server_outlet.append(
                    self.object_mesh_index["servers"][server_name]["outlet"]
                )

        for acu_name, _ in self.room.constructions.acus.items():
            self.acu_supply.append(self.object_mesh_index["acus"][acu_name]["supply"])
            self.acu_return.append(self.object_mesh_index["acus"][acu_name]["return"])

        for sen_name, _ in self.room.constructions.sensors.items():
            self.sensor_index.append(self.object_mesh_index["sensors"][sen_name])

    def _as_tensors(
        self,
        supply_air_temperatures: Dict,
        supply_air_volume_flow_rates: Dict,
        server_powers: Dict,
        server_volume_flow_rates: Dict,
        sensor_temperatures: Optional[Dict] = None,
    ) -> Dict[str, torch.Tensor]:
        """
        convert the boundary conditions into torch.Tensor format
        :param supply_air_temperatures: acu supply temperature dict
        :param supply_air_volume_flow_rates: acu volume flow rate dict
        :param server_powers: server heat loads dict
        :param server_volume_flow_rates: server volume flow rates dict
        """
        server_power_list, server_volume_flow_rate_list = [], []
        supply_air_temperature_list, supply_air_volume_flow_rate_list = [], []
        sensor_temperature_list = []

        for rack_name, rack in self.room.constructions.racks.items():
            for server_name, server in rack.constructions.servers.items():
                server_power_list.append(server_powers[server_name])
                server_volume_flow_rate_list.append(
                    server_volume_flow_rates[server_name]
                )

        for acu_name, acu in self.room.constructions.acus.items():
            supply_air_temperature_list.append(supply_air_temperatures[acu_name])
            supply_air_volume_flow_rate_list.append(
                supply_air_volume_flow_rates[acu_name]
            )

        if sensor_temperatures is not None:
            for sensor_name, sensor in self.room.constructions.sensors.items():
                sensor_temperature_list.append(sensor_temperatures[sensor_name])

        server_powers = torch.tensor(
            server_power_list, dtype=torch.float32, requires_grad=False
        )
        server_volume_flow_rates = torch.tensor(
            server_volume_flow_rate_list, dtype=torch.float32, requires_grad=False
        )
        supply_air_temperatures = torch.tensor(
            supply_air_temperature_list, dtype=torch.float32, requires_grad=False
        )
        supply_air_volume_flow_rates = torch.tensor(
            supply_air_volume_flow_rate_list, dtype=torch.float32, requires_grad=False
        )
        sensor_temperatures = torch.tensor(
            sensor_temperature_list, dtype=torch.float32, requires_grad=False
        )

        return {
            "server_powers": server_powers,
            "server_volume_flow_rates": server_volume_flow_rates,
            "supply_air_temperatures": supply_air_temperatures,
            "supply_air_volume_flow_rates": supply_air_volume_flow_rates,
            "sensor_temperatures": sensor_temperatures,
        }

    def _pre_process_inputs(
        self,
        sensor_temperatures: Optional[Dict] = None,
        **boundary_conditions,
    ) -> Dict[str, torch.Tensor]:
        """
        Pre-process the inputs for the POD model
         - obtain the POD mode data for server inlet/outlet and acu return
         - remove servers with zero volume flow rate to avoid zero division error
        """
        used_modes = self.modes[:, : self.num_modes]
        results = self._as_tensors(
            sensor_temperatures=sensor_temperatures, **boundary_conditions
        )

        mask = results["server_volume_flow_rates"].ne(0.0)
        mean_temp_inlet = torch.masked_select(self.mean_obs[self.server_inlet], mask)
        mean_temp_outlet = torch.masked_select(self.mean_obs[self.server_outlet], mask)
        mean_temp_return = self.mean_obs[self.acu_return]
        mean_temp_sensor = self.mean_obs[self.sensor_index]

        phi_inlet = torch.masked_select(
            used_modes[self.server_inlet], mask.view(-1, 1)
        ).view(-1, self.num_modes)
        phi_outlet = torch.masked_select(
            used_modes[self.server_outlet], mask.view(-1, 1)
        ).view(-1, self.num_modes)
        phi_return = used_modes[self.acu_return]
        phi_sensor = used_modes[self.sensor_index]

        server_powers = torch.masked_select(results["server_powers"], mask)
        server_volume_flow_rates = torch.masked_select(
            results["server_volume_flow_rates"], mask
        )

        input_data = {
            "supply_air_temperatures": results["supply_air_temperatures"],
            "supply_air_volume_flow_rates": results["supply_air_volume_flow_rates"],
            "server_powers": server_powers,
            "server_volume_flow_rates": server_volume_flow_rates,
            "sensor_temperatures": results["sensor_temperatures"],
            "mean_temp_inlet": mean_temp_inlet,
            "mean_temp_outlet": mean_temp_outlet,
            "mean_temp_return": mean_temp_return,
            "mean_temp_sensor": mean_temp_sensor,
            "phi_inlet": phi_inlet,
            "phi_outlet": phi_outlet,
            "phi_return": phi_return,
            "phi_sensor": phi_sensor,
        }

        return input_data

    def _local_search(
        self,
        supply_air_volume_flow_rates: torch.Tensor,
        supply_air_temperatures: torch.Tensor,
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
        sensor_temperatures: Optional[torch.Tensor] = None,
        mean_temp_sensor: Optional[torch.Tensor] = None,
        phi_sensor: Optional[torch.Tensor] = None,
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
                        cp.SOC(
                            c.T @ x + d, A @ x + b
                        ),  # server energy balance violation
                        E @ x <= ub,  # trust region upper bounds
                        E @ x >= lb,  # trust region lower bounds
                        F @ x == g,  # room energy balance
                    ],
                )
                assert prob.is_dcp()
                return prob, [A, b, c, d, E, ub, lb, F, g, y], [x]
            else:
                prob = cp.Problem(
                    cp.Minimize(cp.norm(x - y, 2)),
                    constraints=[
                        cp.SOC(
                            c.T @ x + d, A @ x + b
                        ),  # server energy balance violation
                        F @ x == g,  # room energy balance
                    ],
                )
                assert prob.is_dcp()
                return prob, [A, b, c, d, F, g, y], [x]

        # setup problem dimensions
        num_server = phi_inlet.shape[0]
        num_modes = self.num_modes

        # server energy balance violation as a second order cone constraint
        A = phi_outlet - phi_inlet
        b = (mean_temp_outlet - mean_temp_inlet) - server_powers / (
            self.c_p * self.rho_air * server_volume_flow_rates
        )
        c = torch.zeros(num_modes)
        d = torch.linalg.norm(
            A @ coef_hat.T + b
        )  # use the GP coarse estimation as initialization

        # equality constraint: exact room energy balance
        F = phi_return * supply_air_temperatures.view(-1, 1)
        g = server_powers.sum() / (self.c_p * self.rho_air) - torch.sum(
            (mean_temp_return - supply_air_temperatures) * supply_air_volume_flow_rates
        )

        if coef_std is None:
            # solve the rectification without trust region constraints
            problem, parameters, variables = make_problem(trust_region=False)
            layer = CvxpyLayer(problem, parameters, variables)
            coef = layer(
                A,
                b,
                c,
                d,
                F,
                g,
                coef_hat,
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
                        A,
                        b,
                        c,
                        d,
                        I,
                        upperbound,
                        lowerbound,
                        F,
                        g,
                        coef_hat,
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
        supply_air_temperatures: torch.Tensor,
        supply_air_volume_flow_rates: torch.Tensor,
        mean_temp_inlet: torch.Tensor,
        mean_temp_outlet: torch.Tensor,
        mean_temp_return: torch.Tensor,
        phi_inlet: torch.Tensor,
        phi_outlet: torch.Tensor,
        phi_return: torch.Tensor,
        sensor_temperatures: Optional[torch.Tensor] = None,
        mean_temp_sensor: Optional[torch.Tensor] = None,
        phi_sensor: Optional[torch.Tensor] = None,
    ) -> None:
        """
        Implement flux matching based on the paper:
        "Proper Orthogonal Decomposition for Reduced Order Thermal Modeling of Air Cooled Data Centers"

        The flux-matching problem is to solve the following linear equation system for the POD coefficients:
        
            & \sum_{i=1}^{H}\beta_i(\mathbf{x})(\Phi_\text{out}^{i1}-\Phi_\text{in}^{i1}) = \frac{P_1}{c_\text{p} \rho \alpha_1}, \\
	        & \sum_{i=1}^{H}\beta_i(\mathbf{x})(\Phi_\text{out}^{i2}-\Phi_\text{in}^{i2}) = \frac{P_2}{c_\text{p} \rho \alpha_2}, \\
	        & \dots \\
	        & \sum_{i=1}^{H}\beta_i(\mathbf{x})(\Phi}_\text{out}^{im}-\Phi_\text{in}^{im}) = \frac{P_m}{c_\text{p} \rho \alpha_m},\\
	        & \sum_{k=1}^{l} \sum_{i=1}^{H} V_k \beta_i(\mathbf{x})(\Phi_\text{return}^{ik}-\Phi_\text{supply}^{ik}) = \frac{\sum_{j=1}^{m}{P_j}}{c_\text{p} \rho}

        where $H$ is the number of used modes, $m$ is the number of servers, $l$ is the number of acus, \beta is the coefficients,

        :param server_powers: the power of the servers
        :param server_volume_flow_rates: the volume flow rates of the servers
        :param supply_air_temperatures: the supply temperature of the acus
        :param supply_air_volume_flow_rates: the supply air flow rates of the acus
        :param mean_temp_inlet: the inlet temperatures of the servers
        :param mean_temp_outlet: the outlet temperatures of the servers
        :param mean_temp_return: the return temperature of the acus
        :param phi_inlet: the inlet flux of the servers
        :param phi_outlet: the outlet flux of the servers
        :param phi_return: the return flux of the acus
        """
        # select boundary conditions within the air loop
        phi_server_matrix: torch.Tensor = phi_outlet - phi_inlet
        server_array: torch.Tensor = server_powers / (
            torch.tensor((self.c_p * self.rho_air)) * server_volume_flow_rates
        )
        server_array -= mean_temp_outlet - mean_temp_inlet
        server_array = server_array.view(-1, 1)

        phi_acu_matrix: torch.Tensor = torch.sum(
            phi_return * supply_air_volume_flow_rates.view(-1, 1), dim=0, keepdim=True
        )
        acu_array: torch.Tensor = torch.sum(server_powers) / torch.tensor(
            (self.c_p * self.rho_air)
        )
        acu_array -= torch.sum(
            (mean_temp_return - supply_air_temperatures) * supply_air_volume_flow_rates
        )
        acu_array = acu_array.view(-1, 1)

        sen_array = sensor_temperatures - mean_temp_sensor

        # assemble all matrices and arrays into a big linear system
        a = torch.cat([phi_server_matrix, phi_acu_matrix, phi_sensor], dim=0)
        b = torch.cat([server_array, acu_array, sen_array], dim=0)
        assert (
            a.shape[0] > self.num_modes
        ), "equations are fewer than number of coefficients"
        # solve the least square for optimal coefficients
        self.coefs, _ = torch.linalg.lstsq(a, b)[:2]
        self.coefs = self.coefs.view(1, -1)

    def _gp(
        self,
        server_powers: torch.Tensor,
        server_volume_flow_rates: torch.Tensor,
        supply_air_temperatures: torch.Tensor,
        supply_air_volume_flow_rates: torch.Tensor,
        mean_temp_inlet: torch.Tensor,
        mean_temp_outlet: torch.Tensor,
        mean_temp_return: torch.Tensor,
        phi_inlet: torch.Tensor,
        phi_outlet: torch.Tensor,
        phi_return: torch.Tensor,
        sensor_temperatures: Optional[torch.Tensor] = None,
        mean_temp_sensor: Optional[torch.Tensor] = None,
        phi_sensor: Optional[torch.Tensor] = None,
        local_search: bool = True,
    ) -> None:
        """
        Implement POD coefficient estimation based on Gaussian Process Regression.
        :param server_powers: the power of the servers
        :param server_volume_flow_rates: the flow rate of the servers
        :param supply_air_temperatures: the setpoint of the acus
        :param supply_air_volume_flow_rates: the flow rate of the acus
        :param mean_temp_inlet: the inlet temperature of the servers
        :param mean_temp_outlet: the outlet temperature of the servers
        :param mean_temp_return: the return temperature of the acus
        :param phi_inlet: the inlet flux of the servers
        :param phi_outlet: the outlet flux of the servers
        :param phi_return: the return flux of the acus
        :param local_search: whether to use local search to improve the estimation
        """
        # build the input tensor to the GP model
        inputs = torch.cat(
            [
                server_powers.sum().view(1, -1),
                server_volume_flow_rates.sum().view(1, -1),
                supply_air_temperatures.view(1, -1),
                supply_air_volume_flow_rates.view(1, -1),
            ],
            dim=1,
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
                supply_air_volume_flow_rates=supply_air_volume_flow_rates,
                supply_air_temperatures=supply_air_temperatures,
                coef_hat=coef,
                coef_std=coef_std,
                mean_temp_inlet=mean_temp_inlet,
                mean_temp_outlet=mean_temp_outlet,
                mean_temp_return=mean_temp_return,
                phi_inlet=phi_inlet,
                phi_outlet=phi_outlet,
                phi_return=phi_return,
                sensor_temperatures=sensor_temperatures,
                mean_temp_sensor=mean_temp_sensor,
                phi_sensor=phi_sensor,
            )
        else:
            self.coefs = coef

    def docker_image(self) -> str:
        raise NotImplementedError("Docker image is not available for this model.")

    def command(self) -> Union[list, str]:
        raise NotImplementedError("Command is not available for this model.")

    @classmethod
    def load(cls, room: Room, object_mesh_index: Dict) -> "PODBackend":
        """
        Load the POD modes, mean temperature filed, offline trained GP models from the saved file.
        """
        try:
            pod = cls(room=room, object_mesh_index=object_mesh_index)
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
            pod.likelihood = gpytorch.likelihoods.MultitaskGaussianLikelihood(
                num_tasks=pod.num_modes
            )
            pod.model = BatchIndependentMultiTaskGPModel(
                train_x=pod.train_bc,
                train_y=pod.train_coef,
                likelihood=pod.likelihood,
                num_modes=pod.num_modes,
            )
            # load optimized parameters of the multi-output GP model
            pod.model.load_state_dict(
                torch.load(Path(config.cfd.pod_dir).joinpath("model.pth"))
            )
            pod.likelihood.load_state_dict(
                torch.load(Path(config.cfd.pod_dir).joinpath("likelihood.pth"))
            )
            # switch to evaluation mode
            pod.model.eval()
            pod.likelihood.eval()
        except FileNotFoundError:
            logger.info("POD data not found. Run simulation with CFD backend.")
            pod = None
        return pod

    def run(
        self,
        pod_method: str = "GP-Flux",
        sensor_temperatures: Optional[Dict] = None,
        **boundary_conditions: Dict,
    ) -> np.ndarray:
        """
        Run certain POD coefficient estimation algorithm to predict the temperature field.
        :param pod_method: the POD coefficient estimation algorithm
        :param sensor_temperatures: the temperature of the sensor measurements
        :param boundary_conditions: boundary conditions for simulation
           i.e., boundary_conditions = {
            "supply_air_temperatures": {}, "supply_air_volume_flow_rates": {},
            "server_powers": {}, "server_volume_flow_rates": {}
            }
        """
        assert self.modes is not None, "POD modes are not computed or loaded"
        input_data = self._pre_process_inputs(
            sensor_temperatures=sensor_temperatures, **boundary_conditions
        )
        # POD coefficients calculation for a new test case
        if pod_method == "Flux":
            self._flux_matching(**input_data)
        elif pod_method == "GP":
            self._gp(local_search=False, **input_data)
        elif pod_method == "GP-Flux":
            self._gp(local_search=True, **input_data)
        else:
            raise NotImplementedError(f"{pod_method} not implemented")
        # reconstruct temperature field
        reconstruct = self.mean_obs + torch.matmul(
            self.coefs, self.modes[:, : self.num_modes].T
        )
        return reconstruct


class PODBackend(PODBackendMixin, Backend):
    pass


class PODBackendK8s(PODBackendMixin, BackendK8s):
    pass
