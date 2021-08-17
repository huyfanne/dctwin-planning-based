from typing import Union
from pathlib import Path


def read_internal_field(filename: Union[str, Path]):
    with open(filename) as f:
        started = False
        for line in f:
            if line.strip().startswith("internalField"):
                started = True
                yield line[len("internalField") :]
            elif started:
                if ";" not in line:
                    yield line
                else:
                    return
            else:
                continue
