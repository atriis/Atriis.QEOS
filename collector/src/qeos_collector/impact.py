"""The suggestion for the current change, from QEOS (spec 2026-10-13 §2.1; plan Rulings 1, 2).

The change is what an upload would send (gitdiff.collect_changes: the pull- or merge-request base, else the commit's
parent); QEOS scores it with POST /api/v1/collect/impact and the project API key. Codes:
- SUGGESTED (0): a suggestion with tests;
- NOTHING (3): nothing to suggest, or no change data;
- UNAVAILABLE (4): QEOS unreachable, overloaded or out of time.
A configuration problem (401, 403, 404, TLS, a refused change) raises ConfigError (exit 2), as everywhere in the
collector; a key without the "can read test suggestions" permission gets 403 impact_not_allowed."""
from __future__ import annotations

import http.client
import json
import re
import ssl
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional

from qeos_collector import __version__, cucumber
from qeos_collector.ci import detect
from qeos_collector.config_file import load_config
from qeos_collector.features import _code  # a 403 or 503 detail is {code, message}
from qeos_collector.gitdiff import collect_changes
from qeos_collector.upload import (
    COLLECT_PATH, ConfigError, _detail, _is_tls_error, _json, _reason, _send, endpoint_for, make_context,
)

IMPACT_PATH = "/api/v1/collect/impact"
SUGGESTED, NOTHING, UNAVAILABLE = 0, 3, 4
MAX_PATHS = 5000  # the endpoint's cap; the collector's own diff stops at 1,000 files
FORMATS = ("cucumber", "list", "json")
# 403 impact_not_allowed: the key is upload-only (per-key permission "can read test suggestions")
NOT_ALLOWED = ("This API key may not read test suggestions. Ask a project owner or admin to allow test suggestions "
               "for this key.")


@dataclass(frozen=True)
class Target:
    url: str
    context: Optional[ssl.SSLContext]
    commit: Optional[str]
    branch: Optional[str]


@dataclass
class Suggestion:
    code: int                    # SUGGESTED, NOTHING or UNAVAILABLE
    reason: str = ""             # why there is no suggestion, for the log
    data: Optional[dict] = None  # QEOS's answer (SuggestionOut)
    paths: List[str] = field(default_factory=list)

    @property
    def tests(self) -> List[dict]:
        return list((self.data or {}).get("tests") or [])


def impact_url(url: str) -> str:
    return endpoint_for(url)[: -len(COLLECT_PATH)] + IMPACT_PATH


def resolve(args, env: Mapping[str, str], api_key: str, cwd: str) -> Target:
    """Where to ask and about what: a flag, then the environment, then .qeos.yml, then CI detection, as `upload`
    reads them."""
    config = load_config(cwd)

    def pick(flag: Optional[str], name: str, file_key: Optional[str] = None) -> Optional[str]:
        value = (flag or "").strip() or env.get(name, "").strip()
        if not value and file_key:
            from_file = config.get(file_key)
            value = from_file.strip() if isinstance(from_file, str) else ""
        return value or None

    url = pick(getattr(args, "url", None), "QEOS_URL", "url")
    if not url:
        raise ConfigError("QEOS_URL is not set (or pass --url, or url: in .qeos.yml)")
    impact_url(url)  # the shape: https://, or http:// for localhost only
    if not api_key:
        raise ConfigError("QEOS_API_KEY is not set; the API key is read from the environment only")
    context = make_context(pick(getattr(args, "ca_file", None), "QEOS_CA_FILE", "ca-file"),
                           client_cert=pick(getattr(args, "client_cert", None), "QEOS_CLIENT_CERT"),
                           client_key=pick(getattr(args, "client_key", None), "QEOS_CLIENT_KEY"))
    ci = detect(env)
    return Target(url=url, context=context,
                  commit=pick(getattr(args, "commit", None), "QEOS_COMMIT") or ci.commit,
                  branch=pick(getattr(args, "branch", None), "QEOS_BRANCH", "branch") or ci.branch)


def fetch(target: Target, api_key: str, env: Mapping[str, str], *, collect: Optional[Callable] = None,
          send: Optional[Callable] = None) -> Suggestion:
    """QEOS's suggestion for the change an upload would send. An unreachable QEOS is UNAVAILABLE, never an error."""
    changes = (collect or collect_changes)(env, target.commit)
    if changes is None:
        return Suggestion(NOTHING, "no change data (no pull-request base, and no commit to compare with its parent)")
    paths = [f["path"] for f in changes["files"]][:MAX_PATHS]
    if not paths:
        return Suggestion(NOTHING, f"no changed files against {changes['base_ref']}")
    body = json.dumps({"changed_paths": paths, "branch": target.branch}).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": f"qeos-collector/{__version__}"}
    try:
        status, raw, _ = (send or _send)(impact_url(target.url), body, headers, target.context)
    except (OSError, http.client.HTTPException) as exc:
        if _is_tls_error(exc):
            raise ConfigError(f"TLS error talking to the platform ({_reason(exc)}); if it uses a private CA, "
                              "pass --ca-file") from None
        return Suggestion(UNAVAILABLE, f"cannot reach the platform ({_reason(exc)})", paths=paths)
    if status == 200:
        data = _json(raw)
        if not isinstance(data.get("tests"), list):
            return Suggestion(UNAVAILABLE, "the platform sent an unexpected answer (no tests list)", paths=paths)
        if data["tests"]:
            return Suggestion(SUGGESTED, data=data, paths=paths)
        if data.get("state") == "not_enough_history":
            reason = (f"not enough history yet ({data.get('history_runs')} of {data.get('needed_runs')} runs with "
                      "changed files) and nothing labelled to run first")
        else:
            reason = "no test is likely affected by this change"
        return Suggestion(NOTHING, reason, data=data, paths=paths)
    if status == 401:
        raise ConfigError("the API key is invalid or revoked (401)")
    if status == 404:
        raise ConfigError("the platform has no /api/v1/collect/impact (404): it is older than suggested tests first, "
                          "or QEOS_URL is wrong")
    if status == 403 and _code(raw) == "impact_not_allowed":
        raise ConfigError(NOT_ALLOWED)
    if status == 429:  # from the gateway (nginx), with an HTML body: never read
        return Suggestion(UNAVAILABLE, "the platform answered 429", paths=paths)
    if status >= 500:
        if status == 503 and _code(raw) == "impact_timeout":
            return Suggestion(UNAVAILABLE, "QEOS ran out of time scoring the change (impact_timeout)", paths=paths)
        return Suggestion(UNAVAILABLE, f"the platform answered {status}", paths=paths)
    raise ConfigError(f"the platform refused the change ({status}): {_detail(raw)}")


def _cell(value) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(value or ""))


def render(data: dict, fmt: str, locate: Callable[[dict], List[str]]) -> str:
    """The suggestion as `--format` says (spec 2026-10-13 §2.1): one entry per line, each line once."""
    tests = list(data.get("tests") or [])
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if fmt == "list":
        lines = ["\t".join(_cell(test.get(key)) for key in ("suite", "class_name", "name")) for test in tests]
    else:
        lines = [line for test in tests
                 for line in (locate(test) or [cucumber.name_filter(str(test.get("name") or ""))])]
    seen: set = set()
    unique = [line for line in lines if not (line in seen or seen.add(line))]
    return "".join(f"{line}\n" for line in unique)


def _print(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:  # a console that cannot show the characters
        sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii"))
    sys.stdout.flush()


def _write(path: str, text: str) -> None:
    # UTF-8 with LF line endings on every OS: the file feeds another tool
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def run(args, env: Mapping[str, str], api_key: str, say: Callable[[str], None], cwd: str) -> int:
    """qeos-collector impact: the suggestion on stdout (or --out), messages on stderr, the suggestion's code as the
    exit code (plan Rulings 2, 15)."""
    try:
        target = resolve(args, env, api_key, cwd)
        found = fetch(target, api_key, env)
    except ConfigError:
        if args.out:
            try:  # a later step never reads a stale list, even after a configuration error
                _write(args.out, "")
            except OSError:
                pass
        raise
    fmt = args.format or ("cucumber" if cucumber.has_feature_files(cwd) else "list")
    text = ""
    if found.code == SUGGESTED:
        text = render(found.data or {}, fmt, lambda test: cucumber.locate(cwd, test))
        say(f"{len(found.tests)} likely affected test(s) for {len(found.paths)} changed file(s)")
    else:
        say(f"no suggestion: {found.reason}")
    if args.out:
        try:
            _write(args.out, text)  # emptied when there is no suggestion (exit 3 or 4)
        except OSError as exc:
            raise ConfigError(f"cannot write {args.out}: {exc.strerror or exc}") from None
    else:
        _print(text)
    return found.code
