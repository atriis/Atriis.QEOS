from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from src.casebook.service.import_service import normalise_path


class ImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str

    @field_validator("path", "content")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("must not contain a NUL character")  # PostgreSQL text cannot store it
        return value

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return normalise_path(value)  # ValueError -> 422


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: List[ImportFile] = Field(min_length=1)
    full: bool = False
    allow_mass_archive: bool = False
    expected_plan_hash: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$")
    # Repository suites (spec 2026-10-19 5.2): the suite workflow files, the patterns that found them (a
    # synced workflow they cover but did not send is deleted) and the repository they came from
    suite_files: Optional[List[ImportFile]] = None
    suite_patterns: Optional[List[Annotated[str, StringConstraints(min_length=1, max_length=200)]]] = Field(
        None, max_length=20)
    source_repo: Optional[str] = Field(None, max_length=200, pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

    @field_validator("files", "suite_files")
    @classmethod
    def _unique_paths(cls, files: Optional[List[ImportFile]]) -> Optional[List[ImportFile]]:
        paths = [f.path for f in files or []]
        if len(paths) != len(set(paths)):
            raise ValueError("the same path appears twice")
        return files

    @model_validator(mode="after")
    def _suite_files_need_patterns(self) -> "ImportRequest":
        if self.suite_files is not None and self.suite_patterns is None:
            raise ValueError("suite_files needs suite_patterns")
        return self


class ImportIssueOut(BaseModel):
    path: str
    line: Optional[int] = None
    message: str


class ImportItemOut(BaseModel):
    action: Literal["create", "update", "unchanged", "move", "reactivate", "archive", "skip"]
    path: str
    scenario: Optional[str] = None
    case_number: Optional[int] = None


class SuiteChangeOut(BaseModel):
    action: Literal["created", "updated", "deleted"]
    workflow: str
    external_id: str
    name: str


class SuiteWarningOut(BaseModel):
    workflow: str
    external_id: Optional[str] = None
    message: str


class ImportResult(BaseModel):
    plan_hash: str
    summary: dict
    items: List[ImportItemOut]
    errors: List[ImportIssueOut]
    warnings: List[ImportIssueOut]
    suite_changes: List[SuiteChangeOut] = []
    suite_warnings: List[SuiteWarningOut] = []
