import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { getImpactAccuracy, getRunImpact, scoreChange, type ImpactAccuracy } from "./impact";

const NO_ACCURACY: ImpactAccuracy = { days: 14, caught: 0, missed: 0, rate: null, avg_suggested: null, includes_replayed: false,
  live: { runs: 0, caught: 0, missed: 0, suggested: 0 }, replayed: { runs: 0, caught: 0, missed: 0, suggested: 0 },
  misses: [], misses_total: 0 };

test("a run's impact, a change scored, and the accuracy over 7, 14 or 30 days", async () => {
  setAccessToken("acc");
  const asked: string[] = [];
  let body: unknown;
  server.use(
    http.get("/api/v1/projects/42/runs/61/impact", ({ request }) => {
      asked.push(new URL(request.url).pathname);
      return HttpResponse.json({ run_id: 61, state: "no_change_data", changed_paths: [], replayed: false, scored_at: null,
        suggestion: null, outcome: null });
    }),
    http.post("/api/v1/projects/42/analytics/impact", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ state: "ok", model_version: "stats-v1", history_runs: 30, needed_runs: 20,
        statistical_total: 0, tests: [] });
    }),
    http.get("/api/v1/projects/42/analytics/impact-accuracy", ({ request }) => {
      asked.push(new URL(request.url).search);
      return HttpResponse.json(NO_ACCURACY);
    }),
  );
  expect((await getRunImpact(42, 61)).state).toBe("no_change_data");
  expect((await scoreChange(42, ["src/a.py"], "main")).model_version).toBe("stats-v1");
  expect(body).toEqual({ changed_paths: ["src/a.py"], branch: "main" });
  const accuracy = await getImpactAccuracy(42, 14);
  expect(accuracy.days).toBe(14);
  expect(accuracy.avg_suggested).toBeNull();
  expect(asked).toEqual(["/api/v1/projects/42/runs/61/impact", "?days=14"]);
});

test("a scoring timeout carries its message", async () => {
  setAccessToken("acc");
  server.use(http.post("/api/v1/projects/42/analytics/impact", () => HttpResponse.json(
    { detail: { code: "impact_timeout", message: "Scoring took too long" } }, { status: 503 })));
  await expect(scoreChange(42, ["src/a.py"], null)).rejects.toMatchObject({ status: 503, detail: "Scoring took too long" });
});
