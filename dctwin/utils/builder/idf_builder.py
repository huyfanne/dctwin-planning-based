import json
from pathlib import Path
from loguru import logger
import copy
from eppy.modeleditor import IDF

from dclib.models.geometry.basics import Geometry
from dclib import Building

from .plant import PlantBuilder
from .models import ModelBuilder
from .zone import RoomBuilder, make_surfaces
from .electric import ElectricSystemBuilder


class IDFBuilder:

    idd_path = Path(__file__).parent.parent.parent.joinpath("templates").joinpath("eplus").joinpath("V9-5-0-Energy+.idd")
    template_idf_path = Path(__file__).parent.parent.parent.joinpath("templates").joinpath("eplus").joinpath("template.idf")

    def __init__(
        self,
        building: Building,
    ) -> None:
        IDF.setiddname(iddname=str(self.idd_path))
        self.model = IDF(idfname=self.template_idf_path)
        self.building = building

        self.model_builder = ModelBuilder(self.model)
        self.plant_builder = PlantBuilder(self.model)
        self.room_builder = RoomBuilder(self.model)
        self.electric_system_builder = ElectricSystemBuilder(self.model)

        self._set_global_geometry_rules(building.geometry)

    def _set_global_geometry_rules(self, geometry_config: Geometry):
        # GlobalGeometryRules
        geometry = self.model.newidfobject(key="GlobalGeometryRules".upper())
        geometry["Starting_Vertex_Position"] = geometry_config.starting_vertex_position
        geometry["Vertex_Entry_Direction"] = geometry_config.vertex_entry_direction
        geometry["Coordinate_System"] = geometry_config.coordinate_system
        geometry[
            "Daylighting_Reference_Point_Coordinate_System"
        ] = geometry_config.daylighting_reference_point_coordinate_system
        geometry["Rectangular_Surface_Coordinate_System"] = geometry_config.rectangular_surface_coordinate_system

    def _make_models(self):
        self.model_builder.make_models(self.building.models)

    def _make_surfaces(self):
        if self.building.constructions.surfaces is not None and self.building.geometry is not None:
            make_surfaces(self.model, self.building.geometry, self.building.constructions.surfaces)

    def _make_rooms(self) -> None:
        self.room_builder.make_rooms(self.building.constructions.zones)

    def _make_plant(self) -> None:
        self.plant_builder.make_plant(self.building.constructions.plant)

    def _make_schedule(self) -> None:
        pass

    def _make_elctric_load_centers(self) -> None:
        self.electric_system_builder.make_electric_load_centers(
            self.building.constructions.electrical_load_centers
        )

    def _make_device_key_mapping(self) -> None:
        self.device_key_map = {
            "chilled water loops": {},
            "condenser water loops": {},
            "zones": {},
            "ites": {},
            "acus": {},
            "chilled water pumps": {},
            "chillers": {},
            "condenser water pumps": {},
            "cooling towers": {},
        }
        # create chilled water loop device key mapping
        chilled_water_loop_names = self.building.constructions.plant.chilled_water_loops
        for chilled_water_loop_name in chilled_water_loop_names:
            chilled_water_loop_obj = self.model.getobject(
                key="PlantLoop".upper(),
                name=chilled_water_loop_name
            )
            self.device_key_map["chilled water loops"][chilled_water_loop_name] = {
                "supply temperature": f"{chilled_water_loop_obj['Plant_Side_Outlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "return temperature": f"{chilled_water_loop_obj['Plant_Side_Inlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "supply flow rate": f"{chilled_water_loop_obj['Plant_Side_Outlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "return flow rate": f"{chilled_water_loop_obj['Plant_Side_Inlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
            }
        # create condenser water loop device key mapping
        condenser_water_loop_names = self.building.constructions.plant.condenser_water_loops
        for condenser_water_loop_name in condenser_water_loop_names:
            condenser_water_loop_obj = self.model.getobject(
                key="PlantLoop".upper(),
                name=condenser_water_loop_name
            )
            self.device_key_map["condenser water loops"][condenser_water_loop_name] = {
                "supply temperature": f"{condenser_water_loop_obj['Plant_Side_Outlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "return temperature": f"{condenser_water_loop_obj['Plant_Side_Inlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "supply flow rate": f"{condenser_water_loop_obj['Plant_Side_Outlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "return flow rate": f"{condenser_water_loop_obj['Plant_Side_Inlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
            }
        # create zone device key mapping
        for zone_name in self.building.constructions.zones:
            self.device_key_map["zones"][zone_name] = {}
            zone_obj = self.model.getobject(
                key="Zone".upper(),
                name=f"{zone_name}"
            )
            self.device_key_map["zones"][zone_name] = {
                "air temperature": f"{zone_obj['Name'].upper()}:Zone Air Temperature [C](TimeStep)",
                "air relative humidity": f"{zone_obj['Name'].upper()}:Zone Air Relative Humidity [%](TimeStep)",
                "ite power": f"{zone_obj['Name'].upper()}:Zone ITE CPU Electricity Rate [W](TimeStep)",
            }
        # create ITE device key mapping
        for ite_name in self.building.constructions.ites:
            self.device_key_map["ites"][ite_name] = {}
            ite_obj = self.model.getobject(
                key="ElectricEquipment:ITE:AirCooled".upper(),
                name=f"{ite_name}"
            )
            self.device_key_map["ites"][ite_name] = {
                "inlet dry-bulb temperature": f"{ite_obj['Name'].upper()}:ITE Air Inlet Dry-Bulb Temperature [C](TimeStep)",
                "cpu power": f"{ite_obj['Name'].upper()}:ITE CPU Electricity Rate [%](TimeStep)",
                "fan power": f"{ite_obj['Name'].upper()}:ITE Fan Electricity Rate [%](TimeStep)",
                "ups power": f"{ite_obj['Name'].upper()}:ITE UPS Electricity Rate [W](TimeStep)",
            }
        # create ACU device key mapping
        for acu_name in self.building.constructions.acus:
            self.device_key_map["acus"][acu_name] = {}
            fan_obj = self.model.getobject(
                key="Fan:VariableVolume".upper(),
                name=f"{acu_name} fan"
            )
            self.device_key_map["acus"][acu_name]["fan"]= {
                "air mass flow rate": f"{fan_obj['Air_Outlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "power": f"{fan_obj['Name'].upper()}:Fan Electricity Rate [W](TimeStep)",
            }
            coil_obj = self.model.getobject(
                key="Coil:Cooling:Water".upper(),
                name=f"{acu_name} cooling coil"
            )
            self.device_key_map["acus"][acu_name]["cooling coil"] = {
                "inlet air temperature": f"{coil_obj['Air_Inlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "air mass flow rate": f"{coil_obj['Air_Inlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "outlet air temperature": f"{coil_obj['Air_Outlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "inlet water temperature": f"{coil_obj['Water_Inlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "water mass flow rate": f"{coil_obj['Water_Inlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
            }
        # create chilled water pump device key mapping
        pump_names = self.building.constructions.chilled_water_pumps
        for pump_name in pump_names:
            pump_obj = self.model.getobject(
                key="Pump:VariableSpeed".upper(),
                name=pump_name
            )
            self.device_key_map["chilled water pumps"][pump_name] = {
                "mass flow rate": f"{pump_obj['Outlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "power": f"{pump_obj['Name'].upper()}:Pump Electricity Rate [W](TimeStep)",
            }
        # create chiller device key mapping
        chiller_names = self.building.constructions.chillers
        for chiller_name in chiller_names:
            chiller_obj = self.model.getobject(
                key="Chiller:Electric:EIR".upper(),
                name=chiller_name
            )
            self.device_key_map["chillers"][chiller_name] = {
                "cooling load": f"{chiller_obj['Name'].upper()}:Chiller Evaporator Cooling Rate [W](TimeStep)",
                "chilled water supply temperature": f"{chiller_obj['Chilled_Water_Outlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "chilled water return temperature": f"{chiller_obj['Chilled_Water_Inlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "condensing water return temperature": f"{chiller_obj['Condenser_Outlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "condensing water supply temperature": f"{chiller_obj['Condenser_Inlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "power": f"{chiller_obj['Name'].upper()}:Chiller Electricity Rate [W](TimeStep)",
                "mass flow rate": f"{chiller_obj['Chilled_Water_Outlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
            }
        # create secondary chilled water pump device key mapping
        self.device_key_map["secondary chilled water pumps"] = {}
        pump_names = self.building.constructions.secondary_chilled_water_pumps
        for pump_name in pump_names:
            pump_obj = self.model.getobject(
                key="Pump:VariableSpeed".upper(),
                name=pump_name
            )
            self.device_key_map["secondary chilled water pumps"][pump_name] = {
                "mass flow rate": f"{pump_obj['Outlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "power": f"{pump_obj['Name'].upper()}:Pump Electricity Rate [W](TimeStep)",
            }
        # create condenser water pump device key mapping
        pump_names = self.building.constructions.condenser_water_pumps
        for pump_name in pump_names:
            pump_obj = self.model.getobject(
                key="Pump:VariableSpeed".upper(),
                name=pump_name
            )
            self.device_key_map["condenser water pumps"][pump_name] = {
                "mass flow rate": f"{pump_obj['Outlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "power": f"{pump_obj['Name'].upper()}:Pump Electricity Rate [W](TimeStep)",
            }
        # create cooling tower device key mapping
        tower_names = self.building.constructions.cooling_towers
        for tower_name in tower_names:
            tower_obj = self.model.getobject(
                key="CoolingTower:VariableSpeed".upper(),
                name=tower_name
            )
            self.device_key_map["cooling towers"][tower_name] = {
                "return water temperature": f"{tower_obj['Water_Inlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "water mass flow rate": f"{tower_obj['Water_Inlet_Node_Name'].upper()}:System Node Mass Flow Rate [kg/s](TimeStep)",
                "supply water temperature": f"{tower_obj['Water_Outlet_Node_Name'].upper()}:System Node Temperature [C](TimeStep)",
                "air flow rate ratio": f"{tower_obj['Name'].upper()}:Cooling Tower Air Flow Rate Ratio [](TimeStep)",
                "outside air wetbulb temperature": "Environment:Site Outdoor Air Wetbulb Temperature [C](TimeStep)",
                "power": f"{tower_obj['Name'].upper()}:Cooling Tower Fan Electricity Rate [W](TimeStep)"
            }

    def _make_room2ite_mapping(self) -> None:
        self.room2ite_map = {}
        for zone_name, zone in self.building.constructions.zones.items():
            ite2rack = zone.constructions.ite2rack(zone_name)
            ites = {}
            for ite_name, ite in zone.constructions.heat_gains.ites.items():
                ites[ite_name] = {}
                if ite_name in ite2rack and len(ite2rack[ite_name]["racks"]) > 0:
                    ites[ite_name]["racks"] = ite2rack[ite_name]["racks"]
                ites[ite_name]["wattsPerUnit"] = ite.watts_per_unit
                ites[ite_name]["numberOfUnits"] = ite.number_of_units
                ites[ite_name]["totalWatts"] = ite.watts_per_unit * ite.number_of_units

            self.room2ite_map[zone_name] = ites

    def replace_entries_with_dict(self, data):
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict):
                    self.replace_entries_with_dict(value)
                else:
                    data[key] = {
                        value: []
                    }

    def make(self) -> None:
        self._make_models()
        self._make_surfaces()
        self._make_rooms()
        self._make_plant()
        self._make_schedule()
        self._make_elctric_load_centers()
        self._make_device_key_mapping()
        self._make_room2ite_mapping()

    def save(
        self,
        idf_save_dir: Path,
        map_save_dir: Path,
    ) -> None:
        if self.model is not None:
            self.model.saveas(str(idf_save_dir.joinpath("building.idf").absolute()))
            logger.info(f"Model saved to {idf_save_dir.joinpath('building.idf').absolute()}")
            with open(map_save_dir.joinpath("device_key_map.json"),  "w") as f:
                json.dump(self.device_key_map, f, indent=4)
            with open(map_save_dir.joinpath("device_his_map.json"),  "w") as f:
                # replace all entries with empty list for calibration
                self.device_his_map = copy.deepcopy(self.device_key_map)
                self.replace_entries_with_dict(self.device_his_map)
                json.dump(self.device_his_map, f, indent=4)
            with open(map_save_dir.joinpath("room2ite_map.json"),  "w") as f:
                json.dump(self.room2ite_map, f, indent=4)
            logger.info(f"Mapping json saved to {map_save_dir.absolute()}")
        else:
            logger.critical("Model is empty. Cannot save.")
