import json
from datetime import datetime, timedelta, timezone

import pytest

from qeos_collector import __version__, payload
from qeos_collector.payload import build_parts, build_run, run_times, summarize

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
RUN = {"ci_provider": "local", "started_at": "x", "finished_at": "x"}


def result(name, status="passed", duration_ms=0):
    return {"suite": "", "class_name": "", "name": name, "status": status, "duration_ms": duration_ms}


def test_started_at_is_the_earliest_suite_timestamp():
    early, late = NOW - timedelta(minutes=10), NOW - timedelta(minutes=5)
    assert run_times([late, early], 99, [], NOW) == (early, NOW)


def test_without_timestamps_started_at_is_now_minus_the_suite_time():
    assert run_times([], 90.5, [], NOW) == (NOW - timedelta(seconds=90.5), NOW)


def test_without_suite_time_the_result_durations_are_summed():
    results = [result("a", duration_ms=1500), result("b", duration_ms=500)]
    assert run_times([], 0, results, NOW)[0] == NOW - timedelta(seconds=2)


def test_started_at_is_clamped_to_seven_days_and_to_finished_at():
    assert run_times([NOW - timedelta(days=30)], 0, [], NOW)[0] == NOW - timedelta(days=7)
    assert run_times([NOW + timedelta(hours=2)], 0, [], NOW)[0] == NOW
    # Suite times that add up to centuries must not overflow timedelta
    assert run_times([], 1e300, [], NOW)[0] == NOW - timedelta(days=7)


def test_build_run_sends_what_the_server_accepts():
    run = build_run(
        ci_provider="github_actions",
        started_at=NOW - timedelta(minutes=1),
        finished_at=NOW,
        ci_run_url="https://github.com/acme/shop/actions/runs/1",
        commit_sha="a" * 40,
        branch="main",
        environment="staging",
    )
    assert run == {
        "ci_provider": "github_actions",
        "agent_version": f"qeos-collector/{__version__}",
        "started_at": "2026-09-29T11:59:00+00:00",
        "finished_at": "2026-09-29T12:00:00+00:00",
        "ci_run_url": "https://github.com/acme/shop/actions/runs/1",
        "commit_sha": "a" * 40,
        "branch": "main",
        "environment": "staging",
    }


@pytest.mark.parametrize("field, value", [
    ("commit_sha", "HEAD"),
    ("commit_sha", "abc"),
    ("ci_run_url", "ftp://ci.acme.test/1"),
    ("ci_run_url", "https://has a space"),
    ("ci_run_url", "https://ci.acme.test/" + "a" * 2048),
    ("branch", ""),
    ("environment", None),
])
def test_invalid_or_empty_metadata_is_left_out(field, value):
    run = build_run(ci_provider="local", started_at=NOW, finished_at=NOW, **{field: value})
    assert field not in run


def test_long_metadata_is_cut():
    run = build_run(ci_provider="local", started_at=NOW, finished_at=NOW, branch="b" * 300, environment="e" * 150)
    assert len(run["branch"]) == 255 and len(run["environment"]) == 100


def test_undecodable_metadata_is_made_storable():
    # os.environ holds undecodable bytes as lone surrogates, which UTF-8 cannot encode
    run = build_run(ci_provider="local", started_at=NOW, finished_at=NOW, branch="bad\udcff")
    assert run["branch"] == "bad?"
    json.dumps(run, ensure_ascii=False).encode("utf-8")


def test_one_part_keeps_the_key_as_is():
    parts = build_parts(RUN, [result("a"), result("b")], "gh-1-1-test")

    assert [(p.idempotency_key, p.count) for p in parts] == [("gh-1-1-test", 2)]
    assert json.loads(parts[0].body) == {"run": RUN, "results": [result("a"), result("b")]}


def test_more_results_than_the_server_takes_are_split_into_numbered_parts(monkeypatch):
    monkeypatch.setattr(payload, "MAX_RESULTS_PER_PART", 3)
    parts = build_parts(RUN, [result(str(i)) for i in range(7)], "k")

    assert [(p.idempotency_key, p.count) for p in parts] == [("k-part-1", 3), ("k-part-2", 3), ("k-part-3", 1)]
    assert [r["name"] for p in parts for r in json.loads(p.body)["results"]] == [str(i) for i in range(7)]
    assert all(json.loads(p.body)["run"] == RUN for p in parts)


def test_a_part_over_the_size_limit_is_halved_until_it_fits(monkeypatch):
    rows = [dict(result(str(i)), details="x" * 1000) for i in range(8)]
    monkeypatch.setattr(payload, "MAX_PART_BYTES", 2500)
    parts = build_parts(RUN, rows, "k")

    assert all(len(p.body) <= 2500 for p in parts)
    assert [p.count for p in parts] == [2, 2, 2, 2]
    assert [p.idempotency_key for p in parts] == ["k-part-1", "k-part-2", "k-part-3", "k-part-4"]


def test_a_single_result_is_never_split_further(monkeypatch):
    monkeypatch.setattr(payload, "MAX_PART_BYTES", 10)
    parts = build_parts(RUN, [result("a"), result("b")], "k")

    assert [p.count for p in parts] == [1, 1]


def test_summarize():
    results = [result("a"), result("b", "failed"), result("c", "errored"), result("d", "skipped"), result("e")]
    assert summarize(results) == {"passed": 2, "failed": 1, "errored": 1, "skipped": 1}


def test_build_parts_carries_changes_in_every_part():
    import json as _json
    from qeos_collector.payload import build_parts

    run = {"ci_provider": "local", "started_at": "2026-10-02T00:00:00+00:00",
           "finished_at": "2026-10-02T00:01:00+00:00"}
    results = [{"name": f"t{i}", "status": "passed"} for i in range(3)]
    changes = {"base_ref": "origin/main", "truncated": False,
               "files": [{"path": "a.py", "status": "M", "additions": 1, "deletions": 0}]}
    parts = build_parts(run, results, "key", changes)
    for part in parts:
        assert _json.loads(part.body)["changes"] == changes

    without = build_parts(run, results, "key")
    assert "changes" not in _json.loads(without[0].body)


def test_build_run_carries_git_metadata_when_valid():
    from qeos_collector.payload import build_run
    from datetime import datetime, timezone

    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    run = build_run(ci_provider="local", started_at=now, finished_at=now,
                    commit_author="Ada", commit_message="m" * 600,
                    pr_number=123, base_branch="main")
    assert run["commit_author"] == "Ada"
    assert len(run["commit_message"]) == 500  # cut, not rejected
    assert run["pr_number"] == 123
    assert run["base_branch"] == "main"

    bare = build_run(ci_provider="local", started_at=now, finished_at=now, pr_number=0)
    assert "pr_number" not in bare and "commit_author" not in bare


@pytest.mark.parametrize("trigger, sent", [("manual", "manual"), ("qeos", "qeos"), (None, None), ("cron", None)])
def test_trigger_is_sent_only_when_known(trigger, sent):
    now = datetime.now(timezone.utc)
    run = build_run(ci_provider="github_actions", started_at=now, finished_at=now, trigger=trigger)
    assert run.get("trigger") == sent


def test_scope_and_stages_are_sent_only_when_given():
    moment = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)
    base = {"ci_provider": "local", "started_at": moment, "finished_at": moment}
    plain = build_run(**base)
    assert "scope" not in plain and "stages" not in plain  # an ordinary upload hashes as before (plan Ruling 5)
    stages = {"stages": [{"name": "all", "duration_s": 1.0, "tests": 1, "failed": 0}], "time_to_first_failure_s": None}
    run = build_run(**base, scope="impact-subset", stages=stages)
    assert (run["scope"], run["stages"]) == ("impact-subset", stages)
    assert build_run(**base, scope="full")["scope"] == "full"
    assert "scope" not in build_run(**base, scope="partial")
    assert payload.SCOPES == ("full", "impact-subset")


def test_stages_go_with_the_first_part_only(monkeypatch):
    """Split uploads: the platform keeps the first part's stages (plan Ruling, split uploads)."""
    stages = {"stages": [{"name": "all", "duration_s": 1.0, "tests": 8, "failed": 0}], "time_to_first_failure_s": None}
    run = {**RUN, "scope": "full", "stages": stages}
    rows = [dict(result(str(i)), details="x" * 1000) for i in range(8)]
    monkeypatch.setattr(payload, "MAX_PART_BYTES", 2700)
    parts = build_parts(run, rows, "k")
    bodies = [json.loads(p.body) for p in parts]
    assert len(parts) == 4 and all(len(p.body) <= 2700 for p in parts)
    assert bodies[0]["run"]["stages"] == stages
    assert all("stages" not in body["run"] for body in bodies[1:])
    assert all(body["run"]["scope"] == "full" for body in bodies)
    assert sum(len(body["results"]) for body in bodies) == 8


def test_one_part_keeps_its_stages():
    stages = {"stages": [], "time_to_first_failure_s": None}
    [part] = build_parts({**RUN, "stages": stages}, [result("a")], "k")
    assert json.loads(part.body)["run"]["stages"] == stages
