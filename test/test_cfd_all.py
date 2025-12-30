from os import error

from dclib import Room
from dclib.models.geometry import Vertex
from loguru import logger
from dctwin.managers import CFDManager
from dctwin.utils import config
import json
import docker
import shutil
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
import os 
from datetime import datetime
import matplotlib.pyplot as plt
import fnmatch
from pathlib import Path
import pandas as pd
import traceback

class CFDExecutor:
    def __init__(self, room_config_path, preserve_foam_log=True, iterations=100):
        self.room = Room.load(room_config_path)
        self.room_cofig_path = room_config_path
        config.PRESERVE_FOAM_LOG = preserve_foam_log
        self.is_modulus = False
        self.case_dir = None
        self.residuals = []
        self.flow_rate_df = None
        self.residuals = None
        self.execution_time = None
        room_name = room_config_path.split("/")[-1].split(".")[0]
        config.cfd.case_dir = Path(f"log/{room_name}").absolute()
        config.LOG_DIR = Path(f"log/{room_name}").absolute()
        config.cfd.mesh_dir = Path("")
        logger.add(config.LOG_DIR / "base/cfd.log", rotation="300 MB")
        self.case_dir = config.LOG_DIR / "base"
        if self.room.meta.name == "TDC23v2(final)22":
            location_in_mesh = Vertex(x=1.2, y=1.2, z=0.)
        else:
            location_in_mesh = Vertex(x=0, y=0, z=0.)
        self.manager = CFDManager(
            room=self.room,
            solve_process=6,
            mesh_process=6,
            is_gpu=False,
            end_time=iterations,
            location_in_mesh=location_in_mesh
        )

    def execute(self):
        print("Executing CFD simulation...")
        self.manager.run()

    def prepare_probes(self):
        """
        Prepare the probes for the data hall CFD simulation.

        This method retrieves the positions of servers and ACUs in the data hall,
        and saves the probe information into probes.json.

        Returns:
            None
        """
        servers = []
        acus = []
        for server_id in self.room.constructions.server_keys:
            inlet_center, outlet_center, _ = (
                self.room.constructions.server_patch_positions(server_id)
            )
            result = [inlet_center.__dict__, outlet_center.__dict__, server_id]
            servers.append(result)
        for acu_id in self.room.constructions.acu_keys:
            return_center, supply_center, _ = (
                self.room.constructions.acu_patch_positions(acu_id)
            )
            result = [return_center.__dict__, supply_center.__dict__]
            acus.append(result)


        with open(self.case_dir / "probes.json", "w") as f:
            json.dump({"servers": servers, "acus": acus}, f)

    def run_parse_result_job(self):
        shutil.copy("./result.py", self.case_dir)
        client = docker.from_env()
        command = ["pvpython", "/data/result.py"]
        # command = ["sleep", "10000"]
        image = "ntucap/paraview"
        environment = {
            "WIDTH": str(
                max(i.x for i in self.room.geometry.plane)
                - min(i.x for i in self.room.geometry.plane)
            ),
            "DEPTH": str(
                max(i.y for i in self.room.geometry.plane)
                - min(i.y for i in self.room.geometry.plane)
            ),
            "HEIGHT": str(self.room.geometry.height),
            "IS_MODULUS": str(self.is_modulus),
            "MINIMUM_T_CELSIUS": str(15 if self.is_modulus else 15),
            "MAXIMUM_T_CELSIUS": str(30 if self.is_modulus else 45)
        }
        # Run the container
        container = client.containers.run(
            image=image,
            command=command,
            working_dir="/data",
            environment=environment,
            volumes={self.case_dir: {'bind': '/data', 'mode': 'rw'}},
            detach=True,
            remove=True
        )

        # Stream the logs
        logger.info("Parsing the result with paraview...")
        for line in container.logs(stream=True):
            logger.info(line.strip().decode())
        logger.info("Parsing completed with paraview...")
        container.wait()

    def create_pdf(self):

        file_path = str(self.case_dir / "result.pdf")
        c = canvas.Canvas(file_path, pagesize=letter)
        page_width, page_height = letter
        top_margin = 1 * cm
        bottom_margin = 1 * cm

        # Add a title at the top
        c.setFont("Helvetica-Bold", 18)
        y_position = page_height - top_margin
        room_name = self.room_cofig_path.split("/")[-1].split(".")[0]
        c.drawString(1 * cm, y_position, f"CFD Simulation Result Report for {room_name}")

        # Draw some text below the title
        c.setFont("Helvetica-Bold", 12)
        y_position -= 0.5 * cm  # Adjust the gap between the title and text
        text = "Execution time"
        c.drawString(1 * cm, y_position, text)
        y_position -= 0.5 * cm
        c.setFont("Helvetica", 12)
        for key, value in self.execution_time.items():
            text = f"{key}: {value:.2f} seconds"
            c.drawString(1 * cm, y_position, text)
            y_position -= 0.5 * cm

        # Define image size
        image_height = 10 * cm
        image_width = 16 * cm

        # Collect all PNG files
        image_paths = []
        for root, dirs, files in os.walk(self.case_dir / "thermal"):
            for file in files:
                if file.endswith('.png'):
                    image_path = os.path.join(root, file)
                    image_paths.append(image_path)

        # Sort the image paths by filename
        image_paths.sort()
        residual_path = self.case_dir / "initial_residuals.png"
        c.drawImage(residual_path, 1 * cm, y_position - image_height, width=image_width, height=image_height)
        y_position -= (image_height + 0.5 * cm)  # Adjust for spacing below the image
        c.drawString(1 * cm, y_position, "residual")
        y_position -= 0.5 * cm

        if y_position - image_height < bottom_margin:
            c.showPage()
            y_position = page_height - top_margin
        
        flow_rate_chart_path = self.case_dir / "flow_rate_line_chart.png"
        c.drawImage(flow_rate_chart_path, 1 * cm, y_position - image_height, width=image_width, height=image_height)
        y_position -= (image_height + 0.5 * cm)  # Adjust for spacing below the image
        c.drawString(1 * cm, y_position, "flow rate imbalance (m3/s)")
        y_position -= 0.5 * cm

        # Add images to the PDF
        for image_path in image_paths:
            # Check if the current page has enough space for another image
            if y_position - image_height < bottom_margin:
                c.showPage()
                y_position = page_height - top_margin

            c.drawImage(image_path, 1 * cm, y_position - image_height, width=image_width, height=image_height)

            y_position -= (image_height + 0.5 * cm)  # Adjust for spacing below the image
            c.drawString(1 * cm, y_position, image_path)
            y_position -= 0.5 * cm

        # Finalize the PDF
        c.showPage()
        c.save()
    def extract_execution_time(self):
        mesh_start = self.extract_datetime_from_logs("start meshing geometry")
        mesh_end = self.extract_datetime_from_logs("Mesh finished")
        solver_start = self.extract_datetime_from_logs("start running CFD solver")
        solver_end = self.extract_datetime_from_logs("Reading temperature from")
        paraview_start = self.extract_datetime_from_logs("Parsing the result with paraview")
        paraview_end = self.extract_datetime_from_logs("Parsing completed with paraview")
        total_start = mesh_start  # Assume the entire process starts with geometry
        total_end = paraview_end  # Assume the entire process ends with paraview
        if mesh_start and mesh_end:
            mesh_time = (mesh_end - mesh_start).total_seconds()
        if solver_start and solver_end:
            solver_time = (solver_end - solver_start).total_seconds()
        if paraview_start and paraview_end:
            paraview_time = (paraview_end - paraview_start).total_seconds()
        if total_start and total_end:
            total_time = (total_end - total_start).total_seconds()
        self.execution_time = {
            "mesh_time": mesh_time,
            "solver_time": solver_time,
            "paraview_time": paraview_time,
            "total_time": total_time
        }
        print(self.execution_time)


    def extract_datetime_from_logs(self, search_string):
        # Escape special characters in user-defined search string for regex
        # Replace 'your_log_file.log' with the path to your log file
        log_file_path = self.case_dir/"cfd.log"

        with open(log_file_path, 'r') as file:
            for line in file:
                if search_string in line:
                    datetime_str = line.split(' | ')[0]
                    datetime_format = "%Y-%m-%d %H:%M:%S.%f"
                    log_datetime = datetime.strptime(datetime_str, datetime_format)
                    return log_datetime
    def extract_iteration_residuals(self):
        log_file_path = self.case_dir / "cfd.log"
        residuals = []

        with open(log_file_path, 'r') as file:
            lines = file.readlines()
            for i, line in enumerate(lines):
                if "Time = " in line and "ClockTime" not in line:
                    ux_initial_residual, ux_final_residual = self.extract_residual_float(i, lines, "Ux")
                    uy_initial_residual, uy_final_residual = self.extract_residual_float(i, lines, "Uy")
                    uz_initial_residual, uz_final_residual = self.extract_residual_float(i, lines, "Uz")
                    T_initial_residual, T_final_residual = self.extract_residual_float(i, lines, "T")
                    epsilon_initial_residual, epsilon_final_residual = self.extract_residual_float(i, lines, "epsilon")
                    k_initial_residual, k_final_residual = self.extract_residual_float(i, lines, "Solving for k")
                    residual = {
                        "ux_initial_residual": ux_initial_residual, "ux_final_residual": ux_final_residual,
                        "uy_initial_residual": uy_initial_residual, "uy_final_residual": uy_final_residual,
                        "uz_initial_residual": uz_initial_residual, "uz_final_residual": uz_final_residual,
                        "T_initial_residual": T_initial_residual, "T_final_residual": T_final_residual,
                        "epsilon_initial_residual": epsilon_initial_residual,
                        "epsilon_final_residual": epsilon_final_residual,
                        "k_initial_residual": k_initial_residual, "k_final_residual": k_final_residual
                    }

                    if None in [ux_initial_residual, ux_final_residual, uy_initial_residual, uy_final_residual,
                                uz_initial_residual, uz_final_residual, T_initial_residual, T_final_residual,
                                epsilon_initial_residual, epsilon_final_residual, k_initial_residual, k_final_residual]:
                        continue

                    residuals.append(residual)
        self.residuals = residuals
        print(len(residuals))
        return residuals

    def extract_residual_float(self, i, lines, key):
        for offset in range(1, 20):
            current_line = lines[i + offset]
            if "Time = " in current_line:
                return None, None
            if key in current_line:
                initial_residual = self.extract_value(current_line, "Initial residual =")
                final_residual = self.extract_value(current_line, "Final residual =")
                return initial_residual, final_residual
        return None, None


    def extract_value(self, line, key):
        """
        Extracts a float value from line given a specific key.

        Parameters:
        line (str): The line from which to extract the value.
        key (str): The key indicating the value's position.

        Returns:
        float or None: The extracted float value, or None if parsing fails.
        """
        start = line.find(key)
        if start != -1:
            start += len(key)
            end = line.find(',', start)
            if end == -1:
                end = None  # Ensures we capture the entire string till end if there is no comma
            value_str = line[start:end].strip()
            try:
                return float(value_str)
            except ValueError:
                pass
        return None

    def create_residual_line_chart(self):
        if self.residuals is None:
            self.extract_iteration_residuals()
        if self.residuals:
            fig, ax = plt.subplots()
            for key in self.residuals[0].keys():
                if "initial" in key:
                    ax.plot([i[key] for i in self.residuals], label=key)
            ax.set_xlabel("Iteration")
            ax.set_ylabel("Residual")
            ax.set_yscale("log")
            ax.set_title("Initial Residuals")
            ax.legend()
            plt.savefig(self.case_dir / "initial_residuals.png")
            plt.close()
            fig, ax = plt.subplots()
            for key in self.residuals[0].keys():
                if "final" in key:
                    ax.plot([i[key] for i in self.residuals], label=key)
            ax.set_xlabel("Iteration")
            ax.set_ylabel("Residual")
            ax.set_yscale("log")
            ax.set_title("Final Residuals")
            ax.legend()
            plt.savefig(self.case_dir / "final_residuals.png")
            plt.close()
        else:
            print("No residuals found")
        return self.residuals

    def flow_rate_monitor(self):
        logger.info("Parsing flow rate...")
        postprocessing_path = self.case_dir / "postProcessing"
        patch_names = []

        for (root, dirs, files) in os.walk(postprocessing_path): #Checks all files in postProcessing folder
            
            for file in files:
                if file.endswith('.dat') and not(file.startswith("yPlus")): # Checks for .dat file
                
                # Sequence to find correct renamed file
                    patch_dir = (Path(root).parent / "0" / "surfaceFieldValue.dat") # Finds surfacefieldvalue which contains flowrate

                    if patch_dir.exists():
                        patch_dir = \
                        patch_dir.rename(Path(patch_dir.parent, f"{Path(root).parent.name}.dat")) # Renames file
                    else:
                        patch_dir = Path(root).parent / "0" / f"{Path(root).parent.name}.dat" # If file was already renamed
                    
                    patch_names.append(patch_dir)
                    # Correct file found, extract contents

        df_patch = pd.DataFrame()
        #print(patch_names)
        

        for patch_name in patch_names:
            try:

                patch_flow_rate = pd.read_csv(patch_name, skiprows=5, header=None,sep='\t',usecols=[1])
                patch_flow_rate.rename(columns={1: f"{patch_name.stem}"}, inplace=True)
            
                df_patch = pd.concat([df_patch, patch_flow_rate], axis=1)
            except Exception as e:
                logger.info(f"Error concatenating patch {patch_name}: {e}")
                continue

        df_patch['net_mass_flow_rate'] = df_patch.sum(axis=1)
        df_patch['net_mass_flow_rate_abs'] = df_patch['net_mass_flow_rate'].abs()    
        df_patch.to_csv(self.case_dir / "flow_rate.csv")

        self.flow_rate_df = df_patch
        return self.flow_rate_df
    
    def flow_rate_line_chart(self):

        if self.flow_rate_df is None:
            self.flow_rate_monitor()

        if self.flow_rate_df is not None:
            logger.info("Creating flow rate line chart...")
            fig, ax = plt.subplots()
            ax.plot(self.flow_rate_df.index, self.flow_rate_df['net_mass_flow_rate_abs'])
            ax.set_xlabel("Timestep")
            ax.set_ylabel("Flow Rate Imbalance [m3/s]")
            ax.set_yscale("log")
            ax.set_title("Flow Rate Imbalance")
            
            plt.savefig(self.case_dir / "flow_rate_line_chart.png")
            plt.close()
            return self.flow_rate_df
        else:
            logger.info("No flow rate data found")
            return None


    def yplus_parsing(self):

        postprocessing_path = self.case_dir / "postProcessing"
        yplus_path = postprocessing_path / "yPlusWallFunction" / "0" / "yPlus.dat"

        df = pd.read_csv(yplus_path, sep=r'\s+', comment='#', 
                 names=['Time', 'patch','min', 'max', 'average'])

        # ABSOLUTE CINEMA - cursor found this solution not me 
        # Pivot: patches as rows, times as columns (using average column)
        df_pivot = df.pivot(index='patch', columns='Time', values='average').reset_index()

        # Rename time columns to 'time=1', 'time=2', etc.
        df_pivot.columns = ['patch'] + [f'time={int(col)}' for col in df_pivot.columns[1:]]
        
        yPlus_mean = df_pivot.iloc[:,-1].mean()
        yPlus_max = df_pivot.iloc[:,-2].max()
        logger.info(f"Average yPlus of all walls: {yPlus_mean}")
        logger.info(f"Maximum yPlus of all walls: {yPlus_max}")
        #return yPlus_mean


    def avg_T_parsing(self):
        pass
    def add_to_csv_report(self, failed=False, error="NA", traceback_message="NA"):
        column_titles = ['case', 'succeeded', 'error', 'traceback', 'mesh time', 'solver time', 'paraview time', 'total time', 'ux_final_residual', 'uy_final_residual', 'uz_final_residual', 'T_final_residual', 'epsilon_final_residual', 'k_final_residual']
        if failed:
            new_data = [[self.room_cofig_path, 'False', error, traceback_message,"NA", "NA", "NA", "NA", "NA", "NA", "NA", "NA", "NA", "NA"]]
        else:
            new_data = [[self.room_cofig_path, 'True', error, traceback_message, self.execution_time['mesh_time'], self.execution_time['solver_time'], self.execution_time['paraview_time'], self.execution_time['total_time'], self.residuals[-1]['ux_final_residual'], self.residuals[-1]['uy_final_residual'], self.residuals[-1]['uz_final_residual'], self.residuals[-1]['T_final_residual'], self.residuals[-1]['epsilon_final_residual'], self.residuals[-1]['k_final_residual']]]
        new_df = pd.DataFrame(new_data, columns=column_titles)
        file_path = 'log/combined_result.csv'
        # Check if the file already exists
        if not os.path.isfile(file_path):
            new_df.to_csv(file_path, index=False, header=True)
        else:
            new_df.to_csv(file_path, mode='a', index=False, header=False)

    def __call__(self, *args, **kwargs):
        #self.execute()
        self.prepare_probes()
        self.run_parse_result_job()
        self.extract_execution_time()
        self.create_residual_line_chart()
        
        self.add_to_csv_report()
        self.flow_rate_monitor()
        self.flow_rate_line_chart()
        self.create_pdf()
        self.yplus_parsing()
        return self

# Example of how to use the CFDExecutor class
if __name__ == "__main__":
    directory = "models/geometry/ba1604"
    csv_path = "log/combined_result.csv"
    if os.path.isfile(csv_path):
        os.remove(csv_path)
    for root, dirs, files in os.walk(directory):
        for filename in fnmatch.filter(files, '*.json'):
            room_path = os.path.join(root, filename)
            try:
                executor = CFDExecutor(room_path)
            except Exception as e:
                print(f"Failed to initialize CFDExecutor for {room_path}, Error {e}")
            try:
                executor()
            except Exception as e:
                traceback_message = traceback.format_exc()
                print(f"Failed to execute CFD simulation for {room_path}")
                executor.add_to_csv_report(failed=True, error=str(e), traceback_message=traceback_message)
