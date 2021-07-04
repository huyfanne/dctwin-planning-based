import os
import typing
from decimal import Decimal
from pathlib import Path


class Environ:
    CASE_DIR: Path
    GEOMETRY_DIR: Path

    def __init__(self, env: typing.MutableMapping = os.environ, base_size: float = 0.2):
        self._environ = env
        self.CASE_DIR = self._environ.get('CASE_DIR', Path('case').absolute())
        self.GEOMETRY_DIR = self._environ.get(
            'GEOMETRY_DIR', Path(self.CASE_DIR, 'geometry')
        )
        self.base_size = Decimal(base_size)


environ = Environ()
