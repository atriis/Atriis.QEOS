"""Raw .feature storage, GET /features, GET /features/detail and search_in on the case list."""
import pytest

from src.casebook.models import FeatureFile

P = "/api/v1/projects/1"
IMPORT = f"{P}/cases/import"


def feature(name, *scenarios):
    return f"Feature: {name}\n" + "".join(f"  Scenario: {s}\n    Given {s}\n" for s in scenarios)


def do_import(client, auth, files, **extra):
    r = client.post(IMPORT, json={"files": [{"path": p, "content": c} for p, c in files], **extra}, headers=auth())
    assert r.status_code == 200, r.text
    return r


@pytest.fixture
def member(project_role):
    project_role("member")


@pytest.fixture
def seeded(client, auth, member):
    do_import(client, auth, [
        ("tests/features/hotels/b.feature", feature("Booking", "b1", "b2")),
        ("tests/features/hotels/a.feature", feature("Availability", "a1")),
        ("tests/features/auth/login.feature", feature("Login", "l1")),
        ("tests/features/auth/odd_100%.feature", feature("Odd_name", "o1")),
    ])
    client.post(f"{P}/cases", json={"title": "manual one"}, headers=auth())
    client.post(f"{P}/cases", json={"title": "manual two"}, headers=auth())
    return client


def rows(client, auth, query=""):
    r = client.get(f"{P}/features{query}", headers=auth())
    assert r.status_code == 200, r.text
    return r.json()


# --- raw content --------------------------------------------------------------------------------------

def test_import_stores_the_raw_text_and_a_reimport_updates_it(client, auth, member, db):
    text = "Feature: A\n\n  # a comment\n  Scenario: one\n    Given x\n"
    do_import(client, auth, [("a.feature", text)])
    row = db.query(FeatureFile).one()
    assert (row.project_id, row.path, row.feature_name, row.content) == (1, "a.feature", "A", text)
    assert len(row.content_sha256) == 64
    first = row.imported_at
    do_import(client, auth, [("a.feature", text)])  # same text: untouched
    db.expire_all()
    assert db.query(FeatureFile).one().imported_at == first
    changed = text + "  Scenario: two\n    Given y\n"
    do_import(client, auth, [("a.feature", changed)])
    db.expire_all()
    assert db.query(FeatureFile).one().content == changed


def test_a_dry_run_and_a_broken_file_store_nothing(client, auth, member, db):
    client.post(f"{IMPORT}?dry_run=true", json={"files": [{"path": "a.feature", "content": feature("A", "s")}]},
                headers=auth())
    do_import(client, auth, [("broken.feature", "Feature: B\n  Scenario: s\n    Given x\n  oops\n")])
    assert db.query(FeatureFile).count() == 0


def test_a_full_import_deletes_the_files_that_vanished_and_a_partial_one_keeps_them(client, auth, member, db):
    do_import(client, auth, [("a.feature", feature("A", "s")), ("b.feature", feature("B", "t"))])
    do_import(client, auth, [("a.feature", feature("A", "s"))])
    assert {r.path for r in db.query(FeatureFile).all()} == {"a.feature", "b.feature"}
    do_import(client, auth, [("a.feature", feature("A", "s"))], full=True)
    db.expire_all()
    assert {r.path for r in db.query(FeatureFile).all()} == {"a.feature"}
    assert [i["path"] for i in rows(client, auth)["items"]] == ["a.feature"]


def test_a_full_import_keeps_a_broken_file_that_is_still_in_the_folder(client, auth, member, db):
    do_import(client, auth, [("a.feature", feature("A", "s"))])
    do_import(client, auth, [("a.feature", "Feature: A\n  Scenario: s\n    Given x\n  oops\n")], full=True)
    assert db.query(FeatureFile).filter_by(path="a.feature").count() == 1


def test_files_are_per_project(client, auth, project_role, db):
    project_role("member", project_id=1)
    project_role("member", project_id=2)
    do_import(client, auth, [("a.feature", feature("A", "s"))])
    client.post("/api/v1/projects/2/cases/import",
                json={"files": [{"path": "a.feature", "content": feature("Other", "s")}]}, headers=auth())
    assert {(r.project_id, r.feature_name) for r in db.query(FeatureFile).all()} == {(1, "A"), (2, "Other")}
    assert [i["feature_name"] for i in rows(client, auth)["items"]] == ["A"]
    assert client.get(f"{P}/features/detail?path=a.feature", headers=auth()).json()["feature_name"] == "A"


# --- list: grouping, order, pagination ------------------------------------------------------------------

def test_groups_by_file_ordered_by_folder_then_feature_with_manual_last(seeded, auth):
    data = rows(seeded, auth)
    assert data["total"] == 5
    assert [(i["feature_name"], i["path"], i["folder"], i["case_count"]) for i in data["items"]] == [
        ("Login", "tests/features/auth/login.feature", "tests/features/auth", 1),
        ("Odd_name", "tests/features/auth/odd_100%.feature", "tests/features/auth", 1),
        ("Availability", "tests/features/hotels/a.feature", "tests/features/hotels", 1),
        ("Booking", "tests/features/hotels/b.feature", "tests/features/hotels", 2),
        (None, None, None, 2),
    ]
    booking, manual = data["items"][3], data["items"][4]
    assert booking["case_numbers"] == [4, 5] and booking["has_source"] is True
    assert manual["case_numbers"] == [6, 7] and manual["has_source"] is False


def test_pagination(seeded, auth):
    first = rows(seeded, auth, "?limit=2")
    assert first["total"] == 5 and [i["feature_name"] for i in first["items"]] == ["Login", "Odd_name"]
    last = rows(seeded, auth, "?limit=2&offset=4")
    assert [i["feature_name"] for i in last["items"]] == [None]
    assert rows(seeded, auth, "?limit=2&offset=9")["items"] == []
    assert seeded.get(f"{P}/features?limit=201", headers=auth()).status_code == 422


def test_case_numbers_are_capped_at_200(client, auth, member):
    many = "Feature: Big\n" + "".join(f"  Scenario: s{i}\n    Given x\n" for i in range(205))
    do_import(client, auth, [("big.feature", many)])
    item = rows(client, auth)["items"][0]
    assert item["case_count"] == 205 and item["case_numbers"] == list(range(1, 201))


def test_archived_cases_and_files_do_not_show(seeded, auth):
    seeded.patch(f"{P}/cases/3", json={"status": "archived"}, headers=auth())  # a1: Availability's only case
    assert "Availability" not in [i["feature_name"] for i in rows(seeded, auth)["items"]]
    assert seeded.get(f"{P}/features/detail?path=tests/features/hotels/a.feature", headers=auth()).status_code == 404
    assert rows(seeded, auth, "?status=archived")["total"] == 0


def test_filters_apply_to_the_groups(seeded, auth):
    assert [i["feature_name"] for i in rows(seeded, auth, "?folder=tests/features/auth")["items"]] == [
        "Login", "Odd_name"]
    seeded.patch(f"{P}/cases/4", json={"priority": "high"}, headers=auth())
    data = rows(seeded, auth, "?priority=high")
    assert [(i["feature_name"], i["case_count"], i["case_numbers"]) for i in data["items"]] == [("Booking", 1, [4])]
    assert [i["feature_name"] for i in rows(seeded, auth, "?linked=false")["items"]][-1] is None


# --- list: aggregates ------------------------------------------------------------------------------------

def by_name(data):
    return {i["feature_name"]: i for i in data["items"]}


def test_aggregates_for_a_mixed_group(seeded, auth):
    # Booking holds cases 4 and 5
    # Imports link themselves; unlink case 5
    seeded.patch(f"{P}/cases/4", json={"priority": "high", "status": "ready"}, headers=auth())
    seeded.patch(f"{P}/cases/5", json={"priority": "low", "automated_test_key": None, "status": "draft"}, headers=auth())
    booking = by_name(rows(seeded, auth))["Booking"]
    assert booking["linked_count"] == 1
    assert booking["top_priority"] == "high"
    assert booking["status_counts"] == {"draft": 1, "ready": 1, "archived": 0}
    seeded.patch(f"{P}/cases/5", json={"priority": "critical"}, headers=auth())
    assert by_name(rows(seeded, auth))["Booking"]["top_priority"] == "critical"


def test_aggregates_for_the_manual_group(seeded, auth):
    manual = by_name(rows(seeded, auth))[None]
    assert (manual["linked_count"], manual["top_priority"]) == (0, "medium")
    assert manual["status_counts"] == {"draft": 2, "ready": 0, "archived": 0}
    seeded.patch(f"{P}/cases/6", json={"priority": "low", "status": "ready"}, headers=auth())
    seeded.patch(f"{P}/cases/7", json={"priority": "low"}, headers=auth())
    manual = by_name(rows(seeded, auth))[None]
    assert manual["top_priority"] == "low"
    assert manual["status_counts"] == {"draft": 1, "ready": 1, "archived": 0}


def test_the_filters_change_the_aggregates(seeded, auth):
    seeded.patch(f"{P}/cases/4", json={"priority": "high", "status": "ready"}, headers=auth())
    seeded.patch(f"{P}/cases/5", json={"automated_test_key": None, "status": "draft"}, headers=auth())
    booking = by_name(rows(seeded, auth, "?status=draft"))["Booking"]
    assert booking["case_count"] == 1 and booking["linked_count"] == 0
    assert booking["top_priority"] == "medium" and booking["status_counts"] == {"draft": 1, "ready": 0, "archived": 0}
    booking = by_name(rows(seeded, auth, "?linked=true"))["Booking"]
    assert (booking["case_count"], booking["linked_count"], booking["top_priority"]) == (1, 1, "high")
    # An archived case is never in a feature group, so it adds to no count
    seeded.patch(f"{P}/cases/5", json={"status": "archived"}, headers=auth())
    booking = by_name(rows(seeded, auth))["Booking"]
    assert booking["case_count"] == 1 and booking["status_counts"]["archived"] == 0


def test_aggregates_are_per_project(client, auth, project_role):
    project_role("member", project_id=1)
    project_role("member", project_id=2)
    do_import(client, auth, [("a.feature", feature("A", "s"))])
    client.post("/api/v1/projects/2/cases/import", json={"files": [{"path": "a.feature", "content": feature("A", "s", "t")}]},
                headers=auth())
    client.patch("/api/v1/projects/2/cases/1", json={"priority": "critical", "automated_test_key": None}, headers=auth())
    client.patch("/api/v1/projects/2/cases/2", json={"automated_test_key": None}, headers=auth())
    item = rows(client, auth)["items"][0]
    assert (item["case_count"], item["linked_count"], item["top_priority"]) == (1, 1, "medium")
    assert item["status_counts"] == {"draft": 0, "ready": 1, "archived": 0}  # synced cases start ready


# --- list: search modes ----------------------------------------------------------------------------------

def names(data):
    return [i["feature_name"] for i in data["items"]]


def test_search_feature_matches_the_name_or_the_path(seeded, auth):
    assert names(rows(seeded, auth, "?search=book&search_in=feature")) == ["Booking"]
    assert names(rows(seeded, auth, "?search=HOTELS/&search_in=feature")) == ["Availability", "Booking"]
    assert rows(seeded, auth, "?search=b1&search_in=feature")["total"] == 0  # a scenario name is not a feature


def test_search_scenario_matches_title_gherkin_and_key(seeded, auth):
    assert names(rows(seeded, auth, "?search=b1&search_in=scenario")) == ["Booking"]
    assert names(rows(seeded, auth, "?search=TC-2&search_in=scenario")) == ["Odd_name"]
    assert rows(seeded, auth, "?search=Booking&search_in=scenario")["total"] == 0


def test_search_both_is_either(seeded, auth):
    assert names(rows(seeded, auth, "?search=Booking&search_in=both")) == ["Booking"]
    assert names(rows(seeded, auth, "?search=l1&search_in=both")) == ["Login"]
    # "1": scenario titles and keys (l1, o1, a1, b1, TC-1) in "scenario", the path odd_100% in "feature"
    assert names(rows(seeded, auth, "?search=1&search_in=both")) == ["Login", "Odd_name", "Availability", "Booking"]
    assert names(rows(seeded, auth, "?search=100&search_in=both")) == ["Odd_name"]


def test_like_wildcards_in_the_search_are_literal(seeded, auth):
    assert names(rows(seeded, auth, "?search=%25&search_in=feature")) == ["Odd_name"]  # 100% in a path
    assert names(rows(seeded, auth, "?search=d_n&search_in=feature")) == ["Odd_name"]
    assert rows(seeded, auth, "?search=_&search_in=feature")["total"] == 1  # not "any character"
    assert rows(seeded, auth, "?search=%25%25&search_in=both")["total"] == 0


def test_search_in_is_validated(seeded, auth):
    assert seeded.get(f"{P}/features?search_in=title", headers=auth()).status_code == 422


# --- B4: search_in on the case list ---------------------------------------------------------------------

def test_cases_search_in(seeded, auth):
    def titles(path):
        r = seeded.get(path, headers=auth())
        assert r.status_code == 200, r.text
        return sorted(c["title"] for c in r.json()["items"])

    assert titles(f"{P}/cases?search=Booking") == []  # default: scenario
    assert titles(f"{P}/cases?search=Booking&search_in=scenario") == []
    assert titles(f"{P}/cases?search=Booking&search_in=feature") == ["b1", "b2"]
    assert titles(f"{P}/cases?search=Booking&search_in=both") == ["b1", "b2"]
    assert titles(f"{P}/cases?search=b1&search_in=both") == ["b1"]
    assert titles(f"{P}/cases?search=b1&search_in=feature") == []
    assert titles(f"{P}/cases?search=hotels/a&search_in=feature") == ["a1"]
    assert titles(f"{P}/cases?search=%25&search_in=feature") == ["o1"]


def test_cases_search_in_on_post_search(seeded, auth):
    def titles(body):
        r = seeded.post(f"{P}/cases/search", json=body, headers=auth())
        assert r.status_code == 200, r.text
        return sorted(c["title"] for c in r.json()["items"])

    assert titles({"search": "Booking"}) == []
    assert titles({"search": "Booking", "search_in": "feature"}) == ["b1", "b2"]
    assert titles({"search": "Login", "search_in": "both"}) == ["l1"]
    assert seeded.post(f"{P}/cases/search", json={"search_in": "x"}, headers=auth()).status_code == 422


# --- detail ---------------------------------------------------------------------------------------------

def test_detail_has_the_raw_content_and_the_cases_in_file_order(seeded, auth):
    text = "Feature: Z\n\n  Scenario: zed\n    Given z\n\n  Scenario: alpha\n    Given a\n"
    do_import(seeded, auth, [("z.feature", text)])
    r = seeded.get(f"{P}/features/detail?path=z.feature", headers=auth())
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["feature_name"], d["path"], d["folder"], d["content"]) == ("Z", "z.feature", "", text)
    assert d["imported_at"] is not None
    assert [(c["key"], c["title"], c["scenario_name"], c["status"], c["priority"]) for c in d["cases"]] == [
        ("TC-9", "zed", "zed", "ready", "medium"), ("TC-8", "alpha", "alpha", "ready", "medium")]
    assert [c["line"] for c in d["cases"]] == [3, 6]
    assert set(d["cases"][0]) == {"number", "key", "title", "scenario_name", "status", "priority",
                                  "automated_test_key", "line"}


def test_detail_without_stored_content_has_null_content(seeded, auth, db):
    db.query(FeatureFile).delete()
    db.commit()
    d = seeded.get(f"{P}/features/detail?path=tests/features/auth/login.feature", headers=auth()).json()
    assert d["feature_name"] == "Login" and d["content"] is None and d["imported_at"] is None
    assert [(c["title"], c["line"]) for c in d["cases"]] == [("l1", 2)]  # the line was stored at import
    item = next(i for i in rows(seeded, auth)["items"] if i["feature_name"] == "Login")
    assert item["has_source"] is False


def test_detail_404_for_an_unknown_path_and_422_without_one(seeded, auth):
    assert seeded.get(f"{P}/features/detail?path=nope.feature", headers=auth()).status_code == 404
    assert seeded.get(f"{P}/features/detail", headers=auth()).status_code == 422


# --- roles ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["viewer", "member", "admin", "owner"])
def test_every_role_can_read(client, auth, project_role, role):
    project_role(role)
    assert client.get(f"{P}/features", headers=auth()).status_code == 200
    assert client.get(f"{P}/features/detail?path=a.feature", headers=auth()).status_code == 404


def test_strangers_and_anonymous_are_refused(client, auth, project_role):
    project_role(status_code=404, body={"detail": "Project not found"})
    assert client.get(f"{P}/features", headers=auth()).status_code == 404
    assert client.get(f"{P}/features/detail?path=a", headers=auth()).status_code == 404
    assert client.get(f"{P}/features").status_code in (401, 403)


# --- scenario_line (migration 007) ---------------------------------------------------------------------

from src.casebook.models import Case  # noqa: E402

RULES = """# language: en
Feature: Rules

  Background:
    Given a base

  Rule: first
    Scenario Outline: outlined <n>
      Given the number <n>
      Examples:
        | n |
        | 1 |

    Scenario: plain
      Given outlined 1
      When "Scenario: plain" is quoted
      \"\"\"
      Scenario: plain
      \"\"\"

  Rule: second
    Example: last
      Given z
"""


def lines_of(client, auth, path):
    d = client.get(f"{P}/features/detail?path={path}", headers=auth()).json()
    return [(c["scenario_name"], c["line"]) for c in d["cases"]]


def test_import_stores_the_heading_line_of_outlines_and_rule_scenarios(client, auth, member, db):
    do_import(client, auth, [("r.feature", RULES)])
    stored = {c.scenario_name: c.scenario_line for c in db.query(Case).all()}
    assert stored == {"outlined <n>": 8, "plain": 14, "last": 22}
    assert lines_of(client, auth, "r.feature") == [("outlined <n>", 8), ("plain", 14), ("last", 22)]


def test_a_non_english_file_stores_its_lines(client, auth, member, db):
    text = open("tests/fixtures/portugues.feature", encoding="utf-8").read()
    do_import(client, auth, [("pt.feature", text)])
    assert [c.scenario_line for c in db.query(Case).all()] == [3]


def test_a_moved_scenario_is_an_update_that_changes_its_line_only(client, auth, member, db):
    do_import(client, auth, [("a.feature", feature("A", "s"))])
    r = do_import(client, auth, [("a.feature", "# comment\n" + feature("A", "s"))])
    assert [i["action"] for i in r.json()["items"]] == ["update"]
    db.expire_all()
    assert db.query(Case).one().scenario_line == 3
    r = do_import(client, auth, [("a.feature", "# comment\n" + feature("A", "s"))])
    assert [i["action"] for i in r.json()["items"]] == ["unchanged"]


def test_detail_is_in_file_order_by_stored_line(client, auth, member):
    text = feature("Z", "zed", "alpha")
    do_import(client, auth, [("z.feature", text)])
    assert lines_of(client, auth, "z.feature") == [("zed", 2), ("alpha", 4)]


@pytest.fixture
def legacy(client, auth, member, db):
    """A file imported before 007: stored text, no scenario_line on its cases."""
    text = RULES.replace("\n", "\r\n")
    do_import(client, auth, [("r.feature", text)])
    db.query(Case).update({Case.scenario_line: None})
    db.commit()
    return client


def test_fallback_derives_lines_from_the_text_for_cases_without_one(legacy, auth):
    # CRLF text; a quoted step and a doc string repeat "Scenario: plain"
    assert lines_of(legacy, auth, "r.feature") == [("outlined <n>", 8), ("plain", 14), ("last", 22)]


def test_fallback_ignores_lines_that_are_not_headings(client, auth, member, db):
    text = 'Feature: F\n  Scenario: a\n    Given x\n    """\n    Scenario: b\n    """\n  Scenario: b\n    Given y\n'
    do_import(client, auth, [("f.feature", text)])
    db.query(Case).update({Case.scenario_line: None})
    db.commit()
    assert lines_of(client, auth, "f.feature") == [("a", 2), ("b", 7)]


def test_fallback_handles_bare_cr_line_breaks(client, auth, member, db):
    do_import(client, auth, [("a.feature", feature("A", "s", "t"))])
    db.query(Case).update({Case.scenario_line: None})
    db.query(FeatureFile).update({FeatureFile.content: feature("A", "s", "t").replace("\n", "\r")})
    db.commit()
    assert lines_of(client, auth, "a.feature") == [("s", 2), ("t", 4)]


# --- list: test_keys ---------------------------------------------------------------------------------------

def test_test_keys_are_distinct_sorted_and_skip_nulls(seeded, auth):
    item = by_name(rows(seeded, auth))["Booking"]
    assert len(item["test_keys"]) == 2 and item["test_keys"] == sorted(set(item["test_keys"]))
    seeded.patch(f"{P}/cases/5", json={"automated_test_key": item["test_keys"][0]}, headers=auth())
    assert by_name(rows(seeded, auth))["Booking"]["test_keys"] == [item["test_keys"][0]]
    seeded.patch(f"{P}/cases/4", json={"automated_test_key": None}, headers=auth())
    seeded.patch(f"{P}/cases/5", json={"automated_test_key": None}, headers=auth())
    assert by_name(rows(seeded, auth))["Booking"]["test_keys"] == []
    assert by_name(rows(seeded, auth))[None]["test_keys"] == []


def test_test_keys_are_capped_at_200(client, auth, member):
    many = "Feature: Big\n" + "".join(f"  Scenario: s{i}\n    Given x\n" for i in range(205))
    do_import(client, auth, [("big.feature", many)])
    item = rows(client, auth)["items"][0]
    assert len(item["test_keys"]) == 200 and item["test_keys"] == sorted(item["test_keys"])


def test_the_filters_apply_to_test_keys(seeded, auth):
    both = by_name(rows(seeded, auth))["Booking"]["test_keys"]
    seeded.patch(f"{P}/cases/4", json={"priority": "high"}, headers=auth())
    only = by_name(rows(seeded, auth, "?priority=high"))["Booking"]["test_keys"]
    assert len(both) == 2 and len(only) == 1 and only[0] in both
    seeded.patch(f"{P}/cases/5", json={"status": "archived"}, headers=auth())
    assert len(by_name(rows(seeded, auth))["Booking"]["test_keys"]) == 1


def test_test_keys_are_per_project(client, auth, project_role):
    project_role("member", project_id=1)
    project_role("member", project_id=2)
    do_import(client, auth, [("a.feature", feature("A", "s"))])
    client.post("/api/v1/projects/2/cases/import", json={"files": [{"path": "a.feature", "content": feature("A", "s", "t")}]},
                headers=auth())
    assert len(rows(client, auth)["items"][0]["test_keys"]) == 1
