r"""One-off: test impact analysis against its budgets on a big project (spec 2026-10-12 §3.7). Not part of CI.

Against a throwaway PostgreSQL, never the stack's own database (build the image first with
`docker compose build ingestion-service`):

    docker network create qeos-impact-bench
    docker run -d --name qeos-impact-bench-pg --network qeos-impact-bench \
        -e POSTGRES_PASSWORD=bench -e POSTGRES_DB=ingestion_db postgres:15
    BENCH="docker run --rm -i --network qeos-impact-bench -e SECRET_KEY=bench \
        -e DATABASE_URL=postgresql://postgres:bench@qeos-impact-bench-pg:5432/ingestion_db qeos/ingestion-service:local"
    $BENCH alembic upgrade head
    $BENCH python - < scripts/impact_benchmark.py; echo "exit $?"
    docker rm -f qeos-impact-bench-pg && docker network rm qeos-impact-bench

Seeds project
900002 like scripts/analytics_benchmark.py (90 days x 22 runs x 1,000 tests, about two million results, one commit
per run), each run with 3 to 12 changed files from 40 folders, and the daily flaky rollups the analytics-rollup job
keeps. Then times:

- the impact rollup of the project (rebuild_statistics, flaky keys included; budget 60 s);
- live scoring of a 10-file change on main (score_change, p95 of 50; budget 200 ms);
- what an upload adds: scoring inside the request (score_upload, with its 2 s statement timeout) and the outcome
  after the response (evaluate, on a fresh 1,000-result run);
- replay of the last 3 days (runs per second).

Deletes everything it seeded. Exits 1 over a budget.
"""
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, text

from src.ingestion.analytics import rollup
from src.ingestion.db.session import SessionLocal
from src.ingestion.jobs.impact_rollup import window_start
from src.ingestion.models import ApiKey, Run, RunChangedFile, RunResult
from src.ingestion.models.flaky_rollup import FlakyDaily, FlakyRollupDay
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact
from src.ingestion.service import analytics_service, impact_service
from src.ingestion.service.impact_history import flaky_keys
from src.ingestion.service.impact_replay import replay_project
from src.ingestion.service.impact_stats import rebuild_statistics
from src.ingestion.service.ingest_service import test_key

PROJECT = 900002
DAYS = 90
RUNS_PER_DAY = 22
TESTS = 1000
STATUSES = ("passed", "failed", "errored", "skipped")
WEIGHTS = (95, 3, 1, 1)
FOLDERS = [f"src/area{i}/mod{j}" for i in range(8) for j in range(5)]
ROLLUP_BUDGET_S = 60.0
SCORE_BUDGET_MS = 200.0
SAMPLES = 50
REPLAY_DAYS = 3

random.seed(11)
keys = [test_key("bench", f"Class{i // 50}", f"test_{i}") for i in range(TESTS)]
now = datetime.now(timezone.utc)
db = SessionLocal()
over = False
commits = 0


def changed_paths(count):
    return sorted({f"{random.choice(FOLDERS)}/file{random.randint(0, 30)}.py" for _ in range(count)})


def seed_run(api_key_id, started, branch):
    global commits
    commits += 1
    statuses = random.choices(STATUSES, WEIGHTS, k=TESTS)
    paths = changed_paths(random.randint(3, 12))
    run = Run(project_id=PROJECT, api_key_id=api_key_id, request_hash="bench", ci_provider="local",
              branch=branch, commit_sha=f"{commits:07x}",  # one commit per run
              started_at=started, finished_at=started + timedelta(minutes=5), duration_ms=300000,
              total=TESTS, passed=statuses.count("passed"), failed=statuses.count("failed"),
              errored=statuses.count("errored"), skipped=statuses.count("skipped"),
              change_base_ref="abc1234^", changed_files=len(paths), additions=len(paths), deletions=0,
              changes_truncated=False)
    db.add(run)
    db.flush()
    db.execute(insert(RunResult), [
        {"run_id": run.id, "test_key": keys[i], "suite": "bench", "class_name": f"Class{i // 50}",
         "name": f"test_{i}", "status": statuses[i], "duration_ms": random.randint(5, 2000),
         "truncated": False, "redacted": False}
        for i in range(TESTS)
    ])
    db.execute(insert(RunChangedFile), [
        {"run_id": run.id, "path": path, "status": "M", "additions": 1, "deletions": 0} for path in paths
    ])
    return run, paths


def p(values, q):
    return statistics.quantiles(values, n=100)[q - 1]


try:
    api_key = ApiKey(project_id=PROJECT, organization_id=1, name="bench", key_prefix="qeos_bench2",
                     key_hash="e" * 64, created_by=1)
    db.add(api_key)
    db.flush()
    started_seeding = time.perf_counter()
    for day in range(DAYS):
        for number in range(RUNS_PER_DAY):
            seed_run(api_key.id, now - timedelta(days=day, minutes=number * 30 + 1),
                     random.choice(("main", "main", "feature")))
        db.commit()
    for day in range(DAYS + 1):
        rollup.upsert_day(db, PROJECT, (now - timedelta(days=day)).date())
    db.commit()
    for table in ("test_runs", "test_results", "run_changed_files", "flaky_daily"):
        db.execute(text(f"ANALYZE {table}"))
    db.commit()
    print(f"seeded {DAYS * RUNS_PER_DAY} runs x {TESTS} results (one commit per run, daily flaky rollups) in "
          f"{time.perf_counter() - started_seeding:.0f} s")

    start = time.perf_counter()
    since = window_start(now)
    flaky = flaky_keys(db, PROJECT, since)
    flaky_s = time.perf_counter() - start
    pairs, tests = rebuild_statistics(db, PROJECT, since, now, flaky, analytics_service.muted_keys(db, PROJECT), now)
    rollup_s = time.perf_counter() - start
    print(f"impact rollup, one project: {rollup_s:.1f} s (flaky keys {flaky_s:.1f} s; {pairs} pairs, {tests} tests, "
          f"{len(flaky)} flaky); budget {ROLLUP_BUDGET_S:.0f} s: {'ok' if rollup_s <= ROLLUP_BUDGET_S else 'OVER'}")
    over |= rollup_s > ROLLUP_BUDGET_S

    timings, suggested = [], []
    for _ in range(SAMPLES):
        change = changed_paths(10)
        before = time.perf_counter()
        suggestion = impact_service.score_change(db, PROJECT, change, "main", now=now)
        timings.append((time.perf_counter() - before) * 1000)
        suggested.append(len(suggestion["tests"]))
        db.rollback()
    score_p95 = p(timings, 95)
    print(f"live scoring, 10 changed files: p50 {statistics.median(timings):.0f} ms, p95 {score_p95:.0f} ms "
          f"({statistics.mean(suggested):.0f} tests suggested on average); budget {SCORE_BUDGET_MS:.0f} ms: "
          f"{'ok' if score_p95 <= SCORE_BUDGET_MS else 'OVER'}")
    over |= score_p95 > SCORE_BUDGET_MS

    in_request, after = [], []
    for number in range(10):
        change = changed_paths(10)
        started = now + timedelta(minutes=number + 1)
        before = time.perf_counter()
        scored = impact_service.score_upload(db, PROJECT, change, "main", started)
        in_request.append((time.perf_counter() - before) * 1000)
        run, _ = seed_run(api_key.id, started, "main")
        db.add(impact_service.stored_suggestion(run.id, scored, replayed=False))
        db.commit()
        before = time.perf_counter()
        impact_service.evaluate(db, run.id, now)
        after.append((time.perf_counter() - before) * 1000)
    print(f"upload: scoring in the request p50 {statistics.median(in_request):.0f} ms, max {max(in_request):.0f} ms; "
          f"outcome after the response p50 {statistics.median(after):.0f} ms, max {max(after):.0f} ms")

    db.execute(delete(RunImpact).where(RunImpact.run_id.in_(select(Run.id).where(Run.project_id == PROJECT))))
    db.commit()
    before = time.perf_counter()
    replay_since = now - timedelta(days=REPLAY_DAYS)
    replayed = replay_project(db, PROJECT, replay_since, now)
    replay_s = time.perf_counter() - before
    # Replay rebuilds the statistics once per date that has runs (as replay_project groups them), not per window day
    dates = len({started.date() for started in db.scalars(select(Run.started_at).where(
        Run.project_id == PROJECT, Run.started_at >= replay_since, Run.started_at < now))})
    print(f"replay, last {REPLAY_DAYS} days: {replayed} runs on {dates} dates in {replay_s:.0f} s "
          f"({replayed / replay_s:.1f} runs/s, {replay_s / max(dates, 1):.0f} s per replayed date)")
finally:
    db.rollback()
    run_ids = select(Run.id).where(Run.project_id == PROJECT)
    db.execute(delete(RunImpact).where(RunImpact.run_id.in_(run_ids)))
    db.execute(delete(RunChangedFile).where(RunChangedFile.run_id.in_(run_ids)))
    db.execute(delete(RunResult).where(RunResult.run_id.in_(run_ids)))
    db.execute(delete(Run).where(Run.project_id == PROJECT))
    db.execute(delete(ApiKey).where(ApiKey.project_id == PROJECT))
    db.execute(delete(ImpactPair).where(ImpactPair.project_id == PROJECT))
    db.execute(delete(ImpactTestBase).where(ImpactTestBase.project_id == PROJECT))
    db.execute(delete(FlakyDaily).where(FlakyDaily.project_id == PROJECT))
    db.execute(delete(FlakyRollupDay).where(FlakyRollupDay.project_id == PROJECT))
    db.commit()
    db.close()
sys.exit(1 if over else 0)
