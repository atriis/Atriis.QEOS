import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { addDays, todayIn } from "../../pages/report/useReportFilters";
import { CAUSES_REPORT, REGRESSIONS_REPORT, SUMMARY_REPORT, TESTS_REPORT, emptyReport } from "../../pages/report/testFixtures";
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
  expect(await screen.findByText(/2,124 failures from 37 causes/)).toBeInTheDocument();
  expect(screen.getByText(/1 new · 2 recurring among the top 3 · 1 resolved/)).toBeInTheDocument();
  expect(screen.getByText("TimeoutError: locator('#pay-button') after 30000 ms")).toBeInTheDocument();
  expect(screen.getByText("New")).toBeInTheDocument();
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["failure_causes"]);
  expect(bodies[0].branch).toBeNull();
  expect(bodies[0].from).toBe(addDays(bodies[0].to, -29));
  expect(await headingLink("Failure causes")).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-causes");
  // The card foot opens the same section
  expect(screen.getByRole("link", { name: "Report" })).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-causes");
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
  expect(screen.getByRole("link", { name: "Report" })).toHaveAttribute("href", "/projects/42/report?period=7&branch=main#report-regressions");
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
  expect(await screen.findAllByText(/2,124 failures from 37 causes/)).toHaveLength(2);
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

const key = (n: number) => n.toString(16).padStart(64, "0");
const AREAS_WIRE = {
  generated_at: "v1", counts: { cases: 4, linked: 3, manual: 1 },
  folders: ["features/booking", "features/payments"], features: ["Booking", "Payments"], labels: ["smoke"],
  suites: [{ id: 12, name: "Regression" }],
  cases: [
    { n: 1, t: "Book one-way", k: key(1), fo: 0, fe: 0, l: [0], s: [0] },
    { n: 2, t: "Pay by card", k: key(2), fo: 1, fe: 1, l: [], s: [0] },
    { n: 3, t: "Refund", k: key(3), fo: 1, fe: 1, l: [], s: [] },
    { n: 4, t: "Manual check", k: null, fo: null, fe: null, l: [], s: [] },
  ],
};

test("Slowest tests reads the summary's slowest tests and links to the report", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "slowest_tests", size: "normal" }) });
  const bodies = reportAsked(() => SUMMARY_REPORT);
  renderOverview();
  expect(await screen.findByRole("link", { name: "slow one" })).toHaveAttribute("href", `/projects/42/tests/${"b".repeat(64)}`);
  expect(screen.getByText("1m 21s on average · 30 runs")).toBeInTheDocument();
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["summary"]);
  expect(bodies[0].branch).toBeNull();
  expect(await headingLink("Slowest tests")).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-summary");
  expect(screen.getByRole("link", { name: "Report" })).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-summary");
});

test("Slowest tests on a branch without runs says so", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "slowest_tests", size: "normal", settings: { period: 7, branch: "release" } }) });
  reportAsked(() => emptyReport());
  renderOverview();
  expect(await screen.findByText("No runs on release in the last 7 days")).toBeInTheDocument();
});

test("Coverage joins the cases with the tests section like the Report does, across every branch", async () => {
  mockOverviewData({ layout: personalState({ id: "v", type: "coverage", size: "normal" }) });
  const bodies = reportAsked(() => TESTS_REPORT);
  server.use(http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json(AREAS_WIRE)));
  const { qc } = renderOverview();
  expect(await screen.findByText("Automated, not run in 30 days")).toBeInTheDocument();
  expect(screen.getByText("Active cases").nextElementSibling).toHaveTextContent("4");
  expect(screen.getByText("Linked (automated)").nextElementSibling).toHaveTextContent("3");
  expect(screen.getByText("Manual").nextElementSibling).toHaveTextContent("1");
  expect(screen.getByText("Automated, not run in 30 days").nextElementSibling).toHaveTextContent("1");
  expect(screen.getByText("Tests without a case").nextElementSibling).toHaveTextContent("1");
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["tests"]);
  expect(bodies[0].branch).toBeNull();
  expect(await headingLink("Coverage")).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-coverage");
  expect(screen.getByRole("link", { name: "Report" })).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-coverage");
  // The Report's case-areas query, shared with it
  expect(qc.getQueryData(["case-areas", 42])).toBeDefined();
});

test("Coverage says when the cases cannot be loaded, with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "v", type: "coverage", size: "normal" }) });
  reportAsked(() => TESTS_REPORT);
  server.use(http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json({ detail: "down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Coverage" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Cases could not be loaded");
  expect(within(card).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("Slowest tests with no tests in the period says so", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "slowest_tests", size: "normal" }) });
  reportAsked(() => ({ ...SUMMARY_REPORT, summary: { ...SUMMARY_REPORT.summary!, slowest: [] } }));
  renderOverview();
  expect(await screen.findByText("No tests ran in the last 30 days.")).toBeInTheDocument();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

test("Coverage with no tests in the period counts every linked case as not run and no test without a case", async () => {
  mockOverviewData({ layout: personalState({ id: "v", type: "coverage", size: "normal", settings: { period: 7 } }) });
  reportAsked(() => ({ ...TESTS_REPORT, tests: { ...TESTS_REPORT.tests!, rows: [] } }));
  server.use(http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json(AREAS_WIRE)));
  renderOverview();
  expect(await screen.findByText("Automated, not run in 7 days")).toBeInTheDocument();
  expect(screen.getByText("Automated, not run in 7 days").nextElementSibling).toHaveTextContent("3");
  expect(screen.getByText("Tests without a case").nextElementSibling).toHaveTextContent("0");
});

test("Coverage cut at 50,000 tests hides the counts that would read as fact and says why", async () => {
  mockOverviewData({ layout: personalState({ id: "v", type: "coverage", size: "normal" }) });
  reportAsked(() => ({ ...TESTS_REPORT, tests: { ...TESTS_REPORT.tests!, truncated: true } }));
  server.use(http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json(AREAS_WIRE)));
  renderOverview();
  expect(await screen.findByText(/The test list was cut at 50,000 tests/)).toBeInTheDocument();
  expect(screen.getByText("Active cases").nextElementSibling).toHaveTextContent("4");
  expect(screen.queryByText(/Automated, not run/)).not.toBeInTheDocument();
  expect(screen.queryByText("Tests without a case")).not.toBeInTheDocument();
});
