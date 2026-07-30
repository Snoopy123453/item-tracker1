from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    location: str = ""
    depth: Literal["Standard", "Deep"] = "Standard"
    force_refresh: bool = False
    max_results: int = Field(default=25, ge=1, le=100)


class ResearchJob(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    query: str
    progress: int = 0
    stage: str = "Queued"
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {}
    error: str | None = None


class ApprovalUpdate(BaseModel):
    status: str
    notes: str = ""
    actor: str = ""
