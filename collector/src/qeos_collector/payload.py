"""The upload body: run times, run metadata, and splitting into parts the server accepts."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from qeos_collector import __version__

MAX_RESULTS_PER_PART = 20000
# The gateway accepts bodies up to 10 MB
MAX_PART_BYTES = 9 * 1024 * 1024
TRIGGERS = ("manual", "automatic", "qeos")
SCOPES = ("full", "impact-subset")  # run-impact (spec 2026-10-13 §3.1): the one list of scopes
MAX_RUN_SPAN = timedelta(days=7)
BRANCH_LENGTH = 255
ENVIRONMENT_LENGTH = 100
RUN_URL_LENGTH = 2048
_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")
_RUN_URL = re.compile(r"^https?://\S+$")
MAX_COMPONENTS = 20       # mirrors the server's cap
MAX_COMPONENT_NAME = 100


@dataclass
class Part:
    body: bytes
    idempotency_key: str
    count: int


def run_times(
    timestamps: Sequence[datetime], suite_seconds: float, results: Sequence[dict], now: datetime
) -> Tuple[datetime, datetime]:
    finished = now
    if timestamps:
        started = min(timestamps)
    else:
        seconds = suite_seconds if suite_seconds > 0 else sum(r["duration_ms"] for r in results) / 1000
        started = finished - timedelta(seconds=min(seconds, MAX_RUN_SPAN.total_seconds()))
    # The server rejects runs longer than 7 days and starts after the finish
    started = min(max(started, finished - MAX_RUN_SPAN), finished)
    return started, finished


def build_run(
    *,
    ci_provider: str,
    started_at: datetime,
    finished_at: datetime,
    ci_run_url: Optional[str] = None,
    commit_sha: Optional[str] = None,
    branch: Optional[str] = None,
    environment: Optional[str] = None,
    commit_author: Optional[str] = None,
    commit_message: Optional[str] = None,
    pr_number: Optional[int] = None,
    base_branch: Optional[str] = None,
    trigger: Optional[str] = None,
    scope: Optional[str] = None,
    stages: Optional[dict] = None,
) -> Dict[str, str]:
    """Metadata the server would reject is left out or cut, so it never costs the whole run."""
    run = {
        "ci_provider": ci_provider,
        "agent_version": f"qeos-collector/{__version__}",
        "started_at": started_at.astimezone(timezone.utc).isoformat(),
        "finished_at": finished_at.astimezone(timezone.utc).isoformat(),
    }
    ci_run_url, commit_sha = _storable(ci_run_url), _storable(commit_sha)
    branch, environment = _storable(branch), _storable(environment)
    if ci_run_url and len(ci_run_url) <= RUN_URL_LENGTH and _RUN_URL.match(ci_run_url):
        run["ci_run_url"] = ci_run_url
    if commit_sha and _SHA.match(commit_sha):
        run["commit_sha"] = commit_sha
    if branch:
        run["branch"] = branch[:BRANCH_LENGTH]
    if environment:
        run["environment"] = environment[:ENVIRONMENT_LENGTH]
    commit_author, commit_message = _storable(commit_author), _storable(commit_message)
    base_branch = _storable(base_branch)
    if commit_author:
        run["commit_author"] = commit_author[:255]
    if commit_message:
        run["commit_message"] = commit_message[:500]
    if isinstance(pr_number, int) and pr_number > 0:
        run["pr_number"] = pr_number
    if base_branch:
        run["base_branch"] = base_branch[:BRANCH_LENGTH]
    if trigger in TRIGGERS:
        run["trigger"] = trigger
    # Only run-impact sends them, so an ordinary upload's body and request hash stay as they were
    if scope in SCOPES:
        run["scope"] = scope
    if stages:
        run["stages"] = stages
    return run


def parse_components(values: Sequence[str]) -> List[dict]:
    """NAME@SHA pairs naming the repos/versions the run exercised. The server
    stores them for later cross-repo analysis. Bad input is a config error:
    this is identity data, silently dropping it would poison the history."""
    components: List[dict] = []
    for value in values:
        name, separator, sha = value.strip().partition("@")
        name = name.strip()
        sha = sha.strip()
        if not separator or not name:
            raise ValueError(f"component {value!r} must look like NAME@SHA")
        if len(name) > MAX_COMPONENT_NAME:
            raise ValueError(f"component name {name!r} is longer than {MAX_COMPONENT_NAME} characters")
        if not _SHA.match(sha):
            raise ValueError(f"component {name!r}: {sha!r} is not a 7-40 character hexadecimal sha")
        components.append({"name": name, "sha": sha})
    names = [c["name"] for c in components]
    if len(names) != len(set(names)):
        raise ValueError("component names must be unique")
    if len(components) > MAX_COMPONENTS:
        raise ValueError(f"at most {MAX_COMPONENTS} components per run")
    return components


def build_parts(run: dict, results: List[dict], idempotency_key: str,
                changes: "dict | None" = None, components: "List[dict] | None" = None) -> List[Part]:
    # "_images" is the collector's own: the bytes are uploaded apart and never part of the body
    results = [{k: v for k, v in row.items() if k != "_images"} if "_images" in row else row for row in results]
    chunks = [results[i:i + MAX_RESULTS_PER_PART] for i in range(0, len(results), MAX_RESULTS_PER_PART)]
    encoded: List[Tuple[bytes, int]] = []
    for chunk in chunks:
        encoded.extend(_fit(run, chunk, changes, components))
    if len(encoded) == 1:
        body, count = encoded[0]
        return [Part(body=body, idempotency_key=idempotency_key, count=count)]
    if "stages" in run:
        # The stages go with the first part only: the platform keeps the first it gets for the run
        encoded = encoded[:1] + [(_without_stages(body), count) for body, count in encoded[1:]]
    # Numbered keys, so a re-run of the same CI job replays exactly the same parts
    return [
        Part(body=body, idempotency_key=f"{idempotency_key}-part-{number}", count=count)
        for number, (body, count) in enumerate(encoded, start=1)
    ]


def _without_stages(body: bytes) -> bytes:
    payload = json.loads(body)
    payload["run"].pop("stages", None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="replace")


def summarize(results: Sequence[dict]) -> Dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errored": 0}
    for result in results:
        counts[result["status"]] += 1
    return counts


def _fit(run: dict, chunk: List[dict], changes: "dict | None" = None,
         components: "List[dict] | None" = None) -> List[Tuple[bytes, int]]:
    payload = {"run": run, "results": chunk}
    if changes is not None:
        payload["changes"] = changes
    if components:
        payload["components"] = components
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="replace")
    if len(body) <= MAX_PART_BYTES or len(chunk) == 1:
        return [(body, len(chunk))]
    middle = len(chunk) // 2
    return _fit(run, chunk[:middle], changes, components) + _fit(run, chunk[middle:], changes, components)


def _storable(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    # Lone surrogates (undecodable bytes in os.environ or argv) become "?"
    return value.encode("utf-8", errors="replace").decode("utf-8").strip() or None
