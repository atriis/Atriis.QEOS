import { fileLabel, groupByFeature, mergeStrips } from "./featureQueries";
import type { StripEntry, StripStatus } from "../api/analytics";
import type { Case } from "../api/cases";

const kase = (number: number, extra: Partial<Case>) => ({
  number, key: `TC-${number}`, title: `Case ${number}`, priority: "medium", status: "draft", automated_test_key: null,
  source_path: null, feature_name: null, ...extra,
}) as unknown as Case;

test("fileLabel drops the path and a trailing .feature, in any case", () => {
  expect(fileLabel("a/b/foo_bar.feature")).toBe("foo_bar");
  expect(fileLabel("foo.FEATURE")).toBe("foo");
  expect(fileLabel("a/b/foo.feature.txt")).toBe("foo.feature.txt");
  expect(fileLabel("x.feature/y")).toBe("y");
});

const at = (run_id: number, status: StripStatus, hour = run_id): StripEntry =>
  ({ run_id, started_at: `2026-10-06T${String(hour).padStart(2, "0")}:00:00Z`, branch: "main", status });

test("mergeStrips takes the worst status per run: failed > rerun > passed > skipped", () => {
  expect(mergeStrips([[at(1, "passed"), at(2, "skipped")], [at(1, "failed"), at(2, "passed")]]).map((e) => e.status))
    .toEqual(["failed", "passed"]);
  expect(mergeStrips([[at(1, "skipped"), at(2, "rerun")], [at(1, "passed"), at(2, "passed")]]).map((e) => e.status))
    .toEqual(["passed", "rerun"]);
  expect(mergeStrips([])).toEqual([]);
});

test("mergeStrips joins scenarios that ran in different runs, oldest to newest, newest ten kept", () => {
  const a = [1, 3, 5, 7, 9, 11].map((r) => at(r, "passed"));
  const b = [2, 4, 6, 8, 10, 12].map((r) => at(r, r === 12 ? "failed" : "passed"));
  const merged = mergeStrips([a, b]);
  expect(merged.map((e) => e.run_id)).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  expect(merged[merged.length - 1].status).toBe("failed");
});

test("mergeStrips orders by start time, then run id", () => {
  expect(mergeStrips([[at(9, "passed", 1)], [at(4, "passed", 2), at(5, "failed", 1)]]).map((e) => e.run_id)).toEqual([5, 9, 4]);
});

test("the client-side grouping fills test_keys with its cases' distinct keys, sorted", () => {
  const rows = groupByFeature([
    kase(1, { source_path: "a.feature", feature_name: "A", automated_test_key: "b".repeat(64) }),
    kase(2, { source_path: "a.feature", feature_name: "A", automated_test_key: "a".repeat(64) }),
    kase(3, { source_path: "a.feature", feature_name: "A", automated_test_key: "a".repeat(64) }),
    kase(4, { source_path: "a.feature", feature_name: "A" }),
    kase(5, {}),
  ]);
  expect(rows[0].test_keys).toEqual(["a".repeat(64), "b".repeat(64)]);
  expect(rows[1].test_keys).toEqual([]);
});

test("mergeStrips joins a run's values over its scenarios, per pattern, duplicates removed", () => {
  const a = { ...at(1, "passed"), values: [{ name: "trip_id", values: ["1"] }] };
  const b = { ...at(1, "failed"), values: [{ name: "trip_id", values: ["1", "2"] }, { name: "route_key", values: ["r"] }] };
  const c = at(2, "passed"); // an older server: no values
  const merged = mergeStrips([[a, c], [b]]);
  expect(merged[0].status).toBe("failed");
  expect(merged[0].values).toEqual([{ name: "route_key", values: ["r"] }, { name: "trip_id", values: ["1", "2"] }]);
  expect(merged[1].values).toEqual([]);
});
