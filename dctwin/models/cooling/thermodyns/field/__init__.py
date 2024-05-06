"""
Fine-grained field models for data hall with spatial resolution.

e.g.,  \rho_\textup{air}\left(\frac{\partial \mathbf{T}_\textup{z}}{\partial t} + \frac{\partial \mathbf{U}_i \mathbf{T}_\textup{z}}{\partial x_i} \right) = \frac{\partial}{\partial x_i}\left(\Gamma_\textup{eff} \frac{\partial \mathbf{T}_\textup{z}}{\partial x_i}\right) + Q(t),
where $t$ is time, $x_i$ is one of the three-dimensional spatial coordinates,
$\mathbf{U}_i\in \mathbb{R}^{N} $ is the vector of air velocity in different directions with $i$ equals 1, 2 or 3, respectively,
$\rho_\textup{air}$ is the air density;
$\Gamma_\textup{eff}$ is the diffusion coefficient;
$Q$ is the sensible heat load
"""


from .pod import PODDockerBackend, PODK8SBackend, PODBackendMixin

__all__ = [
    "PODDockerBackend",
    "PODK8SBackend",
    "PODBackendMixin",
]
