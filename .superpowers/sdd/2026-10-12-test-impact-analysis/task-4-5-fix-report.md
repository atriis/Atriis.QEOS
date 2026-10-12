# Tasks 4-5 fix round

1. impact_pairs keeps pairs with new_failures >= MIN_NEW_FAILURES: HAVING in the pair INSERT...SELECT (impact_stats._pairs). Tests: new test for a 1-failure pair not stored; truncated/300-file/lock-file tests rebuilt around 2 failures; the SQL-equals-Python test gets an extra test `e` (2 new failures in 4 runs, not flaky) and asserts the filter drops some pairs. README, impact.py docstring updated.
2. Staging tables dropped as pg_temp.<name> on PostgreSQL (plain name on SQLite).
3. ANALYZE on the three staging tables after staging, PostgreSQL only. COLLATE "C" not applied (optional; no PG run here to confirm identical results).
4. Test: late target with a pass about 100 days back and an earlier target 95 days back; fails with the 90-day check removed (mutation checked).
5. Tests: passed->failed on a null branch; 90-day cut-off of the base-branch fallback (mutation checked).
6. scaffold.serve: SIGTERM sets the stop event (main thread only, when serve created the event). Test calls the installed handler; fails without it.
7. newest_row excludes skipped rows; test with a later skipped row carrying another file; fails without it.

Not verified on PostgreSQL (pg_temp drop, ANALYZE): no PG run in this round.
