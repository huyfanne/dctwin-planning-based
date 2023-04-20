"""Panel model
"""
from typing import Optional, OrderedDict
from pydantic import BaseModel, Field

from .basics import Opening


class PanelGeometry(BaseModel):
    height: float


class PanelConstruction(BaseModel):
    openings: OrderedDict[str, Opening] = Field(default_factory=dict)


class Panel(BaseModel):
    geometry: PanelGeometry
    constructions: Optional[PanelConstruction]
    meta: Optional[OrderedDict] = Field(default_factory=dict)
