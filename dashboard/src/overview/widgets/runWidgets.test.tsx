import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { FAILING_RUN, RUN, mockOverviewData, personalState, renderOverview } from "../testing";

function runsAsked(answer: (params: URLSearchParams) => object[]) {
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/runs", ({ request }) => {
    const params = new URL(request.url).searchParams;
    asked.push(params);
    return HttpResponse.json(answer(params));
  }));
  return asked;
}

const headingLink = async (name: string) => within(await screen.findByRole("heading", { name })).getByRole("link");

test("Recent runs shares the Runs view's first page for its branch and shows each verdict in words", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "recent_runs", size: "normal", settings: { branch: "develop", rows: 5 } }) });
  const asked = runsAsked((p) => (p.get("branch") === "develop" ? [{ ...FAILING_RUN, id: 70, branch: "develop", errored: 1 }] : [RUN]));
  const { qc } = renderOverview();
  expect(await screen.findByRole("link", { name: "Run #70" })).toHaveAttribute("href", "/projects/42/runs/70");
  expect(screen.getByText("Failed")).toBeInTheDocument();
  expect(screen.getByText(/develop · .* · 21 passed, 3 failed, 1 errored/)).toBeInTheDocument();
  const page = asked.find((p) => p.get("branch") === "develop")!;
  expect(page.get("limit")).toBe("50");
  expect(page.get("offset")).toBe("0");
  expect(await headingLink("Recent runs")).toHaveAttribute("href", "/projects/42/runs?branch=develop");
  expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute("href", "/projects/42/runs?branch=develop");
  // The Runs view's own key for its first page with only Branch applied
  expect(qc.getQueryData(["runs", 42, { branch: "develop" }, 0])).toBeDefined();
});

test("Recent runs on every branch names no branch in its request or its link", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "recent_runs", size: "normal" }) });
  const asked = runsAsked(() => [RUN]);
  renderOverview();
  expect(await screen.findByRole("link", { name: "Run #61" })).toBeInTheDocument();
  expect(asked.filter((p) => p.get("limit") === "50").every((p) => p.get("branch") === null)).toBe(true);
  expect(asked.some((p) => p.get("limit") === "50")).toBe(true);
  expect(await headingLink("Recent runs")).toHaveAttribute("href", "/projects/42/runs");
});

test("Recent runs on a branch without runs says so with its settings button", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "recent_runs", size: "normal", settings: { branch: "gone" } }) });
  runsAsked((p) => (p.get("branch") === "gone" ? [] : [RUN]));
  renderOverview();
  expect(await screen.findByText("No runs on gone")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Change settings Recent runs" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^Change settings/ }));
  expect(await screen.findByRole("form", { name: "Recent runs settings" })).toBeInTheDocument();
});

test("Recent runs shows its error with Retry, and Retry asks again", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "recent_runs", size: "normal" }) });
  let calls = 0;
  server.use(http.get("/api/v1/projects/42/runs", ({ request }) => {
    // Only the widget's own page (limit 50) fails; the page's latest-run lookup answers
    if (new URL(request.url).searchParams.get("limit") !== "50") return HttpResponse.json([RUN]);
    calls += 1;
    return calls === 1 ? HttpResponse.json({ detail: "Runs are down" }, { status: 500 }) : HttpResponse.json([RUN]);
  }));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Recent runs" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Runs are down");
  await userEvent.click(within(card).getByRole("button", { name: "Retry" }));
  expect(await within(card).findByRole("link", { name: "Run #61" })).toBeInTheDocument();
});

test("Branch health lists branches newest first with pass rate, runs and last run, and links to Branches", async () => {
  mockOverviewData({ layout: personalState({ id: "b", type: "branch_health", size: "normal" }) });
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/analytics/branches", ({ request }) => {
    asked.push(new URL(request.url).searchParams);
    return HttpResponse.json([
      { branch: "main", runs: 1200, total: 400, passed: 390, failed: 10, errored: 0, skipped: 0, pass_rate: 0.975, last_seen: "2026-10-01T10:00:00Z" },
      { branch: "develop", runs: 1, total: 10, passed: 5, failed: 5, errored: 0, skipped: 0, pass_rate: 0.5, last_seen: "2026-10-04T10:00:00Z" },
    ]);
  }));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Branch health" });
  await waitFor(() => expect(within(card).getAllByRole("listitem")).toHaveLength(2));
  const [first, second] = within(card).getAllByRole("listitem");
  expect(first).toHaveTextContent(/develop.*50\.0% pass rate · 1 run · last/);
  expect(second).toHaveTextContent(/main.*97\.5% pass rate · 1,200 runs · last/);
  expect(within(first).getByRole("link", { name: "develop" })).toHaveAttribute("href", "/projects/42/runs?branch=develop");
  expect(asked[0].get("days")).toBe("30");
  expect(await headingLink("Branch health")).toHaveAttribute("href", "/projects/42/branches");
  expect(within(card).getByRole("link", { name: "Branches" })).toHaveAttribute("href", "/projects/42/branches");
});

test("Branch health with no runs in 30 days says so", async () => {
  mockOverviewData({ layout: personalState({ id: "b", type: "branch_health", size: "normal" }) });
  server.use(http.get("/api/v1/projects/42/analytics/branches", () => HttpResponse.json([])));
  renderOverview();
  expect(await screen.findByText("No runs in the last 30 days.")).toBeInTheDocument();
});

test("Branch health shows its error with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "b", type: "branch_health", size: "normal" }) });
  server.use(http.get("/api/v1/projects/42/analytics/branches", () => HttpResponse.json({ detail: "Branches are down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Branch health" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Branches are down");
  expect(within(card).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
