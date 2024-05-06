"""
The Adapters are interfaces between any two models or simulation backends, such as EnergyPlus and CFD.
They are used to transfer data in the backend.
"""


from .eplus_cfd_adapter import EplusCFDAdapter
from .eplus_liquid_adapter import EplusLiquidAdapter

__all__ = [
    "EplusCFDAdapter",
    "EplusLiquidAdapter",
]
