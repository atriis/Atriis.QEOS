"""qeos-collector command line: parse JUnit XML reports and upload them as one run."""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Mapping, Optional, Sequence

from qeos_collector import __version__, cucumber, features, impact, run_impact, traces
from qeos_collector import upload as uploads
from qeos_collector.ci import detect, sanitize_key
from qeos_collector.codeowners import load_codeowners
from qeos_collector.config_file import FILE_NAME, LEGACY_FILE_NAME, load_config, uses_legacy_file
from qeos_collector.formats import parse_file
from qeos_collector.gitdiff import collect_changes, collect_commit_info
from qeos_collector.payload import (
    TRIGGERS, build_parts, build_run, parse_components, run_times, summarize,
)
from qeos_collector.spool import spool_part, spooled_parts
from qeos_collector.upload import (
    ConfigError, UploadError, check_key, endpoint_for, make_context, upload_artifacts, upload_images, upload_part,
)

CI_PROVIDERS = ("github_actions", "gitlab_ci", "jenkins", "azure_pipelines", "other", "local")
_TRUE = ("1", "true", "yes")
EXTRA_ARGS = run_impact.EXTRA_ARGS
_API_KEY = re.compile(r"^[\x21-\x7e]+$")


# Environment variables were QAV_* before the QEOS rename; they still work as fallbacks
_PREFIX, _LEGACY_PREFIX = "QEOS_", "QAV_"
# Only the variables the collector reads: other QAV_* names (QAV_BACKUP_DIR, ...) belong to other tools
ENV_NAMES = (
    "URL", "API_KEY", "BRANCH", "COMMIT", "CI_PROVIDER", "CI_RUN_URL", "ENVIRONMENT", "IDEMPOTENCY_KEY",
    "CA_FILE", "CLIENT_CERT", "CLIENT_KEY", "COMPONENTS", "FAIL_ON_ERROR", "GATE", "NO_CHANGES", "SPOOL",
    "IMPORT_BRANCH", "TRIGGER",
)


def resolve_env(env: Mapping[str, str]) -> "tuple[dict, list]":
    """A copy of env where each of the collector's QAV_* variables fills in its QEOS_* name unless
    that is already set (the new name wins), and the legacy names that were used that way."""
    resolved = dict(env)
    used = []
    for suffix in ENV_NAMES:
        legacy, current = _LEGACY_PREFIX + suffix, _PREFIX + suffix
        if legacy in env and current not in env:
            resolved[current] = env[legacy]
            used.append(legacy)
    return resolved, used


class _UploadFailed(Exception):
    pass


class _Output:
    """One stderr line per message, prefixed "qeos:"; the API key never reaches them."""

    def __init__(self, secret: str):
        self.secret = secret

    def __call__(self, message: str) -> None:
        if self.secret:
            message = message.replace(self.secret, "***")
        line = f"qeos: {message}"
        try:
            print(line, file=sys.stderr)
        except UnicodeEncodeError:  # a console that cannot show the characters
            print(line.encode("ascii", "backslashreplace").decode("ascii"), file=sys.stderr)


def _target_options(parser: argparse.ArgumentParser) -> None:
    """Where QEOS is and which change it is about: every command that sends the key to /collect."""
    parser.add_argument("--url", help="platform URL (default: $QEOS_URL)")
    parser.add_argument("--ca-file", help="trust exactly this CA certificate, e.g. a private or self-signed one "
                                          "(default: $QEOS_CA_FILE)")
    parser.add_argument("--client-cert", help="client certificate for mTLS (default: $QEOS_CLIENT_CERT)")
    parser.add_argument("--client-key", help="private key for --client-cert (default: $QEOS_CLIENT_KEY)")
    parser.add_argument("--branch", help="default: $QEOS_BRANCH, else detected")
    parser.add_argument("--commit", help="full or short SHA (default: $QEOS_COMMIT, else detected)")


def _run_options(parser: argparse.ArgumentParser) -> None:
    """What every uploading command takes: where to send the run, and what to say about it."""
    _target_options(parser)
    parser.add_argument("--ci-provider", choices=CI_PROVIDERS, help="default: $QEOS_CI_PROVIDER, else detected")
    parser.add_argument("--trigger", help="manual, automatic or qeos (default: $QEOS_TRIGGER, else detected; ADR-030)")
    parser.add_argument("--ci-run-url", help="default: $QEOS_CI_RUN_URL, else detected")
    parser.add_argument("--environment", help="e.g. staging (default: $QEOS_ENVIRONMENT)")
    parser.add_argument("--idempotency-key", help="default: $QEOS_IDEMPOTENCY_KEY, else derived from the CI job")
    parser.add_argument("--component", action="append", default=[], metavar="NAME@SHA",
                        help="a repo/version this run exercised, e.g. product-api@3f2a9c1; repeatable "
                             "(default: $QEOS_COMPONENTS, comma separated)")
    parser.add_argument("--fail-on-error", action="store_true",
                        help="exit 1 if the upload fails (default: $QEOS_FAIL_ON_ERROR)")
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 when the run has failures outside quarantine, or when it could not be "
                             "uploaded (default: $QEOS_GATE)")
    parser.add_argument("--spool", metavar="DIR",
                        help="keep parts a failed upload could not deliver in DIR and resend them on "
                             "the next invocation (default: $QEOS_SPOOL)")
    parser.add_argument("--no-screenshots", action="store_true",
                        help="send no step screenshots: no image upload, no references in the run "
                             "(default: $QEOS_NO_SCREENSHOTS, or no-screenshots: true in .qeos.yml)")
    parser.add_argument("--no-artifacts", action="store_true",
                        help="send no traces: no trace upload, no references in the run "
                             "(default: $QEOS_NO_ARTIFACTS, or no-artifacts: true in .qeos.yml)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qeos-collector", description="Upload JUnit XML test results to the QEOS platform."
    )
    parser.add_argument("--version", action="version", version=f"qeos-collector {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    upload = commands.add_parser(
        "upload",
        help="parse JUnit XML files and upload them as one run",
        description="Parse the JUnit XML files matching PATTERN (** matches any directories) and upload "
        "them as one run. The API key is read from the QEOS_API_KEY environment variable only.",
    )
    upload.add_argument("patterns", nargs="*", metavar="PATTERN",
                        help="default: the patterns list in .qeos.yml")
    _run_options(upload)
    upload.add_argument("--no-changes", action="store_true",
                        help="skip git code-change collection (default: $QEOS_NO_CHANGES)")
    upload.add_argument("--dry-run", action="store_true", help="print the JSON that would be sent; upload nothing")
    check = commands.add_parser(
        "check",
        help="verify the configuration without uploading: URL, TLS, API key, and report parsing",
        description="Verify the collector can talk to the platform: URL shape, TLS trust, API key. "
        "With PATTERN arguments, also checks that reports match and parse. Uploads nothing. "
        "Exits 2 on the first failed check.",
    )
    check.add_argument("patterns", nargs="*", metavar="PATTERN")
    check.add_argument("--url", help="platform URL (default: $QEOS_URL)")
    check.add_argument("--ca-file", help="trust exactly this CA certificate (default: $QEOS_CA_FILE)")
    import_features = commands.add_parser(
        "import-features",
        help="sync the repository's Gherkin .feature files into QEOS test cases",
        description="Read the .feature files matching PATTERN (default: features in .qeos.yml, else "
        "**/*.feature) and import them as test cases. Runs only on the sync branch (default: "
        "$QEOS_IMPORT_BRANCH, else the repository's default branch). The API key is read from QEOS_API_KEY only.",
    )
    import_features.add_argument("patterns", nargs="*", metavar="PATTERN")
    import_features.add_argument("--branch", help="the branch cases sync from (default: $QEOS_IMPORT_BRANCH, else the repository's default branch)")
    import_features.add_argument("--no-full", action="store_true",
                                 help="compare only the given files; never archive cases of other files")
    import_features.add_argument("--allow-mass-archive", action="store_true",
                                 help="let a full import archive more than half of the imported cases")
    import_features.add_argument("--suites", action="append", metavar="PATTERN",
                                 help="also import the CI workflow files matching PATTERN (repeatable, e.g. "
                                 ".github/workflows/suite-*.yml) as repository suites")
    import_features.add_argument("--strict", action="store_true",
                                 help="exit 1 when a .feature file fails to parse or a suite has a warning")
    import_features.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    import_features.add_argument("--url", help="platform URL (default: $QEOS_URL)")
    import_features.add_argument("--ca-file", help="trust exactly this CA certificate (default: $QEOS_CA_FILE)")
    impact_cmd = commands.add_parser(
        "impact",
        help="print the tests the current change likely affects, from QEOS",
        description="Ask QEOS which tests the change likely affects: the files an upload would send as changed (the "
        "pull- or merge-request base, else the commit's parent). Exit codes: 0 a suggestion was printed, 3 nothing "
        "to suggest, 4 QEOS unreachable or out of time, 2 a configuration error (including a key that may not "
        "read test suggestions); none of them means tests failed. The API key is read from QEOS_API_KEY only.",
    )
    impact_cmd.add_argument("--format", choices=impact.FORMATS,
                            help="cucumber: one path/to/x.feature:LINE per line (the default when the working "
                                 "directory has .feature files); list: suite<TAB>class<TAB>name; json: the whole "
                                 "suggestion")
    impact_cmd.add_argument("--out", metavar="FILE",
                            help="write the suggestion to FILE instead of stdout (emptied when there is none)")
    _target_options(impact_cmd)
    run_impact_cmd = commands.add_parser(
        "run-impact",
        help="run a Cucumber command with the likely affected scenarios first, then the rest, and upload one run",
        description="Ask QEOS which tests the change likely affects, run those scenarios first and every other one "
        "after, and upload both as one run. Cucumber only: cucumber-js, cucumber-jvm through Maven or Gradle, or Ruby "
        "Cucumber. When QEOS cannot score the change, the command runs as given. Put the test command after --. The "
        "API key is read from QEOS_API_KEY only.",
    )
    _run_options(run_impact_cmd)
    run_impact_cmd.add_argument("--cucumber", choices=cucumber.FLAVOURS,
                                help="which Cucumber the command runs (default: detected from the command)")
    run_impact_cmd.add_argument("--fail-fast", action="store_true",
                                help="stop after stage 1 when a suggested scenario fails; the run is uploaded as "
                                     "suggested tests only")
    run_impact_cmd.add_argument("--suggested-only", action="store_true",
                                help="run only the suggested scenarios (the full suite when there is no suggestion)")
    run_impact_cmd.add_argument("--no-fallback", action="store_true",
                                help="with --suggested-only: when there is no suggestion, run nothing and exit 2, 3 "
                                     "or 4 as impact would")
    run_impact_cmd.add_argument("test_command", nargs=argparse.REMAINDER, metavar="-- COMMAND",
                                help="the Cucumber test command, after --")
    run_impact_cmd.set_defaults(patterns=[], no_changes=False, dry_run=False)
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    env = os.environ if env is None else env
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = env.get(EXTRA_ARGS, "").strip()
    if extra and argv[:1] and not argv[0].startswith("-"):
        # The GitHub Action's extra-args: one string, split as a POSIX shell would split words, never run by one
        words = _extra_words(argv[0], extra)
        if words is None:
            return 2
        argv = [argv[0], *words, *argv[1:]]
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version, usage errors
        return exc.code if isinstance(exc.code, int) else 2
    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2

    env, legacy_names = resolve_env(env)
    api_key = env.get("QEOS_API_KEY", "").strip()
    say = _Output(api_key)
    for name in sorted(legacy_names):
        say(f"{name} is deprecated; use {_PREFIX}{name[len(_LEGACY_PREFIX):]}")
    if args.command != "check" and uses_legacy_file(os.getcwd()):
        say(f"{LEGACY_FILE_NAME} is deprecated; rename it to {FILE_NAME}")
    if args.command == "check":
        # A diagnostic: any failure is the answer, so it always exits 2, never softened
        try:
            return _check(args, env, api_key, say)
        except (ConfigError, UploadError) as exc:
            say(str(exc))
            return 2
    if args.command == "import-features":
        try:
            _usable_key(api_key)
            return features.run(args, env, api_key, say, os.getcwd())
        except ConfigError as exc:
            say(str(exc))
            return 2
    if args.command == "impact":
        # Its own codes (0 a suggestion, 3 nothing, 4 unavailable); never softened like an upload's
        try:
            _usable_key(api_key)
            return impact.run(args, env, api_key, say, os.getcwd())
        except ConfigError as exc:
            impact.empty_out(args.out)
            say(str(exc))
            return 2
    fail_on_error, gate = _flags(args, env)
    if args.command == "run-impact":
        try:
            try:
                _usable_key(api_key)
                problem = None
            except ConfigError as exc:  # the tests still run (run_impact.run); nothing is sent with this key
                problem = str(exc)
            return run_impact.run(
                args, env, api_key, say, os.getcwd(), gate=gate, fail_on_error=fail_on_error, clock=clock,
                setup_problem=problem,
                upload=lambda reports, scope, stages: _upload_reports(
                    args, env, api_key, say, reports, scope, stages, now=now, sleep=sleep, clock=clock),
                judge=lambda receipt: _verdict(receipt, say),
            )
        except ConfigError as exc:
            say(str(exc))
            return 2
    try:
        receipt = _upload(args, env, api_key, say, now=now, sleep=sleep, clock=clock)
        if isinstance(receipt, int):  # dry run, or nothing to upload
            return receipt
        return _verdict(receipt, say) if gate else 0
    except ConfigError as exc:
        say(str(exc))
        return 2
    except _UploadFailed:
        pass
    except Exception as exc:  # a bug in the collector must not break the build either
        say(f"unexpected error: {type(exc).__name__}: {exc}")
    if gate:
        say("gate failed: the gate cannot pass without an upload")
        return 1
    if fail_on_error:
        return 1
    say("not failing the build (pass --fail-on-error to change that)")
    return 0


def _extra_words(command: str, extra: str) -> Optional[List[str]]:
    """QEOS_ACTION_EXTRA_ARGS as words, or None (said) when they cannot go in front of the command's own arguments:
    they must be flags. For run-impact a "--", or a word that is not a flag's value, would start the test command
    and swallow the arguments the action adds after them (--url, the command itself)."""
    try:
        words = shlex.split(extra)
    except ValueError as exc:
        print(f"qeos: {EXTRA_ARGS} cannot be split ({exc})", file=sys.stderr)
        return None
    problem = "it holds --" if "--" in words else ""
    if not problem:
        try:
            alone = build_parser().parse_args([command, *words])
        except SystemExit:  # a usage error (argparse said it), or --help: never a reason to go on
            return None
        if getattr(alone, "test_command", None):
            problem = f"{' '.join(alone.test_command)!r} is not a flag"
    if problem:
        print(f"qeos: {EXTRA_ARGS} must hold flags only ({problem}); the test command goes in test-command",
              file=sys.stderr)
        return None
    return words


def main_deprecated() -> int:
    """`qav-collector`, the command name before the QEOS rename."""
    print("qav-collector is deprecated; use qeos-collector", file=sys.stderr)
    return main()


def _usable_key(api_key: str) -> None:
    """Refused before any request: http.client would otherwise reject the header with an error that quotes the key
    in a form the output scrubbing does not recognise. The one key check of every command that sends the key."""
    if api_key and not _API_KEY.match(api_key):
        raise ConfigError("QEOS_API_KEY must be printable ASCII without spaces; check the CI secret")


def _gate(receipt: dict, say: _Output) -> int:
    """The run's verdict for CI: failures of quarantined tests do not count."""
    if "blocking" in receipt:
        blocking, held = int(receipt["blocking"]), int(receipt.get("quarantined", 0))
    else:
        say("the platform does not report quarantine; every failure counts")
        blocking, held = int(receipt.get("failed", 0)) + int(receipt.get("errored", 0)), 0
    if blocking > 0:
        say(f"gate failed: {blocking} failing test(s) outside quarantine"
            + (f", {held} more in quarantine" if held else ""))
        return 1
    say(f"gate passed: {held} failure(s) in quarantine, not counted" if held else "gate passed: no failures")
    return 0


def _flags(args, env: Mapping[str, str]) -> "tuple[bool, bool]":
    """(--fail-on-error, --gate): a flag, then the environment, then .qeos.yml."""
    fail_on_error = args.fail_on_error or env.get("QEOS_FAIL_ON_ERROR", "").strip().lower() in _TRUE
    gate = args.gate or env.get("QEOS_GATE", "").strip().lower() in _TRUE
    if not (fail_on_error and gate):
        try:
            file_config = load_config(os.getcwd())
            fail_on_error = fail_on_error or file_config.get("fail-on-error") is True
            gate = gate or file_config.get("gate") is True
        except ConfigError:
            pass  # _upload reads the file itself and reports the problem properly
    return fail_on_error, gate


def _verdict(receipt: dict, say: _Output) -> int:
    """The gate on a receipt. A run the platform did not collect has no verdict there: its local counts decide."""
    if receipt.get("discarded"):
        say("gate: decided on local results (run not collected)")
        return _gate({"blocking": receipt["failed"] + receipt["errored"]}, say)
    return _gate(receipt, say)


def _upload_reports(args, env, api_key, say, reports, scope, stages, *, now, sleep, clock) -> Optional[dict]:
    """run-impact's upload of its stage reports as one run: the last receipt, or None when nothing was stored (what
    went wrong is already said). The tests have run by now, so even a configuration error only means "not uploaded":
    the caller still answers with their exit code, or the gate's."""
    try:
        receipt = _upload(args, env, api_key, say, now=now, sleep=sleep, clock=clock, reports=reports, scope=scope,
                          stages=stages)
    except _UploadFailed:
        return None
    except ConfigError as exc:
        say(f"not uploaded: {exc}")
        return None
    except Exception as exc:  # a bug in the collector must not hide the tests' own result
        say(f"unexpected error: {type(exc).__name__}: {exc}")
        return None
    return receipt if isinstance(receipt, dict) else None


def _check(args, env: Mapping[str, str], api_key: str, say: _Output) -> int:
    def pick(flag: Optional[str], name: str) -> Optional[str]:
        return (flag or "").strip() or env.get(name, "").strip() or None

    url = pick(args.url, "QEOS_URL")
    if not url:
        raise ConfigError("QEOS_URL is not set (or pass --url)")
    endpoint_for(url)  # validates the shape; raises ConfigError
    say(f"url: ok ({url})")

    if not api_key:
        raise ConfigError("QEOS_API_KEY is not set; the API key is read from the environment only")
    _usable_key(api_key)
    context = make_context(pick(args.ca_file, "QEOS_CA_FILE"))
    identity = check_key(url, api_key, context)
    say(f"key: ok (project {identity.get('project_id', '?')}, key {identity.get('name', '?')!r})")
    if isinstance(identity.get("can_read_impact"), bool):  # absent on a platform older than suggested tests first
        say(f"Test suggestions: {'allowed' if identity['can_read_impact'] else 'not allowed'}")

    if args.patterns:
        files = _expand(args.patterns)
        if not files:
            raise ConfigError(f"no file matched {' '.join(args.patterns)}")
        parsed = [parse_file(path, read_traces=False) for path in files]
        for report in parsed:
            for warning in report.warnings:
                say(warning)
        results = [result for report in parsed for result in report.results]
        say(f"reports: {sum(1 for report in parsed if not report.skipped)} file(s), {len(results)} results")
    return 0


def _upload(args, env: Mapping[str, str], api_key: str, say: _Output, *, now, sleep, clock, reports=None, scope=None,
            stages=None) -> "int | dict":
    """The last receipt after an upload; an exit code when nothing was uploaded. run-impact hands its stage reports,
    the run's scope and its stages."""
    file_config = load_config(os.getcwd())

    def from_file(key: str) -> Optional[str]:
        value = file_config.get(key)
        return value if isinstance(value, str) else None

    def pick(flag: Optional[str], name: str, detected: Optional[str] = None,
             file_key: Optional[str] = None) -> Optional[str]:
        # Precedence: flag, then environment, then .qeos.yml, then detection
        return ((flag or "").strip() or env.get(name, "").strip()
                or (from_file(file_key) if file_key else None) or detected)

    endpoint, context, url = "", None, None
    if not args.dry_run:
        url = pick(args.url, "QEOS_URL", file_key="url")
        if not url:
            raise ConfigError("QEOS_URL is not set (or pass --url, or url: in .qeos.yml)")
        if not api_key:
            raise ConfigError("QEOS_API_KEY is not set; the API key is read from the environment only")
        _usable_key(api_key)
        endpoint = endpoint_for(url)
        context = make_context(
            pick(args.ca_file, "QEOS_CA_FILE", file_key="ca-file"),
            client_cert=pick(args.client_cert, "QEOS_CLIENT_CERT"),
            client_key=pick(args.client_key, "QEOS_CLIENT_KEY"),
        )

    ci = detect(env)
    provider = pick(args.ci_provider, "QEOS_CI_PROVIDER", ci.provider, file_key="ci-provider")
    if provider not in CI_PROVIDERS:
        raise ConfigError(f"QEOS_CI_PROVIDER must be one of {', '.join(CI_PROVIDERS)}, got {provider!r}")

    trigger = pick(args.trigger, "QEOS_TRIGGER", ci.trigger)
    if trigger is not None and trigger not in TRIGGERS:
        raise ConfigError(f"--trigger / QEOS_TRIGGER must be one of {', '.join(TRIGGERS)}, got {trigger!r}")

    # Known before the reports are read: with traces turned off, a report's traces are only counted, never opened
    skip_artifacts = traces.turned_off(args.no_artifacts, env, file_config)
    if reports is not None:  # run-impact's stage reports
        parsed = list(reports)
    else:
        patterns = args.patterns or list(file_config.get("patterns") or [])
        if not patterns:
            raise ConfigError("no report patterns given (arguments, or patterns: in .qeos.yml)")
        files = _expand(patterns)
        if not files:
            raise ConfigError(f"no file matched {' '.join(patterns)}")
        parsed = [parse_file(path, read_traces=not skip_artifacts) for path in files]
    for report in parsed:
        for warning in report.warnings:
            say(warning)
    results = [result for report in parsed for result in report.results]
    if not results:
        say("no test results found")
        return 0

    owners_for = load_codeowners(os.getcwd())
    owned = 0
    for result in results:
        owner = owners_for(result["file"]) if result.get("file") else None
        if owner:
            result["owner"] = owner
            owned += 1
    if owned:
        say(f"owners from CODEOWNERS on {owned} result(s)")

    counts = summarize(results)
    say(
        f"parsed {sum(1 for report in parsed if not report.skipped)} file(s), {len(results)} results "
        f"({counts['failed']} failed, {counts['errored']} errored, {counts['skipped']} skipped)"
    )

    author, subject = collect_commit_info(pick(args.commit, "QEOS_COMMIT", ci.commit))

    started, finished = run_times(
        [stamp for report in parsed for stamp in report.suite_timestamps],
        sum(report.suite_seconds for report in parsed),
        results,
        now(),
    )
    run = build_run(
        ci_provider=provider,
        started_at=started,
        finished_at=finished,
        ci_run_url=pick(args.ci_run_url, "QEOS_CI_RUN_URL", ci.run_url),
        commit_sha=pick(args.commit, "QEOS_COMMIT", ci.commit),
        branch=pick(args.branch, "QEOS_BRANCH", ci.branch, file_key="branch"),
        environment=pick(args.environment, "QEOS_ENVIRONMENT", file_key="environment"),
        commit_author=author,
        commit_message=subject,
        pr_number=ci.pr_number,
        base_branch=ci.base_branch,
        trigger=trigger,
        scope=scope,
        stages=stages,
    )
    changes = None
    skip_changes = (args.no_changes or env.get("QEOS_NO_CHANGES", "").strip().lower() in _TRUE
                    or file_config.get("no-changes") is True)
    if not skip_changes:
        changes = collect_changes(env, run.get("commit_sha"))
        if changes is not None:
            adds = sum(f["additions"] or 0 for f in changes["files"])
            dels = sum(f["deletions"] or 0 for f in changes["files"])
            say(f"changes vs {changes['base_ref']}: {len(changes['files'])} file(s), +{adds} -{dels}"
                + (" (truncated)" if changes["truncated"] else ""))

    component_values = (args.component
                        or [v for v in env.get("QEOS_COMPONENTS", "").split(",") if v.strip()]
                        or list(file_config.get("components") or []))
    try:
        components = parse_components(component_values)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    if components:
        say("components under test: " + ", ".join(f"{c['name']}@{c['sha'][:12]}" for c in components))

    key = sanitize_key(pick(args.idempotency_key, "QEOS_IDEMPOTENCY_KEY") or "")
    if not key:
        # The CI identifiers name the job, but every leg of a matrix and every upload step in one
        # job share them, and the server answers 409 when a key comes back with a different body
        # (finished_at alone always differs). So each invocation adds its own random suffix: the
        # collector's retries reuse the key, and a POST stored without an answer is replayed.
        key = f"{ci.idempotency_key or 'local'}-{uuid.uuid4().hex[:12]}"
    skip_screenshots = (args.no_screenshots or env.get("QEOS_NO_SCREENSHOTS", "").strip().lower() in _TRUE
                        or file_config.get("no-screenshots") is True)
    _send_screenshots(results, None if args.dry_run else url, api_key, context, say, skip=skip_screenshots,
                      sleep=sleep, clock=clock)
    trace_skips: dict = {}
    for report in parsed:
        for reason, number in getattr(report, "artifact_skips", {}).items():
            trace_skips[reason] = trace_skips.get(reason, 0) + number
    _send_artifacts(results, trace_skips, None if args.dry_run else url, api_key, context, say,
                    skip=skip_artifacts, sleep=sleep, clock=clock)
    parts = build_parts(run, results, key, changes, components)

    if args.dry_run:
        for part in parts:
            print(json.dumps(json.loads(part.body), indent=2))
        say(f"dry run: {len(parts)} part(s), nothing uploaded")
        return 0

    spool_dir = pick(args.spool, "QEOS_SPOOL", file_key="spool")
    if spool_dir:
        _resend_spooled(spool_dir, endpoint, api_key, context, say, sleep=sleep, clock=clock)

    stored: List[str] = []
    for number, part in enumerate(parts, start=1):
        of = f"part {number} of {len(parts)}"
        try:
            status, receipt = upload_part(endpoint, api_key, part, context, sleep=sleep, clock=clock, warn=say)
        except UploadError as exc:
            say(f"upload failed: {exc}")
            if stored:
                say(f"stored before the failure: {', '.join(stored)}")
            if spool_dir and exc.retryable:
                # This part and every later one: a 409 on a later part out of order is worse
                # than retrying all of them under their original keys
                spooled = sum(1 for p in parts[number - 1:] if spool_part(spool_dir, p) is not None)
                say(f"spooled {spooled} part(s) for the next run")
            raise _UploadFailed() from None
        if status == 202 and receipt.get("discarded"):
            say(f"run not collected: {receipt.get('reason', 'the platform discarded it')}")
            if stored:
                say(f"stored before the discard: {', '.join(stored)}")
            # every part shares the trigger: the rest would be discarded too. The caller gates
            # on the local counts when asked to
            return {"discarded": True, "failed": counts["failed"], "errored": counts["errored"]}
        run_id = receipt.get("id", "?")
        say(f"uploaded run {run_id} ({status})" + (f", {of}" if len(parts) > 1 else ""))
        stored.append(f"run {run_id} ({of})")
    # The last part's receipt counts the whole run: the gate reads it
    return receipt


def _send_screenshots(results: List[dict], url: Optional[str], api_key: str, context, say: _Output, *, skip: bool,
                      sleep, clock) -> None:
    """Step screenshots (spec 2026-10-19 §5.2): uploads the rows' images, then keeps only the references to images
    QEOS holds, so the run never points at a missing one. Every row loses its `_images` here, so the bytes are not
    held through the run upload. A dry run (no url) keeps the references and uploads nothing. Best effort: whatever
    goes wrong is one line, and the run is still sent."""
    images: dict = {}
    for row in results:
        images.update(row.pop("_images", None) or {})
    if url is None and not skip:
        return
    stored: set = set()
    if images and not skip:
        notes: List[str] = []
        # One budget for the whole phase, the key check included: screenshots never hold the run up for longer
        deadline = clock() + uploads.IMAGE_BUDGET_SECONDS
        try:
            identity = check_key(url, api_key, context, timeout=min(uploads.TIMEOUT_SECONDS, deadline - clock()))
        except UploadError as exc:
            notes.append(f"key check failed: {exc}")
        except Exception as exc:  # a bug or an odd environment must never cost the run
            notes.append(f"unexpected error: {type(exc).__name__}: {exc}")
        else:
            if identity.get("screenshots") is True:
                try:
                    stored = upload_images(url, api_key, images, max(0.0, deadline - clock()), context=context,
                                           warn=notes.append, sleep=sleep, clock=clock)
                except Exception as exc:  # as above: the run goes without screenshots
                    stored = set()
                    notes.append(f"unexpected error: {type(exc).__name__}: {exc}")
            elif "screenshots" not in identity:
                notes.append("the platform is older than this collector (upgrade QEOS to see step screenshots)")
            else:
                notes.append("off for this project (a project owner or admin turns on Keep screenshots from "
                             "uploads in Project Settings)")
        say(f"screenshots: {len(stored)} stored, {len(images) - len(stored)} skipped"
            + (f" ({'; '.join(notes)})" if notes else ""))
    for row in results:
        if "screenshots" in row:
            kept = [shot for shot in row["screenshots"] if shot["sha256"] in stored]
            if kept:
                row["screenshots"] = kept
            else:
                del row["screenshots"]


def _send_artifacts(results: List[dict], skips: dict, url: Optional[str], api_key: str, context, say: _Output, *,
                    skip: bool, sleep, clock) -> None:
    """Traces (spec 2026-10-21 §4.2), after the screenshots and before the run. The rows' `_artifacts` (TraceFiles
    checked but not hashed while the reports were read) are hashed and streamed up only when the key check says the
    project keeps traces; each row then gets `artifacts: [{sha256, kind: "trace", name}]` for the traces QEOS holds.
    Every row loses its `_artifacts` here. `skips` counts the traces left out while reading the reports, by reason. With
    no trace readable the key is not checked (0.14.1), so the line says only that none could be read, with the skips
    (whether the project keeps traces is unknown). A dry run (no url) hashes them under the same budget and
    per-run cap and keeps the references of those hashed, uploading nothing. Best effort with its own budget:
    whatever goes wrong is one line, and the run is still sent. When traces are off (here or on the platform) that
    line is all: no reasons per file."""
    row_traces: list = []
    files: dict = {}  # one TraceFile per resolved path, across the run
    for row in results:
        found = row.pop("_artifacts", None) or []
        paths = [files.setdefault(trace.path, trace).path for trace in found]
        if paths:
            row_traces.append((row, paths))
    left_out = sum(skips.values())
    held: set = set()
    if skip:
        if files or left_out:
            say(f"traces: {len(files) + left_out} skipped (turned off by --no-artifacts, QEOS_NO_ARTIFACTS or "
                "no-artifacts in .qeos.yml)")
        return
    if url is None:
        held = _dry_run_artifacts(list(files.values()), skips, say, clock)
    elif not files:
        if left_out:  # none readable: nothing to send, so no key check either
            say(f"traces: none could be read, {left_out} skipped ({traces.reasons(skips)})")
    else:
        notes: List[str] = []
        on = False
        # One budget for the whole phase, the key check included: traces never hold the run up for longer
        deadline = clock() + uploads.ARTIFACT_BUDGET_SECONDS
        try:
            identity = check_key(url, api_key, context, timeout=min(uploads.TIMEOUT_SECONDS, deadline - clock()))
        except UploadError as exc:
            notes.append(f"key check failed: {exc}")
        except Exception as exc:  # a bug or an odd environment must never cost the run
            notes.append(f"unexpected error: {type(exc).__name__}: {exc}")
        else:
            if identity.get("artifacts") is True:
                on = True
                if files:
                    upload_notes: List[str] = []
                    try:
                        held = upload_artifacts(url, api_key, list(files.values()), max(0.0, deadline - clock()),
                                                context=context, warn=upload_notes.append, sleep=sleep, clock=clock)
                    except Exception as exc:  # as above: the run goes without traces
                        held = set()
                        upload_notes.append(f"unexpected error: {type(exc).__name__}: {exc}")
                    notes += upload_notes
            elif "artifacts" not in identity:
                notes.append("the platform is older than this collector (upgrade QEOS to keep traces)")
            else:
                notes.append("off for this project (a project owner or admin turns on Keep traces from uploads in "
                             "Project Settings)")
        if on and left_out:
            notes.insert(0, traces.reasons(skips))
        say(_trace_line(list(files.values()), held, left_out, "stored", "", notes))
    for row, paths in row_traces:
        kept: list = []
        for path in paths:
            trace = files[path]
            if trace.sha256 is None or trace.sha256 not in held:
                continue
            if any(artifact["sha256"] == trace.sha256 for artifact in kept):
                continue  # two files with the same bytes: one reference
            kept.append({"sha256": trace.sha256, "kind": "trace", "name": trace.name})
        if kept:
            row["artifacts"] = kept


def _dry_run_artifacts(files: List["traces.TraceFile"], skips: dict, say: _Output, clock) -> set:
    """The dry run's trace phase: hashes what the real phase would, under its per-run cap and budget (so a dry run
    never takes longer than the upload would), and says how many would be sent, counted per file as the upload's
    `stored` is (MB per content); returns their sha256s."""
    left_out = sum(skips.values())
    if not files and not left_out:
        return set()
    budget, most = uploads.ARTIFACT_BUDGET_SECONDS, uploads.MAX_ARTIFACTS_PER_RUN
    notes: List[str] = []
    if len(files) > most:
        notes.append(f"{len(files) - most} beyond {most} per run")
    deadline = clock() + budget
    changed = 0
    for trace in files[:most]:
        try:
            trace.digest(deadline, clock)
        except traces.TraceTimeout:
            notes.append(f"out of time after {budget:g} s")
            break
        except traces.TraceChanged:
            changed += 1
    if changed:  # as the upload says it
        notes.insert(0, f"{changed} changed since the report was read")
    if left_out:
        notes.insert(0, traces.reasons(skips))
    hashed = {trace.sha256 for trace in files if trace.sha256 is not None}
    say(_trace_line(files, hashed, left_out, "would be sent", f" within the {budget:g} s budget", notes))
    return hashed


def _trace_line(files: List["traces.TraceFile"], held: set, left_out: int, verb: str, after: str,
                notes: List[str]) -> str:
    """The trace phase's line, for the upload and the dry run alike: the files whose bytes QEOS holds (or would be
    sent), counted per file, their megabytes per content, and the rest skipped with `left_out` (read from the
    reports) and the notes."""
    sent = [trace for trace in files if trace.sha256 is not None and trace.sha256 in held]
    megabytes = sum({trace.sha256: trace.size for trace in sent}.values()) / (1024 * 1024)
    return (f"traces: {len(sent)} {verb} ({megabytes:.1f} MB){after}, {len(files) - len(sent) + left_out} skipped"
            + (f" ({'; '.join(notes)})" if notes else ""))


def _resend_spooled(spool_dir, endpoint, api_key, context, say: _Output, *, sleep, clock) -> None:
    """Best effort before the current run: a still-broken platform keeps the
    files, a non-retryable answer (replayed key, revoked access) drops them."""
    resent = discarded = 0
    for path, part in spooled_parts(spool_dir):
        try:
            status, receipt = upload_part(endpoint, api_key, part, context, sleep=sleep, clock=clock, warn=say)
        except UploadError as exc:
            if exc.retryable:
                say(f"a spooled part still fails: {exc}")
                continue
            say(f"dropping a spooled part the platform will never take: {exc}")
        else:
            if status == 202 and receipt.get("discarded"):
                discarded += 1
            else:
                resent += 1
        try:
            path.unlink()
        except OSError:
            pass
    if resent:
        say(f"resent {resent} spooled part(s)")
    if discarded:
        say(f"{discarded} spooled part(s) not collected (discarded by the platform)")


def _expand(patterns: Sequence[str]) -> List[str]:
    files: List[str] = []
    seen = set()
    for pattern in patterns:
        for path in sorted(glob.glob(pattern, recursive=True)):
            identity = os.path.normcase(os.path.realpath(path))
            if os.path.isfile(path) and identity not in seen:
                seen.add(identity)
                files.append(path)
    return files
