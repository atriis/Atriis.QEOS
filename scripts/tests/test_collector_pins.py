"""Every collector pin names the collector's current version (ADR-037 follow-up).

A release moves the pins by hand in the files below (pip installs, raw template URLs, the Action, the Jenkins and CI
template defaults, prose such as "Pin the tag (`collector-vX.Y.Z`)"). Each must still hold a pin, and every
collector-vX.Y.Z in it must be the current version, except a tag a history phrase sits right next to ("from
`collector-v0.7.0`", "`@collector-v0.5.2` or later", "`collector-v0.3.0` and before"). A file that starts carrying a
pin joins PINNED.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PINNED = ["README.md", "docs/SETUP.md", "collector/README.md", "collector-jenkins/vars/qeosCollectorUpload.groovy",
          "templates/qeos-collector.azure-pipelines.yml", "templates/qeos-collector.gitlab-ci.yml"]
# Not part of a longer name (qav-collector-v...); a pre-release (-rc1) or a longer patch (0.5.12) is never cut short
TAG = re.compile(r"(?<!\w)(?<!\w-)collector-v(\d+\.\d+\.\d+)(?![\w-]|\.\d)")
BEFORE = re.compile(r"(?:\bfrom\b|\bbefore\b)\W{0,3}$", re.I)
AFTER = re.compile(r"^\W{0,3}(?:or later|and later|or older|and before|or before)", re.I)


def current_version() -> str:
    text = (ROOT / "collector/src/qeos_collector/__init__.py").read_text(encoding="utf-8")
    found = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text)
    assert found, "collector/src/qeos_collector/__init__.py has no __version__ = '...' line"
    return found.group(1)


def history(line: str, match: re.Match) -> bool:
    """A tag a history phrase sits right next to: "from `collector-v0.7.0`", "`collector-v0.4.0` or later"."""
    start = max(0, match.start() - 16)
    return bool(BEFORE.search(line[start:match.start()].replace("@", " ").replace("collector-action", " "))
                or AFTER.search(line[match.end():match.end() + 16]))


def pins(text: str) -> "list[tuple[int, str, bool]]":
    """(line number, version, is history) of every tag in a file's text."""
    return [(n, m.group(1), history(line, m)) for n, line in enumerate(text.splitlines(), 1) for m in TAG.finditer(line)]


def test_every_pin_names_the_current_version_and_every_pinned_file_still_has_one():
    version = current_version()
    stale, empty = [], []
    for name in PINNED:
        found = pins((ROOT / name).read_text(encoding="utf-8"))
        if not [v for _, v, old in found if not old]:
            empty.append(name)
        stale += [f"{name}:{n}: collector-v{v}" for n, v, old in found if not old and v != version]
    assert empty == [], "these files no longer hold a collector pin"
    assert stale == []


def test_history_is_recognised_next_to_its_own_tag_only():
    assert pins("Suggested tests first (Cucumber, from `collector-v0.7.0`)") == [(1, "0.7.0", True)]
    assert pins("use `collector-action@collector-v0.5.0` or later") == [(1, "0.5.0", True)]
    assert pins("use `@collector-v0.5.12` or later") == [(1, "0.5.12", True)]
    # A history word elsewhere on the line does not excuse a pin
    line = 'pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.13.0#subdirectory=collector"  # from GitHub'
    assert pins(line) == [(1, "0.13.0", False)]
    for line in ("Pin the tag (`collector-v0.1.0`)", "default: collector-v0.1.0", "QEOS_COLLECTOR_REF:-collector-v0.1.0",
                 "String ref = config.ref ?: 'collector-v0.1.0'"):
        assert pins(line) == [(1, "0.1.0", False)], line
    # Neither a longer name nor a pre-release is a pin of this collector
    assert pins("qav-collector-v0.3.0 and collector-v0.15.0-rc1") == []
    # A pin ending a sentence is still a pin
    assert pins("Use collector-v0.1.0.") == [(1, "0.1.0", False)]


# Documents that record history (plans, specs, decisions, the to-do list) may name any tag: ADRs and plans keep the
# version they were written for on purpose
HISTORY_DIRS = ("docs/superpowers/", "docs/architecture/adr/")
HISTORY_ROOT_FILES = {"TODO.md", "IMPLEMENTATION_PLAN.md", "NEXT_STEPS.md"}
THIS_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()


def candidate_files() -> "list[str] | None":
    """Tracked files that name a collector tag (what CI sees; untracked clutter such as caches is not the repo's).
    None only when there is no git checkout to ask; any other git failure fails the test with git's message."""
    try:
        out = subprocess.run(["git", "grep", "-lzI", "-E", "collector-v[0-9]"], cwd=ROOT, capture_output=True)
    except FileNotFoundError:
        return None
    if out.returncode == 128 and b"not a git repository" in out.stderr:
        return None
    assert out.returncode in (0, 1), out.stderr.decode("utf-8", "replace")  # 1: no match
    return [name for name in out.stdout.decode("utf-8").split("\0") if name]


def test_no_file_outside_pinned_carries_a_collector_pin():
    """A file that starts carrying a pin is caught when it is committed, whatever tag it names: a pin anywhere outside
    PINNED (and the history documents) fails, so the file joins PINNED and is checked from then on."""
    names = candidate_files()
    if names is None:
        # CI always has its checkout: there the check must run, never skip quietly
        if os.environ.get("CI"):
            pytest.fail("the collector pin check needs git and a checkout")
        pytest.skip("not a git checkout")
    strays = []
    for name in names:
        if name in PINNED or name == THIS_FILE or name.startswith(HISTORY_DIRS) or name in HISTORY_ROOT_FILES:
            continue
        text = (ROOT / name).read_text(encoding="utf-8")
        if any(not old for _, _, old in pins(text)):
            strays.append(name)
    assert strays == [], "these files carry a collector pin: add them to PINNED"
