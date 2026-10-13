"""run-impact's summary (spec 2026-10-13 §2.2; plan Ruling 20)."""
from types import SimpleNamespace

import pytest

from qeos_collector import summary

STAT = {"name": "Pays | 10", "kind": "statistical",
        "evidence": {"path_unit": "src/pay/", "changed_runs": 6, "new_failures": 4}}
LABEL = {"name": "refunds\nlater", "kind": "failing_on_branch", "evidence": None}


def stage(name, tests, failed, seconds):
    return SimpleNamespace(name=name, tests=tests, failed=failed, duration_s=seconds)


# The dashboard's formatDuration (dashboard/src/api/analytics.ts) on these milliseconds, as node 24 printed it from
# that file's own source. The rounding boundaries are the point: toFixed(1) ties go up (2.25 -> "2.3", where Python's
# "%.1f" says "2.2"); Math.round(59.5) is 60, so 119.5 s is "1m 60s"; 178.5 s is "2m 59s" (Python's round says 58).
DASHBOARD = [(0, "0 ms"), (400, "400 ms"), (999, "999 ms"), (1000, "1.0 s"), (2250, "2.3 s"), (2350, "2.4 s"),
             (3000, "3.0 s"), (42500, "42.5 s"), (59940, "59.9 s"), (59950, "60.0 s"), (59960, "60.0 s"),
             (60000, "1m 00s"), (65000, "1m 05s"), (119400, "1m 59s"), (119499, "1m 59s"), (119500, "1m 60s"),
             (119999, "1m 60s"), (120000, "2m 00s"), (178500, "2m 59s"), (915000, "15m 15s")]


@pytest.mark.parametrize("ms, text", DASHBOARD)
def test_durations_read_exactly_as_the_dashboard_says_them(ms, text):
    assert summary.duration(ms / 1000) == text


def test_cells_escape_pipes_and_line_breaks():
    assert summary.cell("a|b\r\nc") == "a\\|b c"


def test_why_names_the_evidence_or_the_label():
    assert summary.why(STAT) == "newly failed in 4 of 6 runs that changed src/pay/"
    assert summary.why(STAT, markdown=True) == "newly failed in 4 of 6 runs that changed `src/pay/`"
    assert summary.why(LABEL) == "failing on this branch"


def test_the_markdown_has_the_stages_the_first_failure_and_the_suggested_tests():
    md = summary.markdown([STAT, LABEL], [{"name": "Gone"}],
                          [stage("suggested", 1, 1, 60), stage("rest", 4, 0, 60)],
                          {"time_to_first_failure_s": 3.0}, "full")
    assert "### QEOS: suggested tests first" in md
    assert "| 1 | suggested tests | 1 | 1 | 1m 00s |" in md
    assert "| 2 | the rest | 4 | 0 | 1m 00s |" in md
    assert "First failure after 3.0 s (full suite 2m 00s)." in md
    assert "| Pays \\| 10 | newly failed in 4 of 6 runs that changed `src/pay/` |" in md
    assert "| refunds later | failing on this branch |" in md
    assert "Not among this command's scenarios (left out by its filters, or not Cucumber): Gone." in md


def test_a_subset_says_suggested_tests_only():
    lines = summary.text([STAT], [], [stage("suggested", 1, 1, 60)],
                         {"time_to_first_failure_s": 3.0, "stopped_after_stage": 1}, "impact-subset")
    assert lines[:2] == ["stage 1 (suggested tests): 1 scenario(s), 1 failed, 1m 00s",
                         "suggested tests only, stopped after stage 1: first failure after 3.0 s"]


def test_a_run_without_failures_says_so():
    assert summary.outcome([stage("all", 5, 0, 60)], {"time_to_first_failure_s": None}, "full") == "no failures"


def test_long_lists_are_cut():
    tests = [{"name": f"t{i}", "kind": "no_history"} for i in range(summary.SHOWN + 3)]
    assert "| … and 3 more | |" in summary.markdown(tests, [], [stage("all", 1, 0, 1)], {}, "full")
    assert summary.text(tests, [], [stage("all", 1, 0, 1)], {}, "full")[-1] == "  … and 3 more"


@pytest.mark.parametrize("env", [
    {"GITHUB_ACTIONS": "true"},                              # no file named
    {"GITHUB_STEP_SUMMARY": "SUMMARY"},                      # not GitHub Actions
    {"GITHUB_ACTIONS": "", "GITHUB_STEP_SUMMARY": "SUMMARY"},
])
def test_the_step_summary_needs_both_variables(tmp_path, env):
    target = tmp_path / "summary.md"
    env = {name: (str(target) if value == "SUMMARY" else value) for name, value in env.items()}
    said = []
    summary.publish(env, said.append, [STAT], [], [stage("all", 5, 0, 60)], {}, "full")
    assert not target.exists()
    assert said[0] == "stage 1 (full suite): 5 scenario(s), 0 failed, 1m 00s"


def test_the_step_summary_never_holds_the_key(tmp_path):
    key = "qeos_secret_key_123"
    target = tmp_path / "summary.md"
    said = []
    leaky = {"name": f"logs in with {key}", "kind": "statistical",
             "evidence": {"path_unit": f"src/{key}/", "changed_runs": 2, "new_failures": 1}}
    summary.publish({"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(target)}, said.append, [leaky],
                    [{"name": key}], [stage("all", 5, 0, 60)], {}, "full", secret=key)
    written = target.read_text(encoding="utf-8")
    assert key not in written and "logs in with ***" in written and "`src/***/`" in written
    assert said == ["summary written to the job's step summary"]



def test_names_and_paths_cannot_inject_markup():
    """A test name is shown as written: no HTML, no code span, no extra column. A path unit stays one code span,
    whatever backticks it holds."""
    test = {"name": "<img src=x onerror=alert(1)> A & B `x` | y", "kind": "statistical",
            "evidence": {"path_unit": "src/`odd``|dir/", "changed_runs": 6, "new_failures": 4}}
    md = summary.markdown([test], [{"name": "<b>gone</b>"}], [stage("all", 1, 0, 1)], {}, "full")
    assert "| &lt;img src=x onerror=alert(1)&gt; A &amp; B \\`x\\` \\| y | newly failed in 4 of 6 runs that changed " \
           "```src/`odd``\\|dir/``` |" in md
    assert "<img" not in md and "<b>" not in md and "&lt;b&gt;gone&lt;/b&gt;" in md
    assert summary.code("`edge`") == "`` `edge` ``"
    assert summary.text([test], [], [stage("all", 1, 0, 1)], {}, "full")[-1] == (
        "  <img src=x onerror=alert(1)> A & B `x` | y: newly failed in 4 of 6 runs that changed src/`odd``|dir/")
