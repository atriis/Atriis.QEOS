"""POST /cases/import: dry run, apply, plan hash, limits, roles; imported cases are read-only."""
import pytest

from src.casebook.core.config import settings

URL = "/api/v1/projects/1/cases/import"
FEATURE = "Feature: A\n  @smoke\n  Scenario: one\n    Given x\n"


def body(*files, **extra):
    return {"files": [{"path": p, "content": c} for p, c in files], **extra}


@pytest.fixture
def member(project_role):
    project_role("member")


def test_dry_run_previews_and_writes_nothing(client, auth, member):
    r = client.post(f"{URL}?dry_run=true", json=body(("a.feature", FEATURE)), headers=auth())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["summary"]["created"] == 1 and len(data["plan_hash"]) == 64
    assert data["items"] == [{"action": "create", "path": "a.feature", "scenario": "one", "case_number": None}]
    assert client.get("/api/v1/projects/1/cases", headers=auth()).json()["total"] == 0


def test_apply_with_the_previewed_hash_imports(client, auth, member):
    preview = client.post(f"{URL}?dry_run=true", json=body(("a.feature", FEATURE)), headers=auth()).json()
    r = client.post(URL, json=body(("a.feature", FEATURE), expected_plan_hash=preview["plan_hash"]), headers=auth())
    assert r.status_code == 200 and r.json()["items"][0]["case_number"] == 1


def test_a_stale_hash_is_409_and_writes_nothing(client, auth, member):
    r = client.post(URL, json=body(("a.feature", FEATURE), expected_plan_hash="0" * 64), headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_changed"
    assert client.get("/api/v1/projects/1/cases", headers=auth()).json()["total"] == 0


def test_parse_errors_come_back_with_their_line(client, auth, member):
    r = client.post(f"{URL}?dry_run=true", json=body(("b.feature", "Feature: B\n  Scenario: s\n    Given x\n  oops\n")), headers=auth())
    assert r.status_code == 200
    assert r.json()["errors"][0]["path"] == "b.feature" and r.json()["errors"][0]["line"] == 4


@pytest.mark.parametrize("path", ["/abs.feature", "../up.feature", "C:\\x.feature"])
def test_paths_outside_the_repository_are_422(client, auth, member, path):
    assert client.post(URL, json=body((path, FEATURE)), headers=auth()).status_code == 422


@pytest.mark.parametrize("field", ["path", "content"])
def test_a_nul_character_is_422(client, auth, member, field):
    file = {"path": "a.feature", "content": FEATURE}
    file[field] = file[field][:3] + "\x00" + file[field][3:]
    assert client.post(f"{URL}?dry_run=true", json={"files": [file]}, headers=auth()).status_code == 422


def test_the_same_path_twice_is_422(client, auth, member):
    r = client.post(URL, json=body(("a.feature", FEATURE), ("./a.feature", FEATURE)), headers=auth())
    assert r.status_code == 422


@pytest.mark.parametrize("setting, value, files", [
    ("IMPORT_MAX_FILES", 1, [("a.feature", FEATURE), ("b.feature", FEATURE)]),
    ("IMPORT_MAX_FILE_BYTES", 10, [("a.feature", FEATURE)]),
    ("IMPORT_MAX_TOTAL_BYTES", 50, [("a.feature", FEATURE), ("b.feature", FEATURE)]),
])
def test_limits_are_413_and_name_their_setting(client, auth, member, monkeypatch, setting, value, files):
    monkeypatch.setattr(settings, setting, value)
    r = client.post(URL, json=body(*files), headers=auth())
    assert r.status_code == 413 and setting in r.json()["detail"]


def test_viewer_is_403_and_strangers_404(client, auth, project_role):
    project_role("viewer")
    assert client.post(URL, json=body(("a.feature", FEATURE)), headers=auth()).status_code == 403
    project_role(status_code=404, body={"detail": "Project not found"})
    assert client.post(URL, json=body(("a.feature", FEATURE)), headers=auth()).status_code == 404


def test_imported_cases_are_read_only_where_the_repository_owns_them(client, auth, member):
    client.post(URL, json=body(("a.feature", FEATURE)), headers=auth())
    case = client.get("/api/v1/projects/1/cases/1", headers=auth()).json()
    assert case["source_path"] == "a.feature" and case["gherkin"].startswith("Scenario: one")
    for field, value in [("title", "x"), ("labels", ["y"]), ("steps", []), ("gherkin", "z")]:
        r = client.patch("/api/v1/projects/1/cases/1", json={field: value}, headers=auth())
        assert r.status_code == 422, field
        assert "a.feature" in r.json()["detail"], field  # the guard rejected it, not pydantic
    ok = client.patch("/api/v1/projects/1/cases/1", json={"priority": "high", "status": "ready",
                                                          "description": "d"}, headers=auth())
    assert ok.status_code == 200 and ok.json()["priority"] == "high"


def test_origin_filter_and_search_in_gherkin(client, auth, member):
    client.post(URL, json=body(("a.feature", FEATURE)), headers=auth())
    client.post("/api/v1/projects/1/cases", json={"title": "manual"}, headers=auth())
    cases = "/api/v1/projects/1/cases"
    assert [c["title"] for c in client.get(f"{cases}?origin=imported", headers=auth()).json()["items"]] == ["one"]
    assert [c["title"] for c in client.get(f"{cases}?origin=manual", headers=auth()).json()["items"]] == ["manual"]
    assert [c["title"] for c in client.get(f"{cases}?search=given%20x", headers=auth()).json()["items"]] == ["one"]


def test_gherkin_on_a_manual_case_is_ignored_on_patch_and_refused_on_create(client, auth, member):
    cases = "/api/v1/projects/1/cases"
    assert client.post(cases, json={"title": "manual", "gherkin": "Scenario: x"}, headers=auth()).status_code == 422
    client.post(cases, json={"title": "manual"}, headers=auth())
    r = client.patch(f"{cases}/1", json={"gherkin": "Scenario: x"}, headers=auth())
    assert r.status_code == 200 and r.json()["gherkin"] is None
    assert client.get(f"{cases}/1", headers=auth()).json()["gherkin"] is None


def test_synced_cases_start_ready_and_manual_cases_draft(client, auth, member):
    cases = "/api/v1/projects/1/cases"
    client.post(URL, json=body(("a.feature", FEATURE)), headers=auth())
    client.post(cases, json={"title": "manual"}, headers=auth())
    statuses = {c["title"]: c["status"] for c in client.get(cases, headers=auth()).json()["items"]}
    assert statuses == {"one": "ready", "manual": "draft"}


def test_a_status_set_by_hand_survives_the_next_sync(client, auth, member):
    client.post(URL, json=body(("a.feature", FEATURE)), headers=auth())
    client.patch("/api/v1/projects/1/cases/1", json={"status": "draft"}, headers=auth())
    changed = FEATURE.replace("Given x", "Given y")
    assert client.post(URL, json=body(("a.feature", changed)), headers=auth()).json()["summary"]["updated"] == 1
    assert client.get("/api/v1/projects/1/cases/1", headers=auth()).json()["status"] == "draft"


def test_a_returning_synced_case_comes_back_ready(client, auth, member):
    other = "Feature: B\n  Scenario: two\n    Given z\n"
    client.post(URL, json=body(("a.feature", FEATURE), ("b.feature", other)), headers=auth())
    client.post(URL, json=body(("b.feature", other), full=True), headers=auth())
    assert client.get("/api/v1/projects/1/cases/1", headers=auth()).json()["status"] == "archived"
    client.post(URL, json=body(("a.feature", FEATURE), ("b.feature", other), full=True), headers=auth())
    assert client.get("/api/v1/projects/1/cases/1", headers=auth()).json()["status"] == "ready"
