"""Strict API contracts for broker safety reporting."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BrokerApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanaryReadinessResponse(BrokerApiModel):
    schema_version: int = 1
    status: Literal[
        "NO_EVIDENCE",
        "REHEARSING",
        "REHEARSAL_TARGET_MET",
        "ACTION_REQUIRED",
        "INTEGRITY_ERROR",
    ]
    rehearsal_count: int = Field(ge=0)
    qualifying_rehearsal_count: int = Field(ge=0)
    gslo_rehearsal_count: int = Field(ge=0)
    failed_rehearsal_count: int = Field(ge=0)
    unresolved_failure_count: int = Field(ge=0)
    required_rehearsals: int = Field(ge=1)
    remaining_rehearsals: int = Field(ge=0)
    operational_rehearsal_target_met: bool
    all_positions_verified_closed: bool
    practice_entry_orders_submitted: int = Field(ge=0)
    practice_close_orders_submitted: int = Field(ge=0)
    live_orders_submitted: Literal[0] = 0
    latest_rehearsal_id: str | None
    latest_completed_at_utc: datetime | None
    latest_instrument: str | None
    latest_failure_at_utc: datetime | None
    latest_failure_stage: str | None
    latest_loss_budget_gbp: str | None
    latest_worst_case_loss_gbp: str | None
    latest_gslo_premium_gbp: str | None
    live_canary_build_enabled: Literal[False] = False
    live_execution_locked: Literal[True] = True
    live_trading_allowed: Literal[False] = False
    network_calls_made: Literal[0] = 0
    files_changed: Literal[0] = 0
    blocking_issues: list[str]
    next_actions: list[str]
