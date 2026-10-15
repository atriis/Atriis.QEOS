"""Values captured at upload (ADR-032): from the masked, stored log, with the project's own patterns."""
import pytest

from src.ingestion.models import LogPattern, LogValue, RunResult
from src.ingestion.service import log_pattern_service
from src.ingestion.utils.log_values import LogPatternError
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TOKEN = "ghp_" + "a" * 36
TRIP = r'tripId="(\d+)"'
ROUTE = r'routeKey="([^"]+)"'


@pytest.fixture
def patterns(db):
    def _add(*pairs, project_id=1):
        rows = [LogPattern(project_id=project_id, name=name, pattern=regex) for name, regex in pairs]
        db.add_all(rows)
        db.commit()
        return rows
    return _add


def values_of(db):
    db.expire_all()
    rows = (db.query(RunResult.name, LogPattern.name, LogValue.position, LogValue.value)
            .join(LogValue, LogValue.result_id == RunResult.id).join(LogPattern, LogPattern.id == LogValue.pattern_id)
            .order_by(RunResult.id, LogPattern.name, LogValue.position))
    return [tuple(row) for row in rows]


def post(client, key, results, idem=None):
    response = client.post(URL, json=upload_body(results=results), headers=key_headers(key, idem=idem))
    assert response.status_code in (200, 201), response.text
    return response


def test_values_are_captured_at_upload(client, make_key, db, patterns):
    patterns(("trip_id", TRIP), ("route_key", ROUTE))
    _, key = make_key(project_id=1)
    post(client, key, [
        {"name": "books", "status": "passed", "log": 'tripId="3960562" routeKey="wasToBos" tripId="3960563"'},
        {"name": "quiet", "status": "passed"},
        {"name": "fails", "status": "failed", "log": 'tripId="3960562"'},
    ])
    assert values_of(db) == [
        ("books", "route_key", 0, "wasToBos"), ("books", "trip_id", 0, "3960562"), ("books", "trip_id", 1, "3960563"),
        ("fails", "trip_id", 0, "3960562"),
    ]


def test_without_a_group_the_whole_match_is_the_value(client, make_key, db, patterns):
    patterns(("trip", r"TRIP-\d+"))
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "skipped", "log": "made TRIP-12"}])
    assert values_of(db) == [("t", "trip", 0, "TRIP-12")]


def test_a_secret_is_masked_before_values_are_read(client, make_key, db, patterns):
    patterns(("token", r"GITHUB_TOKEN=(\S+)"))
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "passed", "log": f"GITHUB_TOKEN={TOKEN}"}])
    assert values_of(db) == []


def test_another_projects_patterns_never_apply(client, make_key, db, patterns):
    patterns(("trip_id", TRIP), project_id=2)
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "passed", "log": 'tripId="1"'}])
    assert values_of(db) == []


def test_a_replayed_upload_adds_no_values(client, make_key, db, patterns):
    patterns(("trip_id", TRIP))
    _, key = make_key(project_id=1)
    # One body: upload_body stamps the time, and a replay is the same bytes
    body = upload_body(results=[{"name": "t", "status": "passed", "log": 'tripId="1"'}])
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-values")).status_code == 201
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-values")).status_code == 200
    assert values_of(db) == [("t", "trip_id", 0, "1")]


def test_the_pattern_service_validates_and_limits(db):
    with pytest.raises(LogPatternError) as err:
        log_pattern_service.add_pattern(db, 1, "trip_id", r"(a)(b)", None, 1)
    assert err.value.field == "pattern"
    with pytest.raises(LogPatternError) as err:
        log_pattern_service.add_pattern(db, 1, "trip_id", r"a", "http://backoffice.example.com/{value}", 1)
    assert err.value.field == "link_template"
    for n in range(20):
        log_pattern_service.add_pattern(db, 1, f"p{n}", f"token{n}", None, 1)
    with pytest.raises(LogPatternError) as err:
        log_pattern_service.add_pattern(db, 1, "p20", "token20", None, 1)
    assert err.value.field == "limit" and "20" in str(err.value)


def test_a_name_is_unique_per_project(db):
    log_pattern_service.add_pattern(db, 2, "same", "a", None, 1)
    log_pattern_service.add_pattern(db, 3, "same", "a", None, 1)
    with pytest.raises(log_pattern_service.DuplicatePattern):
        log_pattern_service.add_pattern(db, 2, "same", "b", None, 1)


def test_patterns_are_listed_in_name_order(db):
    for name in ("trip_id", "booking", "route_key"):
        log_pattern_service.add_pattern(db, 1, name, "a", None, 1)
    assert [p.name for p in log_pattern_service.list_patterns(db, 1)] == ["booking", "route_key", "trip_id"]


def test_deleting_a_pattern_deletes_its_values(client, make_key, db, patterns):
    trip, route = patterns(("trip_id", TRIP), ("route_key", ROUTE))
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "passed", "log": 'tripId="1" routeKey="r"'}])
    assert log_pattern_service.delete_pattern(db, 1, trip.id) is True
    assert values_of(db) == [("t", "route_key", 0, "r")]
    assert log_pattern_service.delete_pattern(db, 2, route.id) is False  # another project's pattern id
