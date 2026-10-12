"""Manual runs are discarded while the project does not collect them (ADR-030)."""
import threading

from sqlalchemy.orm import sessionmaker

from src.ingestion.models import CollectionSettings, Run
from src.ingestion.service import collection_settings_service
from src.ingestion.utils import metrics
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

REASON = "manual runs are not collected for this project"


def switch_off(db, project_id=1):
    db.add(CollectionSettings(project_id=project_id, collect_manual=False, discarded_count=0))
    db.commit()


def discarded():
    return metrics.REGISTRY.get_sample_value("qeos_runs_discarded_total", {"reason": "manual"}) or 0.0


def test_off_and_manual_is_discarded(client, make_key, db):
    _, key = make_key(project_id=1)
    switch_off(db)
    before = discarded()
    response = client.post(URL, json=upload_body(trigger="manual"), headers=key_headers(key))
    assert response.status_code == 202
    assert response.json() == {"discarded": True, "reason": REASON}
    assert db.query(Run).count() == 0
    db.expire_all()
    row = db.get(CollectionSettings, 1)
    assert row.discarded_count == 1 and row.last_discarded_at is not None
    assert discarded() == before + 1


def test_off_keeps_everything_else(client, make_key, db):
    _, key = make_key(project_id=1)
    switch_off(db)
    for trigger in ("automatic", "qeos", None):
        body = upload_body(trigger=trigger) if trigger else upload_body()
        assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    assert sorted(str(r.trigger) for r in db.query(Run)) == ["None", "automatic", "qeos"]


def test_on_stores_manual_with_its_trigger(client, make_key, db, auth, project_role):
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(trigger="manual"), headers=key_headers(key))
    assert response.status_code == 201 and response.json()["trigger"] == "manual"
    project_role("viewer")
    detail = client.get(f"/api/v1/runs/{response.json()['id']}", headers=auth())
    assert detail.status_code == 200 and detail.json()["trigger"] == "manual"


def test_replay_of_a_discarded_upload_is_discarded_again(client, make_key, db):
    _, key = make_key(project_id=1)
    switch_off(db)
    for _ in range(2):
        assert client.post(URL, json=upload_body(trigger="manual"), headers=key_headers(key, idem="k-1")).status_code == 202
    db.expire_all()  # the counter was updated by SQL, not through this session's cached row
    assert db.get(CollectionSettings, 1).discarded_count == 2


def test_replay_of_a_stored_run_is_not_discarded_later(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(trigger="manual")
    first = client.post(URL, json=body, headers=key_headers(key, idem="k-2"))
    assert first.status_code == 201
    switch_off(db)
    again = client.post(URL, json=body, headers=key_headers(key, idem="k-2"))
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]


def test_concurrent_discards_are_all_counted(db):
    """The test client shares one session across requests, so this drives the service directly: one
    session per thread, as concurrent requests have in production."""
    switch_off(db)
    factory = sessionmaker(bind=db.get_bind())

    def discard():
        session = factory()
        try:
            collection_settings_service.count_discard(session, 1)
        finally:
            session.close()

    threads = [threading.Thread(target=discard) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    db.expire_all()
    assert db.get(CollectionSettings, 1).discarded_count == 8


def test_discard_is_logged_with_a_masked_url_and_marks_the_key_used(client, make_key, db, caplog):
    from src.ingestion.models import ApiKey
    api_key, key = make_key(project_id=1)
    switch_off(db)
    secret = "ghp_" + "a1B2c3D4e5" * 3 + "a1B2c3"
    url = f"https://ci.example/run?token={secret}"
    with caplog.at_level("WARNING"):
        response = client.post(URL, json=upload_body(trigger="manual", ci_run_url=url), headers=key_headers(key))
    assert response.status_code == 202
    assert "upload discarded" in caplog.text and "project=1" in caplog.text
    assert secret not in caplog.text
    assert any(r.levelname == "WARNING" and "upload discarded" in r.getMessage() for r in caplog.records)
    db.expire_all()
    assert db.get(ApiKey, api_key.id if hasattr(api_key, "id") else api_key).last_used_at is not None
