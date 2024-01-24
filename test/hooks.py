from dctwin.adapters import EplusCFDAdapter
from typing import Dict


def map_boundary_condition_fn(
    eplus_adaptor: EplusCFDAdapter,
    action_dict: Dict,
) -> Dict:
    """
    Map the action dict into boundary condition dict with a given format.
    Boundary conditions should include supply temperature, supply
    volumetric flow rate, server powers and server flow rates.
    Server power and server flow rate are computed in a model-based manner
    with the model from Eplus. The curve parameters for the server power model
    and flow rate model are from parsing the idf file automatically.
    """
    boundary_conditions = {
        "supply_air_temperatures": {},
        "supply_air_volume_flow_rates": {},
        "server_powers": {},
        "server_volume_flow_rates": {},
    }
    for crac in eplus_adaptor.eplus_manager.idf_parser.epm.AirLoopHVAC:
        uid = eplus_adaptor.idf2room_mapper[crac.name]
        boundary_conditions["supply_air_temperatures"][uid] = action_dict[
            f"{uid}_setpoint"
        ]
        boundary_conditions["supply_air_volume_flow_rates"][uid] = (
            action_dict[f"{uid}_flow_rate"] / eplus_adaptor.rho_air
        )
    for idx, it_equipment in enumerate(
        eplus_adaptor.eplus_manager.idf_parser.epm.ElectricEquipment_ITE_AirCooled
    ):
        for server_id in eplus_adaptor.idf2room_mapper[it_equipment.name]["servers"]:
            heat_load = eplus_adaptor.eplus_manager.idf_parser.compute_server_power(
                utilization=action_dict[f"cpu_loading_schedule{idx + 1}"],
                inlet_temperature=eplus_adaptor.server_inlet_temps[server_id],
                name=it_equipment.name,
            )
            volume_flow_rate = (
                eplus_adaptor.eplus_manager.idf_parser.compute_server_flow_rate(
                    utilization=action_dict[f"cpu_loading_schedule{idx + 1}"],
                    inlet_temperature=eplus_adaptor.server_inlet_temps[server_id],
                    name=it_equipment.name,
                )
            )
            boundary_conditions["server_powers"][server_id] = heat_load
            boundary_conditions["server_volume_flow_rates"][
                server_id
            ] = volume_flow_rate

    return boundary_conditions
