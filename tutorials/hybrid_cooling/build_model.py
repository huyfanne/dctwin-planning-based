from loguru import logger
from dclib import Building
from dctwin.third_parties.eplus.builder import IDFBuilder

building = Building.load(
    path="models/dc.json",
)

logger.info("CDUs:")
logger.info(building.constructions.cdus_keys)

logger.info("ACUs:")
logger.info(building.constructions.acu_keys)

logger.info("Chillers:")
logger.info(building.constructions.chiller_keys)

logger.info("Chilled Water Pumps:")
logger.info(building.constructions.chilled_water_pump_keys)

logger.info("Condenser Water Pumps:")
logger.info(building.constructions.condenser_water_pump_keys)

logger.info("Cooling Towers:")
logger.info(building.constructions.cooling_tower_keys)

builder = IDFBuilder(building=building)
builder.make()
builder.save(
    idf_save_path="models/idf/dc.idf",
    device_key_map_save_path="configs/dt/device_key_map.json",
)
