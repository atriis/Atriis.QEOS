import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { addDays, todayIn } from "../../pages/report/useReportFilters";
import { CAUSES_REPORT, REGRESSIONS_REPORT, emptyReport } from "../../pages/report/testFixtures";
import { mockOverviewData, personalState, renderOverview } from "../testing";

type ReportBody = { from: string; to: string; branch: string | null; sections: string[] };

function reportAsked(answer: (sections: string[]) => object) {
  const bodies: ReportBody[] = [];
  server.use(http.post("/api/v1/projects/42/analytics/report", async ({ request }) => {
    const body = (await request.json()) as ReportBody;
    bodies.push(body);
    return HttpResponse.json(answer(body.sections));
  }));
  return bodies;
}

const headingLink = async (name: string) => within(await screen.findByRole("heading", { name })).getByRole("link");

test("Failure causes asks only for its section over the last 30 days on every branch", async () => {
  mockOverviewData({ layout: personalState({ id: "c", type: "failure_causes", size: "normal" }) });
  const bodies = reportAsked(() => CAUSES_REPORT);
  const { qc } = renderOverview();
  expect(await screen.findByText(/2124 failures from 37 causes/)).toBeInTheDocument();
  expect(screen.getByText(/1 new · 2 recurring among the top 3 · 1 resolved/)).toBeInTheDocument();
  expect(screen.getByText("TimeoutError: locator('#pay-button') after 30000 ms")).toBeInTheDocument();
  expect(screen.getByText("New")).toBeInTheDocument();
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["failure_causes"]);
  expect(bodies[0].branch).toBeNull();
  expect(bodies[0].from).toBe(addDays(bodies[0].to, -29));
  expect(await headingLink("Failure causes")).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-causes");
  // The Report page's own key for the same period on every branch, so either one reuses the other's answer
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const filters = { from: bodies[0].from, to: bodies[0].to, tz, branch: null, environment: "", ci: "", origin: "any", area: null, suite: null };
  expect(qc.getQueryData(["report", 42, "failure_causes", filters, null])).toEqual(CAUSES_REPORT);
});

test("Regressions and flips counts what started failing, what was fixed and the flips, and lists the newly failing", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "regressions", size: "normal", settings: { period: 7, branch: "main", rows: 5 } }) });
  const bodies = reportAsked(() => REGRESSIONS_REPORT);
  renderOverview();
  expect(await screen.findByText("9 newly failing · 5 fixed · 51 flips")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "pays" })).toHaveAttribute("href", `/projects/42/tests/${"pays".padEnd(64, "0")}`);
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["regressions"]);
  expect(bodies[0].branch).toBe("main");
  expect(bodies[0].from).toBe(addDays(bodies[0].to, -6));
  expect(await headingLink("Regressions and flips")).toHaveAttribute("href", "/projects/42/report?period=7&branch=main#report-regressions");
});

test("a 14-day report widget links to the Report with that range, as the Report has no 14-day preset", async () => {
  mockOverviewData({ layout: personalState({ id: "c", type: "failure_causes", size: "normal", settings: { period: 14 } }) });
  reportAsked(() => CAUSES_REPORT);
  renderOverview();
  const today = todayIn(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  expect(await headingLink("Failure causes"))
    .toHaveAttribute("href", `/projects/42/report?from=${addDays(today, -13)}&to=${today}&branch=*#report-causes`);
});

test("two identical report widgets cost one request", async () => {
  mockOverviewData({ layout: personalState(
    { id: "a", type: "failure_causes", size: "normal" },
    { id: "b", type: "failure_causes", size: "normal" },
  ) });
  const bodies = reportAsked(() => CAUSES_REPORT);
  renderOverview();
  expect(await screen.findAllByText(/2124 failures from 37 causes/)).toHaveLength(2);
  expect(bodies).toHaveLength(1);
});

test("a report widget on a branch without runs says so; a failing one shows its error with Retry", async () => {
  mockOverviewData({ layout: personalState(
    { id: "c", type: "failure_causes", size: "normal", settings: { period: 14, branch: "release" } },
    { id: "r", type: "regressions", size: "normal" },
  ) });
  server.use(http.post("/api/v1/projects/42/analytics/report", async ({ request }) => {
    const body = (await request.json()) as ReportBody;
    return body.sections[0] === "failure_causes"
      ? HttpResponse.json(emptyReport())
      : HttpResponse.json({ detail: "Report is down" }, { status: 500 });
  }));
  renderOverview();
  expect(await screen.findByText("No runs on release in the last 14 days")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Change settings" })).toBeInTheDocument();
  const regressions = screen.getByRole("region", { name: "Regressions and flips" });
  expect(await within(regressions).findByRole("alert")).toHaveTextContent("Report is down");
  expect(within(regressions).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
