"""A failed step is its step definition, else its text (spec 2026-10-14 §3.2)."""
import re

from src.ingestion.analytics.failed_steps import step_key, step_text_identity


def test_one_definition_is_one_step_whatever_the_parameters():
    lisbon = step_key("steps/search.js:12", "When I search Lisbon")
    porto = step_key("steps/search.js:12", "When I search Porto")
    assert lisbon == porto and lisbon[1] == "definition"


def test_without_a_definition_the_text_is_compared_without_case_or_extra_spaces():
    assert step_key(None, "When I  search\tLisbon ")[0] == step_key("", "when i search lisbon")[0]
    assert step_key(None, "When I search Lisbon")[1] == "text"
    assert step_key(None, "When I search Lisbon")[0] != step_key(None, "When I search Porto")[0]


def test_a_definition_and_a_text_never_share_a_key():
    assert step_key("When I search Lisbon", "x")[0] != step_key(None, "When I search Lisbon")[0]


def test_the_key_is_short_hex_safe_in_a_url_fragment():
    assert re.fullmatch(r"[0-9a-f]{16}", step_key("steps/search.js:12", "x")[0])


def test_identity_collapses_whitespace_and_lowercases():
    assert step_text_identity("  When I   SEARCH\nLisbon ") == "when i search lisbon"
