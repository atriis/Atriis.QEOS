"""GET /collect/key: lets a collector prove its API key works without
uploading anything (the `qeos-collector check` command)."""

URL = "/api/v1/collect/key"


def test_a_valid_key_names_its_project(client, make_key):
    row, key = make_key(project_id=7)
    response = client.get(URL, headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200, response.text
    assert response.json() == {"project_id": 7, "name": row.name, "can_read_impact": False,
                               "screenshots": False}


def test_an_invalid_key_is_401(client):
    response = client.get(URL, headers={"Authorization": "Bearer qeos_wrong000000000"})
    assert response.status_code == 401


def test_a_missing_key_is_401(client):
    assert client.get(URL).status_code == 401


def test_the_check_says_whether_the_key_may_read_test_suggestions(client, make_key):
    _, key = make_key(can_read_impact=True)
    response = client.get(URL, headers={"Authorization": f"Bearer {key}"})
    assert response.json()["can_read_impact"] is True


def test_key_check_reports_screenshots(client, make_key, db):
    from src.ingestion.api.main import app
    from src.ingestion.models import CollectionSettings
    from src.ingestion.utils.artifact_store import MemoryArtifactStore, get_artifact_store

    _, key = make_key(project_id=7)
    headers = {"Authorization": f"Bearer {key}"}
    app.dependency_overrides[get_artifact_store] = lambda: MemoryArtifactStore()
    assert client.get(URL, headers=headers).json()["screenshots"] is False  # store, setting off
    db.add(CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=True, discarded_count=0))
    db.commit()
    assert client.get(URL, headers=headers).json()["screenshots"] is True
    app.dependency_overrides[get_artifact_store] = lambda: None
    assert client.get(URL, headers=headers).json()["screenshots"] is False  # setting on, no store
