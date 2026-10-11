import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { mockOverviewData, personalState, renderOverview } from "../testing";

const bucket = (date: string, runs: number, pass_rate: number | null) => ({
  date, runs, total: runs * 10, passed: 0, failed: 0, errored: 0, skipped: 0, pass_rate, avg_run_duration_ms: 1, max_run_duration_ms: 1,
});
const WEEKS = { tz: "UTC", bucket: "week", days: [bucket("2026-09-21", 10, 0.833), bucket("2026-09-28", 12, 0.958)] };
const NO_RUNS = { tz: "UTC", bucket: "day", days: [bucket("2026-10-03", 0, null), bucket("2026-10-04", 0, null)] };

function trendsAsked(answer: object) {
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/analytics/trends", ({ request }) => {
    asked.push(new URL(request.url).searchParams);
    return HttpResponse.json(answer);
  }));
  return asked;
}

test("Pass-rate trend asks the Trends view's query for weekly buckets over 90 days and links to that view", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "wide" }) });
  const asked = trendsAsked(WEEKS);
  const { qc } = renderOverview();
  const heading = await screen.findByRole("heading", { name: "Pass-rate trend" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/trends?days=90&bucket=week");
  expect(await screen.findByRole("link", { name: "Trends" })).toHaveAttribute("href", "/projects/42/trends?days=90&bucket=week");
  expect(await screen.findByText(/Pass rate per week, from 83\.3% to 95\.8%/)).toBeInTheDocument();
  // The chart is named by the card's heading
  expect(screen.getByRole("figure", { name: "Pass-rate trend" })).toBeInTheDocument();
  expect(screen.getByText(/Latest week: 95\.8%/)).toBeInTheDocument();
  await waitFor(() => expect(asked.length).toBeGreaterThan(0));
  expect(asked[0].get("days")).toBe("90");
  expect(asked[0].get("bucket")).toBe("week");
  expect(asked[0].get("branch")).toBeNull();
  // The Trends view's own key: opening the title link reuses this answer
  expect(qc.getQueryData(["trends", 42, 90, "week", "", ""])).toEqual(WEEKS);
});

test("Pass-rate trend by day asks 30 days on its branch and links with that branch", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "normal", settings: { granularity: "day", branch: "main" } }) });
  const asked = trendsAsked({ ...WEEKS, bucket: "day" });
  renderOverview();
  const heading = await screen.findByRole("heading", { name: "Pass-rate trend" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/trends?days=30&bucket=day&branch=main");
  await waitFor(() => expect(asked.length).toBeGreaterThan(0));
  expect(asked[0].get("days")).toBe("30");
  expect(asked[0].get("branch")).toBe("main");
});

test("Pass-rate trend shows its error with Retry inside its own card", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "wide" }) });
  server.use(http.get("/api/v1/projects/42/analytics/trends", () => HttpResponse.json({ detail: "Trends are down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Pass-rate trend" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Trends are down");
  expect(within(card).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("Pass-rate trend on every branch without runs says so plainly, with no settings button", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "normal" }) });
  trendsAsked(NO_RUNS);
  renderOverview();
  expect(await screen.findByText("No runs in the last 90 days.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Change settings" })).not.toBeInTheDocument();
});

test("a branch without runs says so with its settings button, which opens that widget's settings", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "normal", settings: { granularity: "day", branch: "release" } }) });
  const asked = trendsAsked(NO_RUNS);
  renderOverview();
  expect(await screen.findByText("No runs on release in the last 30 days")).toBeInTheDocument();
  expect(asked[0].get("branch")).toBe("release");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Change settings" }));
  expect(await screen.findByText("Editing your Overview")).toBeInTheDocument();
  expect(screen.getByRole("form", { name: "Pass-rate trend settings" })).toBeInTheDocument();
});

test("Pass rate this week on a branch without runs says so instead of showing nothing", async () => {
  mockOverviewData({ layout: personalState({ id: "p", type: "pass_rate_week", size: "normal", settings: { branch: "release" } }) });
  trendsAsked({ tz: "UTC", bucket: "week", days: [] });
  renderOverview();
  expect(await screen.findByText("No runs on release in the last 14 days")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Change settings" })).toBeInTheDocument();
});
