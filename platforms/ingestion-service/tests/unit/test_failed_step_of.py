from src.ingestion.service.analytics_service import failed_step_of


def test_stored_step_wins():
    assert failed_step_of("failed", "boom", "When x\nboom", "When I search", 14) == {"text": "When I search", "line": 14}


def test_old_rows_take_the_first_details_line_when_it_is_not_the_message():
    assert failed_step_of("failed", "boom", "When I search Lisbon\nboom\n  at x", None, None) == {"text": "When I search Lisbon"}


def test_no_step_when_details_starts_with_the_message():
    assert failed_step_of("failed", "boom", "boom\n  at x", None, None) is None


def test_errored_counts_and_passed_never_has_a_step():
    assert failed_step_of("errored", None, "Given y\nE", None, None) == {"text": "Given y"}
    assert failed_step_of("passed", None, None, "When x", 3) is None
    assert failed_step_of("failed", None, None, None, None) is None
