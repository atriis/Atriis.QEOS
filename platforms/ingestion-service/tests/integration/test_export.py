"""Export a project's stored results before deleting it (or for a legal request): one NDJSON
download, owners and admins only, nothing from any other project."""
import json
from datetime import datetime, timezone

import pytest

from src.ingestion.models import Run, RunChangedFile, RunComponent, RunResult

URL = "/api/v1/projects/1/export"
WHEN = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def stored(db, make_key):
    def _add(project_id, name):
        key, _ = make_key(project_id=project_id)
        run = Run(project_id=project_id, api_key_id=key.id, request_hash="h", ci_provider="github_actions",
                  branch="main", commit_sha="abc1234", started_at=WHEN, finished_at=WHEN, duration_ms=0,
                  total=2, passed=1, failed=1, skipped=0, errored=0)
        db.add(run)
        db.flush()
        db.add_all([
            RunResult(run_id=run.id, test_key="0" * 64, name=f"{name} ok", status="passed", duration_ms=3),
            RunResult(run_id=run.id, test_key="1" * 64, name=f"{name} bad", status="failed", duration_ms=4,
                      message="password=[REDACTED:password]", redacted=True,
                      failed_step_text="When I log in", failed_step_line=7,
                      failed_step_definition="steps/login.js:3", failed_step_pattern="When I log in"),
            RunChangedFile(run_id=run.id, path="src/app.py", status="modified", additions=1, deletions=0),
            RunComponent(run_id=run.id, name="shop-api", sha="def5678"),
        ])
        db.commit()
        return run.id

    return _add


def lines(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_an_owner_downloads_every_run_and_result_of_the_project(client, auth, project_role, stored):
    mine = stored(1, "mine")
    stored(2, "theirs")
    project_role(role="owner", project_id=1)

    response = client.get(URL, headers=auth())

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert 'attachment; filename="qeos-project-1-' in response.headers["content-disposition"]
    header, run, *results = lines(response)
    assert header["type"] == "export" and header["project_id"] == 1 and header["format"] == 1
    assert run["type"] == "run" and run["id"] == mine and run["branch"] == "main"
    assert run["changed_files"] == [{"path": "src/app.py", "status": "modified", "additions": 1, "deletions": 0}]
    assert run["components"] == [{"name": "shop-api", "sha": "def5678"}]
    assert [r["name"] for r in results] == ["mine ok", "mine bad"]
    assert all(r["type"] == "result" and r["run_id"] == mine for r in results)
    # Exported as stored: masked text stays masked
    assert results[1]["message"] == "password=[REDACTED:password]"
    assert (results[1]["failed_step_text"], results[1]["failed_step_line"]) == ("When I log in", 7)
    assert results[0]["failed_step_text"] is None and results[0]["failed_step_line"] is None
    assert (results[1]["failed_step_definition"], results[1]["failed_step_pattern"]) == ("steps/login.js:3", "When I log in")
    assert results[0]["failed_step_definition"] is None and results[0]["failed_step_pattern"] is None
    assert "theirs" not in response.text


@pytest.mark.parametrize("role", ["member", "viewer", "billing_manager"])
def test_only_owners_and_admins_export(client, auth, project_role, role):
    project_role(role=role, project_id=1)
    assert client.get(URL, headers=auth()).status_code == 403


def test_an_empty_project_exports_just_the_header(client, auth, project_role):
    project_role(role="admin", project_id=1)
    response = client.get(URL, headers=auth())
    assert [line["type"] for line in lines(response)] == ["export"]


def test_the_log_and_its_values_are_exported(client, auth, project_role, stored, db):
    from src.ingestion.models import LogPattern, LogValue

    run_id = stored(1, "mine")
    bad = db.query(RunResult).filter_by(run_id=run_id, name="mine bad").one()
    bad.log = 'Trip id captured tripId="3960562" routeKey="wasToBos"'
    trip = LogPattern(project_id=1, name="trip_id", pattern=r'tripId="(\d+)"')
    route = LogPattern(project_id=1, name="route_key", pattern=r'routeKey="([^"]+)"')
    db.add_all([trip, route])
    db.flush()
    db.add_all([LogValue(result_id=bad.id, pattern_id=trip.id, position=0, value="3960562"),
                LogValue(result_id=bad.id, pattern_id=route.id, position=0, value="wasToBos")])
    db.commit()
    project_role(role="owner", project_id=1)

    _, _, ok, bad_line = lines(client.get(URL, headers=auth()))
    assert bad_line["log"] == 'Trip id captured tripId="3960562" routeKey="wasToBos"'
    assert bad_line["log_values"] == [{"pattern": "route_key", "value": "wasToBos"},
                                      {"pattern": "trip_id", "value": "3960562"}]
    assert ok["log"] is None and ok["log_values"] == []


def test_export_includes_screenshot_references_without_bytes(client, auth, project_role, stored, db):
    from src.ingestion.models import Blob, ResultScreenshot

    run_id = stored(1, "mine")
    project_role(role="owner", project_id=1)
    blob = Blob(project_id=1, sha256="f" * 64, media_type="image/png", bytes=1234)
    db.add(blob)
    db.flush()
    bad = db.query(RunResult).filter_by(run_id=run_id, status="failed").one()
    db.add_all([
        ResultScreenshot(result_id=bad.id, position=1, blob_id=blob.id, step_text="Then I see it",
                         step_line=9, hook=None),
        ResultScreenshot(result_id=bad.id, position=0, blob_id=blob.id, step_text="When I log in",
                         step_line=7, hook="after"),
    ])
    db.commit()

    _, _, ok, failed = lines(client.get(URL, headers=auth()))

    assert "screenshots" not in ok  # omitted when empty
    assert failed["screenshots"] == [
        {"step_text": "When I log in", "step_line": 7, "hook": "after", "media_type": "image/png",
         "bytes": 1234, "sha256": "f" * 64},
        {"step_text": "Then I see it", "step_line": 9, "hook": None, "media_type": "image/png",
         "bytes": 1234, "sha256": "f" * 64},
    ]
