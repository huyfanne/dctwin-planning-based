from typing import Dict

from eppy.modeleditor import IDF

from dclib.electrical.generators import PhotovoltaicGenerator
from dclib.electrical.auxiliaries import Inverter
from dclib.electrical.storages import SimpleBattery
from dclib.electrical.center import ElectricalLoadCenter

from .utils import fill_info


class ElectricSystemBuilder:
    def __init__(self, model: IDF):
        self.model = model

    def _make_inverter(self, config: Inverter):
        inverter_obj = self.model.newidfobject(
            "ElectricLoadCenter:Inverter:Simple".upper(),
            Name=config.uid,
        )
        inverter_obj["Availability_Schedule_Name"] = "ALWAYS ON"
        inverter_obj["Zone_Name"] = config.zone_name
        inverter_obj["Inverter_Efficiency"] = config.inverter_efficiency
        inverter_obj["Radiative_Fraction"] = config.radiant_fraction

    def _make_battery(self, config: SimpleBattery):
        battery_obj = self.model.newidfobject(
            "ElectricLoadCenter:Storage:Simple".upper(),
            Name=config.uid,
        )
        battery_obj["Availability_Schedule_Name"] = "ALWAYS ON"

    def _make_generator(self, generator_config: PhotovoltaicGenerator):
        performance_model_obj = self.model.newidfobject(
            key="PhotovoltaicPerformance:EquivalentOne-Diode".upper(),
            defaultvalues=True,
            Name=f"{generator_config.uid} performance model",
        )
        fill_info(
            idf_obj_name="PhotovoltaicPerformance:EquivalentOne-Diode",
            idf_obj=performance_model_obj,
            idd_infos=self.model.idd_info,
            filled_field=[],
            config=generator_config.performance_model,
        )
        generator_obj = self.model.newidfobject(
            key="Generator:Photovoltaic".upper(), defaultvalues=True
        )
        generator_obj["Name"] = generator_config.uid
        generator_obj["Number_of_Modules_in_Series"] = (
            generator_config.number_of_modules_in_series
        )
        generator_obj["Number_of_Series_Strings_in_Parallel"] = (
            generator_config.number_of_series_strings_in_parallel
        )
        generator_obj["Photovoltaic_Performance_Object_Type"] = (
            "PhotovoltaicPerformance:EquivalentOne-Diode"
        )
        generator_obj["Module_Performance_Name"] = performance_model_obj.Name
        generator_obj["Surface_Name"] = generator_config.surface_name
        generator_obj["Heat_Transfer_Integration_Mode"] = (
            generator_config.heat_transfer_integration_mode
        )

        # find the surface object that is attached to the solar generator
        surface_obj = self.model.getobject(
            key="BuildingSurface:Detailed".upper(), name=generator_config.surface_name
        )
        surface_obj["Outside_Boundary_Condition"] = "OtherSideConditionsModel"
        surface_obj["Outside_Boundary_Condition_Object"] = (
            f"{generator_config.surface_name} outside boundary condition object"
        )
        self.model.newidfobject(
            key="SurfaceProperty:OtherSideConditionsModel",
            Name=(f"{generator_config.surface_name} outside boundary condition object"),
            Type_of_Modeling="GapConvectionRadiation",
        )
        self.model.newidfobject(
            key="SurfaceProperty:ExteriorNaturalVentedCavity",
            Name=(f"{generator_config.uid} exterior ventilation cavity"),
            Boundary_Conditions_Model_Name=(
                f"{generator_config.surface_name} outside boundary condition object"
            ),
            Area_Fraction_of_Openings=0.02,
            Thermal_Emissivity_of_Exterior_Baffle_Material=0.9,
            Solar_Absorbtivity_of_Exterior_Baffle=0.92,
            Height_Scale_for_BuoyancyDriven_Ventilation=0.05,
            Effective_Thickness_of_Cavity_Behind_Exterior_Baffle=0.05,
            Ratio_of_Actual_Surface_Area_to_Projected_Surface_Area=0.97,
            Roughness_of_Exterior_Surface="Smooth",
            Effectiveness_for_Perforations_with_Respect_to_Wind=0.1,
            Discharge_Coefficient_for_Openings_with_Respect_to_Buoyancy_Driven_Flow=0.5,
            Surface_1_Name=generator_config.surface_name,
        )
        return generator_obj

    def _make_generators(
        self,
        electric_load_center_name: str,
        generators: Dict[str, PhotovoltaicGenerator],
    ):
        obj = self.model.newidfobject(
            key="ElectricLoadCenter:Generators".upper(),
            Name=f"{electric_load_center_name} generators",
        )
        for idx, (generator_name, generator) in enumerate(generators.items()):
            generator_obj = self._make_generator(generator)
            obj[f"Generator_{int(idx) + 1}_Name"] = generator_name
            obj[f"Generator_{int(idx) + 1}_Object_Type"] = generator_obj["key"]
            obj[f"Generator_{int(idx) + 1}_Rated_Electric_Power_Output"] = (
                generator.rated_electric_power_output
            )
            obj[f"Generator_{int(idx) + 1}_Availability_Schedule_Name"] = "ALWAYS ON"

    def _make_electric_load_center(
        self, electric_load_center_name: str, config: ElectricalLoadCenter
    ):
        obj = self.model.newidfobject(
            key="ElectricLoadCenter:Distribution".upper(), defaultvalues=True
        )
        self._make_generators(electric_load_center_name, config.generators)
        self._make_inverter(config.inverter)
        self._make_battery(
            config.electrical_storage
        ) if config.electrical_storage else None

        obj["Name"] = electric_load_center_name
        obj["Electrical_Buss_Type"] = config.electrical_buss_type
        obj["Generator_List_Name"] = f"{electric_load_center_name} generators"
        obj["Generator_Demand_Limit_Scheme_Purchased_Electric_Demand_Limit"] = (
            config.generator_demand_limit_scheme_purchased_electric_demand_limit
        )
        obj["Generator_Operation_Scheme_Type"] = config.generator_operation_scheme_name
        obj["Inverter_Name"] = config.inverter.uid
        obj["Electrical_Storage_Object_Name"] = (
            config.electrical_storage.name if config.electrical_storage else ""
        )
        obj["Transformer_Object_Name"] = (
            config.transformer.name if config.transformer else ""
        )
        obj["Storage_Operation_Scheme"] = ""

    def make_electric_load_centers(
        self, electric_load_centers: Dict[str, ElectricalLoadCenter]
    ):
        for (
            electric_load_center_name,
            electric_load_center,
        ) in electric_load_centers.items():
            self._make_electric_load_center(
                electric_load_center_name, electric_load_center
            )
