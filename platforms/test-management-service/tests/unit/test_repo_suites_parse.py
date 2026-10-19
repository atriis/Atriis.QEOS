"""Parsing a suite workflow file into the legs (repository suites) it defines. No database."""
import json
from pathlib import Path

import yaml

from src.casebook.repo_suites.parse import parse_workflow

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workflows"
WF = ".github/workflows/"


def _workflow(matrix, name="Suite - X", as_mapping=False):
    body = matrix if as_mapping else json.dumps(matrix)
    doc = {"name": name, "jobs": {"suite": {"uses": "./.github/workflows/suite-runner.yml", "with": {"matrix": body}}}}
    if name is None:
        del doc["name"]
    return yaml.safe_dump(doc)


def _leg(**kw):
    return {"suite_id": "a", "suite_name": "A", "test_path": "tests/a/", **kw}


def test_flights_fixture():
    wf, issues = parse_workflow(WF + "suite-flights.yml", (FIXTURES / "suite-flights.yml").read_text(encoding="utf-8"))
    assert issues == []
    assert wf.workflow == "suite-flights.yml"
    assert wf.group_name == "Flights"
    first = wf.legs[0]
    assert first.external_id == "flights-amadeus-non-booking"
    assert first.name == "Flights Amadeus Non Booking"
    assert first.folders == ("tests/features/flights/flights_amadeus/flights_amadeus_non_booking",)
    assert first.files == ()
    assert first.shard is None
    assert [leg.shard for leg in wf.legs] == [None, "1/2", "2/2"]


def test_preprod_fixture():
    wf, issues = parse_workflow(WF + "suite-preprod.yml", (FIXTURES / "suite-preprod.yml").read_text(encoding="utf-8"))
    assert issues == []
    assert wf.group_name == "Pre-Prod"
    flights = wf.legs[0]
    assert flights.folders == ()
    assert len(flights.files) == 3
    assert all(f.endswith(".feature") for f in flights.files)
    assert flights.files[0].startswith("tests/features/flights/flights_travelfusion/")


def test_matrix_as_mapping():
    matrix = {"include": [_leg(), _leg(suite_id="b", suite_name="B", test_path="x.feature", shard="1/2")]}
    from_text, _ = parse_workflow(WF + "suite-x.yml", _workflow(matrix))
    from_map, issues = parse_workflow(WF + "suite-x.yml", _workflow(matrix, as_mapping=True))
    assert issues == []
    assert from_map == from_text
    assert len(from_map.legs) == 2


def test_whitespace_and_folder_without_slash():
    wf, issues = parse_workflow(WF + "suite-x.yml", _workflow({"include": [_leg(test_path="a/  b.feature  c ")]}))
    assert issues == []
    assert wf.legs[0].folders == ("a", "c")
    assert wf.legs[0].files == ("b.feature",)


def test_leg_without_suite_id():
    matrix = {"include": [{"suite_name": "N", "test_path": "t/"}, _leg()]}
    wf, issues = parse_workflow(WF + "suite-x.yml", _workflow(matrix))
    assert [leg.external_id for leg in wf.legs] == ["a"]
    assert len(issues) == 1
    assert issues[0].workflow == "suite-x.yml"
    assert issues[0].external_id is None


def test_leg_without_test_path():
    matrix = {"include": [_leg(test_path="  "), _leg(suite_id="b")]}
    wf, issues = parse_workflow(WF + "suite-x.yml", _workflow(matrix))
    assert [leg.external_id for leg in wf.legs] == ["b"]
    assert len(issues) == 1
    assert issues[0].external_id == "a"


def test_duplicate_suite_id():
    matrix = {"include": [_leg(test_path="first/"), _leg(test_path="second/")]}
    wf, issues = parse_workflow(WF + "suite-x.yml", _workflow(matrix))
    assert len(wf.legs) == 1
    assert wf.legs[0].folders == ("first",)
    assert len(issues) == 1
    assert issues[0].external_id == "a"


def test_bad_yaml():
    wf, issues = parse_workflow(WF + "suite-x.yml", "jobs: [unclosed")
    assert wf is None
    assert len(issues) == 1


def test_no_runner_job():
    content = yaml.safe_dump({"name": "Suite - X", "jobs": {"build": {"runs-on": "ubuntu-latest"}}})
    wf, issues = parse_workflow(WF + "suite-x.yml", content)
    assert wf is None
    assert len(issues) == 1


def test_path_outside_workflows_dir():
    wf, issues = parse_workflow("docs/suite-x.yml", _workflow({"include": [_leg()]}))
    assert wf is None
    assert len(issues) == 1


def test_group_name_fallback():
    named, _ = parse_workflow(WF + "suite-x.yml", _workflow({"include": [_leg()]}, name="Nightly things"))
    assert named.group_name == "Nightly things"
    unnamed, _ = parse_workflow(WF + "suite-x.yml", _workflow({"include": [_leg()]}, name=None))
    assert unnamed.group_name == "suite-x"
