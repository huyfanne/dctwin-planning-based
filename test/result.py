# state file generated using paraview version 5.9.0

import json
import os
from pathlib import Path
import logging
from paraview.simple import *
from paraview.servermanager import *
from vtk.util import numpy_support
import pandas as pd
import numpy as np
import math


# DEFINE UTILS FUNCTION
def parse(variable, default):
    try:
        return float(os.getenv(variable, default))
    except ValueError:
        return default


# DEFINE CONSTANTS and VARIABLES
width = parse("WIDTH", 12)
depth = parse("DEPTH", 6)
height = parse("HEIGHT", 3)

minimum_t_full_range_celsius = parse("MINIMUM_T_FULL_RANGE_CELSIUS", 0)
maximum_t_full_range_celsius = parse("MAXIMUM_T_FULL_RANGE_CELSIUS", 100)
minimum_t_celsius = parse("MINIMUM_T_CELSIUS", 15)
maximum_t_celsius = parse("MAXIMUM_T_CELSIUS", 45)

is_modulus = os.getenv("IS_MODULUS", "false").lower() == "true"

minimum_t_full_range_kelvin = minimum_t_full_range_celsius + 273.15
maximum_t_full_range_kelvin = maximum_t_full_range_celsius + 273.15
minimum_t_kelvin = minimum_t_celsius + 273.15
maximum_t_kelvin = maximum_t_celsius + 273.15

T_LUT_RGB_POINTS = [
    288.15,
    0.003921569,
    0.03137255,
    0.9647059,
    288.6151,
    0,
    0.1803922,
    0.9921569,
    289.0802,
    0.003921569,
    0.282353,
    0.9882353,
    289.5453,
    0.007843138,
    0.3764706,
    1,
    290.0105,
    0.09411765,
    0.4627451,
    0.9960784,
    290.4756,
    0.1686275,
    0.5411765,
    1,
    290.9407,
    0.2470588,
    0.6078432,
    1,
    291.4058,
    0.2980392,
    0.6705883,
    0.9843137,
    291.8709,
    0.3254902,
    0.7333333,
    0.972549,
    292.336,
    0.3294118,
    0.7529412,
    0.9372549,
    292.8011,
    0.3333333,
    0.7843137,
    0.8980392,
    293.2663,
    0.3254902,
    0.8078431,
    0.8705882,
    293.7314,
    0.2980392,
    0.8431373,
    0.8235294,
    294.1965,
    0.2705882,
    0.8666667,
    0.7843137,
    294.6616,
    0.2392157,
    0.8862745,
    0.7176471,
    295.1267,
    0.1921569,
    0.9176471,
    0.6509804,
    295.5919,
    0.1372549,
    0.9372549,
    0.5882353,
    296.057,
    0.08235294,
    0.945098,
    0.5137255,
    296.5221,
    0.03137255,
    0.972549,
    0.4352941,
    296.9872,
    0.03921569,
    0.9764706,
    0.3647059,
    297.4523,
    0.1215686,
    0.9803922,
    0.2666667,
    297.9174,
    0.1803922,
    0.9921569,
    0.1607843,
    298.3826,
    0.282353,
    0.9960784,
    0,
    298.8477,
    0.3254902,
    1,
    0,
    299.3128,
    0.4,
    0.9921569,
    0.007843138,
    299.7779,
    0.4627451,
    0.9921569,
    0.003921569,
    300.243,
    0.5490196,
    1,
    0.007843138,
    300.7081,
    0.6039216,
    1,
    0.05098039,
    301.1732,
    0.682353,
    1,
    0.04705882,
    301.6384,
    0.7372549,
    0.9921569,
    0.03529412,
    302.1035,
    0.7843137,
    0.9686275,
    0.03529412,
    302.5686,
    0.8509804,
    0.945098,
    0.02745098,
    303.0337,
    0.9019608,
    0.9333333,
    0.01960784,
    303.4988,
    0.9333333,
    0.9176471,
    0.007843138,
    303.964,
    0.9882353,
    0.9058824,
    0,
    304.4291,
    1,
    0.8588235,
    0.003921569,
    304.8942,
    1,
    0.7882353,
    0.007843138,
    305.3593,
    0.9882353,
    0.7137255,
    0,
    305.8244,
    1,
    0.6196079,
    0,
    306.2895,
    1,
    0.5137255,
    0.01176471,
    306.7546,
    1,
    0.4039216,
    0.01176471,
    307.2198,
    0.972549,
    0.2980392,
    0,
    307.6849,
    0.9254902,
    0.05882353,
    0,
]
T_PWF_POINTS = [minimum_t_full_range_kelvin, 0.0, 0.5, 0.0, maximum_t_full_range_kelvin, 1.0, 0.5, 0.0]
diff = maximum_t_kelvin - minimum_t_kelvin
diff = diff / 43
final = []

for index, item in enumerate(T_LUT_RGB_POINTS):
    if index % 4 == 0:
        final.append(minimum_t_kelvin)
        minimum_t_kelvin = minimum_t_kelvin + diff
    else:
        final.append(item)

T_LUT_RGB_POINTS = [
    minimum_t_full_range_kelvin,
    0.003921569,
    0.03137255,
    0.9647059,
    *final,
    maximum_t_full_range_kelvin,
    0.9254902,
    0.05882353,
    0,
]
# T_LUT_RGB_POINTS = final


# ----------------------------------------------------------------
# setup views
# ----------------------------------------------------------------

# disable automatic camera reset on 'Show'
paraview.simple._DisableFirstRenderCameraReset()
materialLibrary1 = GetMaterialLibrary()

# Create a new 'Render View'
renderView1 = CreateView("RenderView")
renderView1.ViewSize = [1680, 1016]
renderView1.AxesGrid = "GridAxes3DActor"
renderView1.CenterOfRotation = [6.300000190734863, 3.0, 1.9997654735052492]
renderView1.StereoType = "Crystal Eyes"
adjusted_height = max(width, depth)*3
renderView1.CameraPosition = [
    width/2,  # same x as the focal point
    depth/2,  # same y as the focal point
    adjusted_height   # z height above the point; adjust as needed for your dataset
]

renderView1.CameraFocalPoint = [
    width/2, # focus on x
    depth/2, # focus on y
    0   # focus on z
]

renderView1.CameraViewUp = [
    0,  # x direction
    1,  # y direction up
    0   # z direction
]
renderView1.CameraFocalDisk = 1.0
renderView1.CameraParallelScale = 7.258852565264085
renderView1.BackEnd = "OSPRay raycaster"
renderView1.OSPRayMaterialLibrary = materialLibrary1

# setup view layouts
SetActiveView(None)
layout1 = CreateLayout(name="Layout #1")
layout1.AssignView(0, renderView1)
layout1.SetSize(1680, 1016)
SetActiveView(renderView1)

# ----------------------------------------------------------------
# setup the data processing pipelines (casefoam)
# ----------------------------------------------------------------

casefoam = OpenFOAMReader(registrationName="case.foam", FileName="/data/case.foam")
casefoam.MeshRegions = ["internalMesh"]
if is_modulus:
    casefoam.CellArrays = ["T", "U"]
else:
    casefoam.CellArrays = ["T", "U", "alphat", "epsilon", "k", "nut", "p", "p_rgh"]
casefoamDisplay = Show(casefoam, renderView1, "UnstructuredGridRepresentation")

# ----------------------------------------------------------------
# create location probes
# ----------------------------------------------------------------

location = ProbeLocation(
    registrationName="ProbeLocation1",
    Input=casefoam,
    ProbeType="Fixed Radius Point Source",
)


def get_temperature(x, y, z):
    location.ProbeType.Center = [x, y, z]
    return location.PointData.GetArray("T").GetRange()[0]


# ----------------------------------------------------------------
# create a new 'Stream Tracer'
# ----------------------------------------------------------------

streamTracer1 = StreamTracer(
    registrationName="StreamTracer1", Input=casefoam, SeedType="Point Cloud"
)
streamTracer1.Vectors = ["POINTS", "U"]
streamTracer1.MaximumStreamlineLength = 12.600000381469727
streamTracer1.SeedType.Center = [
    width / 2,
    depth / 2,
    height / 2,
]
streamTracer1.SeedType.NumberOfPoints = int(width // 2 * 500)
streamTracer1.SeedType.Radius = width // 1.2

# ----------------------------------------------------------------
# CREATE T LUT COLOR LOOKUP TABLE
# ----------------------------------------------------------------

tLUT = GetColorTransferFunction("T")
tLUT.RGBPoints = T_LUT_RGB_POINTS
tLUT.ColorSpace = "RGB"
tLUT.NanColor = [1.0, 0.0, 0.0]
tLUT.ScalarRangeInitialized = 1.0

# ----------------------------------------------------------------
# CREATE A SLICE
# ----------------------------------------------------------------
slice1 = Slice(registrationName="Slice1", Input=casefoam, SliceType="Plane")
slice1.SliceType.Origin = [0, 0, 0.3]
slice1.SliceType.Normal = [0, 0, 1]

# ----------------------------------------------------------------
# CREATE A SLICE DISPLAY WITH T LUT
# ----------------------------------------------------------------
slice1Display = Show(slice1, renderView1, "GeometryRepresentation")
slice1Display.Representation = "Surface"
slice1Display.ColorArrayName = ["POINTS", "T"]
slice1Display.LookupTable = tLUT
slice1Display.Opacity = 1

# ----------------------------------------------------------------
# export airflow csv
# ----------------------------------------------------------------

logging.basicConfig(
    filename="csv_generation.log",
    filemode="w",
    format="%(name)s - %(levelname)s - %(message)s",
)
Path("/data/airflow").mkdir(parents=True, exist_ok=True)
Path("/data/thermal").mkdir(parents=True, exist_ok=True)
try:
    streamTracer1_data = Fetch(streamTracer1)
    points = numpy_support.vtk_to_numpy(streamTracer1_data.GetPoints().GetData())
    processed_points = np.stack(points, axis=1)
    point_datas = streamTracer1_data.GetPointData()
    point_datas_len = point_datas.GetNumberOfArrays()
    csv_attributes = {
        "T": True,
        "U": True,
        "alphat": False,
        "epsilon": False,
        "k": False,
        "nut": False,
        "p": False,
        "p_rgh": False,
        "IntegrationTime": True,
        "Vorticity": False,
        "Rotation": False,
        "AngularVelocity": False,
        "Normals": False,
    }
    data_obj = {
        "Points_0": processed_points[0],
        "Points_1": processed_points[1],
        "Points_2": processed_points[2],
    }
    for x in range(point_datas_len):
        name = point_datas.GetArrayName(x)
        if csv_attributes[f"{name}"]:
            arr = numpy_support.vtk_to_numpy(point_datas.GetArray(x))
            if arr.ndim > 1:
                processed_arr = np.stack(arr, axis=1)
                for i in range(len(processed_arr)):
                    data_obj[f"{name}_{i}"] = processed_arr[i]
            else:
                data_obj[f"{name}"] = arr

    data = pd.DataFrame(data=data_obj)
    data.to_csv("/data/airflow/airflow.csv", index_label="Point ID")
except Exception as e:
    logging.critical(e, exc_info=True)

# ----------------------------------------------------------------
# export thermal csv
# ----------------------------------------------------------------

try:
    casefoam_data = Fetch(casefoam).GetBlock(0)
    points = numpy_support.vtk_to_numpy(casefoam_data.GetPoints().GetData())
    processed_points = np.stack(points, axis=1)
    point_datas = casefoam_data.GetPointData()
    point_datas_len = point_datas.GetNumberOfArrays()
    csv_attributes = {
        "T": True,
        "U": True,
        "alphat": False,
        "epsilon": False,
        "k": False,
        "nut": False,
        "p": False,
        "p_rgh": False,
    }

    data_obj = {
        "Points_0": processed_points[0],
        "Points_1": processed_points[1],
        "Points_2": processed_points[2],
    }
    for x in range(point_datas_len):
        name = point_datas.GetArrayName(x)
        if csv_attributes[f"{name}"]:
            arr = numpy_support.vtk_to_numpy(point_datas.GetArray(x))
            if arr.ndim > 1:
                processed_arr = np.stack(arr, axis=1)
                for i in range(len(processed_arr)):
                    data_obj[f"{name}_{i}"] = processed_arr[i]
            else:
                data_obj[f"{name}"] = arr

    final_data_obj = {}
    target_number_of_points = 250000
    divider = math.ceil(len(data_obj["Points_0"]) / target_number_of_points)
    for i in range(len(data_obj["Points_0"])):
        if i % divider == 0:
            for attributes in data_obj.keys():
                if attributes not in final_data_obj:
                    final_data_obj[attributes] = []
                final_data_obj[attributes].append(data_obj[attributes][i])
    data = pd.DataFrame(data=final_data_obj)
    data.to_csv("/data/thermal/thermal.csv", index_label="Point ID")

    print(f'thermal: {len(data_obj["Points_0"])}')
    print(f"divider: {divider}")
    print(f'thermal_reduced: {len(final_data_obj["Points_0"])}')

except Exception as e:
    logging.critical(e, exc_info=True)


# ----------------------------------------------------------------
# GENERATE THERMAL SLICE GLTF
# ----------------------------------------------------------------
Hide(casefoam, renderView1)
Hide(streamTracer1, renderView1)
Show(slice1, renderView1)
Path("/data/thermal").mkdir(parents=True, exist_ok=True)
for index in range(10):
    temp_height = index * (height / 10)
    if temp_height == 0:
        temp_height = 0.1
    if temp_height == height:
        temp_height = height - 0.1
    slice1.SliceType.Origin = [0, 0, temp_height]
    ExportView(
        f"/data/thermal/thermal_slice_{index}_.gltf", view=renderView1, InlineData=1
    )
    Show(slice1, renderView1)
    SaveScreenshot(f"/data/thermal/thermal_slice_{index}_.png", renderView1)

# ----------------------------------------------------------------
# GENERATE PROBES LIST
# ----------------------------------------------------------------
if not is_modulus:
    results = {"servers": [], "acus": [], "servers_data": []}
    with open("/data/probes.json") as f:
        probes = json.load(f)
    try:
        servers = probes["servers"]
        acus = probes["acus"]
    except KeyError:
        print(probes)
    else:
        for data in servers:
            inlet = data[0]
            outlet = data[1]
            serverId = data[2]
            item = [
                get_temperature(inlet["x"], inlet["y"], inlet["z"]),
                get_temperature(outlet["x"], outlet["y"], outlet["z"]),
            ]
            serverData = {
                "id": serverId,
                "inlet_location": inlet,
            }
            results["servers"].append(item)
            results["servers_data"].append(serverData)
        for data in acus:
            inlet, outlet = data
            item = [
                get_temperature(inlet["x"], inlet["y"], inlet["z"]),
                get_temperature(outlet["x"], outlet["y"], outlet["z"]),
            ]
            results["acus"].append(item)
        with open("/data/results.json", "w") as f:
            json.dump(results, f)
