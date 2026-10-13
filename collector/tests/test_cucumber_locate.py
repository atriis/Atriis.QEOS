"""Where a suggested scenario is, read from the local .feature files (spec 2026-10-13 §2.1; plan Ruling 14)."""
from qeos_collector.cucumber import has_feature_files, locate, name_filter, scan_feature

PAY = (
    "@payments\n"                                        # 1
    "Feature: Pay\n"                                     # 2
    "\n"                                                 # 3
    "  Background:\n"                                    # 4
    "    Given a shopper\n"                              # 5
    "\n"                                                 # 6
    "  @smoke\n"                                         # 7
    "  Scenario: Pays with card\n"                       # 8
    "    When the shopper pays: by card\n"               # 9
    "      | card | 4111 |\n"                            # 10
    "\n"                                                 # 11
    "  Scenario Outline: Pays <amount> in <currency>\n"  # 12
    "    When the shopper pays <amount>\n"               # 13
    "\n"                                                 # 14
    "    Examples:\n"                                    # 15
    "      | amount | currency |\n"                      # 16
    "      | 10     | EUR      |\n"                      # 17
    "      | 20     | USD      |\n"                      # 18
    "\n"                                                 # 19
    "  Rule: refunds\n"                                  # 20
    "    Example: Refunds a payment\n"                   # 21
    "      Then the money returns\n"                     # 22
)


def test_scenarios_and_outline_rows_have_their_own_lines():
    assert scan_feature(PAY) == [("Pays with card", 8), ("Pays 10 in EUR", 17), ("Pays 20 in USD", 18),
                                 ("Refunds a payment", 21)]


def test_a_scenario_template_with_scenarios():
    text = "Feature: F\n  Scenario Template: T <x>\n    Scenarios:\n      | x |\n      | a |\n"
    assert scan_feature(text) == [("T a", 5)]


def test_doc_strings_are_text_not_scenarios():
    text = ('Feature: F\n  Scenario: Real\n    Given a note\n      """\n      Scenario: Not one\n      """\n'
            "    And code\n      ```\n      Scenario: Nor this\n      ```\n  Scenario: Next\n")
    assert scan_feature(text) == [("Real", 2), ("Next", 11)]


def test_a_feature_in_another_language_gives_no_lines():
    assert scan_feature("# language: fr\nFonctionnalité: Payer\n  Scénario: Paie\n") == []
    assert scan_feature("# language: en\nFeature: Pay\n  Scenario: Pays\n") == [("Pays", 3)]


def test_locate_reads_the_tests_feature_file(tmp_path):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "pay.feature").write_text(PAY, encoding="utf-8")
    test = {"suite": "Pay", "class_name": "features/pay.feature", "name": "Pays with card"}
    assert locate(str(tmp_path), test) == ["features/pay.feature:8"]
    assert locate(str(tmp_path), {**test, "class_name": "file:features/pay.feature"}) == ["file:features/pay.feature:8"]
    assert locate(str(tmp_path), {**test, "name": "Pays 20 in USD"}) == ["features/pay.feature:18"]


def test_windows_line_endings_and_a_byte_order_mark_change_nothing(tmp_path):
    (tmp_path / "pay.feature").write_bytes(("\ufeff" + PAY.replace("\n", "\r\n")).encode("utf-8"))
    assert locate(str(tmp_path), {"class_name": "pay.feature", "name": "Pays 20 in USD"}) == ["pay.feature:18"]


def test_locate_gives_nothing_it_cannot_read_here(tmp_path):
    (tmp_path / "pay.feature").write_text(PAY, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    for class_name in ("classpath:features/pay.feature", "missing.feature", "PayTest", "../pay.feature",
                       str(tmp_path / "pay.feature")):
        assert locate(str(tmp_path / "sub"), {"class_name": class_name, "name": "Pays with card"}) == []


def test_a_name_filter_is_anchored_and_safe_to_paste():
    assert name_filter("Gone away") == '--name "^Gone away$"'
    assert name_filter('Pay $5 (card) "now"!') == '--name "^Pay .5 .card. .now..$"'
    assert name_filter("a\tb\nc") == '--name "^a.b.c$"'


def test_feature_files_are_found_outside_vendored_folders(tmp_path):
    assert not has_feature_files(str(tmp_path))
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "a.feature").write_text("Feature: A\n", encoding="utf-8")
    assert not has_feature_files(str(tmp_path))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "b.feature").write_text("Feature: B\n", encoding="utf-8")
    assert has_feature_files(str(tmp_path))
