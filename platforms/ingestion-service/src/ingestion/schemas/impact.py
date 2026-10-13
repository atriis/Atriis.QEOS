"""Test impact answers (spec 2026-10-12 §3.5, §9; plan Rulings 17-19)."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class ImpactTestOut(BaseModel):
    test_key: str
    suite: str
    class_name: str
    name: str


class ImpactEvidenceOut(BaseModel):
    path_unit: str
    changed_runs: int
    new_failures: int
    confidence: float
    lift: Optional[float] = None       # None when the test never newly failed otherwise (base rate 0)
    base_rate: Optional[float] = None


class SuggestedTestOut(ImpactTestOut):
    kind: Literal["statistical", "test_file_changed", "failing_on_branch", "no_history"]
    evidence: Optional[ImpactEvidenceOut] = None


class SuggestionOut(BaseModel):
    # `model_version` is in pydantic's protected "model_" namespace: opt out, so the JSON name stays and no warning
    model_config = ConfigDict(protected_namespaces=())

    state: Literal["ok", "not_enough_history"]
    model_version: str
    history_runs: int
    needed_runs: int
    statistical_total: int
    tests: List[SuggestedTestOut]


class OutcomeOut(BaseModel):
    evaluated_at: datetime
    caught: List[ImpactTestOut]
    missed: List[ImpactTestOut]


class RunImpactOut(BaseModel):
    run_id: int
    state: Literal["ok", "not_enough_history", "no_change_data", "not_scored"]
    changed_paths: List[str]
    replayed: bool = False
    scored_at: Optional[datetime] = None
    suggestion: Optional[SuggestionOut] = None
    outcome: Optional[OutcomeOut] = None
    # not_evaluated: the run ran only the suggested tests (spec 2026-10-13 §3.1); None without a stored suggestion
    evaluation: Optional[Literal["pending", "evaluated", "not_evaluated"]] = None


class AccuracyPartOut(BaseModel):
    runs: int
    caught: int
    missed: int
    suggested: int  # tests suggested over those runs


class MissOut(ImpactTestOut):
    run_id: int
    started_at: datetime
    branch: Optional[str] = None
    replayed: bool


class ImpactAccuracyOut(BaseModel):
    days: int
    caught: int
    missed: int
    rate: Optional[float] = None           # caught / (caught + missed); None without new failures
    avg_suggested: Optional[float] = None  # suggested tests per run counted (spec §9); None without runs
    includes_replayed: bool
    live: AccuracyPartOut
    replayed: AccuracyPartOut
    misses: List[MissOut]
    misses_total: int
