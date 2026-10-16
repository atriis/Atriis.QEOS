"""DELETE /internal/v1/projects/{id}: the purge job empties test-management of one project (spec 2026-10-16)."""
import base64
from datetime import datetime, timezone

import pytest

from src.casebook.core.config import settings
from src.casebook.models import (
    Case, CaseLabel, CiTarget, CiTargetEvent, FeatureFile, RunRequest, Suite, SuiteCase,
)

PASSWORD = "internal-test-password"
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_USERNAME", "ingestion-service")
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", PASSWORD)


def basic(user="ingestion-service", password=PASSWORD):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def seed(db, project_id):
    case = Case(project_id=project_id, number=1, title="t", steps=[], created_by=1)
    db.add(case)
    db.flush()
    db.add(CaseLabel(case_id=case.id, label="smoke"))
    suite = Suite(project_id=project_id, name=f"s{project_id}", created_by=1)
    db.add(suite)
    db.flush()
    db.add(SuiteCase(suite_id=suite.id, case_id=case.id, position=0))
    db.add(FeatureFile(project_id=project_id, path="f.feature", feature_name="f", content="Feature: f",
                       content_sha256="0" * 64, imported_at=NOW))
    db.add(RunRequest(project_id=project_id, requested_by=1, requested_at=NOW, selection=[], status="completed"))
    db.add(CiTarget(project_id=project_id, repo="acme/r", workflow="qeos.yml", token_encrypted="x",
                    token_last4="abcd", updated_by=1, updated_at=NOW))
    db.add(CiTargetEvent(project_id=project_id, user_id=1, action="created", at=NOW))
    db.commit()


def count(db, project_id):
    return sum(db.query(m).filter(m.project_id == project_id).count()
               for m in (Case, Suite, FeatureFile, RunRequest, CiTarget, CiTargetEvent))


def test_it_deletes_every_row_of_the_project_and_nothing_else(client, configured, db):
    seed(db, 1)
    seed(db, 2)
    response = client.delete("/internal/v1/projects/1", headers=basic())
    assert response.status_code == 204
    db.expire_all()
    assert count(db, 1) == 0 and db.query(CaseLabel).count() == 1 and db.query(SuiteCase).count() == 1
    assert count(db, 2) == 6


def test_a_project_with_nothing_is_204(client, configured):
    assert client.delete("/internal/v1/projects/99", headers=basic()).status_code == 204


@pytest.mark.parametrize("headers", [{}, basic(password="wrong"), basic(user="someone-else")])
def test_without_the_credentials_it_is_401(client, configured, headers, db):
    seed(db, 1)
    assert client.delete("/internal/v1/projects/1", headers=headers).status_code == 401
    assert count(db, 1) == 6


def test_without_a_configured_password_it_is_503(client):
    assert client.delete("/internal/v1/projects/1", headers=basic()).status_code == 503


def test_the_endpoint_is_not_in_the_public_openapi(client):
    paths = client.get(f"{settings.API_V1_STR}/openapi.json").json()["paths"]
    assert not any(path.startswith("/internal") for path in paths)
