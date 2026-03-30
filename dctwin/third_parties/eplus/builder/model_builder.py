from eppy.modeleditor import IDF
from dclib.models.composite import Models


class ModelBuilder:
    def __init__(self, model: IDF):
        self.model = model

    def _make_materials(self, model_config: Models):
        for material_name, material_config in model_config.material_models.items():
            material = self.model.newidfobject(key="Material".upper())
            material["Name"] = material_name
            material["Roughness"] = material_config.roughness
            material["Thickness"] = material_config.thickness
            material["Conductivity"] = material_config.conductivity
            material["Density"] = material_config.density
            material["Specific_Heat"] = material_config.specific_heat
            material["Thermal_Absorptance"] = material_config.thermal_absorptance
            material["Solar_Absorptance"] = material_config.thermal_absorptance
            material["Visible_Absorptance"] = material_config.visible_absorptance

        for (
            construction_name,
            construction_config,
        ) in model_config.construction_models.items():
            construction = self.model.newidfobject(key="Construction".upper())
            construction["Name"] = construction_name
            for idx, material in enumerate(construction_config.materials):
                construction["Outside_Layer" if idx == 0 else f"Layer_{idx + 1}"] = (
                    material
                )

    def _make_curves(self):
        pass

    def make_models(self, model_config: Models):
        self._make_materials(model_config=model_config)
