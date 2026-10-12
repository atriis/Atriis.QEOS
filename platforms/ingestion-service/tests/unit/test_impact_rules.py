"""Test impact definitions (spec 2026-10-12 §3.1; plan Rulings 3, 4, 5, 8, 12)."""
import pytest

from src.ingestion.analytics.impact_rules import (
    FOLDER_ONLY_ABOVE, ChangedFiles, base_branch_of, change_units, is_ignored, path_units,
)


def test_a_path_counts_as_itself_and_its_parent_folders():
    assert path_units("src/payment/api.py") == ["src/payment/api.py", "src/payment/", "src/"]


def test_at_most_three_parent_folders_the_nearest_ones():
    assert path_units("a/b/c/d/e.py") == ["a/b/c/d/e.py", "a/b/c/d/", "a/b/c/", "a/b/"]


def test_a_file_at_the_root_is_only_itself():
    assert path_units("README.md") == ["README.md"]


def test_empty_segments_are_dropped():
    assert path_units("/src//payment/api.py") == ["src/payment/api.py", "src/payment/", "src/"]


def test_dot_segments_are_dropped_not_resolved():
    """Git never sends "." or ".."; dropping them keeps "../" from ever being a unit."""
    assert path_units("./src/pay/api.py") == ["src/pay/api.py", "src/pay/", "src/"]
    assert path_units("src/../pay/api.py") == ["src/pay/api.py", "src/pay/", "src/"]
    assert path_units("../..") == [] and is_ignored("./..")


def test_unicode_paths_keep_their_characters():
    assert path_units("src/páginas/ação.py", repository="repó") == [
        "repó:src/páginas/ação.py", "repó:src/páginas/", "repó:src/"]


def test_an_empty_change_has_no_units():
    assert change_units([]) == set()
    assert not ChangedFiles([]).touches("tests/test_pay.py")


def test_a_repository_prefixes_every_unit():
    assert path_units("src/payment/api.py", repository="repo-a") == [
        "repo-a:src/payment/api.py", "repo-a:src/payment/", "repo-a:src/"]


def test_folders_only_leaves_the_file_out():
    assert path_units("src/payment/api.py", folders_only=True) == ["src/payment/", "src/"]


@pytest.mark.parametrize("path", [
    "poetry.lock", "web/package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock",
    "web/dist/app.js", "build/x.o", "vendor/lib/a.go", "web/node_modules/left-pad/index.js", "/",
])
def test_lock_files_generated_or_vendored_and_blank_paths_are_ignored(path):
    assert is_ignored(path)


@pytest.mark.parametrize("path", ["src/build.py", "docs/distribution.md", "src/vendor.py", "lockfile.txt", "dist"])
def test_lookalikes_are_kept(path):
    assert not is_ignored(path)


def test_change_units_leave_ignored_paths_out():
    assert change_units(["src/a.py", "poetry.lock", "node_modules/x/y.js", "/"]) == {"src/a.py", "src/"}


def test_a_change_of_more_than_300_files_counts_at_folder_level_only():
    units = change_units([f"src/mod{i}/f.py" for i in range(FOLDER_ONLY_ABOVE + 1)])
    assert "src/mod0/f.py" not in units and {"src/mod0/", "src/"} <= units


def test_a_change_of_exactly_300_files_keeps_its_files():
    assert "src/mod0/f.py" in change_units([f"src/mod{i}/f.py" for i in range(FOLDER_ONLY_ABOVE)])


def test_the_300_counts_paths_once_normalised():
    paths = [f"src/mod{i}/f.py" for i in range(FOLDER_ONLY_ABOVE)] + ["src//mod0/f.py", "/src/mod1/f.py", "/"]
    assert "src/mod0/f.py" in change_units(paths)


def test_ignored_paths_still_count_toward_the_300():
    paths = [f"vendor/lib{i}.go" for i in range(FOLDER_ONLY_ABOVE)] + ["src/pay/api.py"]
    assert change_units(paths) == {"src/pay/", "src/"}


@pytest.mark.parametrize("branch, base_branch, change_base_ref, expected", [
    ("feature/x", "main", "origin/main", "main"),
    ("feature/x", None, "origin/develop", "develop"),
    ("main", None, "abc1234^", None),
    ("main", "main", "origin/main", None),
    ("feature/x", None, None, None),
])
def test_the_base_branch(branch, base_branch, change_base_ref, expected):
    assert base_branch_of(branch, base_branch, change_base_ref) == expected


def test_a_test_file_matches_when_one_path_ends_the_other():
    files = ChangedFiles(["tests/test_pay.py", "src/pay/api.py"])
    assert files.touches("tests/test_pay.py")
    assert files.touches("web/tests/test_pay.py")  # recorded from another checkout root
    assert files.touches("test_pay.py")            # a file name alone
    assert files.touches("tests\\test_pay.py")     # Windows separators
    assert ChangedFiles(["web/tests/test_pay.py"]).touches("tests/test_pay.py")
    assert not files.touches("tests/test_cart.py")
    assert not files.touches("other/test_pay.py")
    assert not files.touches(None) and not files.touches("")
