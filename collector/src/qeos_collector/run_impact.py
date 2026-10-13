"""qeos-collector run-impact: the scenarios a change likely affects first, then the rest, uploaded as one run (spec
2026-10-13 §2.2; plan Rulings 6-13, 16, 21).

1. QEOS scores the change (impact.fetch: the upload's changed files, POST /api/v1/collect/impact). Scoring never
   keeps a test from running: when it fails for any reason (401, 403, 404, 422, 429, 5xx, a timeout, no answer, no
   change data), the command runs as given, as one stage, and the log says why.
2. Discovery: the test command as given, as a Cucumber dry run with a JSON report: the scenarios it would run.
3. The plan:
   - the suggested scenarios among them go in stage 1's rerun file, every other one in stage 2's, so none runs twice;
   - feature paths the command shows are left out of the stage commands;
   - a dry run of stage 1 checks that its rerun file alone decides what runs. A profile's `paths`, an npm script or
     `--shard` would not let it; then nothing runs.
4. The stages' JSON reports are uploaded as one run, with its scope and stages."""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from qeos_collector import cucumber, impact
from qeos_collector.formats import parse_file
from qeos_collector.junit import ParsedFile
from qeos_collector.payload import SCOPES
from qeos_collector.upload import ConfigError

FULL, SUBSET = SCOPES
REFUSED = 2  # QEOS refused to score (a configuration problem): `impact` would exit 2
FAILING = ("failed", "errored")
SHOWN_MISSING = 5
_WINDOWS = os.name == "nt"
# cmd.exe expands % and splits on & | < > ^ even inside the quotes subprocess adds
_CMD_SPECIAL = frozenset('%&|<>^"')

# (stage reports, scope, stages) -> the last receipt, or None when nothing was stored
Upload = Callable[[List[ParsedFile], str, dict], Optional[dict]]


@dataclass
class Stage:
    name: str  # "suggested", "rest" or "all"
    returncode: int
    duration_s: float
    report: ParsedFile

    @property
    def tests(self) -> int:
        return len(self.report.results)

    @property
    def failed(self) -> int:
        return sum(1 for row in self.report.results if row["status"] in FAILING)


def run_command(argv: Sequence[str]) -> int:
    """The command's exit code. The program is looked up with shutil.which, so a Windows runner finds npx.cmd or
    mvn.cmd through PATHEXT, which a bare CreateProcess does not (plan Ruling 21). Never through a shell."""
    program = shutil.which(argv[0]) or argv[0]
    try:
        return subprocess.run([program, *argv[1:]], check=False).returncode
    except OSError as exc:
        raise ConfigError(f"cannot run {argv[0]}: {exc.strerror or exc}") from None


def check_paths(flavour: str, command: Sequence[str], cwd: str) -> None:
    """On Windows, a .cmd or .bat program (mvn.cmd, gradlew.bat, cucumber.bat) runs through cmd.exe, which would
    expand a % or split on a & in the absolute paths run-impact hands cucumber-jvm and Ruby Cucumber. cucumber-js only
    gets paths relative to the working directory, made of run-impact's own safe names."""
    if not _WINDOWS or flavour == "js" or not command:
        return
    program = (shutil.which(command[0]) or command[0]).lower()
    if program.endswith((".cmd", ".bat")) and _CMD_SPECIAL & set(cwd):
        raise ConfigError(f"run-impact cannot hand {command[0]} paths under {cwd}: cmd.exe would change the "
                          f"characters {' '.join(sorted(_CMD_SPECIAL & set(cwd)))} in them. Run it from a folder "
                          "without them. Nothing was run.")


def first_failure_after(stages: Sequence[Stage]) -> Optional[float]:
    """Seconds from the start of stage 1 to the end of the first failing scenario: the earlier stages' wall time, plus
    the failing stage's scenarios in report order (plan Ruling 6). With parallel workers, an upper bound."""
    offset = 0.0
    for stage in stages:
        elapsed = 0.0
        for row in stage.report.results:
            elapsed += row["duration_ms"] / 1000
            if row["status"] in FAILING:
                return round(offset + elapsed, 3)
        offset += stage.duration_s
    return None


def stages_payload(stages: Sequence[Stage], stopped_after_stage: Optional[int] = None) -> dict:
    payload = {
        "stages": [{"name": s.name, "duration_s": round(s.duration_s, 3), "tests": s.tests, "failed": s.failed}
                   for s in stages],
        "time_to_first_failure_s": first_failure_after(stages),
    }
    if stopped_after_stage is not None:
        payload["stopped_after_stage"] = stopped_after_stage
    return payload


class _Cucumber:
    """The dry runs and stages of one invocation, their files in one working directory."""

    def __init__(self, flavour: str, workdir: Path, cwd: str, runner: Callable[[Sequence[str]], int],
                 clock: Callable[[], float], say: Callable[[str], None]):
        self.flavour, self.workdir, self.cwd = flavour, workdir, cwd
        self.runner, self.clock, self.say = runner, clock, say

    def _rerun(self, label: str, scenarios: Sequence[cucumber.Scenario]) -> str:
        if not scenarios:  # an empty rerun file is "everything" to some runners
            raise AssertionError(f"no scenarios for {label}")
        path = self.workdir / f"@{label}.txt"
        cucumber.write_rerun(path, scenarios)
        return cucumber.rerun_argument(self.flavour, path, self.cwd)

    def dry_run(self, command: Sequence[str], label: str,
                plan: Optional[Sequence[cucumber.Scenario]] = None) -> List[cucumber.Scenario]:
        report = self.workdir / f"{label}.json"
        extra = list(cucumber.dry_run_arguments(self.flavour))
        if plan is not None:
            extra.append(self._rerun(label, plan))
        extra += cucumber.report_arguments(self.flavour, report, self.cwd)
        code = self.runner([*command, *extra])
        try:
            return cucumber.read_scenarios(report)
        except (OSError, ValueError):
            raise ConfigError(f"the Cucumber dry run ({label}) wrote no JSON report ({command[0]} exited {code}); "
                              f"is --cucumber {self.flavour} right for this command?") from None

    def stage(self, number: int, name: str, command: Sequence[str],
              scenarios: Optional[Sequence[cucumber.Scenario]] = None) -> Stage:
        report = self.workdir / f"stage-{number}.json"
        extra = [] if scenarios is None else [self._rerun(f"stage-{number}", scenarios)]
        extra += cucumber.report_arguments(self.flavour, report, self.cwd)
        self.say(f"stage {number} ({name}): "
                 + ("the command as given" if scenarios is None else f"{len(scenarios)} scenario(s)"))
        started = self.clock()
        code = self.runner([*command, *extra])
        return Stage(name, code, max(0.0, self.clock() - started), parse_file(str(report)))


def _command(args) -> List[str]:
    command = list(args.test_command or [])
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise ConfigError("give the test command after --, e.g. qeos-collector run-impact -- npx cucumber-js")
    return command


def _score(target: impact.Target, api_key: str, env: Mapping[str, str]) -> impact.Suggestion:
    """QEOS's suggestion; never raises. A refusal (401, 403, 404, 422, TLS) is REFUSED with its reason, a bug in the
    collector UNAVAILABLE: either way the tests still run (the safety ruling)."""
    try:
        return impact.fetch(target, api_key, env)
    except ConfigError as exc:
        return impact.Suggestion(REFUSED, str(exc))
    except Exception as exc:  # noqa: BLE001 - scoring must never cost the test run
        return impact.Suggestion(impact.UNAVAILABLE, f"unexpected error: {type(exc).__name__}: {exc}")


def _check_selection(steps: _Cucumber, command: Sequence[str], plan: Sequence[cucumber.Scenario]) -> None:
    """Stage 1's command, as a dry run, must select exactly the plan (plan Ruling 8); otherwise scenarios would run
    twice, or not at all. Nothing has run yet when this refuses."""
    selected = {s.location for s in steps.dry_run(command, "stage-1-check", plan)}
    planned = {s.location for s in plan}
    if selected == planned:
        return
    extra, left_out = sorted(selected - planned), sorted(planned - selected)
    problems = []
    if extra:
        problems.append(f"run {len(extra)} scenario(s) it did not plan (e.g. {extra[0]})")
    if left_out:
        problems.append(f"leave out {len(left_out)} it planned (e.g. {left_out[0]})")
    raise ConfigError(
        "run-impact cannot narrow this command: with the rerun file, stage 1 would " + " and ".join(problems)
        + ". Feature paths in a Cucumber profile or config (`paths`), inside an npm script, or a --shard option change "
          "what runs; select features with tags instead, or call Cucumber directly. Nothing was run.")


def _without_suggestion(args, say: Callable[[str], None], command: Sequence[str], steps: _Cucumber) -> List[Stage]:
    """Nothing to run first: the full suite as one stage, or nothing at all with --suggested-only --no-fallback."""
    if args.suggested_only and args.no_fallback:
        say("nothing run (--no-fallback)")
        return []
    say("running the full suite instead (--suggested-only falls back to it)" if args.suggested_only
        else "running the full suite as one stage")
    return [steps.stage(1, "all", command)]


def _run_stages(args, say, command, flavour, cwd, found: impact.Suggestion,
                steps: _Cucumber) -> Tuple[List[Stage], str, Optional[int], List[dict]]:
    """(stages, scope, stopped_after_stage, suggested tests not discovered); no stages when nothing may run."""
    if found.code != impact.SUGGESTED:
        # QEOS answered "nothing" as a plain note; anything else is a problem worth a warning
        say(f"no suggestion: {found.reason}" if found.data is not None
            else f"warning: cannot score the change: {found.reason}")
        return _without_suggestion(args, say, command, steps), FULL, None, []
    discovered = steps.dry_run(command, "discovery")
    first, rest, missing = cucumber.split(found.tests, discovered)
    say(f"{len(discovered)} scenario(s) in this command, {len(first)} of them suggested")
    if missing:
        names = ", ".join(str(test.get("name")) for test in missing[:SHOWN_MISSING])
        more = f" and {len(missing) - SHOWN_MISSING} more" if len(missing) > SHOWN_MISSING else ""
        say(f"skipped by the filter: {len(missing)} suggested test(s) are not among this command's scenarios "
            f"(left out by its filters, or not Cucumber): {names}{more}")
    if not first:
        say("no suggested scenario is among them")
        return _without_suggestion(args, say, command, steps), FULL, None, missing
    narrowed, removed = cucumber.strip_paths(flavour, command, cwd)
    if removed:
        say(f"the stages leave out the command's own feature paths ({' '.join(removed)}): the rerun files choose")
    _check_selection(steps, narrowed, first)
    stages = [steps.stage(1, "suggested", narrowed, first)]
    if rest:  # every scenario suggested: one stage, still the full suite (plan Ruling 9)
        stages.append(steps.stage(2, "rest", narrowed, rest))
    return stages, FULL, None, missing


def _finish(say, stages: List[Stage], scope: str, stopped: Optional[int], *, upload: Upload,
            judge: Callable[[dict], int], gate: bool, fail_on_error: bool) -> int:
    """Upload the stages as one run, then the exit code (plan Ruling 12): the gate's verdict with --gate (1 when
    nothing was uploaded), else the test command's own exit code (1 with --fail-on-error when the upload failed)."""
    payload = stages_payload(stages, stopped)
    receipt = upload([stage.report for stage in stages], scope, payload)
    tests = next((stage.returncode for stage in stages if stage.returncode != 0), 0)
    if gate:
        if receipt is None:
            say("gate failed: the gate cannot pass without an upload")
            return 1
        return judge(receipt)
    if receipt is None and fail_on_error and tests == 0:
        return 1
    return tests


def _workdir(cwd: str) -> Path:
    """.qeos-impact/<random>/ for this invocation's files; .qeos-impact/.gitignore keeps git from listing them."""
    base = Path(cwd, cucumber.WORKDIR)
    workdir = base / uuid.uuid4().hex[:12]
    try:
        workdir.mkdir(parents=True)
        ignore = base / ".gitignore"
        if not ignore.exists():
            with open(ignore, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("*\n")
    except OSError as exc:
        raise ConfigError(f"cannot create {workdir}: {exc.strerror or exc}") from None
    return workdir


def run(args, env: Mapping[str, str], api_key: str, say: Callable[[str], None], cwd: str, *, upload: Upload,
        judge: Callable[[dict], int], gate: bool, fail_on_error: bool, clock: Callable[[], float],
        runner: Callable[[Sequence[str]], int] = run_command) -> int:
    command = _command(args)
    flavour = args.cucumber or cucumber.detect_flavour(command)
    if flavour is None:
        raise ConfigError(f"cannot tell which Cucumber `{' '.join(command)}` runs; pass --cucumber js, jvm or ruby")
    if args.no_fallback and not args.suggested_only:
        raise ConfigError("--no-fallback only goes with --suggested-only")
    command = cucumber.with_separator(flavour, command)
    target = impact.resolve(args, env, api_key, cwd)
    check_paths(flavour, command, cwd)
    found = _score(target, api_key, env)
    workdir = _workdir(cwd)
    try:
        steps = _Cucumber(flavour, workdir, cwd, runner, clock, say)
        stages, scope, stopped, _missing = _run_stages(args, say, command, flavour, cwd, found, steps)
        if not stages:  # --suggested-only --no-fallback: nothing ran, nothing to upload
            return found.code if found.code != impact.SUGGESTED else impact.NOTHING
        return _finish(say, stages, scope, stopped, upload=upload, judge=judge, gate=gate,
                       fail_on_error=fail_on_error)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
