"""Every collector pin in the repository names the collector's current version (ADR-037 follow-up).

A release moves the pins by hand in about twenty places (pip installs, raw template URLs, the Action, the Jenkins and
CI template defaults, prose such as "Pin the tag (`collector-vX.Y.Z`)"). This scans every tracked file, so a pin added
anywhere is covered, and fails on any collector-vX.Y.Z that is not the current version. A line that tells history
("from `collector-v0.7.0`", "`@collector-v0.5.2` or later", "0.3.0 or older") is not a pin, nor are the plans,
specs, ADRs and the TODO list, which record what happened when.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# (?!\d): a multi-digit patch is never cut short by backtracking ("0.5.12" is not "0.5.1")
TAG = re.compile(r"collector-v(\d+\.\d+\.\d+)(?![\d])")
HISTORY_FILES = ("docs/superpowers/", "docs/architecture/adr/", "TODO.md", "IMPLEMENTATION_PLAN.md",
                 "scripts/tests/test_collector_pins.py")
HISTORY_WORDS = re.compile(r"or later|and later|or older|and before|\bfrom\b|\bbefore\b|older tags|version \d", re.I)


def current_version() -> str:
    text = (ROOT / "collector/src/qeos_collector/__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    for name in out.splitlines():
        if not name.startswith(HISTORY_FILES):
            yield name


def stale_pins(version: str) -> list:
    stale = []
    for name in tracked_files():
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in TAG.finditer(line):
                if match.group(1) != version and not HISTORY_WORDS.search(line):
                    stale.append(f"{name}:{number}: {match.group(0)}")
    return stale


def test_every_collector_pin_names_the_current_version():
    version = current_version()
    assert stale_pins(version) == []


def test_a_stale_pin_is_found_and_a_history_note_is_not():
    assert TAG.findall("use `@collector-v0.5.12` or later") == ["0.5.12"]
    assert not HISTORY_WORDS.search('pip install "qeos-collector @ git+https://x@collector-v0.14.0#subdirectory=collector"')
    assert HISTORY_WORDS.search("Suggested tests first (Cucumber, from `collector-v0.7.0`)")
    assert HISTORY_WORDS.search("use `collector-action@collector-v0.5.0` or later")
    # Every current pin form is checked, backticked prose included
    for line in ("Pin the tag (`collector-v0.1.0`)", "default: collector-v0.1.0", "QEOS_COLLECTOR_REF:-collector-v0.1.0",
                 "String ref = config.ref ?: 'collector-v0.1.0'"):
        assert TAG.search(line) and not HISTORY_WORDS.search(line), line
