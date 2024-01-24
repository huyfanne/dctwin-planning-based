class DCTwinError(Exception):
    def __init__(self, *args, **kwargs):  # real signature unknown
        pass


class CFDConfigError(DCTwinError):
    def __init__(self, *args, **kwargs):  # real signature unknown
        pass


class EplusConfigError(DCTwinError):
    def __init__(self, *args, **kwargs):  # real signature unknown
        pass


class PODConfigError(DCTwinError):
    def __init__(self, *args, **kwargs):  # real signature unknown
        pass


class GeometryBuildError(OSError):
    """File not found."""

    def __init__(self, *args, **kwargs):  # real signature unknown
        pass


class MeshBuildError(OSError):
    """File not found."""

    def __init__(self, *args, **kwargs):  # real signature unknown
        pass


class FoamSolveError(OSError):
    """File not found."""

    def __init__(self, *args, **kwargs):  # real signature unknown
        pass
