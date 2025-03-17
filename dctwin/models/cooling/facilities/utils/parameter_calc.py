import torch


def nusseltCoefficient(Re):
    coef = torch.zeros(Re.shape)
    expo = torch.zeros(Re.shape)
    coef[Re < 1e3] = 64
    expo[Re < 1e3] = 1
    coef[(1e3 <= Re) & (Re <= 2e5)] = 0.27
    expo[(1e3 <= Re) & (Re <= 2e5)] = 0.63
    coef[(2e5 < Re) & (Re <= 2e6)] = 0.021
    expo[(2e5 < Re) & (Re <= 2e6)] = 0.84
    return coef, expo


def firctionFactor(
    rr: torch.Tensor,
    Re: torch.Tensor
):
    """
    Calculate the friction factor of internal fluid
    :param rr: relative roughness
    :param Re: reynolds number
    :return:
    """
    a = 1 / (1 + (Re / 2720) ** 9)
    b = 1 / (1 + (rr * Re / 160) ** 2)
    c = (Re / 64) ** a
    d = (1.8 * torch.log10(Re / 6.8)) ** (2 * (1 - a) * b)
    e = (2 * torch.log10(3.7 / rr)) ** (2 * (1 - a) * (1 - b))
    fr = 1 / (c * d * e)
    return fr


def NTUHE(
    C_inside: torch.Tensor,
    C_outside: torch.Tensor,
    U_total: torch.Tensor,
    A_HE: torch.Tensor
):
    """
    Calculate the NTU and effectiveness of a cross-flow heat exchanger
    :param C_inside: specific heat capacity of inside fluid
    :param C_outside: specific heat capacity of outside fluid
    :param U_total: heat transfer coefficient
    :param A_HE: heat transfer area
    :return:
    """
    CC = torch.zeros(C_inside.shape)
    eff = torch.zeros(C_inside.shape)
    NTU = torch.zeros(C_inside.shape)
    for idx, (C_in, C_out) in enumerate(zip(C_inside, C_outside)):
        if C_in < C_out:
            Cr = C_in / C_out
            C_min = C_in
            NTU = U_total[idx] * A_HE / C_min
            CC[idx] = torch.exp(-Cr * (1 - torch.exp(-NTU)))
            eff[idx] = (1 - CC[idx]) / Cr
        else:
            Cr = C_out / C_in
            C_min = C_out
            NTU = U_total[idx] * A_HE / C_min
            CC[idx] = 1 - torch.exp(-Cr * NTU)
            eff[idx] = 1 - torch.exp(-CC[idx] / Cr)
    return eff, NTU


def nusseltNumberIn(
    rr: torch.Tensor,
    Re: torch.Tensor,
    PrandtlNumber: torch.Tensor
):
    """
    calculate the Nusselt number and friction factor of internal fluid
    :param rr: relative roughness
    :param Re: Reynolds number
    :param PrandtlNumber: Prandtl number
    :return:
    """
    Pr = PrandtlNumber
    fr = firctionFactor(rr, Re)
    nu = (fr / 8) * (Re - 1000) * Pr / (1 + 12.7 * (fr / 8) ** 0.5 * (Pr ** (2 / 3) - 1))
    nu[Re <= 2300] = 4.01
    return fr, nu


def reynolds_number(
    fluid_velocity,
    pipe_diameter,
    fluid_density,
    fluid_viscosity
):
    return fluid_velocity * pipe_diameter * fluid_density / fluid_viscosity


def nusselt_number(reynold_number):
    if reynold_number < 1e3:
        coefficient = 64
        expo = 1
    elif 1e3 <= reynold_number <= 2e5:
        coefficient = 0.27
        expo = 0.63
    elif 2e5 < reynold_number <= 2e6:
        coefficient = 0.021
        expo = 0.84
    else:
        raise ValueError(f"Reynolds number is too large: {reynold_number}")
    return coefficient, expo


def friction_factor(relative_roughness: torch.Tensor, reynold_number: torch.Tensor):
    """
    Calculate the friction factor of internal fluid.
    :param relative_roughness: relative roughness
    :param reynold_number: reynolds number
    """
    a = 1 / (1 + (reynold_number / 2720) ** 9)
    b = 1 / (1 + (relative_roughness * reynold_number / 160) ** 2)
    c = (reynold_number / 64) ** a
    d = (1.8 * torch.log10(reynold_number / 6.8)) ** (2 * (1 - a) * b)
    e = (2 * torch.log10(3.7 / relative_roughness)) ** (2 * (1 - a) * (1 - b))
    fr = 1 / (c * d * e)
    return fr
