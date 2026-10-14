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
