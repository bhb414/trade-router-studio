from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from trade_router import ProviderEnvironment, RiskLimits


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


class ProfileRegistration(BaseModel):
    id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    provider: Literal["kis", "namuh", "simulated"]
    environment: ProviderEnvironment = ProviderEnvironment.PAPER
    display_name: str | None = Field(default=None, max_length=128)
    app_key: str | None = None
    app_secret: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class AccountRegistration(BaseModel):
    alias: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    profile_id: str
    account_number: str = Field(min_length=1, max_length=64)
    risk: RiskLimits = Field(default_factory=RiskLimits)
