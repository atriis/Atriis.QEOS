"""Inside a step, failures group by the shape of their error (spec 2026-10-14 §3.2)."""
from src.ingestion.analytics.failed_steps import error_shape


def test_quoted_values_are_replaced_quotes_kept():
    assert error_shape("Invalid city 'Lisb0n'") == "Invalid city '…'"
    assert error_shape('expected "ok" but was "ko"') == 'expected "…" but was "…"'
    assert error_shape("locator `#pay` not found") == "locator `…` not found"


def test_an_apostrophe_inside_a_word_is_not_a_quote():
    assert error_shape("can't find 'pay button'") == "can't find '…'"


def test_numbers_uuids_and_hex_are_replaced():
    assert error_shape("Timeout of 30000ms exceeded") == "Timeout of …ms exceeded"
    assert error_shape("order 123e4567-e89b-12d3-a456-426614174000 missing") == "order … missing"
    assert error_shape("object 0x7ffe12 at deadbeef1 freed") == "object … at … freed"


def test_two_failures_that_differ_only_in_values_share_a_shape():
    assert error_shape("Invalid city 'Lisb0n' (id 12)") == error_shape("Invalid city 'P0rto' (id 7)")


def test_only_the_first_non_empty_line_counts_and_spaces_collapse():
    assert error_shape("\n  Invalid   city 'x'\n    at Steps.search(Steps.java:12)") == "Invalid city '…'"


def test_no_message_is_the_empty_shape():
    assert error_shape(None) == "" and error_shape("   \n") == ""


def test_different_http_statuses_are_different_shapes():
    assert error_shape("Request failed with status 500") != error_shape("Request failed with status 404")


def test_expected_and_actual_status_are_kept_when_the_line_speaks_of_a_status():
    assert error_shape("expected status 200 but got 500") != error_shape("expected status 200 but got 404")
    assert error_shape("expected status 200 but got 500") == "expected status 200 but got 500"


def test_a_bare_expected_got_pair_without_a_status_word_collapses():
    assert error_shape("expected 200 got 500") == "expected … got …"


def test_a_count_after_got_is_not_a_status():
    assert error_shape("expected 3 items, got 250 rows") == "expected … items, got … rows"


def test_http_followed_by_a_status_is_kept():
    assert error_shape("HTTP 503 Service Unavailable") == "HTTP 503 Service Unavailable"


def test_other_numbers_are_still_replaced():
    assert error_shape("Timeout after 30012 ms") == "Timeout after … ms"


def test_a_number_that_is_not_a_status_code_after_a_keyword_is_replaced():
    assert error_shape("expected 20 got 7") == "expected … got …"


def test_values_of_different_length_near_the_cut_share_a_shape():
    prefix = "x" * 290
    a = error_shape(f"{prefix} 123e4567-e89b-12d3-a456-426614174000 tail")
    b = error_shape(f"{prefix} 7 tail")
    assert a == b and len(a) <= 300


def test_a_huge_first_line_is_bounded():
    assert len(error_shape("y " * 5000 + "status 500")) <= 300
