from typing import Tuple

import torch
import torch.nn as nn
from CoolProp.CoolProp import PropsSI
from loguru import logger

from dclib.cooling.plant.facilities import CoolingTower
from dctwin.data import Batch, Buffer
from dctwin.models.utils import solve_root, CubicCurve


class VariableSpeedCoolingTowerModel(nn.Module):
    """
    Variable speed cooling tower model that always operates at the maximum capacity.
    """
    def __init__(
        self,
        config: CoolingTower,
        key_mapping: dict,
        learnable: bool = True,
        max_root_finding_iter: int = 1000,
        tol: float = 1e-3,
    ) -> None:
        super(VariableSpeedCoolingTowerModel, self).__init__()
        self.config = config
        self.uid = config.uid
        self.learnable = learnable
        self.buffer = Buffer(size=100)
        self.key_mapping = key_mapping
        self.single_setpoint = True
        self.max_root_finding_iter = max_root_finding_iter
        self.tol = tol
        # YorkCalc coefficients and suitable ranges for the empirical model
        self.min_inlet_air_wb_temp = torch.tensor(-34.4, dtype=torch.float32)
        self.max_inlet_air_wb_temp = torch.tensor(29.4444, dtype=torch.float32)
        self.min_range_temp = torch.tensor(1.1111, dtype=torch.float32)
        self.max_range_temp = torch.tensor(22.2222, dtype=torch.float32)
        self.min_approach_temp = torch.tensor(1.1111, dtype=torch.float32)
        self.max_approach_temp = torch.tensor(40.0, dtype=torch.float32)
        # Coefficients for the YorkCalc empirical model
        self.yor_calc_coe = torch.tensor([
            -0.359741205, -0.055053608, 0.0023850432, 0.173926877, -0.0248473764, 0.00048430224, -0.005589849456,
            0.0005770079712, -0.00001342427256, 2.84765801111111, -0.121765149, 0.0014599242, 1.680428651, -0.0166920786,
            -0.0007190532, -0.025485194448, 0.0000487491696, 0.00002719234152, -0.0653766255555556, -0.002278167, 0.0002500254,
            -0.0910565458, 0.00318176316, 0.000038621772, -0.0034285382352, 0.00000856589904, -0.000001516821552,
        ], dtype=torch.float32)

        self.fan_power_f_air_flow_curve = True
        self.fan_power_of_air_flow_curve = CubicCurve(
            init_params=torch.tensor(
                config.power.fan_power_ratio_function_of_air_flow_rate_ratio_curve,
                dtype=torch.float32,
            ),
            requires_grad=learnable,
        )

        self._calibrate_flow()

    def _calibrate_flow(self) -> None:
        """
        Calibrate variable speed tower model based on user input
        by finding calibration water flow rate ratio that
        yields an approach temperature that matches user input.
        """
        # Check range for water flow rate ratio (ensure RegulaFalsi converges)
        max_water_flow_rate_ratio = torch.tensor(0.5, dtype=torch.float32)  # maximum water flow rate ratio which yields desired approach temp
        t_approach = torch.tensor(0.0, dtype=torch.float32)  # temporary tower approach temp variable [C]
        flow_rate_ratio_step = (
            self.config.cooling.cell_maximum_water_flow_rate_fraction -
            self.config.cooling.cell_minimum_water_flow_rate_fraction
        ) / 10
        model_calibrated = True
        model_water_flow_ratio_max = self.config.cooling.cell_maximum_water_flow_rate_fraction * 4  # maximum water flow rate ratio used for model calibration
        # Find a flow rate large enough to provide an approach temperature > than the user-defined approach
        water_flow_rate_ratio = torch.tensor(0.0, dtype=torch.float32)
        while (
            t_approach < self.config.cooling.design_approach_temperature
            and
            max_water_flow_rate_ratio <= model_water_flow_ratio_max
        ):
            water_flow_rate_ratio = max_water_flow_rate_ratio
            t_approach = self._calc_approach_temp(
                water_flow_rate_ratio,
                torch.tensor(1.01, dtype=torch.float32),
                torch.tensor(self.config.cooling.design_inlet_air_wet_bulb_temperature, dtype=torch.float32),
                torch.tensor(self.config.cooling.design_range_temperature, dtype=torch.float32),
            )
            if t_approach < self.config.cooling.design_approach_temperature:
                max_water_flow_rate_ratio += flow_rate_ratio_step

            # If no suitable water flow rate ratio exists to meet user-defined approach temperature
            if (
                (max_water_flow_rate_ratio == torch.tensor(0.5, dtype=torch.float32)
                 and
                 t_approach < self.config.cooling.design_approach_temperature
                )
                or (max_water_flow_rate_ratio >= model_water_flow_ratio_max)
            ):
                model_calibrated = False
                break

        water_flow_ratio = torch.tensor(0.0, dtype=torch.float32)  # Tower water flow rate ratio found during model calibration

        if model_calibrated:
            def f_calib(flow_ratio):
                t_act = self._calc_approach_temp(
                    flow_ratio,
                    torch.tensor(1.01, dtype=torch.float32),
                    torch.tensor(self.config.cooling.design_inlet_air_wet_bulb_temperature, dtype=torch.float32),
                    torch.tensor(self.config.cooling.design_range_temperature, dtype=torch.float32),
                )
                return self.config.cooling.design_approach_temperature - t_act

            flag, water_flow_ratio = solve_root(
                self.tol, self.max_root_finding_iter, 1, water_flow_ratio, f_calib,
                0.5, max_water_flow_rate_ratio
            )

            if flag == -1:
                logger.error(
                    "Iteration limit exceeded in calculating tower water flow ratio during calibration"
                )
                logger.error(
                    "Inlet air wet-bulb, range, and/or approach temperature does not allow calibration of "
                    "water flow rate ratio for this variable-speed cooling tower"
                )
                logger.error("Cooling tower calibration failed for the tower")
            elif flag == -2:
                logger.error(
                    "Bad starting values for cooling tower water flow rate ratio calibration"
                )
                logger.error(
                    "Inlet air wet-bulb, range, and/or approach temperature does not allow calibration of "
                    "water flow rate ratio for this variable-speed cooling tower"
                )
                logger.error("Cooling tower calibration failed for the tower")
        else:
            logger.error("Bad starting values for cooling tower water flow rate ratio calibration")
            logger.error(
                "Design inlet air wet-bulb or range temperature must be modified to achieve the design approach"
            )
            logger.error(
                f"A water flow rate ratio of {water_flow_rate_ratio.item()} was calculated to yield an approach "
                f"temperature of {t_approach.item()}"
            )
            logger.error("Cooling tower calibration failed for tower")

        self.calibrated_water_flow_rate = self.config.cooling.design_water_flow_rate / water_flow_ratio

        if (
            water_flow_ratio < self.config.cooling.cell_minimum_water_flow_rate_fraction
            or
            water_flow_ratio > self.config.cooling.cell_maximum_water_flow_rate_fraction
        ):
            logger.warning(
                f"CoolingTower:VariableSpeed, the calibrated water flow rate ratio is determined to be "
                f"{water_flow_ratio.item():.5}. "
                f"This is outside the valid range of "
                f"{self.config.cooling.cell_minimum_water_flow_rate_fraction:.5} to "
                f"{self.config.cooling.cell_maximum_water_flow_rate_fraction:.5}"
            )

        rho = self.get_fluid_property(
            fluid_name="water",
            temperature=self.config.cooling.design_inlet_air_wet_bulb_temperature +
                        self.config.cooling.design_approach_temperature +
                        self.config.cooling.design_range_temperature,
            property_type="density"
        )

        cp = self.get_fluid_property(
            fluid_name="water",
            temperature=self.config.cooling.design_inlet_air_wet_bulb_temperature +
                        self.config.cooling.design_approach_temperature +
                        self.config.cooling.design_range_temperature,
            property_type="specific_heat"
        )

        self.tower_nominal_capacity = (
            (rho * self.config.cooling.design_water_flow_rate) * cp * self.config.cooling.design_range_temperature
        )
        logger.info(
            f"Tower Nominal Capacity: {self.tower_nominal_capacity:.5} [W]"
        )

        self.free_conv_air_flow_rate = self.config.cooling.minimum_air_flow_rate_ratio * self.config.cooling.design_air_flow_rate
        logger.info(
            f"Air Flow Rate in free convection "
            f"regime {self.free_conv_air_flow_rate:.5f} [m3/s]."
        )

        self.tower_free_conv_nom_cap = (
            self.tower_nominal_capacity *
            self.config.cooling.fraction_of_tower_capacity_in_free_convection_regime
        )
        logger.info(
            f"Tower capacity in free convection regime at "
            f"design conditions {self.tower_free_conv_nom_cap:.5f} [W]"
        )

    def _calc_approach_temp(
        self,
        m_water_flow_ratio: torch.Tensor,  # Water flow ratio of cooling tower
        m_air_flow_ratio: torch.Tensor,  # Air flow ratio of cooling tower
        outside_air_wet_bulb_temp: torch.Tensor,  # Inlet air wet-bulb temperature [C]
        t_range: torch.Tensor, # Cooling tower range (outlet water temp minus inlet air wet-bulb temp) [C]
    ) -> torch.Tensor:
        """ Calculate tower approach temperature (e.g. outlet water temp minus inlet air wet-bulb temp)
        given air flow ratio, water flow ratio, inlet air wet-bulb temp, and tower range.

        METHODOLOGY EMPLOYED:
            Calculation method used empirical models from CoolTools or York to determine performance
            of variable speed (variable air flow rate) cooling towers.
        """
        flow_factor = m_water_flow_ratio / m_air_flow_ratio

        t_approach = (
            self.yor_calc_coe[0] + self.yor_calc_coe[1] * outside_air_wet_bulb_temp +
            self.yor_calc_coe[2] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp +
            self.yor_calc_coe[3] * t_range + self.yor_calc_coe[4] * outside_air_wet_bulb_temp * t_range +
            self.yor_calc_coe[5] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * t_range +
            self.yor_calc_coe[6] * t_range * t_range + self.yor_calc_coe[7] * outside_air_wet_bulb_temp * t_range * t_range +
            self.yor_calc_coe[8] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * t_range * t_range +
            self.yor_calc_coe[9] * flow_factor + self.yor_calc_coe[10] * outside_air_wet_bulb_temp * flow_factor +
            self.yor_calc_coe[11] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * flow_factor +
            self.yor_calc_coe[12] * t_range * flow_factor + self.yor_calc_coe[13] * outside_air_wet_bulb_temp * t_range * flow_factor +
            self.yor_calc_coe[14] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * t_range * flow_factor +
            self.yor_calc_coe[15] * t_range * t_range * flow_factor +
            self.yor_calc_coe[16] * outside_air_wet_bulb_temp * t_range * t_range * flow_factor +
            self.yor_calc_coe[17] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * t_range * t_range * flow_factor +
            self.yor_calc_coe[18] * flow_factor * flow_factor +
            self.yor_calc_coe[19] * outside_air_wet_bulb_temp * flow_factor * flow_factor +
            self.yor_calc_coe[20] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * flow_factor * flow_factor +
            self.yor_calc_coe[21] * t_range * flow_factor * flow_factor +
            self.yor_calc_coe[22] * outside_air_wet_bulb_temp * t_range * flow_factor * flow_factor +
            self.yor_calc_coe[23] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * t_range * flow_factor * flow_factor +
            self.yor_calc_coe[24] * t_range * t_range * flow_factor * flow_factor +
            self.yor_calc_coe[25] * outside_air_wet_bulb_temp * t_range * t_range * flow_factor * flow_factor +
            self.yor_calc_coe[26] * outside_air_wet_bulb_temp * outside_air_wet_bulb_temp * t_range * t_range * flow_factor * flow_factor
        )

        return t_approach

    def collect(self, data: dict) -> None:
        self.buffer.add(
            Batch(
                cooling_tower_return_water_temperature=data[self.key_mapping["return water temperature"]],
                cooling_tower_water_mass_flow_rate=data[self.key_mapping["water mass flow rate"]],
                cooling_tower_supply_water_temperature=data[self.key_mapping["supply water temperature"]],
                outside_air_wetbulb_temperature=data[self.key_mapping["outside air wetbulb temperature"]],
                cooling_tower_air_flow_rate_ratio=data[self.key_mapping["air flow rate ratio"]],
                cooling_tower_fan_power=data[self.key_mapping["power"]],
            )
        )

    def learn(self) -> None:
        if self.learnable:
            raise NotImplementedError("Learnable cooling tower model is not implemented yet !")
        else:
            pass

    @staticmethod
    def get_fluid_property(
        fluid_name: str,
        temperature: float | torch.Tensor,
        property_type: str,
    ) -> float:
        try:
            # Convert temperature to Kelvin
            temperature_k = temperature + 273.15  # Assuming input temperature is in Celsius
            # Define property mapping
            property_map = {
                'density': 'D',
                'specific_heat': 'C'
            }
            # Check if the property type is valid
            if property_type not in property_map:
                raise ValueError(f"Invalid property type: {property_type}")
            # Get the property
            prop = PropsSI(
                property_map[property_type],
                'T',
                temperature_k,
                'P',
                101325,
                fluid_name
            )
            return prop
        except ValueError as e:
            logger.error(f"Error: {e:.2f}")

    def forward(
        self,
        m_air_flow_rate_ratio: torch.Tensor,
        m_water_flow_rate_ratio: torch.Tensor,
        outside_air_wet_bulb_temp: torch.Tensor,
        cw_return_water_temp: torch.Tensor,
    ) -> torch.Tensor:
        """
        PURPOSE OF THIS Method:
            To calculate the leaving water temperature of the variable speed cooling tower.

        METHODOLOGY EMPLOYED:
            The range temperature is varied to determine balance point where model output (Tapproach),
            range temperature and inlet air wet-bulb temperature show a balance as:
            outside_air_wet_bulb_temp + Tapproach + Trange = Node(WaterInletNode)%Temp
        """
        # determine tower outlet water temperature
        t_range = None  # range temperature which results in an energy balance

        def f(t_range):
            t_approach = self._calc_approach_temp(
                m_water_flow_rate_ratio,
                m_air_flow_rate_ratio,
                outside_air_wet_bulb_temp,
                t_range
            )
            # Calculate the residual based on the balance equation
            return (outside_air_wet_bulb_temp + t_approach + t_range) - cw_return_water_temp

        flag = 0
        flag, t_range = solve_root(
            self.tol, self.max_root_finding_iter, flag, t_range, f, 0.001, self.max_range_temp
        )
        outlet_water_temp = cw_return_water_temp - t_range

        if flag == -1:
            logger.error(
                "Iteration limit exceeded in calculating tower nominal capacity at minimum air flow ratio. "
                "Design inlet air wet-bulb or approach temperature must be modified to achieve an acceptable "
                "range at the minimum air flow rate. Cooling tower simulation failed to converge for tower."
            )
        # if flag = -2, Tr is returned as minimum value (0.001) and outlet temp = inlet temp - 0.001
        elif flag == -2:  # decide if should run at max flow
            # Determine temperature setpoint based on the calculation scheme
            if self.single_setpoint:
                Temp_SetPoint = 30  # local temporary for loop set point
            else:
                raise Exception("Unknown LoopDemandCalcScheme")  # Raise an error if scheme is unknown

            # Check if the system should operate at maximum cooling tower flow
            if cw_return_water_temp > (Temp_SetPoint + self.max_range_temp):
                # Run the tower at full capacity (flat out)
                outlet_water_temp = cw_return_water_temp - self.max_range_temp

        return outlet_water_temp  # Return the calculated outlet water temperature

    def solve(
        self,
        water_mass_flow_rate: torch.Tensor,
        cw_return_water_temp: torch.Tensor,
        outside_air_wet_bulb_temp: torch.Tensor,
        cw_supply_temp_setpoint: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        PURPOSE OF THIS SUBROUTINE:
            To simulate the operation of a variable-speed fan cooling tower.

        METHODOLOGY EMPLOYED:
        For each simulation time step, a desired range temperature (T_water,inlet-T_water,setpoint) and desired approach
        temperature (T_water,setpoint-Tair,WB) is calculated which meets the outlet water temperature setpoint. This
        desired range and approach temperature also provides a balance point for the empirical model where:
        air,WB + T_water,range + T_approach = Node(WaterInletNode)%Temp
        """
        init_conv_temp = torch.tensor(5.05, dtype=torch.float32)
        rho_water = torch.tensor(
            self.get_fluid_property(
                fluid_name="water",
                temperature=init_conv_temp,
                property_type="density"
            ),
            dtype=torch.float32
        )

        des_water_mass_flow_rate = self.config.cooling.design_water_flow_rate * rho_water

        if des_water_mass_flow_rate > 0.0:
            water_mass_flow_rate_per_cell_min = (
                des_water_mass_flow_rate * self.config.cooling.cell_minimum_water_flow_rate_fraction / self.config.cooling.number_of_cells
            )
            water_mass_flow_rate_per_cell_max = (
                des_water_mass_flow_rate * self.config.cooling.cell_maximum_water_flow_rate_fraction / self.config.cooling.number_of_cells
            )
            num_cell_min = torch.minimum(
                (water_mass_flow_rate / water_mass_flow_rate_per_cell_max + 0.999).int(),
                torch.tensor(self.config.cooling.number_of_cells, dtype=torch.int32)
            )
            num_cell_max = torch.minimum(
                (water_mass_flow_rate / water_mass_flow_rate_per_cell_min + 0.999).int(),
                torch.tensor(self.config.cooling.number_of_cells, dtype=torch.int32)
            )
        else:
            water_mass_flow_rate_per_cell_min = torch.tensor(0.0, dtype=torch.float32)
            num_cell_min = torch.tensor(0, dtype=torch.int32)
            num_cell_max = torch.tensor(0, dtype=torch.int32)

        if num_cell_min <= 0:
            num_cell_min = torch.tensor(1, dtype=torch.int32)
        if num_cell_max <= 0:
            num_cell_max = torch.tensor(1, dtype=torch.int32)

        if self.config.cooling.cell_control == "MinimalCell":
            num_cell_on = num_cell_min
        else:
            num_cell_on = num_cell_max

        water_mass_flow_rate_per_cell = water_mass_flow_rate / num_cell_on
        # Calculate the range and approach temperatures
        t_range = cw_return_water_temp - cw_supply_temp_setpoint
        t_approach = cw_supply_temp_setpoint - outside_air_wet_bulb_temp
        # loop to increment num_cell if we cannot meet the set point with the actual number of cells calculated above
        incr_num_cell_flag = torch.tensor(True, dtype=torch.bool)
        water_flow_rate_ratio_capped = torch.tensor(0.0, dtype=torch.float32)  # Water flow rate ratio passed to VS tower model

        outlet_water_temp_on = torch.tensor(0.0, dtype=torch.float32)
        free_convection_cap_frac = torch.tensor(0.0, dtype=torch.float32)
        outside_air_wet_bulb_temp_capped = outside_air_wet_bulb_temp
        outlet_water_temp = cw_return_water_temp
        fan_power = torch.tensor(0.0, dtype=torch.float32)

        while incr_num_cell_flag:
            incr_num_cell_flag = torch.tensor(False, dtype=torch.bool)
            rho_water = torch.tensor(
                self.get_fluid_property(
                    fluid_name="water",
                    temperature=cw_return_water_temp,
                    property_type="density"
                ),
                dtype=torch.float32
            )
            water_flow_rate_ratio = water_mass_flow_rate_per_cell / (
                rho_water * self.calibrated_water_flow_rate / self.config.cooling.number_of_cells
            )

            # check independent inputs with respect to model boundaries
            outside_air_wet_bulb_temp_capped = torch.clip(
                outside_air_wet_bulb_temp,
                self.min_inlet_air_wb_temp,
                self.max_inlet_air_wb_temp
            )
            water_flow_rate_ratio_capped = torch.clip(
                water_flow_rate_ratio,
                self.config.cooling.cell_minimum_water_flow_rate_fraction,
                self.config.cooling.cell_maximum_water_flow_rate_fraction
            )
            # Determine free convection capacity
            air_flow_rate_ratio = torch.tensor(1.0, dtype=torch.float32)
            outlet_water_temp_off = cw_return_water_temp
            outlet_water_temp = outlet_water_temp_off
            free_convection_cap_frac = self.config.cooling.fraction_of_tower_capacity_in_free_convection_regime
            outlet_water_temp_on = self.forward(
                air_flow_rate_ratio,
                water_flow_rate_ratio_capped,
                outside_air_wet_bulb_temp_capped,
                cw_return_water_temp,
            )
            if outlet_water_temp_on > cw_supply_temp_setpoint:
                fan_power = self.config.power.design_fan_power * num_cell_on / self.config.cooling.number_of_cells
                outlet_water_temp = outlet_water_temp_on
                if (
                    num_cell_on < self.config.cooling.number_of_cells
                    and
                    water_mass_flow_rate / (num_cell_on + 1) > water_mass_flow_rate_per_cell_min
                ):
                    num_cell_on += 1
                    water_mass_flow_rate_per_cell = water_mass_flow_rate / num_cell_on
                    incr_num_cell_flag = torch.tensor(True, dtype=torch.bool)

        # find the correct air ratio only if full flow is too much
        if outlet_water_temp_on < cw_supply_temp_setpoint:
            # outlet water temperature is calculated in the free convection regime
            outlet_water_temp_off = cw_return_water_temp - free_convection_cap_frac * (
                    cw_return_water_temp - outlet_water_temp_on)

            fan_power = torch.tensor(0.0, dtype=torch.float32)
            outlet_water_temp = outlet_water_temp_off

            if outlet_water_temp_off > cw_supply_temp_setpoint:
                # Set point was not met, turn on cooling tower fan at minimum fan speed
                air_flow_rate_ratio = torch.tensor(self.config.cooling.minimum_air_flow_rate_ratio, dtype=torch.float32)

                # Outlet water temperature with fan at minimum speed (C)
                outlet_water_temp_min = self.forward(
                    air_flow_rate_ratio,
                    water_flow_rate_ratio_capped,
                    outside_air_wet_bulb_temp_capped,
                    cw_return_water_temp
                )
                if outlet_water_temp_min < cw_supply_temp_setpoint:
                    # if set point was exceeded, cycle the fan at minimum air flow to meet the set point temperature
                    if self.fan_power_f_air_flow_curve == 0:
                        fan_power = (
                            air_flow_rate_ratio ** 3 * self.config.power.design_fan_power * num_cell_on /
                            self.number_of_cells
                        )
                    else:
                        fan_curve_value = self.fan_power_of_air_flow_curve(air_flow_rate_ratio)
                        fan_power = torch.maximum(
                            torch.tensor(
                                0.0,
                                dtype=torch.float32),
                                (self.config.power.design_fan_power * fan_curve_value)
                        ) * num_cell_on / self.config.cooling.number_of_cells

                    fan_cycling_ratio = (
                        (outlet_water_temp_off - cw_supply_temp_setpoint) /
                        (outlet_water_temp_off - outlet_water_temp_min)
                    )
                    fan_power *= fan_cycling_ratio
                    outlet_water_temp = cw_supply_temp_setpoint
                else:
                    # if the set point was not met at minimum fan speed, set fan speed to maximum
                    air_flow_rate_ratio = torch.tensor(1.0, dtype=torch.float32)

                    def f(flow_ratio):
                        t_approach_actual = self._calc_approach_temp(
                            water_flow_rate_ratio_capped,
                            flow_ratio,
                            outside_air_wet_bulb_temp_capped,
                            t_range
                        )
                        return t_approach - t_approach_actual

                    flag = torch.tensor(0, dtype=torch.int32)
                    flag, air_flow_rate_ratio = solve_root(
                        self.tol, self.max_root_finding_iter, flag, air_flow_rate_ratio, f,
                        self.minimum_air_flow_rate_ratio, torch.tensor(1.0)
                    )

                    if flag == -1:
                        logger.error(
                            "Cooling tower iteration limit exceeded when calculating air flow rate ratio for tower")
                    elif flag == -2:
                        logger.error("Cooling tower air flow rate ratio calculation failed")

                    if self.fan_power_f_air_flow_curve == 0:
                        fan_power = (
                                air_flow_rate_ratio ** 3 * self.config.power.design_fan_power * num_cell_on /
                                self.number_of_cells
                        )
                    else:
                        fan_curve_value = self.fan_power_of_air_flow_curve(air_flow_rate_ratio)
                        fan_power = torch.maximum(
                            torch.tensor(
                                0.0,
                                dtype=torch.float32),
                                (self.config.power.design_fan_power * fan_curve_value)
                        ) * num_cell_on / self.number_of_cells
                    outlet_water_temp = outside_air_wet_bulb_temp + t_approach

        error = torch.abs(outlet_water_temp - cw_supply_temp_setpoint)
        if error > torch.tensor(0.2, dtype=torch.float32):
            logger.warning(f"The set point temperature cannot be reached. Error: {error:.2f}")

        return fan_power, outlet_water_temp
