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


# Number of tied solutions inlined in the first audit response.  With up to
# 30 endmembers and identifiers that may each be ~1000 characters, the full
# tie set can be tens of megabytes; the remaining solutions are paged via
# POST /api/audit/ties without any change to tie_count or classification.
TIE_PAGE_SIZE = 20


class TiePageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endmembers: list[EndmemberIn]
    target: tuple[str, str, str]
    offset: int = Field(0, ge=0)
    limit: int = Field(TIE_PAGE_SIZE, ge=1, le=TIE_PAGE_SIZE)


class TiePageOut(BaseModel):
    # Canonical-order index of solutions[0] within the whole tie set.
    offset: int
    # Size of the whole first-two-level tie set (0 when infeasible).
    tie_count: int
    solutions: list[SolutionOut] = []
    errors: list[FieldError] = []


class AuditResponse(BaseModel):
    feasible: bool
    solution: SolutionOut | None = None
    # First page (canonical order) of the tied solutions only; never the full
    # tie set.  tie_count stays exact and classification still covers every
    # tied solution, both derived from the complete enumeration.
    tied: list[SolutionOut] = []
    tie_count: int = 0
    tie_offset: int = 0
    tie_page_size: int = TIE_PAGE_SIZE
    classification: dict[str, str] = {}
    errors: list[FieldError] = []
