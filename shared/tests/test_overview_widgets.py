"""The Overview widget catalogue (spec docs/superpowers/specs/2026-10-11-customisable-overview-design.md §2.4, §3.2)."""
import re
import tomllib
from pathlib import Path

from qeos_shared.overview_widgets import FILE_NAME, load_catalog

TYPES = {
    "latest_run": [],
    "failing_now": ["rows"],
    "pass_rate_week": ["branch"],
    "flaky_count": ["period"],
    "pass_rate_trend": ["granularity", "branch"],
    "failure_causes": ["period", "branch"],
    "regressions": ["period", "branch", "rows"],
    "recent_runs": ["branch", "rows"],
    "branch_health": ["rows"],
    "slowest_tests": ["period", "branch", "rows"],
    "coverage": ["period"],
    "case_tiles": [],
    "my_failures": ["author", "rows"],
    "my_suites": ["rows"],
    "impact_accuracy": ["period"],
}


def test_the_fifteen_types_and_their_settings():
    catalog = load_catalog()
    assert {name: spec["settings"] for name, spec in catalog["types"].items()} == TYPES


def test_limits_and_sizes():
    catalog = load_catalog()
    assert catalog["schema"] == 1
    assert catalog["max_widgets"] == 24
    assert catalog["max_body_bytes"] == 64 * 1024
    assert catalog["sizes"] == ["normal", "wide"]
    pattern = re.compile(catalog["widget_id_pattern"])
    assert pattern.fullmatch("w1")
    assert pattern.fullmatch("A_b-9" * 6 + "xy")  # 32 characters
    assert not pattern.fullmatch("")
    assert not pattern.fullmatch("x" * 33)
    assert not pattern.fullmatch("bad id")


def test_allowed_values():
    settings = load_catalog()["settings"]
    assert settings["rows"] == {"kind": "choice", "values": [5, 10]}
    assert settings["period"] == {"kind": "choice", "values": [7, 14, 30]}
    assert settings["granularity"] == {"kind": "choice", "values": ["day", "week", "month"]}
    for name in ("branch", "author"):
        assert settings[name] == {"kind": "text", "min_length": 1, "max_length": 255}


def test_every_setting_a_type_names_is_declared():
    catalog = load_catalog()
    for spec in catalog["types"].values():
        assert set(spec["settings"]) <= set(catalog["settings"])


def test_pyproject_declares_the_file_as_package_data():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert FILE_NAME in pyproject["tool"]["setuptools"]["package-data"]["qeos_shared"]
