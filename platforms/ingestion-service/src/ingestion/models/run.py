from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func

from src.ingestion.db.base import Base

CI_PROVIDERS = ("github_actions", "gitlab_ci", "jenkins", "azure_pipelines", "other", "local")
STATUSES = ("passed", "failed", "skipped", "errored")
TRIGGERS = ("manual", "automatic", "qeos")
# run-impact (spec 2026-10-13 §3.1): a full run, or one that ran only the suggested tests. The one list of scopes: the
# model's check, the upload schema and the runs filter all take it from here (migration 020 keeps its own frozen copy)
FULL_SCOPE, SUBSET_SCOPE = "full", "impact-subset"
SCOPES = (FULL_SCOPE, SUBSET_SCOPE)


class Run(Base):
    """One upload: one CI job's test results. Table test_runs. (Not named TestRun: pytest would
    try to collect any imported class whose name starts with Test.)"""

    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    idempotency_key = Column(String(255), nullable=True)
    request_hash = Column(String(64), nullable=False)
    ci_provider = Column(String(20), nullable=False)
    ci_run_url = Column(String(2048), nullable=True)
    commit_sha = Column(String(40), nullable=True)
    branch = Column(String(255), nullable=True)
    environment = Column(String(100), nullable=True)
    agent_version = Column(String(50), nullable=True)
    commit_author = Column(String(255), nullable=True)
    commit_message = Column(String(500), nullable=True)
    pr_number = Column(Integer, nullable=True)
    base_branch = Column(String(255), nullable=True)
    # How the CI run started, as the collector classified it (ADR-030); null: unknown or an older collector
    trigger = Column(String(10), nullable=True)
    # Migration 020: "impact-subset" when only the suggested tests ran (run-impact --suggested-only or --fail-fast);
    # every older upload is a full run. stages: run-impact's stages, null for an ordinary upload (SQL NULL, never a
    # JSON null, so "IS NULL" finds every run without stages)
    scope = Column(String(20), nullable=False, default=FULL_SCOPE, server_default=FULL_SCOPE)
    stages = Column(JSON(none_as_null=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    # Computed by the server from the results, never taken from the payload
    total = Column(Integer, nullable=False)
    passed = Column(Integer, nullable=False)
    failed = Column(Integer, nullable=False)
    skipped = Column(Integer, nullable=False)
    errored = Column(Integer, nullable=False)
    # Code-change summary from the upload's optional `changes`; null means "not reported"
    change_base_ref = Column(String(255), nullable=True)
    changed_files = Column(Integer, nullable=True)
    additions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)
    changes_truncated = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @hybrid_property
    def is_full(self):
        """A full run, not one of only the suggested tests: `run.is_full` in Python, `Run.is_full` in a query. Only
        full runs count in the impact statistics, the outcome evaluation and the accuracy figure (spec 2026-10-13
        §3.1)."""
        return self.scope == FULL_SCOPE

    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_test_runs_project_idempotency"),
        CheckConstraint(
            "ci_provider IN ('github_actions','gitlab_ci','jenkins','azure_pipelines','other','local')", name="chk_test_runs_ci_provider"
        ),
        CheckConstraint("\"trigger\" IN ('manual','automatic','qeos')", name="chk_test_runs_trigger"),
        CheckConstraint(f"scope IN ({','.join(repr(scope) for scope in SCOPES)})", name="chk_test_runs_scope"),
        Index("ix_test_runs_project_created", "project_id", "created_at"),
        Index("ix_test_runs_project_branch", "project_id", "branch"),
        Index("ix_test_runs_project_started", "project_id", "started_at"),
    )


class RunResult(Base):
    """One test case's outcome within a run. Table test_results."""

    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    test_key = Column(String(64), nullable=False, index=True)  # sha256(suite \0 class_name \0 name)
    suite = Column(String(500), nullable=False, default="")
    class_name = Column(String(500), nullable=False, default="")
    name = Column(String(1000), nullable=False)
    status = Column(String(10), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    truncated = Column(Boolean, nullable=False, default=False, server_default=false())
    # True when masking replaced anything in message or details (see utils/redaction.py)
    redacted = Column(Boolean, nullable=False, default=False, server_default=false())
    file = Column(String(1000), nullable=True)
    owner = Column(String(255), nullable=True)  # from CODEOWNERS, via the collector

    __table_args__ = (
        CheckConstraint("status IN ('passed','failed','skipped','errored')", name="chk_test_results_status"),
        Index("ix_test_results_test_key_run", "test_key", "run_id"),
        # Migration 016: the report reads only failing rows for causes and regression candidates
        Index("ix_test_results_failing", "run_id", "test_key",
              postgresql_where=text("status IN ('failed','errored')"),
              sqlite_where=text("status IN ('failed','errored')")),
    )
