import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, PrivateAttr, StringConstraints, ValidationError, field_validator,
    model_validator,
)

from src.ingestion.core.config import settings
from src.ingestion.models.run import FULL_SCOPE, SCOPES, SUBSET_SCOPE

# A CI runner's clock can drift a little; a day ahead means a broken clock or a bad payload
MAX_CLOCK_SKEW = timedelta(hours=1)
# The run's duration_ms is stored as a 32-bit integer (max ~24.8 days); no CI job runs for a week
MAX_RUN_SPAN = timedelta(days=7)

# NUL cannot be stored in a PostgreSQL text column, and a lone UTF-16 surrogate cannot be encoded
# as UTF-8; either one used to turn a valid-looking upload into a 500.
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def _replace_unstorable(value: Optional[str]) -> Optional[str]:
    """Free text (captured output) is never rejected: replace what cannot be stored."""
    return None if value is None else _UNSTORABLE.sub("�", value)


def _reject_unstorable(value: Optional[str]) -> Optional[str]:
    """Identity and metadata fields must be exact, so they are rejected rather than altered."""
    if value is not None and _UNSTORABLE.search(value):
        raise ValueError("must not contain NUL or unpaired surrogate characters")
    return value


def _text(max_length: int):
    return Annotated[str, StringConstraints(max_length=max_length)]


MAX_STAGE_SECONDS = MAX_RUN_SPAN.total_seconds()


class StageIn(BaseModel):
    """One stage of a run-impact run (spec 2026-10-13 §3.1, plan Ruling 6)."""

    model_config = ConfigDict(extra="forbid")

    name: Literal["suggested", "rest", "all"]
    duration_s: float = Field(ge=0, le=MAX_STAGE_SECONDS, allow_inf_nan=False)
    tests: int = Field(ge=0, le=2_147_483_647)
    failed: int = Field(ge=0, le=2_147_483_647)


class StagesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[StageIn] = Field(min_length=1, max_length=2)
    # From the start of stage 1 to the end of the first failing scenario; None without a failure
    time_to_first_failure_s: Optional[float] = Field(None, ge=0, le=MAX_STAGE_SECONDS, allow_inf_nan=False)
    stopped_after_stage: Optional[Literal[1]] = None  # --fail-fast stopped after a failing stage 1


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ci_provider: Literal["github_actions", "gitlab_ci", "jenkins", "azure_pipelines", "other", "local"]
    ci_run_url: Optional[Annotated[str, StringConstraints(max_length=2048, pattern=r"^https?://\S+$")]] = None
    commit_sha: Optional[Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{7,40}$")]] = None
    branch: Optional[_text(255)] = None
    environment: Optional[_text(100)] = None
    agent_version: Optional[_text(50)] = None
    commit_author: Optional[_text(255)] = None
    commit_message: Optional[_text(500)] = None  # first line is enough; collector truncates
    pr_number: Optional[int] = Field(None, ge=1, le=2_147_483_647)
    base_branch: Optional[_text(255)] = None
    # How the CI run started, as the collector classified it (ADR-030); absent: unknown, collected
    trigger: Optional[Literal["manual", "automatic", "qeos"]] = None
    # run-impact (spec 2026-10-13 §3.1): "impact-subset" when only the suggested tests ran; absent: a full run.
    # A split upload may send stages on every part; ingestion keeps them on the first part that has them
    scope: Literal[SCOPES] = FULL_SCOPE
    stages: Optional[StagesIn] = None
    started_at: AwareDatetime
    finished_at: AwareDatetime

    _no_unstorable = field_validator(
        "ci_run_url", "commit_sha", "branch", "environment", "agent_version",
        "commit_author", "commit_message", "base_branch", mode="before"
    )(_reject_unstorable)

    @model_validator(mode="after")
    def _times_make_sense(self):
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not be before started_at")
        if self.finished_at > datetime.now(timezone.utc) + MAX_CLOCK_SKEW:
            raise ValueError("finished_at is too far in the future")
        if self.finished_at - self.started_at > MAX_RUN_SPAN:
            raise ValueError("a run may not span more than 7 days")
        if self.stages is not None and self.stages.stopped_after_stage is not None and self.scope != SUBSET_SCOPE:
            raise ValueError(f"stopped_after_stage needs scope {SUBSET_SCOPE}: a run that stopped did not run in full")
        return self


class FailedStepIn(BaseModel):
    """The Cucumber step that failed (spec 2026-10-13 §2), and from collector 0.8.0 its step definition and its text
    with the matched arguments as {…} (spec 2026-10-14 §3.1). Unknown fields are ignored, not refused: a newer
    collector's addition must never cost the upload."""
    model_config = ConfigDict(extra="ignore")

    text: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    line: Optional[int] = Field(None, ge=1, le=1_000_000)
    definition: Optional[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = None
    pattern: Optional[Annotated[str, StringConstraints(min_length=1, max_length=1000)]] = None

    # Free text like message/details: replaced, never rejected
    _clean_text = field_validator("text", "definition", "pattern", mode="after")(_replace_unstorable)


MAX_SCREENSHOT_KEYS = 5  # ScreenshotIn's fields


class ScreenshotIn(BaseModel):
    """A step screenshot the collector already uploaded to PUT /collect/blobs/{sha256} (ADR-036): the run upload only
    refers to it. Strict, unlike failed_step: a collector that sends the field knows this shape."""
    model_config = ConfigDict(extra="forbid")

    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    step_text: Annotated[str, StringConstraints(max_length=1000)]
    step_line: Optional[int] = Field(None, ge=1, le=1_000_000)
    hook: Optional[Literal["before", "after"]] = None

    # Free text like the failed step's: replaced, never rejected
    _clean_text = field_validator("step_text", mode="after")(_replace_unstorable)


class ResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: _text(500) = ""
    class_name: _text(500) = ""
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    # JUnit reports both "error" and "errored"; both are stored as errored
    status: Literal["passed", "failed", "skipped", "errored", "error"]
    duration_ms: int = Field(0, ge=0, le=2_147_483_647)
    message: Optional[str] = None   # long text is truncated by the service, never rejected
    details: Optional[str] = None
    file: Optional[_text(1000)] = None
    owner: Optional[_text(255)] = None  # from CODEOWNERS, e.g. "@org/qa-team"
    failed_step: Optional[FailedStepIn] = None
    # The result's log (ADR-032, collector 0.9.0): masked and cut to 64 KB by the service, never rejected
    log: Optional[str] = None
    # Step screenshots (ADR-036, spec 2026-10-19 §5.3): references to blobs, in the order shown. A malformed entry is
    # dropped and counted (_screenshots_invalid), never a 422: an image problem never costs the run
    screenshots: Optional[list[ScreenshotIn]] = Field(None, max_length=50)
    _screenshots_invalid: int = PrivateAttr(0)

    _no_unstorable = field_validator("suite", "class_name", "name", "file", "owner", mode="before")(_reject_unstorable)
    _clean_text = field_validator("message", "details", "log", mode="after")(_replace_unstorable)

    @model_validator(mode="wrap")
    @classmethod
    def _drop_malformed_screenshots(cls, data: Any, handler):
        entries = data.get("screenshots") if isinstance(data, dict) else None
        if not isinstance(entries, list) or len(entries) > 50:  # over 50 is the field's 422
            return handler(data)
        valid, invalid = [], 0
        for entry in entries:
            # Cheap shape check first: a nested bomb is never walked
            if not isinstance(entry, dict) or len(entry) > MAX_SCREENSHOT_KEYS:
                invalid += 1
                continue
            try:
                valid.append(ScreenshotIn.model_validate(entry))
            except ValidationError:
                invalid += 1
        result = handler({**data, "screenshots": valid})
        result._screenshots_invalid = invalid
        return result

    @field_validator("status")
    @classmethod
    def _normalise_status(cls, value: str) -> str:
        return "errored" if value == "error" else value


class ChangedFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    status: Literal["A", "M", "D", "R", "C", "T", "U"]  # git name-status letters
    additions: Optional[int] = Field(None, ge=0, le=10_000_000)  # null: binary file
    deletions: Optional[int] = Field(None, ge=0, le=10_000_000)

    _no_unstorable = field_validator("path", mode="before")(_reject_unstorable)


class ChangesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_ref: Optional[_text(255)] = None
    truncated: bool = False  # the collector cut the list at its cap
    files: list[ChangedFileIn] = Field(default_factory=list, max_length=1000)

    _no_unstorable = field_validator("base_ref", mode="before")(_reject_unstorable)


class ComponentIn(BaseModel):
    """A repo/version the run exercised, e.g. the product build an E2E suite ran against."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{7,40}$")]

    _no_unstorable = field_validator("name", mode="before")(_reject_unstorable)


class RunUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: RunIn
    results: list[ResultIn] = Field(min_length=1, max_length=settings.MAX_RESULTS_PER_RUN)
    changes: Optional[ChangesIn] = None
    components: list[ComponentIn] = Field(default_factory=list, max_length=20)

    @field_validator("components")
    @classmethod
    def _component_names_unique(cls, value: list[ComponentIn]) -> list[ComponentIn]:
        names = [c.name for c in value]
        if len(names) != len(set(names)):
            raise ValueError("component names must be unique")
        return value


class KeyCheck(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    name: str
    can_read_impact: bool = False
    screenshots: bool = False  # step images may be uploaded: storage configured and the setting on


class RunReceipt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    total: int
    passed: int
    failed: int
    skipped: int
    errored: int
    # Failing results of quarantined tests, and the failing results that count (the CI gate)
    quarantined: int = 0
    blocking: int = 0
    # Screenshot references ingestion did not store (setting off, blob not stored, malformed): the collector may warn
    # Only on the first upload (201): a replay (200) answers None
    screenshots_dropped: Optional[int] = None
    commit_author: Optional[str] = None
    commit_message: Optional[str] = None
    pr_number: Optional[int] = None
    base_branch: Optional[str] = None
    trigger: Optional[str] = None
    change_base_ref: Optional[str] = None
    changed_files: Optional[int] = None
    additions: Optional[int] = None
    deletions: Optional[int] = None
    changes_truncated: Optional[bool] = None
    created_at: datetime
