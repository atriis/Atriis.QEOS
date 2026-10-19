from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
MAX_SUITE_CASES = 1000


class SuiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    description: Optional[str] = Field(None, max_length=2000)


class SuiteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[Name] = None
    description: Optional[str] = Field(None, max_length=2000)


class SuiteCasesIn(BaseModel):
    """The suite's whole ordered list of case numbers: adds, removes and reorders at once."""

    model_config = ConfigDict(extra="forbid")

    cases: List[Annotated[int, Field(ge=1)]] = Field(max_length=MAX_SUITE_CASES)


class SuiteOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    case_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    origin: str = "manual"
    workflow: Optional[str] = None
    group_name: Optional[str] = None
    external_id: Optional[str] = None
    shard: Optional[str] = None
    test_paths: Optional[List[str]] = None
    source_repo: Optional[str] = None


class SuiteCaseOut(BaseModel):
    number: int
    key: str
    title: str
    status: str
    priority: str
    labels: List[str]
    automated_test_key: Optional[str] = None
    source_path: Optional[str] = None  # null for a manual case: a suite run skips those


class SuiteDetail(SuiteOut):
    cases: List[SuiteCaseOut]
