"""A result's whole masked log on demand (spec 2026-10-15 §2.1), with its values; never in the run payload."""
from datetime import datetime, timezone

import pytest

from src.ingestion.models import LogPattern, LogValue, RunResult

ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")
T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
LOG = 'INFO [App] Trip id captured tripId="3960562"\nINFO [App] Route chosen routeKey="wasToBos"'


def url(run_id, result_id, project_id=1):
    return f"/api/v1/projects/{project_id}/runs/{run_id}/results/{result_id}/log"


@pytest.fixture
def logged(db, seed_run):
    """logged(log, project_id=1) -> (run, result) with the log stored and two values captured."""
    def _make(log=LOG, project_id=1):
        run = seed_run(T0, results=(("books", "passed", 5),), project_id=project_id)
        row = db.query(RunResult).filter_by(run_id=run.id).one()
        row.log = log
        trip = LogPattern(project_id=project_id, name="trip_id", pattern=r'tripId="(\d+)"')
        route = LogPattern(project_id=project_id, name="route_key", pattern=r'routeKey="([^"]+)"')
        db.add_all([trip, route])
        db.flush()
        if log:
            db.add_all([LogValue(result_id=row.id, pattern_id=trip.id, position=0, value="3960562"),
                        LogValue(result_id=row.id, pattern_id=route.id, position=0, value="wasToBos")])
        db.commit()
        return run, row
    return _make


def test_the_log_is_returned_with_its_values(client, auth, project_role, logged):
    run, row = logged()
    project_role("viewer")
    response = client.get(url(run.id, row.id), headers=auth())
    assert response.status_code == 200, response.text
    assert response.json() == {"log": LOG, "values": [
        {"name": "route_key", "values": ["wasToBos"]}, {"name": "trip_id", "values": ["3960562"]}]}


def test_a_result_without_a_log_answers_null_and_no_values(client, auth, project_role, logged):
    run, row = logged(log=None)
    project_role("viewer")
    assert client.get(url(run.id, row.id), headers=auth()).json() == {"log": None, "values": []}


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_reads_the_log(client, auth, project_role, logged, role):
    run, row = logged()
    project_role(role)
    assert client.get(url(run.id, row.id), headers=auth()).status_code == 200


def test_a_result_of_another_run_is_404(client, auth, project_role, logged, seed_run, db):
    run, row = logged()
    other = seed_run(T0, results=(("quiet", "passed", 5),))
    project_role("viewer")
    response = client.get(url(other.id, row.id), headers=auth())
    assert response.status_code == 404 and response.json()["detail"] == "Result not found"
    assert client.get(url(run.id, row.id + 1000), headers=auth()).status_code == 404


def test_a_run_of_another_project_is_404(client, auth, project_role, logged):
    run, row = logged(project_id=2)
    project_role("viewer", project_id=1)
    response = client.get(url(run.id, row.id, project_id=1), headers=auth())
    assert response.status_code == 404 and response.json()["detail"] == "Run not found"


def test_the_run_payload_never_carries_the_log(client, auth, project_role, logged):
    run, _ = logged()
    project_role("viewer")
    [result] = client.get(f"/api/v1/runs/{run.id}", headers=auth()).json()["results"]
    assert "log" not in result
