"""Scoring a change (spec 2026-10-12 §3.3): thresholds at their edges, ordering, the cap, each label (plan Rulings 10, 11)."""
import pytest

from src.ingestion.analytics import impact_score
from src.ingestion.analytics.impact_rules import MAX_PER_LABEL, MAX_STATISTICAL, MIN_HISTORY_RUNS, ChangedFiles
from src.ingestion.analytics.impact_score import BaseStat, ImpactTest, PairStat, evidence, suggest

UNITS = {"src/pay/api.py", "src/pay/", "src/"}


def key(name):
    return name.ljust(64, "0")


def named(name):
    return ImpactTest(key(name), "s", "C", name)


def base(name, runs=40, new_failures=10, file=None, flaky=False):
    return BaseStat(named(name), runs, new_failures, file, flaky)


def pair(name, unit="src/pay/", changed_runs=4, new_failures=2):
    return PairStat(unit, key(name), changed_runs, new_failures)


def score(pairs=(), bases=(), history=MIN_HISTORY_RUNS, paths=("src/pay/api.py",), failing=(), units=UNITS):
    return suggest(units, list(pairs), {b.test.test_key: b for b in bases}, history_runs=history,
                   changed_files=ChangedFiles(paths), failing_on_branch=list(failing))


def kinds(result):
    return [(t["name"], t["kind"]) for t in result["tests"]]


@pytest.mark.parametrize("changed_runs, expected", [(2, None), (3, 0.6667)])
def test_changed_runs_must_be_at_least_3(changed_runs, expected):
    found = evidence(pair("pays", changed_runs=changed_runs), base("pays"))
    assert (found and found["confidence"]) == expected


@pytest.mark.parametrize("new_failures, kept", [(1, False), (2, True)])
def test_new_failures_must_be_at_least_2(new_failures, kept):
    found = evidence(pair("pays", changed_runs=6, new_failures=new_failures), base("pays", runs=100, new_failures=1))
    assert (found is not None) is kept


@pytest.mark.parametrize("base_runs, kept", [(38, False), (40, True)])  # lift 1.9, then exactly 2
def test_lift_must_be_at_least_2(base_runs, kept):
    assert (evidence(pair("pays"), base("pays", runs=base_runs, new_failures=10)) is not None) is kept


def test_a_lift_of_exactly_2_is_kept():
    found = evidence(pair("pays", changed_runs=4, new_failures=2), base("pays", runs=40, new_failures=10))
    assert found is not None and found["lift"] == 2.0


def test_the_lift_threshold_is_compared_exactly_not_in_floats(monkeypatch):
    """3/5 over 1/5 is exactly 3, but (3/5) / (1/5) is 2.9999999999999996 in floats."""
    monkeypatch.setattr(impact_score, "MIN_LIFT", 3)
    found = evidence(pair("pays", changed_runs=5, new_failures=3), base("pays", runs=5, new_failures=1))
    assert found is not None and found["lift"] == 3.0


def test_a_base_rate_of_0_passes_the_lift_test_and_shows_no_normal_rate():
    """Any new failure is infinitely above a test that never newly fails otherwise: the clearest signal, so kept."""
    assert evidence(pair("pays"), base("pays", new_failures=0)) == {
        "path_unit": "src/pay/", "changed_runs": 4, "new_failures": 2, "confidence": 0.5, "lift": None, "base_rate": None}
    assert evidence(pair("pays", changed_runs=2), base("pays", new_failures=0)) is None  # the other thresholds still hold


def test_a_base_rate_of_0_ranks_above_any_finite_lift_at_the_same_confidence():
    result = score([pair("a_finite", changed_runs=3, new_failures=3), pair("z_never_fails", changed_runs=3, new_failures=3)],
                   [base("a_finite", runs=80, new_failures=1), base("z_never_fails", new_failures=0)])
    assert [t["name"] for t in result["tests"]] == ["z_never_fails", "a_finite"]


def test_the_evidence_holds_what_the_card_shows():
    assert evidence(pair("pays"), base("pays")) == {
        "path_unit": "src/pay/", "changed_runs": 4, "new_failures": 2, "confidence": 0.5, "lift": 2.0, "base_rate": 0.25}


def test_each_test_takes_its_best_unit_of_the_change():
    pairs = [pair("pays", "src/", changed_runs=10, new_failures=3), pair("pays", "src/pay/"),
             pair("pays", "lib/", changed_runs=3, new_failures=3)]  # lib/ is not a unit of this change
    assert [t["evidence"]["path_unit"] for t in score(pairs, [base("pays")])["tests"]] == ["src/pay/"]


def test_a_tie_goes_to_the_more_specific_unit():
    # "web/" is shorter but sorts above "src/pay/" as a string: only the length rule picks "src/pay/"
    result = score([pair("pays", "web/"), pair("pays", "src/pay/")], [base("pays")],
                   paths=("src/pay/api.py", "web/app.py"), units=UNITS | {"web/app.py", "web/"})
    assert result["tests"][0]["evidence"]["path_unit"] == "src/pay/"


def test_a_tie_in_confidence_and_lift_goes_to_more_changed_runs_before_specificity():
    result = score([pair("pays", "src/", changed_runs=6, new_failures=3), pair("pays", "src/pay/")], [base("pays")])
    assert result["tests"][0]["evidence"]["path_unit"] == "src/"


def test_confidence_ranks_before_lift():
    pairs = [pair("a_high_lift", changed_runs=4, new_failures=2), pair("z_high_confidence", changed_runs=3, new_failures=3)]
    bases = [base("a_high_lift", runs=80, new_failures=2), base("z_high_confidence")]  # lift 20 at 0.5, lift 4 at 1.0
    assert [t["name"] for t in score(pairs, bases)["tests"]] == ["z_high_confidence", "a_high_lift"]


def test_strongest_first_by_confidence_then_lift_then_name():
    pairs = [pair("b_lower_lift"), pair("a_lower_lift"), pair("strong", changed_runs=3, new_failures=3), pair("c_higher_lift")]
    bases = [base("b_lower_lift"), base("a_lower_lift"), base("strong"), base("c_higher_lift", runs=80)]
    assert [t["name"] for t in score(pairs, bases)["tests"]] == ["strong", "c_higher_lift", "a_lower_lift", "b_lower_lift"]


def test_at_most_50_statistical_suggestions_the_strongest():
    strong = [f"z{i:03d}" for i in range(MAX_STATISTICAL)]
    weak = [f"a{i:03d}" for i in range(10)]  # first by name, so only strength drops them
    pairs = [pair(n, changed_runs=3, new_failures=3) for n in strong] + [pair(n) for n in weak]
    result = score(pairs, [base(n) for n in strong + weak])
    assert [t["name"] for t in result["tests"]] == strong
    assert result["statistical_total"] == MAX_STATISTICAL + 10


def test_a_flaky_test_is_never_suggested_from_statistics():
    assert score([pair("pays")], [base("pays", flaky=True)])["tests"] == []


def test_not_enough_history_leaves_statistics_out_but_keeps_the_labels():
    result = score([pair("pays")], [base("pays"), base("brand_new", runs=1, new_failures=0)], history=MIN_HISTORY_RUNS - 1)
    assert (result["state"], result["history_runs"], result["needed_runs"]) == (
        "not_enough_history", MIN_HISTORY_RUNS - 1, MIN_HISTORY_RUNS)
    assert kinds(result) == [("brand_new", "no_history")]


def test_each_label_outside_the_cap_and_each_test_once():
    names = [f"t{i:03d}" for i in range(MAX_STATISTICAL)]
    bases = [base(n) for n in names] + [base("pay_spec", runs=9, new_failures=0, file="tests/pay_spec.py"),
                                        base("brand_new", runs=2, new_failures=0), base("fresh", runs=1, new_failures=0)]
    failing = [named("cart"), named("t000")]  # t000 is already a statistical suggestion
    result = score([pair(n) for n in names], bases, paths=("src/pay/api.py", "tests/pay_spec.py"), failing=failing)
    assert kinds(result)[MAX_STATISTICAL:] == [("pay_spec", "test_file_changed"), ("cart", "failing_on_branch"),
                                               ("brand_new", "no_history"), ("fresh", "no_history")]
    assert len({t["test_key"] for t in result["tests"]}) == len(result["tests"])


def test_no_history_has_its_own_threshold(monkeypatch):
    """"No history" is NO_HISTORY_RUNS, not the statistical MIN_CHANGED_RUNS: tuning one must not move the other."""
    bases = [base("four", runs=4, new_failures=0), base("five", runs=5, new_failures=0)]
    monkeypatch.setattr(impact_score, "MIN_CHANGED_RUNS", 5)
    assert kinds(score(bases=bases)) == []
    monkeypatch.setattr(impact_score, "NO_HISTORY_RUNS", 5)
    assert kinds(score(bases=bases)) == [("four", "no_history")]


def test_each_label_lists_at_most_100_tests():
    bases = [base(f"new{i:03d}", runs=0, new_failures=0) for i in range(MAX_PER_LABEL + 20)]
    assert len(score(bases=bases)["tests"]) == MAX_PER_LABEL


def test_the_whole_answer():
    assert score([pair("pays")], [base("pays")]) == {
        "state": "ok", "history_runs": MIN_HISTORY_RUNS, "needed_runs": MIN_HISTORY_RUNS, "statistical_total": 1,
        "tests": [{"test_key": key("pays"), "suite": "s", "class_name": "C", "name": "pays", "kind": "statistical",
                   "evidence": {"path_unit": "src/pay/", "changed_runs": 4, "new_failures": 2, "confidence": 0.5,
                                "lift": 2.0, "base_rate": 0.25}}],
    }
