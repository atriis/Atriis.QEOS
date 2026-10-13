import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { getFlaky, getHistory, getTests, getTrends, formatDuration, formatPassRate } from "./analytics";

beforeEach(() => setAccessToken("acc"));

test("getTrends maps options to query params", async () => {
  let url = "";
  server.use(
    http.get("/api/v1/projects/42/analytics/trends", ({ request }) => {
      url = request.url;
      return HttpResponse.json({ tz: "UTC", days: [] });
    }),
  );
  await getTrends(42, { days: 30, tz: "Europe/London", branch: "main", bucket: "week" });
  const params = new URL(url).searchParams;
  expect(params.get("days")).toBe("30");
  expect(params.get("bucket")).toBe("week");
  expect(params.get("tz")).toBe("Europe/London");
  expect(params.get("branch")).toBe("main");
  expect(params.has("environment")).toBe(false);
});

test("getTests maps sort/search/pagination", async () => {
  let url = "";
  server.use(
    http.get("/api/v1/projects/42/analytics/tests", ({ request }) => {
      url = request.url;
      return HttpResponse.json([]);
    }),
  );
  await getTests(42, { days: 14, sort: "duration", search: "login", limit: 50, offset: 100 });
  const params = new URL(url).searchParams;
  expect(params.get("sort")).toBe("duration");
  expect(params.get("search")).toBe("login");
  expect(params.get("limit")).toBe("50");
  expect(params.get("offset")).toBe("100");
});

test("getHistory URL-encodes the test key", async () => {
  const key = "tests/test_login.py::TestLogin::test_ok";
  let hit = false;
  server.use(
    http.get(`/api/v1/projects/42/analytics/tests/${encodeURIComponent(key)}/history`, () => {
      hit = true;
      return HttpResponse.json({
        test_key: key, suite: "s", class_name: "c", name: "n",
        summary: { runs: 0, passed: 0, failed: 0, errored: 0, skipped: 0, pass_rate: null, avg_duration_ms: null },
        executions: [],
      });
    }),
  );
  await getHistory(42, key, { days: 30, limit: 100 });
  expect(hit).toBe(true);
});

test("getFlaky maps snake_case params", async () => {
  let url = "";
  server.use(
    http.get("/api/v1/projects/42/analytics/flaky", ({ request }) => {
      url = request.url;
      return HttpResponse.json([]);
    }),
  );
  await getFlaky(42, { windowDays: 14, minRuns: 5, minFlipRate: 0.3 });
  const params = new URL(url).searchParams;
  expect(params.get("window_days")).toBe("14");
  expect(params.get("min_runs")).toBe("5");
  expect(params.get("min_flip_rate")).toBe("0.3");
});

test("formatters", () => {
  expect(formatPassRate(0.9876)).toBe("98.8%");
  expect(formatPassRate(null)).toBe("—");
  expect(formatDuration(640)).toBe("640 ms");
  expect(formatDuration(2500)).toBe("2.5 s");
  expect(formatDuration(65000)).toBe("1m 05s");
  expect(formatDuration(null)).toBe("—");
});

// The collector's step summary (collector/tests/test_summary.py) pins the same table: one figure, one wording
test.each([
  [0, "0 ms"], [999, "999 ms"], [1000, "1.0 s"], [2250, "2.3 s"], [2350, "2.4 s"], [59940, "59.9 s"],
  [59950, "1m 00s"], [59999, "1m 00s"], [60000, "1m 00s"], [119400, "1m 59s"], [119499, "1m 59s"],
  [119500, "2m 00s"], [119999, "2m 00s"], [120000, "2m 00s"], [178500, "2m 59s"], [915000, "15m 15s"],
])("formatDuration(%i) carries rounded seconds into minutes: %s", (ms, text) => {
  expect(formatDuration(ms)).toBe(text);
});
