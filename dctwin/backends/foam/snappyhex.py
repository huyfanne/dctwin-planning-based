import os
from pathlib import Path

from loguru import logger
from typing import Optional

from dctwin.backends.core import Backend
from dctwin.backends.core_k8s import BackendK8s
from dctwin.backends.foam.utils import (
    init_foam,
    generate_block_dict,
    generate_snappy_dict,
)
from dctwin.utils import config
from dctwin.models import Room


class SnappyHexBackendMixin:
    """
    Backend for snappyHexMesh. The class is inherited from the core Backend.
    """

    docker_image = "ghcr.io/cap-dcwiz/openfoam-v1912-centos72:latest"
    perforated_openings = {}

    @property
    def command(self) -> str:
        if self.process_num > 1:
            topo_set_command = ""
            if len(self.perforated_openings) > 0:
                topo_set_command = "topoSet &&"

            command = [
                "bash",
                "-c",
                (
                    "source /opt/OpenFOAM/setImage_v1912.sh && "
                    "blockMesh && surfaceFeatureExtract && "
                    "decomposePar -copyZero -force && "
                    "mpirun --allow-run-as-root -np "
                    f"{self.process_num} snappyHexMesh -parallel -overwrite && "
                    "reconstructParMesh -constant -mergeTol 6 && "
                    f"{topo_set_command}"
                    "createPatch -overwrite && "
                    "rm -rf /data/constant/triSurface/*.eMesh && "
                    "rm -rf /data/processor*"
                ),
            ]
            # command=["bash", "-c", f"sleep infinity"]
        else:
            command = [
                "bash",
                "-c",
                (
                    "source /opt/OpenFOAM/setImage_v1912.sh && "
                    "blockMesh && surfaceFeatureExtract && snappyHexMesh -overwrite && "
                    "createPatch -overwrite && rm -rf /data/constant/triSurface/*.eMesh"
                ),
            ]

        return command

    def run(
        self,
        room: Room,
        process_num: int = None,
        field_config: Optional[dict] = None,
    ) -> None:
        if process_num is not None:
            self.process_num = process_num

        # check perforated tile opening angle
        if (
            room.constructions.raised_floor
            and room.constructions.raised_floor.geometry.openings
        ):
            for (
                key,
                opening,
            ) in room.constructions.raised_floor.geometry.openings.items():
                if opening.velocity:
                    self.perforated_openings[key] = opening

        init_foam()
        generate_block_dict(room)
        generate_snappy_dict(
            room=room,
            process_num=self.process_num,
            field_config=field_config,
            perforated_openings=self.perforated_openings,
        )

        if config.cfd.dry_run:
            return

        host_path = os.environ.get("HOST_PATH", None)
        if host_path is not None:
            # concatenate the log path in Docker container with external host path
            log_index = config.cfd.case_dir.parts.index("log")
            case_dir = "/".join(config.cfd.case_dir.parts[log_index:])
            case_dir = Path(host_path).joinpath(case_dir)
            logger.info(f"Concatenated Case Directory: {case_dir}")
        else:
            case_dir = config.cfd.case_dir

        self.run_container(user=0, case_dir=case_dir)

        logger.info("***** Mesh finished *****\n\n")


class SnappyHexBackend(SnappyHexBackendMixin, Backend):
    pass


class SnappyHexBackendK8s(SnappyHexBackendMixin, BackendK8s):
    pass
