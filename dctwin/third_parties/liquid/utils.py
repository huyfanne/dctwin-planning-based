import math


def reynolds_number(fluid_velocity, pipe_diameter, fluid_density, fluid_viscosity):
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


def friction_factor(relative_roughness: float, reynold_number: float):
    """
    Calculate the friction factor of internal fluid.
    :param relative_roughness: relative roughness
    :param reynold_number: reynolds number
    """
    a = 1 / (1 + (reynold_number / 2720) ** 9)
    b = 1 / (1 + (relative_roughness * reynold_number / 160) ** 2)
    c = (reynold_number / 64) ** a
    d = (1.8 * math.log10(reynold_number / 6.8)) ** (2 * (1 - a) * b)
    e = (2 * math.log10(3.7 / relative_roughness)) ** (2 * (1 - a) * (1 - b))
    fr = 1 / (c * d * e)
    return fr

