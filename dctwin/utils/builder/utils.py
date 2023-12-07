from typing import List

from eppy.bunch_subclass import EpBunch


def fill_info(
    idf_obj_name: str, idf_obj: EpBunch, idd_infos, filled_field: List, config
):
    """
    Fill the idf_obj with the configs information. If the field is not in the configs, use the default value in idd file.
    :param idf_obj_name:
    :param idf_obj:
    :param idd_infos:
    :param filled_field:
    :param config:
    :return:
    """
    for idd_info in idd_infos:
        if idd_info[0]["idfobj"] == idf_obj_name:
            for field_idx, field_definition in enumerate(idd_info):
                if "field" in field_definition:
                    field_name = (
                        "_".join(field_definition["field"][0].split(" "))
                        .replace("%", "")
                        .replace("-", "")
                    )
                    if field_name not in filled_field:
                        filled_field.append(field_name)
                        try:
                            idf_obj[field_name] = config.__getattribute__(
                                field_name.lower()
                            )
                            if idf_obj[field_name] is None:
                                if "default" in field_definition.keys():
                                    idf_obj[field_name] = (
                                        field_definition.get("default")[0]
                                        if field_definition.get("default")[0]
                                        is not None
                                        else ""
                                    )
                        except:
                            if "default" in field_definition.keys():
                                idf_obj[field_name] = (
                                    field_definition.get("default")[0]
                                    if field_definition.get("default")[0] is not None
                                    else ""
                                )
            break
    return idf_obj, filled_field


def fill_inlet_outlet(
    branch_component_idx: int,
    obj: EpBunch,
    branch: EpBunch,
    name: str,
    inlet_key_name: str,
    outlet_key_name: str,
):
    if branch_component_idx > 1:
        obj[inlet_key_name] = branch[
            f"Component_{branch_component_idx - 1}_Outlet_Node_Name"
        ]
        obj[outlet_key_name] = f"{name} outlet node"
        branch[f"Component_{branch_component_idx}_Inlet_Node_Name"] = branch[
            f"Component_{branch_component_idx - 1}_Outlet_Node_Name"
        ]
        branch[f"Component_{branch_component_idx}_Outlet_Node_Name"] = obj[outlet_key_name]
    else:
        obj[inlet_key_name] = f"{name} inlet node"
        obj[outlet_key_name] = f"{name} outlet node"
        branch["Component_1_Inlet_Node_Name"] = obj[inlet_key_name]
        branch["Component_1_Outlet_Node_Name"] = obj[outlet_key_name]
    return obj
