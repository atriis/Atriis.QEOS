"""Log-value patterns (ADR-032): validation and extraction from a masked log."""
import pytest

from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import CompiledLogPattern, LogPatternError, compile_log_pattern, extract

LOG = "\n".join([
    'INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"',
    'INFO 20:23:25 [App] Route chosen routeKey="wasToBos"',
    'INFO 20:23:26 [App] Trip id captured from booking flow tripId="3960563"',
    'INFO 20:23:27 [App] Trip id captured again tripId="3960562"',
])


def pattern(regex, name="trip_id", pattern_id=1):
    return CompiledLogPattern(pattern_id, name, compile_log_pattern(regex))


def values(text, *patterns):
    return [(pid, pos, value) for pid, pos, value in extract(text, patterns)]


def test_with_one_group_the_value_is_the_groups_text_distinct_in_log_order():
    assert values(LOG, pattern(r'tripId="(\d+)"')) == [(1, 0, "3960562"), (1, 1, "3960563")]


def test_without_a_group_the_value_is_the_whole_match():
    assert values("booked TRIP-12 and TRIP-13", pattern(r"TRIP-\d+")) == [(1, 0, "TRIP-12"), (1, 1, "TRIP-13")]


def test_each_pattern_has_its_own_positions():
    trip, route = pattern(r'tripId="(\d+)"'), pattern(r'routeKey="([^"]+)"', "route_key", 2)
    assert values(LOG, trip, route) == [(1, 0, "3960562"), (1, 1, "3960563"), (2, 0, "wasToBos")]


def test_a_value_is_cut_to_200_characters_and_blank_values_are_skipped():
    long = "a" * 300
    got = values(f'id="{long}" id="   " id="{long}b"', pattern(r'id="([^"]*)"'))
    assert got == [(1, 0, "a" * 200)]  # the cut values are the same value: kept once


def test_at_most_twenty_values_per_pattern():
    text = " ".join(f'tripId="{n}"' for n in range(50))
    got = values(text, pattern(r'tripId="(\d+)"'))
    assert [v for _, _, v in got] == [str(n) for n in range(20)]


def test_a_pattern_matching_thousands_of_times_keeps_twenty_values_and_stops_reading():
    text = "7 " * 32_000  # 64 KB of one value matched 32,000 times
    assert values(text, pattern(r"(\d)")) == [(1, 0, "7")]


def test_matches_after_the_first_thousand_are_not_read():
    text = 'id="1" ' * 1500 + 'id="2"'
    assert [v for _, _, v in values(text, pattern(r'id="(\d)"'))] == ["1"]


def test_a_value_touching_a_masking_marker_is_not_captured():
    masked = 'token=[REDACTED:token] user=[REDACTED:email] tripId="5" [REDACTED:jwt]9'
    assert values(masked, pattern(r"token=(\S+)")) == []
    assert values(masked, pattern(r"user=(\S{5})", "user")) == []       # a group covering part of a marker
    assert values(masked, pattern(r'tripId="(\d+)"')) == [(1, 0, "5")]  # next to a marker: still captured
    # The rule is about the value's own span: a match that starts in a marker but whose group lies outside it counts
    assert values(masked, pattern(r"\](\d)", "digit")) == [(1, 0, "9")]


def test_an_optional_group_that_took_no_part_gives_no_value():
    assert values("trip x", pattern(r"trip (\d+)?", "trip")) == []


def test_no_text_no_values():
    assert extract(None, [pattern(r"x")]) == [] and extract("", [pattern(r"x")]) == []


@pytest.mark.parametrize("regex, reason", [
    (r"(a)(b)", "at most one capture group"),
    (r"(?P<x>a)(?P<y>b)", "at most one capture group"),
    (r"x*", "matches empty text"),
    (r"(?=x)", "not a valid pattern"),
    ("a" * 257, "at most 256"),
    ("", "required"),
])
def test_a_pattern_is_refused_with_its_reason(regex, reason):
    with pytest.raises(LogPatternError) as err:
        compile_log_pattern(regex)
    assert err.value.field == "pattern" and reason in str(err.value)


def test_a_non_capturing_group_is_fine():
    assert compile_log_pattern(r'(?:trip|order)Id="(\d+)"').groups == 1


@pytest.mark.parametrize("name", ["Trip", "1trip", "trip-id", "", "a" * 33])
def test_a_bad_name_is_refused(name):
    with pytest.raises(LogPatternError) as err:
        log_values.validate_name(name)
    assert err.value.field == "name"


def test_a_link_template_is_optional_and_kept_as_given():
    assert log_values.validate_link_template(None) is None
    assert log_values.validate_link_template("  ") is None
    template = "https://backoffice.example.com/trips/{value}?tab=summary"
    assert log_values.validate_link_template(f" {template} ") == template


@pytest.mark.parametrize("template", [
    "javascript:alert(1)//{value}",
    "data:text/html,{value}",
    "http://backoffice.example.com/trips/{value}",
    "https://{value}.example.com/trips",
    "https://backoffice.example.com{value}/trips",
    "https://user@backoffice.example.com/trips/{value}",
    "https:{value}",
    "https:///trips/{value}",
    "https://backoffice.example.com/trips/",
    "https://backoffice.example.com/{value}/{value}",
    "https://backoffice.example.com/trips/{value} x",
    "https://backoffice.example.com/" + "a" * 490 + "/{value}",
])
def test_a_link_template_that_could_leave_the_url_is_refused(template):
    with pytest.raises(LogPatternError) as err:
        log_values.validate_link_template(template)
    assert err.value.field == "link_template"


def test_a_marker_dense_log_is_read_in_well_under_a_second():
    """64 KB of masking markers and a loose pattern: the overlap check must not walk every marker per match."""
    import time

    masked = ("[REDACTED:email] 7 " * 3_400)[:65_536]
    patterns = [pattern(r"(\d)", f"p{n}", n) for n in range(20)]
    started = time.perf_counter()
    got = extract(masked, patterns)
    assert time.perf_counter() - started < 1.0
    assert got == [(n, 0, "7") for n in range(20)]


@pytest.mark.parametrize("regex", ["a\x00b", "trip\ud800"])
def test_a_pattern_that_cannot_be_stored_is_refused_not_500(regex):
    with pytest.raises(LogPatternError) as err:
        compile_log_pattern(regex)
    assert err.value.field == "pattern" and "NUL" in str(err.value)


def test_a_name_with_a_trailing_newline_is_refused():
    with pytest.raises(LogPatternError):
        log_values.validate_name("trip\n")
