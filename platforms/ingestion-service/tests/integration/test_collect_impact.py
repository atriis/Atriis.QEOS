"""POST /api/v1/collect/impact: the collector's scoring with the project API key, for keys an owner or admin allowed to
read test suggestions (spec 2026-10-13 §2.1, §9; plan Ruling 1)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

from src.ingestion.api.v1.endpoints import analytics
from src.ingestion.service import impact_service

URL = "/api/v1/collect/impact"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
NOT_ALLOWED = {"code": "impact_not_allowed",
               "message": "This API key may not read test suggestions. Ask a project owner or admin to allow test "
                          "suggestions for this key."}


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(analytics, "_now", lambda: NOW)


def headers(key):
    return {"Authorization": f"Bearer {key}"}


def allowed_key(make_key, project_id=7):
    return make_key(project_id=project_id, can_read_impact=True)[1]


def seed_two_projects(seed_run):
    started = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    seed_run(started, results=(("cart", "failed", 5),), branch="feature/x", project_id=7)
    seed_run(started, results=(("elsewhere", "failed", 5),), branch="feature/x", project_id=8)


def test_the_key_scores_a_change_in_its_own_project_only(client, make_key, seed_run, http):
    seed_two_projects(seed_run)
    response = client.post(URL, json={"changed_paths": ["src/cart/x.py"], "branch": "feature/x"},
                           headers=headers(allowed_key(make_key)))
    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "stats-v1"
    assert [(t["name"], t["kind"]) for t in body["tests"]] == [("cart", "failing_on_branch")]
    assert "elsewhere" not in response.text  # project 8's failing test, same branch
    assert not http.calls  # the key names the project: project-service is never asked


def test_the_other_projects_key_sees_only_its_own(client, make_key, seed_run):
    seed_two_projects(seed_run)
    response = client.post(URL, json={"changed_paths": ["src/cart/x.py"], "branch": "feature/x"},
                           headers=headers(allowed_key(make_key, project_id=8)))
    assert [t["name"] for t in response.json()["tests"]] == ["elsewhere"]


@pytest.mark.parametrize("body", [{"changed_paths": ["a.py"]}, {"changed_paths": []}, {}])
def test_a_key_without_the_permission_is_403_with_its_code(client, make_key, seed_run, body):
    """Every key is upload-only until an owner or admin allows it; the 403 comes before the body is looked at."""
    seed_two_projects(seed_run)
    _, key = make_key(project_id=7)
    response = client.post(URL, json=body, headers=headers(key))
    assert response.status_code == 403
    assert response.json() == {"detail": NOT_ALLOWED}


@pytest.mark.parametrize("value", ["qeos_not_a_real_key", None])
def test_a_bad_or_revoked_key_is_401(client, make_key, value):
    _, revoked = make_key(project_id=7, revoked=True, can_read_impact=True)
    response = client.post(URL, json={"changed_paths": ["a.py"]}, headers=headers(value or revoked))
    assert response.status_code == 401


def test_a_user_token_is_not_a_key(client, auth):
    assert client.post(URL, json={"changed_paths": ["a.py"]}, headers=auth()).status_code == 401


@pytest.mark.parametrize("body", [
    {"changed_paths": []},
    {"changed_paths": ["a\x00b"]},
    {"changed_paths": ["x" * 1001]},
    {"changed_paths": ["a.py"] * 5001},
    {"changed_paths": ["a.py"], "branch": "b" * 256},
    {"changed_paths": ["a.py"], "extra": 1},
])
def test_input_limits(client, make_key, body):
    assert client.post(URL, json=body, headers=headers(allowed_key(make_key))).status_code == 422


def test_a_scoring_timeout_answers_503_with_its_code(client, make_key, monkeypatch):
    def out_of_time(*args, **kwargs):
        raise impact_service.ScoringTimeout()

    monkeypatch.setattr(impact_service, "score_change", out_of_time)
    response = client.post(URL, json={"changed_paths": ["a.py"]}, headers=headers(allowed_key(make_key)))
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "impact_timeout", "message": impact_service.SCORING_TIMEOUT_MESSAGE}


def test_another_database_error_is_not_a_timeout(client, make_key, monkeypatch):
    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("disk full"))

    monkeypatch.setattr(impact_service, "score_change", broken)
    with pytest.raises(OperationalError):
        client.post(URL, json={"changed_paths": ["a.py"]}, headers=headers(allowed_key(make_key)))

