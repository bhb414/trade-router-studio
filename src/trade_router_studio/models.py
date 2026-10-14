from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScriptRecord(BaseModel):
    strategy_id: str
    source: str
    source_hash: str
    desired_running: bool = False
    created_at: datetime
    updated_at: datetime


class ProcessStatus(BaseModel):
    strategy_id: str
    state: Literal["stopped", "starting", "running", "backoff", "failed"]
    desired_running: bool = False
    pid: int | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    restart_count: int = 0
    exit_code: int | None = None
    message: str | None = None


class ScriptUpdate(BaseModel):
    source: str = Field(min_length=1, max_length=262_144)


class StrategyRegistration(BaseModel):
    id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    trading_account: str
    market_data: str
