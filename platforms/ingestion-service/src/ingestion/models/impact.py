"""Test impact analysis (spec docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md §3, migration 018).

impact_pairs and impact_test_base are rebuilt per project by the impact-rollup job; run_impact holds the suggestion
stored with an uploaded run, and its outcome."""
import hashlib

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, UniqueConstraint, false,
)

from src.ingestion.db.base import Base

PATH_UNIT_LENGTH = 1101  # a 100-character repository, ":", and a 1,000-character path


def unit_hash(path_unit: str) -> str:
    """The md5 hex of the UTF-8 path unit: what PostgreSQL's md5(path_unit) gives in a UTF-8 database.
    A lookup key, not a security measure."""
    return hashlib.md5(path_unit.encode("utf-8"), usedforsecurity=False).hexdigest()


class ImpactPair(Base):
    """How often a test newly failed in the window's runs that changed one path unit (pairs with at least one).

    No surrogate id: keyed by (project_id, unit_hash, test_key), so a long path_unit is never in an index entry and a
    table rebuilt nightly never runs out of ids (supersedes plan Ruling 27)."""

    __tablename__ = "impact_pairs"
    # The key's leading (project_id, unit_hash) serves the unit lookups: no secondary index
    __table_args__ = (PrimaryKeyConstraint("project_id", "unit_hash", "test_key", name="pk_impact_pairs"),)

    project_id = Column(Integer, nullable=False)
    unit_hash = Column(String(32), nullable=False)  # unit_hash(path_unit)
    test_key = Column(String(64), nullable=False)
    path_unit = Column(String(PATH_UNIT_LENGTH), nullable=False)  # for display; never indexed
    changed_runs = Column(Integer, nullable=False)  # the window's runs that changed the unit
    new_failures = Column(Integer, nullable=False)  # of those, the runs where the test newly failed
    computed_at = Column(DateTime(timezone=True), nullable=False)


class ImpactTestBase(Base):
    """One test's base rate over the window's runs with changed files, plus what scoring reads (plan Ruling 9)."""

    __tablename__ = "impact_test_base"
    __table_args__ = (UniqueConstraint("project_id", "test_key", name="uq_impact_test_base"),)

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False)
    test_key = Column(String(64), nullable=False)
    runs = Column(Integer, nullable=False)          # change runs with a non-skipped result of the test
    new_failures = Column(Integer, nullable=False)  # change runs where it newly failed
    flaky = Column(Boolean, nullable=False, default=False, server_default=false())
    suite = Column(String(500), nullable=False)
    class_name = Column(String(500), nullable=False)
    name = Column(String(1000), nullable=False)
    file = Column(String(1000), nullable=True)      # the test's file as the collector recorded it
    computed_at = Column(DateTime(timezone=True), nullable=False)


class RunImpact(Base):
    """The suggestion stored with an uploaded (or replayed) run, and its outcome once evaluated."""

    __tablename__ = "run_impact"

    run_id = Column(Integer, ForeignKey("test_runs.id", ondelete="CASCADE"), primary_key=True)
    suggested = Column(JSON, nullable=False)
    model_version = Column(String(20), nullable=False)
    replayed = Column(Boolean, nullable=False, default=False, server_default=false())
    scored_at = Column(DateTime(timezone=True), nullable=False)
    caught = Column(JSON, nullable=True)   # [{test_key, suite, class_name, name}]
    missed = Column(JSON, nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=True)
