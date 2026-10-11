"""Layout validation against shared/qeos_shared/overview_widgets.json (spec 2026-10-11 §3.2; plan Ruling 8)."""
import pytest
from pydantic import ValidationError

from src.project.schemas.overview_layout import LayoutError, LayoutIn, validate_layout


def widget(id="w1", type="latest_run", size="normal", **settings):
    return {"id": id, "type": type, "size": size, "settings": settings}


def layout(*widgets, schema=1):
    return {"schema": schema, "widgets": list(widgets)}


EVERY_TYPE = layout(
    widget("w1", "latest_run", "wide"),
    widget("w2", "failing_now", rows=10),
    widget("w3", "pass_rate_week"),
    widget("w4", "flaky_count", period=30),
    widget("w5", "pass_rate_trend", granularity="month", branch="release/2026.10"),
    widget("w6", "failure_causes", period=7, branch="main"),
    widget("w7", "regressions", period=14, rows=5),
    widget("w8", "recent_runs", branch="develop", rows=10),
    widget("w9", "branch_health", rows=5),
    widget("w10", "slowest_tests", period=30, rows=10),
    widget("w11", "coverage", period=30),
    widget("w12", "case_tiles", "wide"),
    widget("w13", "my_failures", author="Ada Lovelace", rows=5),
    widget("w14", "my_suites", rows=10),
)


def test_every_type_with_valid_settings_passes():
    assert validate_layout(EVERY_TYPE) is EVERY_TYPE


def test_settings_may_be_left_out_and_a_type_may_repeat():
    value = layout({"id": "a", "type": "pass_rate_trend", "size": "normal"}, widget("b", "pass_rate_trend", branch="develop"))
    assert validate_layout(value) is value


def test_a_widget_without_a_branch_setting_is_valid():
    value = layout(widget("w1", "recent_runs", rows=5))
    assert validate_layout(value) is value


def test_a_branch_named_all_is_an_ordinary_branch():
    value = layout(widget("w1", "recent_runs", branch="all"))
    assert validate_layout(value) is value


def test_the_limits_themselves_pass():
    value = layout(*[widget(f"w{i}") for i in range(23)], widget("x" * 32, "recent_runs", branch="b" * 255))
    assert validate_layout(value) is value


@pytest.mark.parametrize("bad, message", [
    (layout(schema=2), "schema must be 1"),
    ({"widgets": []}, "schema must be 1"),
    (layout(schema=True), "schema must be 1"),
    ({"schema": 1, "widgets": [], "theme": "dark"}, "unknown key 'theme'"),
    ({"schema": 1, "widgets": {}}, "widgets must be a list"),
    (layout(*[widget(f"w{i}") for i in range(25)]), "at most 24 widgets"),
    (layout(widget("w1"), widget("w1")), "duplicate id 'w1'"),
    (layout(widget("")), "widgets[0].id"),
    (layout(widget("x" * 33)), "widgets[0].id"),
    (layout(widget("bad id")), "widgets[0].id"),
    (layout(widget(7)), "widgets[0].id"),
    (layout(widget(type="marketplace")), "unknown type 'marketplace'"),
    (layout(widget(size="huge")), "size: must be normal or wide"),
    (layout({"id": "w1", "type": "latest_run"}), "missing 'size'"),
    (layout({**widget(), "colour": "red"}), "unknown key 'colour'"),
    (layout({**widget(), "settings": []}), "settings must be an object"),
    (layout(widget(rows=5)), "latest_run has no setting 'rows'"),
    (layout(widget(type="failing_now", rows=7)), "7 is not one of 5, 10"),
    (layout(widget(type="failing_now", rows="5")), "is not one of 5, 10"),
    (layout(widget(type="failing_now", rows=True)), "is not one of 5, 10"),
    (layout(widget(type="failing_now", rows=5.0)), "is not one of 5, 10"),
    (layout(widget(type="flaky_count", period=21)), "is not one of 7, 14, 30"),
    (layout(widget(type="pass_rate_trend", granularity="year")), "is not one of day, week, month"),
    (layout(widget(type="recent_runs", branch="")), "1-255 characters"),
    (layout(widget(type="recent_runs", branch="x" * 256)), "1-255 characters"),
    (layout(widget(type="recent_runs", branch="a\x00b")), "no NUL"),
    (layout(widget(type="recent_runs", branch=3)), "1-255 characters"),
    (layout(widget(type="my_failures", author="y" * 256)), "1-255 characters"),
    ("not an object", "layout must be an object"),
    (layout("w1"), "widgets[0] must be an object"),
])
def test_refused(bad, message):
    with pytest.raises(LayoutError) as caught:
        validate_layout(bad)
    assert message in str(caught.value)


def test_the_request_body_validates_the_layout_and_the_version():
    assert LayoutIn(layout=layout(widget()), version=0).version == 0
    with pytest.raises(ValidationError):
        LayoutIn(layout=layout(widget()), version=-1)
    with pytest.raises(ValidationError):
        LayoutIn(layout=layout(widget(type="marketplace")), version=0)
    with pytest.raises(ValidationError):
        LayoutIn(layout=layout(widget()), version=0, extra=True)
