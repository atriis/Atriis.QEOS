"""POST /cases/import with suite_files: the repository's suite workflows become repository suites (spec 5.2)."""
import json
from pathlib import Path

import pytest
import yaml

from src.casebook.models import Case, SuiteCase
from src.casebook.repo_suites import sync

URL = "/api/v1/projects/1/cases/import"
BASE = "/api/v1/projects/1"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workflows"
FLIGHTS = (FIXTURES / "suite-flights.yml").read_text(encoding="utf-8")
PREPROD = (FIXTURES / "suite-preprod.yml").read_text(encoding="utf-8")
WF = ".github/workflows/"
PATTERN = ".github/workflows/suite-*.yml"
AMADEUS = "tests/features/flights/flights_amadeus/flights_amadeus_non_booking/"
GENERAL = "tests/features/flights/flights_general/flights_general_non_booking/"
LEG = ("flights-amadeus-non-booking", "flights-general-non-booking-1", "flights-general-non-booking-2")


def feature(title, *scenarios):
    return f"Feature: {title}\n" + "".join(f"  Scenario: {s}\n    Given {title} {s}\n" for s in scenarios)


FEATURES = [
    (AMADEUS + "b.feature", feature("B", "b1", "b2")),
    (AMADEUS + "a.feature", feature("A", "a1")),
    (GENERAL + "g.feature", feature("G", "g1")),
    ("tests/features/hotels/h.feature", feature("H", "h1")),
]


def workflow(legs, name="Suite - Flights"):
    """A suite workflow calling suite-runner.yml with these (suite_id, suite_name, test_path) legs."""
    include = [{"suite_id": i, "suite_name": n, "test_path": p} for i, n, p in legs]
    return yaml.safe_dump({"name": name, "jobs": {"suite": {
        "uses": "./.github/workflows/suite-runner.yml", "with": {"matrix": json.dumps({"include": include})}}}})


@pytest.fixture
def member(project_role):
    project_role("member")


def post(client, auth, features=FEATURES, workflows=(("suite-flights.yml", FLIGHTS),), patterns=(PATTERN,),
         dry_run=False, status=200, full=True, **extra):
    body = {"files": [{"path": p, "content": c} for p, c in features], "full": full,
            "suite_files": [{"path": WF + n, "content": c} for n, c in workflows],
            "suite_patterns": list(patterns), **extra}
    r = client.post(URL + ("?dry_run=true" if dry_run else ""), json=body, headers=auth())
    assert r.status_code == status, r.text
    return r.json()


def suites(client, auth):
    return {s["external_id"] or s["name"]: s for s in client.get(f"{BASE}/suites", headers=auth()).json()}


def members(client, auth, suite_id):
    body = client.get(f"{BASE}/suites/{suite_id}", headers=auth()).json()
    return [(c["source_path"], c["title"]) for c in body["cases"]]


def changes(result):
    return sorted((c["action"], c["external_id"]) for c in result["suite_changes"])


def test_first_sync_creates_groups_and_members(client, auth, member):
    result = post(client, auth)
    assert changes(result) == [("created", leg) for leg in LEG]
    assert result["suite_warnings"] == []
    rows = suites(client, auth)
    amadeus = rows["flights-amadeus-non-booking"]
    assert amadeus["origin"] == "repository" and amadeus["workflow"] == "suite-flights.yml"
    assert amadeus["group_name"] == "Flights" and amadeus["name"] == "Flights Amadeus Non Booking"
    assert amadeus["test_paths"] == [AMADEUS] and amadeus["shard"] is None
    assert members(client, auth, amadeus["id"]) == [
        (AMADEUS + "a.feature", "a1"), (AMADEUS + "b.feature", "b1"), (AMADEUS + "b.feature", "b2")]
    half = rows["flights-general-non-booking-1"]
    assert half["shard"] == "1/2" and members(client, auth, half["id"]) == [(GENERAL + "g.feature", "g1")]


def test_resync_updates_name_and_paths(client, auth, member):
    post(client, auth)
    before = suites(client, auth)
    changed = FLIGHTS.replace('"Flights Amadeus Non Booking"', '"Amadeus NB"').replace(
        f'"test_path": "{AMADEUS}"', f'"test_path": "{AMADEUS}a.feature"')
    result = post(client, auth, workflows=(("suite-flights.yml", changed),))
    assert changes(result) == [("updated", "flights-amadeus-non-booking")]
    after = suites(client, auth)
    amadeus = after["flights-amadeus-non-booking"]
    assert amadeus["id"] == before["flights-amadeus-non-booking"]["id"]
    assert amadeus["name"] == "Amadeus NB" and amadeus["test_paths"] == [AMADEUS + "a.feature"]
    assert members(client, auth, amadeus["id"]) == [(AMADEUS + "a.feature", "a1")]


def test_leg_removed_deletes_suite(client, auth, member):
    post(client, auth)
    one = workflow([("flights-amadeus-non-booking", "Flights Amadeus Non Booking", AMADEUS)])
    result = post(client, auth, workflows=(("suite-flights.yml", one),))
    assert changes(result) == [("deleted", "flights-general-non-booking-1"), ("deleted", "flights-general-non-booking-2")]
    assert set(suites(client, auth)) == {"flights-amadeus-non-booking"}


def test_archived_and_moved_cases_follow(client, auth, db, member):
    post(client, auth)
    # b2 leaves its file (archived); a.feature moves from the amadeus folder to the general one
    moved = [(AMADEUS + "b.feature", feature("B", "b1")), (GENERAL + "a.feature", feature("A", "a1")),
             (GENERAL + "g.feature", feature("G", "g1")), ("tests/features/hotels/h.feature", feature("H", "h1"))]
    result = post(client, auth, features=moved)
    assert result["summary"]["archived"] == 1 and result["summary"]["moved"] == 1
    assert result["suite_changes"] == []
    rows = suites(client, auth)
    assert members(client, auth, rows["flights-amadeus-non-booking"]["id"]) == [(AMADEUS + "b.feature", "b1")]
    assert members(client, auth, rows["flights-general-non-booking-1"]["id"]) == [
        (GENERAL + "a.feature", "a1"), (GENERAL + "g.feature", "g1")]
    pairs = [(s.suite_id, s.case_id) for s in db.query(SuiteCase).all()]
    assert len(pairs) == len(set(pairs)) == 5  # amadeus 1, each general half 2


def test_deleted_workflow_matching_pattern_deletes_group(client, auth, member):
    post(client, auth, workflows=(("suite-flights.yml", FLIGHTS), ("suite-preprod.yml", PREPROD)))
    assert {"preprod-flights", "preprod-hotels", "preprod-shell"} <= set(suites(client, auth))
    result = post(client, auth)
    assert changes(result) == [("deleted", "preprod-flights"), ("deleted", "preprod-hotels"), ("deleted", "preprod-shell")]
    assert set(suites(client, auth)) == set(LEG)


def test_workflow_outside_pattern_is_kept(client, auth, member):
    post(client, auth)
    result = post(client, auth, workflows=(), patterns=(".github/workflows/suite-hotels.yml",))
    assert result["suite_changes"] == []
    assert set(suites(client, auth)) == set(LEG)


def test_unparsable_workflow_keeps_previous_suites(client, auth, member):
    post(client, auth)
    result = post(client, auth, workflows=(("suite-flights.yml", "jobs: [\n"),))
    assert result["suite_changes"] == []
    [warning] = result["suite_warnings"]
    assert warning["workflow"] == "suite-flights.yml" and warning["external_id"] is None
    assert "not valid YAML" in warning["message"]
    assert set(suites(client, auth)) == set(LEG)


def test_workflow_without_a_usable_leg_keeps_previous_suites(client, auth, member):
    post(client, auth)
    empty = workflow([("", "No id", AMADEUS)])
    result = post(client, auth, workflows=(("suite-flights.yml", empty),))
    assert result["suite_changes"] == []
    assert [w["message"] for w in result["suite_warnings"]] == ["A matrix leg has no suite_id and was skipped"]
    assert set(suites(client, auth)) == set(LEG)


def test_a_workflow_name_qeos_cannot_run_is_skipped(client, auth, member):
    result = post(client, auth, workflows=(("suite flights.yml", FLIGHTS),))
    assert result["suite_changes"] == []
    [warning] = result["suite_warnings"]
    assert warning["workflow"] == "suite flights.yml"
    assert warning["message"] == "suite flights.yml is not a workflow file name QEOS can run; skipped"
    assert suites(client, auth) == {}


def test_name_clash_uses_suite_id(client, auth, member):
    made = client.post(f"{BASE}/suites", json={"name": "Flights Amadeus Non Booking"}, headers=auth())
    assert made.status_code == 201
    result = post(client, auth)
    assert {"workflow": "suite-flights.yml", "external_id": "flights-amadeus-non-booking",
            "message": "Name taken by a suite made in QEOS; using flights-amadeus-non-booking"} in result["suite_warnings"]
    assert suites(client, auth)["flights-amadeus-non-booking"]["name"] == "flights-amadeus-non-booking"


def test_entry_matching_nothing_warns(client, auth, member):
    result = post(client, auth, workflows=(("suite-preprod.yml", PREPROD),))
    entry = "tests/features/hotels/hotels_booking/23109_ehotel_book_hotel_verify_provider_label.feature"
    assert {"workflow": "suite-preprod.yml", "external_id": "preprod-hotels",
            "message": f"{entry} matches no imported case"} in result["suite_warnings"]
    assert "preprod-hotels" in suites(client, auth)  # still synced, with what matched (nothing)


SUNNY = "tests/features/transportation/cars/sunny_cars/"
GLOB_FEATURES = [
    (SUNNY + "x.feature", feature("X", "x1")),
    (SUNNY + "y.feature", feature("Y", "y1")),
    ("tests/features/transportation/cars/other/z.feature", feature("Z", "z1")),
]


def test_glob_leg_members(client, auth, member):
    wf = workflow([("cars", "Cars", SUNNY + "*.feature")])
    post(client, auth, features=GLOB_FEATURES, workflows=(("suite-cars.yml", wf),))
    # fnmatch's * also crosses "/"; cucumber's would not, but a feature folder has no deeper .feature files.
    assert sorted(path for path, _ in members(client, auth, suites(client, auth)["cars"]["id"])) == [
        SUNNY + "x.feature", SUNNY + "y.feature"]


def test_glob_matching_nothing_warns(client, auth, member):
    entry = "tests/features/none/*.feature"
    wf = workflow([("cars", "Cars", entry)])
    result = post(client, auth, features=GLOB_FEATURES, workflows=(("suite-cars.yml", wf),))
    assert {"workflow": "suite-cars.yml", "external_id": "cars",
            "message": f"{entry} matches no imported case"} in result["suite_warnings"]


def test_glob_only_change_changes_plan_hash(client, auth, member):
    def cars(glob):
        return (("suite-cars.yml", workflow([("cars", "Cars", glob)])),)
    one = post(client, auth, features=GLOB_FEATURES, workflows=cars(SUNNY + "x*.feature"), dry_run=True)
    two = post(client, auth, features=GLOB_FEATURES, workflows=cars(SUNNY + "y*.feature"), dry_run=True)
    assert one["plan_hash"] != two["plan_hash"]
    r = client.post(URL, json={
        "files": [{"path": p, "content": c} for p, c in GLOB_FEATURES], "full": True,
        "suite_files": [{"path": WF + "suite-cars.yml", "content": cars(SUNNY + "y*.feature")[0][1]}],
        "suite_patterns": [PATTERN], "expected_plan_hash": one["plan_hash"]}, headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_changed"


def test_dry_run_reports_suite_changes_and_hash_changes(client, auth, member):
    first = post(client, auth, dry_run=True)
    assert changes(first) == [("created", leg) for leg in LEG]
    assert suites(client, auth) == {}
    renamed = FLIGHTS.replace('"Flights Amadeus Non Booking"', '"Amadeus NB"')
    second = post(client, auth, workflows=(("suite-flights.yml", renamed),), dry_run=True)
    assert second["items"] == first["items"] and second["plan_hash"] != first["plan_hash"]
    post(client, auth, expected_plan_hash=first["plan_hash"])
    assert suites(client, auth)["flights-amadeus-non-booking"]["name"] == "Flights Amadeus Non Booking"


def test_without_suite_files_nothing_changes(client, auth, member):
    post(client, auth)
    before = suites(client, auth)
    r = client.post(URL, json={"files": [{"path": p, "content": c} for p, c in FEATURES], "full": True},
                    headers=auth())
    assert r.status_code == 200 and r.json()["suite_changes"] == [] and r.json()["suite_warnings"] == []
    assert suites(client, auth) == before


def test_source_repo_stored(client, auth, member):
    post(client, auth, source_repo="atriis/Atriis.Test.Automation.OBT")
    assert {s["source_repo"] for s in suites(client, auth).values()} == {"atriis/Atriis.Test.Automation.OBT"}


@pytest.mark.parametrize("extra", [
    {"suite_files": [{"path": WF + "suite-flights.yml", "content": FLIGHTS}]},  # files without patterns
    {"suite_patterns": [PATTERN], "source_repo": "not a repo"},
    {"suite_patterns": ["x" * 201]},
    {"suite_patterns": [PATTERN] * 21},
])
def test_bad_suite_fields_are_422(client, auth, member, extra):
    body = {"files": [{"path": p, "content": c} for p, c in FEATURES], **extra}
    assert client.post(URL, json=body, headers=auth()).status_code == 422


def test_a_suite_over_1000_cases_is_cut(client, auth, db, member):
    db.add_all(Case(project_id=1, number=i + 1, title=f"c{i}", steps=[], created_by=1, source_path="tests/big/x.feature",
                    source_key=f"{i:064d}", scenario_line=i + 1) for i in range(1001))
    db.commit()
    big = workflow([("big", "Big", "tests/big/")], name="Suite - Big")
    result = post(client, auth, features=[("other.feature", feature("O", "o1"))], full=False,
                  workflows=(("suite-big.yml", big),))
    assert {"workflow": "suite-big.yml", "external_id": "big",
            "message": "Over 1000 cases; only the first 1000 are in the suite"} in result["suite_warnings"]
    row = suites(client, auth)["big"]
    assert row["case_count"] == 1000
    assert members(client, auth, row["id"])[-1] == ("tests/big/x.feature", "c999")


def test_plan_hash_input_is_order_free(db):
    files = [(WF + "suite-flights.yml", FLIGHTS), (WF + "suite-preprod.yml", PREPROD)]
    one = sync.plan_suites(db, 1, files, [PATTERN], None, [])
    two = sync.plan_suites(db, 1, list(reversed(files)), [PATTERN], None, [])
    assert one.hash_input() == two.hash_input()
