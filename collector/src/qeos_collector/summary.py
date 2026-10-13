"""run-impact's summary (spec 2026-10-13 §2.2, plan Ruling 20): the suggested tests with their evidence, each stage's
size, failures and duration, and the time to the first failure. A table in the GitHub Actions job's step summary;
anywhere else, or when that file cannot be written, the same as lines in the log. Never the API key."""
from __future__ import annotations

import math
import re
from typing import Callable, List, Mapping, Sequence

STAGES = {"suggested": "suggested tests", "rest": "the rest", "all": "full suite"}
LABELS = {"test_file_changed": "test file changed", "failing_on_branch": "failing on this branch",
          "no_history": "no history yet"}
SHOWN = 50


def _round(value: float) -> int:
    """JavaScript's Math.round: halves go up."""
    return math.floor(value + 0.5)


def duration(seconds: float) -> str:
    """The dashboard's formatDuration (dashboard/src/api/analytics.ts), rule for rule, on whole milliseconds: "400 ms";
    below 60 s once rounded to tenths, "42.5 s"; else whole seconds, rounded first and carried into the minutes,
    "1m 05s" (119.5 s is "2m 00s"). One figure, one wording, there and here."""
    ms = _round(seconds * 1000)
    if ms < 1000:
        return f"{ms} ms"
    tenths = _round(ms / 100)
    if tenths < 600:
        return f"{tenths // 10}.{tenths % 10} s"
    total = _round(ms / 1000)
    return f"{total // 60}m {total % 60:02d}s"


def flat(value) -> str:
    """One line: line breaks as one space."""
    return re.sub(r"\s*[\r\n]+\s*", " ", str(value or ""))


def cell(value) -> str:
    """Text for a Markdown table cell, shown as written: & < > as entities (no HTML gets through), backticks
    escaped (no code span opens), pipes escaped, line breaks as one space."""
    text = flat(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("`", "\\`").replace("|", "\\|")


def code(value) -> str:
    """A code span in a table cell, whatever backticks the text holds: a fence one backtick longer than its longest
    run, padded when the text starts or ends with one. Inside it nothing is HTML; only pipes need escaping."""
    text = flat(value).replace("|", "\\|")
    fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def why(test: dict, *, markdown: bool = False) -> str:
    """Why the test is suggested. With markdown, ready for a table cell (cell- and code-escaped)."""
    evidence = test.get("evidence")
    if test.get("kind") == "statistical" and isinstance(evidence, dict):
        unit = str(evidence.get("path_unit") or "")
        failures, runs = evidence.get("new_failures"), evidence.get("changed_runs")
        if markdown:
            return f"newly failed in {cell(failures)} of {cell(runs)} runs that changed {code(unit)}"
        return f"newly failed in {failures} of {runs} runs that changed {flat(unit)}"
    label = LABELS.get(str(test.get("kind")), str(test.get("kind") or ""))
    return cell(label) if markdown else flat(label)


def outcome(stages: Sequence, payload: dict, scope: str) -> str:
    first = payload.get("time_to_first_failure_s")
    if scope == "impact-subset":
        head = "suggested tests only" + (", stopped after stage 1" if payload.get("stopped_after_stage") == 1 else "")
        return f"{head}: " + ("no failures" if first is None else f"first failure after {duration(first)}")
    if first is None:
        return "no failures"
    return f"first failure after {duration(first)} (full suite {duration(sum(s.duration_s for s in stages))})"


def text(tests: Sequence[dict], missing: Sequence[dict], stages: Sequence, payload: dict, scope: str) -> List[str]:
    lines = [f"stage {i} ({STAGES.get(s.name, s.name)}): {s.tests} scenario(s), {s.failed} failed, "
             f"{duration(s.duration_s)}" for i, s in enumerate(stages, start=1)]
    lines.append(outcome(stages, payload, scope))
    lines += [f"  {flat(test.get('name'))}: {why(test)}" for test in tests[:SHOWN]]
    if len(tests) > SHOWN:
        lines.append(f"  … and {len(tests) - SHOWN} more")
    return lines


def markdown(tests: Sequence[dict], missing: Sequence[dict], stages: Sequence, payload: dict, scope: str) -> str:
    said = outcome(stages, payload, scope)
    lines = ["### QEOS: suggested tests first", "", "| Stage | What | Scenarios | Failed | Duration |",
             "|---:|---|---:|---:|---:|"]
    lines += [f"| {i} | {STAGES.get(s.name, s.name)} | {s.tests} | {s.failed} | {duration(s.duration_s)} |"
              for i, s in enumerate(stages, start=1)]
    lines += ["", said[0].upper() + said[1:] + "."]
    if tests:
        lines += ["", f"<details><summary>Suggested tests ({len(tests)})</summary>", "", "| Test | Why |", "|---|---|"]
        lines += [f"| {cell(test.get('name'))} | {why(test, markdown=True)} |" for test in tests[:SHOWN]]
        if len(tests) > SHOWN:
            lines.append(f"| … and {len(tests) - SHOWN} more | |")
        lines += ["", "</details>"]
    if missing:
        lines += ["", "Not among this command's scenarios (left out by its filters, or not Cucumber): "
                  + ", ".join(cell(test.get("name")) for test in missing[:SHOWN]) + "."]
    return "\n".join(lines) + "\n\n"


def publish(env: Mapping[str, str], say: Callable[[str], None], tests: Sequence[dict], missing: Sequence[dict],
            stages: Sequence, payload: dict, scope: str, *, secret: str = "") -> None:
    """The step summary when GITHUB_ACTIONS and GITHUB_STEP_SUMMARY are both set; else, or when it cannot be
    written, the log (`say` scrubs the key from each line). The file is written here, so it is scrubbed here."""
    path = env.get("GITHUB_STEP_SUMMARY", "").strip() if env.get("GITHUB_ACTIONS", "").strip() else ""
    if path:
        table = markdown(tests, missing, stages, payload, scope)
        if secret:
            table = table.replace(secret, "***")
        try:
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(table)
            say("summary written to the job's step summary")
            return
        except OSError as exc:
            say(f"cannot write the step summary ({exc.strerror or exc}); here it is")
    for line in text(tests, missing, stages, payload, scope):
        say(line)
