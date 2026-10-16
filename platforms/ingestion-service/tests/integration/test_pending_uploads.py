"""A project pending deletion takes no uploads (spec 2026-10-16 §4); a restore lets the key in again."""
import httpx
import pytest

from src.ingestion.core.config import settings
from src.ingestion.models import Run
from src.ingestion.utils import project_state
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

INTERNAL = "http://ingestion-service:secret@project-service:8000"
FEED = "http://project-service:8000/internal/v1/projects/retention"


def row(project_id, deleted):
    return {"project_id": project_id, "result_retention_days": 90, "deleted": deleted,
            "deleted_at": "2026-10-16T10:00:00+00:00" if deleted else None, "legal_hold": False}


@pytest.fixture
def feed(http, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", INTERNAL)
    project_state.reset()

    def _answer(*rows, status_code=200):
        return http.get(FEED, name="feed").mock(return_value=httpx.Response(status_code, json={"projects": list(rows)}))
    yield _answer
    project_state.reset()


def test_an_upload_to_a_pending_project_is_410_and_stores_nothing(client, make_key, db, feed):
    feed(row(1, True))
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(), headers=key_headers(key))
    assert response.status_code == 410
    assert response.json()["detail"] == "Project scheduled for deletion"
    assert db.query(Run).count() == 0


def test_a_live_project_uploads_as_before(client, make_key, feed):
    feed(row(1, False))
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 201


def test_after_restore_the_key_works_again(client, make_key, feed, monkeypatch):
    route = feed(row(1, True))
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 410
    route.mock(return_value=httpx.Response(200, json={"projects": [row(1, False)]}))
    project_state.reset()  # the cache's 60 s, elapsed
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 201


def test_project_service_unreachable_lets_uploads_through(client, make_key, http, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", INTERNAL)
    project_state.reset()
    http.get(FEED).mock(side_effect=httpx.ConnectError("refused"))
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 201
    project_state.reset()


def test_the_feed_is_read_once_a_minute(client, make_key, feed):
    route = feed(row(1, False))
    _, key = make_key(project_id=1)
    for _ in range(3):
        client.post(URL, json=upload_body(), headers=key_headers(key))
    assert route.call_count == 1
