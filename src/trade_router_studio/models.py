from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
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
    environment: ProviderEnvironment | Literal["both"] = ProviderEnvironment.PAPER
    display_name: str | None = Field(default=None, max_length=128)
    app_key: str | None = None
    app_secret: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_provider_fields(self) -> ProfileRegistration:
        if self.provider == "simulated":
            if self.environment == "both":
                raise ValueError("시뮬레이션은 공용 프로필 등록을 사용하지 않습니다.")
            return self
        if not (self.app_key or "").strip():
            raise ValueError("App Key를 입력하세요.")
        if not (self.app_secret or "").strip():
            raise ValueError("App Secret을 입력하세요.")
        return self


class AccountRegistration(BaseModel):
    alias: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    profile_id: str
    account_number: str = Field(min_length=1, max_length=64)
    risk: RiskLimits = Field(default_factory=RiskLimits)
