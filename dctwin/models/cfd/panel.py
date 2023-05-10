"""Panel model
"""
from typing import Optional, OrderedDict
from pydantic import Field

from .basics import Opening
from .utils import BaseModel


class PanelGeometry(BaseModel):
    height: float
    openings: OrderedDict[str, Opening] = Field(default_factory=dict)


class Panel(BaseModel):
    geometry: PanelGeometry
    meta: Optional[OrderedDict] = Field(default_factory=dict)
