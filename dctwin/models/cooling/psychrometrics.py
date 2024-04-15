import math


def psy_psat_fn_temp(tdb: float) -> float:
    """Return the saturation pressure of water vapor at a given temperature.

    Args:
        tdb (float): Dry bulb temperature of the air in degrees Celsius.

    Returns:
        float: Saturation pressure of water vapor in kPa.
    """
    tdb_kelvin = tdb + 273.15
    psat = math.exp(
        -5.8002206e3 / tdb_kelvin +
        3.3914993 +
        -7.8640239e-2 * tdb_kelvin +
        3.1764768e-5 * (tdb_kelvin ** 2) -
        1.4452093e-8 * (tdb_kelvin ** 3) +
        6.5459673 * math.log(tdb_kelvin)
    )  # in Pa valid for 0 to 200C
    psat = psat / 1000  # in kPa
    return psat


def psy_rhov_fn_tdb_rh(tdb: float, relative_humidity: float) -> float:
    """
    tdb - dry-bulb temperature in Celsius
    relative_humidity - relative humidity value (0.0-1.0)
    """
    rv = 461.52  # Universal gas constant for water vapor in J/(kg K)

    # Calculate saturation vapor pressure using the earlier provided function
    psat = psy_psat_fn_temp(tdb)

    # Calculate density of water vapor using ideal gas law
    rhov = (psat * relative_humidity) / (rv * (tdb + 273.15))

    return rhov
