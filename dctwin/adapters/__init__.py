"""
The Adapters are interfaces between any two models or simulation backends, such as EnergyPlus and CFD.
They are used to transfer data in the backend.
"""


from .eplus_cfd_adapter import EplusCFDAdapter

__all__ = [
    "EplusCFDAdapter",
]
