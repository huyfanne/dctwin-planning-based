import os
import typing
from pathlib import Path


class Environ:
    CASE_DIR: Path

    def __init__(self, env: typing.MutableMapping = os.environ, base_size: float = 0.2):
        self._environ = env
        self.CASE_DIR = self._environ.get("CASE_DIR", Path("case").absolute())

        # backend
        backend_log_print = self._environ.get("BACKEND_LOG_PRINT", "true").lower()
        self.BACKEND_LOG_PRINT: bool = _backend_log_print == "true"
        self.base_size: float = base_size

    def set_case_dir(self, case_dir: typing.Union[str, Path]) -> None:
        self.CASE_DIR = Path(case_dir)

    @property
    def geometry_dir(self):
        return Path(self.CASE_DIR, "constant/triSurface")


environ = Environ()
