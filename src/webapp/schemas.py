from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PlanParams(BaseModel):
    week_start: str
    days: int = 7
    grid: int = 5
    beam_width: int = 5
    levels: int = 3
    n_workers: int = 8
    time_block: bool = False
    # robust-ensemble size (Stage 6 #9); jobs.run_plan_job reads it with default 4
    n_scenarios: int = Field(default=4, ge=2, le=8)


class PlanCreated(BaseModel):
    plan_id: str
    status: str


class SetpointEdit(BaseModel):
    crah_supply_air_temperature_c: float
    crah_supply_air_mass_flow_rate_kg_s: float
    chilled_water_supply_temperature_c: float
