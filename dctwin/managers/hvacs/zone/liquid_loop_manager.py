from typing import Dict, Optional, Any
from dclib import Room
import torch.nn as nn
import torch

from dctwin.data import Batch
from dctwin.models.cooling.thermodyns.nodal.liquid_flow_network import FlowNetwork


class LiquidLoopManager(nn.Module):
    """
    Implement the liquid cooling manager to simulate the thermal properties and the electrical power consumption
    of a hybrid cooling system with the direct-to-chip cooling system and conventional force ventilation air cooling
    system.
    """
    def __init__(
        self,
        zones: Dict[str, Room],
        device_key_mapping: Optional[Dict] = None
    ) -> None:
        super().__init__()
        self.zones = zones
        self.device_key_mapping = device_key_mapping
        self.models = self._init_models()

    def _init_models(self) -> Dict[str, Any]:
        """
        Initialize the learnable models for the liquid loop equipments,
        including the CDUs and liquid network
        """
        for zone_name, zone in self.zones.items():
            if zone.constructions.liquid_flow_networks is not None:
                for liquid_flow_loop_name, liquid_flow_loop in zone.constructions.liquid_flow_networks.items():
                    self.add_module(
                        name=liquid_flow_loop_name,
                        module=FlowNetwork(
                            liquid_flow_loop=liquid_flow_loop,
                            key_mapping=self.device_key_mapping,
                            learnable=True
                        )
                    )
        return {k: v for k, v in dict(self.named_modules()).items() if k != "" and "." not in k}

    def learn(self) -> None:
        """
        Learn device models from the collected data
        :return:
        """
        # learn the zone equipment models
        for model_name, model in self.models.items():
            model.learn()

    def collect(self, data: Batch | Dict) -> None:
        """
        Collect the data from outside environment and store them into a buffer for learning purposes
        :return:
        """
        for model_name, model in self.models.items():
            model.collect(data)

    def forward(
        self,
        data: Batch
    ) -> None:
        for zone_name, zone in self.zones.items():
            if zone.constructions.liquid_flow_networks is None:
                continue
            for liquid_flow_networks_name, liquid_flow_network in zone.constructions.liquid_flow_networks.items():
                self.models[liquid_flow_networks_name].forward(
                    data=data,
                    zone_name=zone_name
                )
