import torch
import torch.nn as nn
from abc import abstractmethod
from typing import Union, Optional, Any
from loguru import logger
import numpy as np

from dctwin.data import Batch, Buffer


class BaseNNDynamics(nn.Module):
    """
    An abstract class for neural network-based dynamics model
    :param model: neural network model
    :param model_optim: optimizer for the ensemble neural network model
    :lr_scheduler: learning rate scheduler
    :save_best_fn: callback function to save the model
    :param pred_residual: whether to predict residual or not (default: True)
        pred = obs_next - obs
    """

    def __init__(
        self,
        model: Optional[torch.nn.Module],
        model_optim: Optional[torch.optim.Optimizer],
        lr_scheduler: Optional[Union[torch.optim.lr_scheduler.LambdaLR]] = None,
        save_best_fn: Optional[callable] = None,
        pred_residual: bool = True,
        **kwargs: Any,
    ) -> None:
        nn.Module.__init__(self)
        self.model = model
        self.optimizer = model_optim
        self.lr_scheduler = lr_scheduler
        self.save_best_fn = save_best_fn
        self.pred_residual = pred_residual

        # create a buffer to store the dummy offline data
        self.train_buffer = self._create_buffer()

    @staticmethod
    def _create_buffer():
        data = Batch()
        buffer = Buffer(int(1e5))
        time = [0.0, 5]
        temp_zone_initials = [25, 35]
        temp_ins = [20, 25]
        mass_flows = [20, 200]
        heat_loads = [100, 1250]
        t = np.linspace(time[0], time[1], 10)
        temp_zone_initials = np.linspace(
            temp_zone_initials[0], temp_zone_initials[1], 10
        )
        temp_ins = np.linspace(temp_ins[0], temp_ins[1], 10)
        mass_flows = np.linspace(mass_flows[0], mass_flows[1], 20)
        heat_loads = np.linspace(heat_loads[0], heat_loads[1], 20)
        for temp_zone in temp_zone_initials:
            for heat_load in heat_loads:
                for mass_flow in mass_flows:
                    for temp_in in temp_ins:
                        for time_ in t:
                            data.update(
                                supply_air_temperature=np.asarray([temp_in]).reshape(
                                    1, -1
                                ),
                                supply_air_mass_flow_rate=np.asarray(
                                    [mass_flow]
                                ).reshape(1, -1),
                                zone_air_temperature=np.asarray([temp_zone]).reshape(
                                    1, -1
                                ),
                                sensible_heat_load=np.asarray([heat_load]).reshape(
                                    1, -1
                                ),
                                chilled_water_supply_temperature=np.asarray(
                                    [0]
                                ).reshape(1, -1),
                                chilled_water_supply_mass_flow_rate=np.asarray(
                                    [0]
                                ).reshape(1, -1),
                                times=np.asarray([time_]).reshape(1, -1),
                            )
                            buffer.add(data)
        return buffer

    @staticmethod
    def df(
        output: torch.Tensor,
        variable: torch.Tensor,
        order: int = 1,
    ) -> torch.Tensor:
        """Compute neural network derivative with respect to input features"""
        df_value = torch.zeros(output.shape, device=output.device)
        for _ in range(order):
            df_value = torch.autograd.grad(
                output,
                variable,
                grad_outputs=torch.ones_like(variable),
                create_graph=True,
                retain_graph=True,
            )[0]

        return df_value

    @abstractmethod
    def _compute_loss(self, batch: Batch, **kwargs) -> torch.Tensor:
        """Compute the loss value"""

    @abstractmethod
    def forward(
        self,
        **kwargs,
    ) -> torch.Tensor:
        """
        Compute next observation over the given batch of
        current observation and action.
        """

    def _postprocess_pred(
        self,
        output: torch.Tensor,
        obs: torch.Tensor,
        target_obs: torch.Tensor = None,
    ) -> torch.Tensor:
        # check if target_obs is given, can be a subset of observation
        if target_obs is not None:
            size = target_obs.shape[0]
            target_obs = torch.as_tensor(target_obs, dtype=torch.float32).reshape(
                size, -1
            )
            assert len(output) == len(target_obs)
        else:
            target_obs = obs
        # predict the difference between the current observation and the next observation
        if self.pred_residual:
            size = output.shape[0]
            output += target_obs.reshape(size, -1)
        return output

    def learn(
        self,
        train_buffer: Buffer = None,
        test_buffer: Optional[Buffer] = None,
        batch_size: int = 1024,
        epoch: int = 200,
        verbose: bool = True,
        log_per_epoch: int = 10,
        test_per_epoch: int = 10,
    ) -> None:
        """Train the dynamics model with gradient descent"""
        if train_buffer is None:
            train_buffer = self.train_buffer
        train_size = len(train_buffer)
        best_test_loss = float("inf")
        if verbose:
            logger.info(
                f"Start training the {__class__.__name__}-based dynamics model ..."
            )
        for e in range(epoch):
            step, total_train_loss, total_test_loss = 0.0, 0.0, 0.0
            self.model.train()
            for i in range(0, train_size, batch_size):
                self.optimizer.zero_grad()
                train_batch, _ = train_buffer.sample(batch_size)
                train_loss = self._compute_loss(train_batch)
                train_loss.backward()
                self.optimizer.step()
                total_train_loss += train_loss.cpu().detach().numpy()
                step += 1

            if verbose and e % log_per_epoch == 0:
                logger.info(
                    "\nTrain Epoch {}/{}:\nAverage Train Loss: {}".format(
                        e + 1, epoch, total_train_loss / step
                    )
                )

            if test_buffer is not None and e % test_per_epoch == 0:
                step = 0
                test_size = len(test_buffer)
                self.model.eval()
                for i in range(0, test_size, batch_size):
                    test_batch, indices = test_buffer.sample(batch_size)
                    test_loss = self._compute_loss(test_batch)
                    total_test_loss += test_loss.cpu().detach().numpy()
                    step += 1
                if verbose and e % log_per_epoch == 0:
                    logger.info(
                        "\nTest Epoch {}/{}:\nAverage Val Loss: {}".format(
                            e + 1, epoch, total_test_loss / step
                        )
                    )
                if total_test_loss < best_test_loss and self.save_best_fn is not None:
                    self.save_best_fn(self)
                    best_test_loss = total_test_loss

            else:
                if self.save_best_fn is not None:
                    self.save_best_fn(self)
