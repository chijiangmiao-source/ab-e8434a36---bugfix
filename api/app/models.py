"""Pydantic schemas for the audit API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EndmemberIn(BaseModel):
    # All values arrive as raw text so the backend can report precise,
    # field-localised parse errors without the client losing its edits.
    model_config = ConfigDict(extra="ignore")

    id: str = Field(...)
    t0: str = Field(...)
    t1: str = Field(...)
    t2: str = Field(...)
    cost: str = Field(...)


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endmembers: list[EndmemberIn]
    target: tuple[str, str, str]


class WeightOut(BaseModel):
    id: str
    fraction: str  # canonical "p/q" (or "p" when q == 1)
    numerator: int
    denominator: int
    decimal: float


class SolutionOut(BaseModel):
    ids: list[str]
    weights: list[WeightOut]
    cost: int


class FieldError(BaseModel):
    field: str
    message: str


class AuditResponse(BaseModel):
    feasible: bool
    solution: SolutionOut | None = None
    # Only the first page of cost-tied solutions (canonical order); the full
    # set is available through /api/audit/ties.  tie_count and classification
    # always reflect every tied solution, not just this preview.
    tied: list[SolutionOut] = []
    tie_count: int = 0
    classification: dict[str, str] = {}
    errors: list[FieldError] = []


class TiePageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endmembers: list[EndmemberIn]
    target: tuple[str, str, str]
    offset: int = 0
    limit: int = 24


class TiePageResponse(BaseModel):
    feasible: bool = False
    tie_count: int = 0
    offset: int = 0
    limit: int = 0
    tied: list[SolutionOut] = []
    errors: list[FieldError] = []
