"""
Nodal thermodynamic models for data hall without spatial resolution.

e.g., dT/dt = f(T, Q, U, P, ...)
"""

from .base import BaseNNDynamics
from .pinn import PINNDynamics
from .ode import DifferentiableODE
from .steady_state import SteadyStateThermodynamics


__all__ = ["DifferentiableODE", "PINNDynamics", "SteadyStateThermodynamics"]
