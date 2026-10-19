from datetime import datetime
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._-]{1,40}$")]
TestKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
Priority = Literal["low", "medium", "high", "critical"]
Status = Literal["draft", "ready", "archived"]


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    expected: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


def _labels(values: Optional[List[str]]) -> Optional[List[str]]:
    return None if values is None else sorted({v.lower() for v in values})


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Optional[str] = Field(None, max_length=10000)
    steps: List[Step] = Field(default_factory=list, max_length=50)
    labels: List[Label] = Field(default_factory=list, max_length=20)
    priority: Priority = "medium"
    status: Status = "draft"
    automated_test_key: Optional[TestKey] = None
    automated_name: Optional[str] = Field(None, max_length=1500)

    _norm_labels = field_validator("labels")(_labels)

    @field_validator("automated_test_key")
    @classmethod
    def _lower_key(cls, value):
        return value.lower() if value else value


class CaseUpdate(BaseModel):
    """Only the fields sent change. automated_test_key: null unlinks (and clears the name)."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[Title] = None
    description: Optional[str] = Field(None, max_length=10000)
    steps: Optional[List[Step]] = Field(None, max_length=50)
    labels: Optional[List[Label]] = Field(None, max_length=20)
    priority: Optional[Priority] = None
    status: Optional[Status] = None
    automated_test_key: Optional[TestKey] = None
    automated_name: Optional[str] = Field(None, max_length=1500)
    gherkin: Optional[str] = None  # accepted so the 422 for imported cases can name it; manual cases ignore it

    _norm_labels = field_validator("labels")(_labels)

    @field_validator("automated_test_key")
    @classmethod
    def _lower_key(cls, value):
        return value.lower() if value else value


class SuiteRef(BaseModel):
    id: int
    name: str


class CaseOut(BaseModel):
    number: int
    key: str
    title: str
    description: Optional[str] = None
    steps: List[Step]
    labels: List[str]
    priority: str
    status: str
    automated_test_key: Optional[str] = None
    automated_name: Optional[str] = None
    created_by: int
    created_at: datetime
    updated_by: Optional[int] = None
    updated_at: Optional[datetime] = None
    source_path: Optional[str] = None
    gherkin: Optional[str] = None
    feature_name: Optional[str] = None
    suites: List[SuiteRef] = []  # filled on the single-case read


class CaseList(BaseModel):
    total: int
    items: List[CaseOut]


class LabelCount(BaseModel):
    label: str
    count: int


Folder = Annotated[str, StringConstraints(max_length=500, pattern=r"^[^\x00]*$")]
AdoId = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,12}$")]


class CaseSearch(BaseModel):
    """POST /cases/search: GET /cases' filters in a body, plus the test keys of a latest-result filter."""
    model_config = ConfigDict(extra="forbid")

    search: Optional[Annotated[str, StringConstraints(max_length=200, pattern=r"^[^\x00]*$")]] = None
    search_in: Literal["scenario", "feature", "both"] = "scenario"
    labels: List[Label] = Field(default_factory=list, max_length=20)
    status: Optional[Status] = None
    priority: Optional[Priority] = None
    origin: Optional[Literal["manual", "imported"]] = None
    include_archived: bool = False
    folder: Optional[Folder] = None
    linked: Optional[bool] = None
    feature: Optional[Folder] = None
    ado: Optional[AdoId] = None
    suite: Optional[Literal["none"]] = None
    test_keys: Optional[List[TestKey]] = Field(None, max_length=20000)
    keys_mode: Literal["include", "exclude"] = "include"
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class FolderCount(BaseModel):
    path: str
    count: int


class FeatureCount(BaseModel):
    feature: str
    count: int
