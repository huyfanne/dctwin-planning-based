from typing import Dict
import math
from loguru import logger
from CoolProp.CoolProp import PropsSI
import numpy as np
from scipy.interpolate import interp1d

from dclib.cooling.room.facilities import Pump, Pipe, CDU
from dclib.ite.racks import Rack

from .utils import reynolds_number
from .hx import HeatExchanger


class LiquidCoolingPipe:
    gravity: float = 9.81

    def __init__(
        self,
        pipe: Pipe,
        sub_pipe_diameter: float = None
    ):
        self.pipe_diameter = pipe.geometry.pipe_diameter
        self.pipe_length = pipe.geometry.pipe_length
        self.channel_type = pipe.geometry.channel_type
        self.turning_radius = pipe.geometry.turning_radius  # for elbow
        self.sub_pipe_diameter = sub_pipe_diameter  # for tee
        self.fluid_density = PropsSI('D', 'P', 101325, 'Q', 0, "water")
        self.fluid_viscosity = PropsSI('V', 'P', 101325, 'Q', 0, "water")
        self.height_difference = pipe.geometry.height_difference
        self.relative_roughness = pipe.geometry.roughness / pipe.geometry.pipe_diameter

    # Reference: https://doi.org/10.1026/(ASCE)0733-9429(2008)134:9(1357)
    def friction_factor(self, fluid_velocity: float | np.ndarray):
        """
        Calculate the dynamical friction factor of the pipe w.r.t. fluid velocity.
        """
        reynold_number = reynolds_number(
            fluid_velocity=fluid_velocity,
            pipe_diameter=self.pipe_diameter,
            fluid_density=self.fluid_density,
            fluid_viscosity=self.fluid_viscosity
        )
        a = 1 / (1 + (reynold_number/2720)**9)
        b = 1 / (1 + (self.relative_roughness * reynold_number / 160) ** 2)
        c = (reynold_number / 64) ** a
        d = (1.8 * math.log10(reynold_number / 6.8)) ** (2 * (1 - a) * b)
        e = (2 * math.log10(3.7 / self.relative_roughness)) ** (2 * (1 - a) * (1 - b))
        fr = 1 / (c * d * e)  # friction factor
        return fr

    # Reference: Code for designing of cooling tower for mechanical ventilation (GB/T 50352)
    def sim(
        self,
        main_pipe_mass_flow_rate: float | np.ndarray,
        sub_pipe_mass_flow_rate: float | np.ndarray = None,
    ):
        """
        Simulate the pressure drop and mechanical power consumption of the pipe w.r.t. mass flow rate.
        """
        fluid_velocity = main_pipe_mass_flow_rate / self.fluid_density / (math.pi * self.pipe_diameter ** 2 / 4)
        if self.channel_type == 'straight':
            friction_factor = self.friction_factor(
                fluid_velocity=fluid_velocity
            )
            friction_coefficient = friction_factor * (self.pipe_length / self.pipe_diameter)
        elif self.channel_type == 'elbow':
            # angle is 90 degree
            x = np.array([0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0])
            y = np.array([1.2, 0.8, 0.6, 0.48, 0.36, 0.3, 0.29])
            interpolation_function = interp1d(x, y, kind='linear')  # linear interpolation
            ratio = np.array([self.turning_radius / self.pipe_diameter])  # R/d
            friction_coefficient = float(interpolation_function(ratio)[0])
        elif self.channel_type == 'tee':
            if sub_pipe_mass_flow_rate is None:
                logger.critical("Sub pipe mass flow rate is required for tee pipe.")
            area_ratio = (self.sub_pipe_diameter / self.pipe_diameter) ** 2
            velocity_ratio = sub_pipe_mass_flow_rate / main_pipe_mass_flow_rate
            if 0 <= area_ratio <= 0.35:
                if velocity_ratio <= 0.4:
                    friction_coefficient = 1.1 - 0.7 * velocity_ratio
                else:
                    friction_coefficient = 0.85
            elif area_ratio > 0.35:
                if velocity_ratio <= 0.6:
                    friction_coefficient = 1 - 0.65 * velocity_ratio
                else:
                    friction_coefficient = 0.6
        # calculate pressure drop and mechanical power
        delta_p = friction_coefficient * (self.fluid_density * fluid_velocity**2) / 2
        friction_power = delta_p * main_pipe_mass_flow_rate / self.fluid_density
        return friction_power


class LiquidCoolingPump:
    def __init__(self, pump: Pump):
        self.motor_efficiency = pump.power.motor_efficiency

    def sim(self, kinetic_power: float | np.ndarray):
        return kinetic_power / self.motor_efficiency


class CoolantDistributionUnit:
    def __init__(
        self,
        cdu: CDU,
        racks: Dict[str, Rack],
        cpu_number_per_server: int = 8,
        num_turning: int = 3
    ):
        # constant properties
        self.liquid_capacity = PropsSI('C', 'P', 101325, 'Q', 0, "water")
        self.cpu_number_per_server = cpu_number_per_server
        self.num_turning = num_turning
        # variable properties
        self.config = cdu
        self.racks = racks
        self.heat_exchanger = HeatExchanger(
            cdu_uid=cdu.uid,
            tube_diameter=cdu.constructions.heat_exchanger.geometry.tube_diameter,
            tube_length=cdu.constructions.heat_exchanger.geometry.tube_length,
            tube_wall_thickness=cdu.constructions.heat_exchanger.geometry.tube_wall_thickness,
            num_row=cdu.constructions.heat_exchanger.geometry.row_number,
            num_transverse=cdu.constructions.heat_exchanger.geometry.transverse_number,
            row_pitch=cdu.constructions.heat_exchanger.geometry.row_pitch,
            transverse_pitch=cdu.constructions.heat_exchanger.geometry.transverse_pitch,
            tube_roughness=cdu.constructions.heat_exchanger.geometry.tube_roughness,
            thermal_conductivity=cdu.constructions.heat_exchanger.geometry.thermal_conductivity
        )
        self.pump = LiquidCoolingPump(cdu.constructions.pump)
        self.server_pipes, self.rack_supply_side_tee_pipes, self.rack_return_side_tee_pipes, self.bus_pipes =\
            self._make_pipes()

    def _make_pipes(self):
        server_pipes = {}
        rack_supply_side_tee_pipes = {}
        rack_return_side_tee_pipes = {}
        bus_pipe = {}
        # create server pipes and rack tee pipes
        for pipe_name, pipe in self.config.constructions.pipes.items():
            if pipe.meta.server != "":
                pipe.geometry.channel_type = "straight"
                server_pipes[f"{pipe.meta.server} straight"] = LiquidCoolingPipe(
                    pipe=pipe
                )
                for idx in range(1, self.num_turning * 2 + 1):
                    pipe.geometry.channel_type = "elbow"
                    pipe.geometry.turning_radius = 2 * pipe.geometry.pipe_diameter
                    server_pipes[f"{pipe.meta.server} elbow-{idx}"] = LiquidCoolingPipe(
                        pipe=pipe
                    )
                sub_pipe_diameter = pipe.geometry.pipe_diameter
                pipe.geometry.pipe_diameter = self.config.geometry.main_pipe_diameter
                pipe.geometry.channel_type = "tee"
                rack_supply_side_tee_pipes[f"{pipe.meta.server} supply tee"] = LiquidCoolingPipe(
                    pipe=pipe,
                    sub_pipe_diameter=sub_pipe_diameter
                )
                rack_return_side_tee_pipes[f"{pipe.meta.server} return tee"] = LiquidCoolingPipe(
                    pipe=pipe,
                    sub_pipe_diameter=sub_pipe_diameter
                )
        # create bus pipes
        for rack_name in self.config.meta.racks:
            cdu2rack_dist = abs(self.config.geometry.location.x - self.racks[rack_name].geometry.location.x) + \
                            abs(self.config.geometry.location.y - self.racks[rack_name].geometry.location.y)
            pipe = Pipe()
            pipe.geometry.pipe_diameter = self.config.geometry.main_pipe_diameter
            pipe.geometry.pipe_length = cdu2rack_dist
            pipe.geometry.channel_type = "straight"
            bus_pipe[f"{rack_name} supply bus pipe"] = LiquidCoolingPipe(
                pipe=pipe
            )
            bus_pipe[f"{rack_name} return bus pipe"] = LiquidCoolingPipe(
                pipe=pipe
            )
        return server_pipes, rack_supply_side_tee_pipes, rack_return_side_tee_pipes, bus_pipe

    def _sim_hx(
        self,
        cooling_water_return_temperature: float | np.ndarray,
        cooling_water_mass_flow_rate: float | np.ndarray,
        chilled_water_supply_temperature: float | np.ndarray,
        chilled_water_mass_flow_rate: float | np.ndarray,
    ):
        """
        Simulate the heat exchanger performance according to the inner and outer fluid properties.
        :param cooling_water_return_temperature: the temperature of return cooling water from server racks (C)
        :param cooling_water_mass_flow_rate: the mass flow rate of return cooling water from server racks (kg/s)
        :param chilled_water_supply_temperature: the temperature of supply chilled water to server racks (C)
        :param chilled_water_mass_flow_rate: the mass flow rate of supply chilled water to server racks (kg/s)
        :return: the outlet temperature of the inner and outer side of the heat exchanger (C) as well as the heat
        transfer rate (W) and heat transfer coefficient (W/m2K)
        """
        return self.heat_exchanger.sim(
            inner_inlet_temperature=chilled_water_supply_temperature,
            inner_mass_flow_rate=chilled_water_mass_flow_rate,
            outer_inlet_temperature=cooling_water_return_temperature,
            outer_mass_flow_rate=cooling_water_mass_flow_rate,
        )

    def _sim_server_pipes(
        self,
        inlet_temperature: float | np.ndarray,
        power: float | np.ndarray,
        liquid_percentage: float | np.ndarray,
        server_name: str,
        mass_flow_rate: float | np.ndarray
    ):
        """
        Simulate the server friction power due to the liquid cooling pipes installed in the chips.
        """
        mass_flow_rate_chip = mass_flow_rate / self.cpu_number_per_server  # kg/s
        # straight part
        chip_straight_part_friction_power = self.server_pipes[f"{server_name} straight"].sim(mass_flow_rate_chip)
        # elbow part
        chip_elbow_part_friction_power = 0
        for idx in range(1, self.num_turning * 2 + 1):
            chip_elbow_part_friction_power += self.server_pipes[f"{server_name} elbow-{idx}"].sim(mass_flow_rate_chip)
        # chip total friction power
        chip_total_friction_power = chip_straight_part_friction_power + chip_elbow_part_friction_power
        # server total power
        server_friction_power = chip_total_friction_power * self.cpu_number_per_server
        liquid_outlet_temperature = inlet_temperature + power*liquid_percentage / (self.liquid_capacity*mass_flow_rate)
        return server_friction_power, liquid_outlet_temperature

    def _sim_rack_pipes(
        self,
        inlet_temperature: float | np.ndarray,
        server_powers: dict,
        server_mass_flow_rates: dict,
        server_liquid_cooling_percentages: dict
    ):
        """
        Simulate the liquid cooling thermal and mechanical processes inside each rack that is connected to the CDU.
        """
        rack_electrical_power = {}
        rack_mass_flow_rate = {}
        rack_friction_power = {}
        rack_outlet_temperature = {}
        # simulate friction power due to the liquid cooling pipes installed in the chips.
        for rack_name in self.config.meta.racks:
            rack = self.racks[rack_name]
            total_electrical_power = 0
            total_server_friction_power = 0
            total_mass_flow_rate = 0
            outlet_temperature_times_mass_flow_rate = 0
            for server in rack.constructions.servers.values():
                server_friction_power, outlet_temperature_server = self._sim_server_pipes(
                    inlet_temperature=inlet_temperature,
                    power=server_powers[server.uid],
                    liquid_percentage=server_liquid_cooling_percentages[server.uid],
                    server_name=server.uid,
                    mass_flow_rate=server_mass_flow_rates[server.uid]
                )
                outlet_temperature_times_mass_flow_rate += outlet_temperature_server * server_mass_flow_rates[server.uid]
                total_mass_flow_rate += server_mass_flow_rates[server.uid]
                total_server_friction_power += server_friction_power
                total_electrical_power += server_powers[server.uid]
            # summarize result from server simulation
            rack_outlet_temperature[rack_name] = outlet_temperature_times_mass_flow_rate / total_mass_flow_rate
            rack_mass_flow_rate[rack_name] = total_mass_flow_rate
            rack_electrical_power[rack_name] = total_electrical_power

            # simulate pressure drop at rack tees
            total_tee_friction_power = 0
            main_pipe_mass_flow_rate = total_mass_flow_rate
            for server in sorted(rack.constructions.servers.values(), key=lambda x: x.geometry.slot_position):
                sub_mass_flow_rate = server_mass_flow_rates[server.uid]
                total_tee_friction_power += self.rack_supply_side_tee_pipes[
                    f"{server.uid} supply tee"
                ].sim(
                    main_pipe_mass_flow_rate=main_pipe_mass_flow_rate,
                    sub_pipe_mass_flow_rate=sub_mass_flow_rate
                )
                total_tee_friction_power += self.rack_return_side_tee_pipes[
                    f"{server.uid} return tee"
                ].sim(
                    main_pipe_mass_flow_rate=main_pipe_mass_flow_rate,
                    sub_pipe_mass_flow_rate=sub_mass_flow_rate
                )
                main_pipe_mass_flow_rate -= sub_mass_flow_rate
            # total friction power of the rack equals to the sum of server friction power and tee friction power
            rack_friction_power[rack_name] = total_server_friction_power + total_tee_friction_power

        # calculate the total friction power of the rack pipes
        total_friction_power = sum(rack_friction_power.values())
        # calculate weighted CDU return temperature given rack outlet temperature and mass flow rate
        weighted_cdu_return_temperature = 0
        for rack_name in self.config.meta.racks:
            weighted_cdu_return_temperature += rack_mass_flow_rate[rack_name] * rack_outlet_temperature[rack_name]
        cdu_return_temperature = weighted_cdu_return_temperature / sum(rack_mass_flow_rate.values())
        return (
            total_friction_power,
            rack_electrical_power,
            cdu_return_temperature,
            rack_mass_flow_rate,
            rack_outlet_temperature
        )

    def _sim_bus_pipe(
        self,
        rack_mass_flow_rate: Dict[str, float | np.ndarray]
    ):
        bus_pipe_total_friction_power = 0
        for rack_name in self.config.meta.racks:
            bus_pipe_total_friction_power +=\
                self.bus_pipes[f"{rack_name} supply bus pipe"].sim(rack_mass_flow_rate[rack_name])
            bus_pipe_total_friction_power +=\
                self.bus_pipes[f"{rack_name} return bus pipe"].sim(rack_mass_flow_rate[rack_name])
        return bus_pipe_total_friction_power

    def _sim_pipes(
        self,
        inlet_temperature: float | np.ndarray,
        server_powers: dict,
        server_mass_flow_rates: dict,
        server_liquid_cooling_percentages: dict
    ):
        (rack_pipe_friction_power, rack_electrical_power, cdu_return_temperature, rack_mass_flow_rate,
         rack_outlet_temperature) = self._sim_rack_pipes(
            inlet_temperature=inlet_temperature,
            server_powers=server_powers,
            server_mass_flow_rates=server_mass_flow_rates,
            server_liquid_cooling_percentages=server_liquid_cooling_percentages,
        )
        bus_pipe_friction_power = self._sim_bus_pipe(
            rack_mass_flow_rate=rack_mass_flow_rate
        )
        total_friction_power = rack_pipe_friction_power + bus_pipe_friction_power
        return total_friction_power, cdu_return_temperature

    def _sim_pump(self, friction_power: float | np.ndarray):
        return self.pump.sim(friction_power)

    def sim(
        self,
        server_powers: dict,
        server_mass_flow_rates: dict,
        server_liquid_cooling_percentages: dict,
        cooling_water_supply_temperature: float | np.ndarray,
        chilled_water_supply_temperature: float | np.ndarray,
        chilled_water_mass_flow_rate: float | np.ndarray,
    ):
        total_friction_power, cdu_return_temperature = self._sim_pipes(
            inlet_temperature=cooling_water_supply_temperature,
            server_powers=server_powers,
            server_mass_flow_rates=server_mass_flow_rates,
            server_liquid_cooling_percentages=server_liquid_cooling_percentages,
        )
        cdu_electrical_power = self._sim_pump(
            friction_power=total_friction_power
        )
        chilled_water_return_temperature, cooling_water_supply_temperature, chilled_water_mass_flow_rate, hx_info =\
            self._sim_hx(
                cooling_water_return_temperature=cdu_return_temperature,
                cooling_water_mass_flow_rate=sum(server_mass_flow_rates.values()),
                chilled_water_supply_temperature=chilled_water_supply_temperature,
                chilled_water_mass_flow_rate=chilled_water_mass_flow_rate,
            )
        return (
            cdu_electrical_power,
            chilled_water_return_temperature,
            cooling_water_supply_temperature,
            cdu_return_temperature,
            chilled_water_mass_flow_rate,
            hx_info
        )
