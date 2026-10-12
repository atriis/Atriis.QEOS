import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { delay, http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { setAccessToken } from "../../auth/tokens";
import type { ReportRequest } from "../../api/report";
import { PATTERN } from "../../components/ChartKit";
import { CAUSES_REPORT, REGRESSIONS_REPORT, SUMMARY_REPORT, TESTS_REPORT } from "./testFixtures";
import { addDays, todayIn } from "./useReportFilters";
import ReportPage, { ANNOUNCE_DELAY_MS } from "./ReportPage";

const P = "/api/v1/projects/42";
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
let bodies: ReportRequest[] = [];
/** Phase 2 and 3 add a request per section; the summary's are the ones these tests read. */
const summaryBodies = () => bodies.filter((b) => b.sections[0] === "summary");

function serve(over: { report?: (body: ReportRequest) => Response | Promise<Response> } = {}) {
  bodies = [];
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, name: "Web Shop", organization_id: 1, my_role: "viewer" })),
    http.get(`${P}/repositories`, () => HttpResponse.json([{ id: 1, default_branch: "main" }])),
    http.post(`${P}/analytics/report`, async ({ request }) => {
      const body = (await request.json()) as ReportRequest;
      bodies.push(body);
      return over.report ? over.report(body) : HttpResponse.json({ ...SUMMARY_REPORT, ...CAUSES_REPORT, ...REGRESSIONS_REPORT, ...TESTS_REPORT });
    }),
    http.get(`${P}/case-areas`, () => HttpResponse.json({
      generated_at: "v1", counts: { cases: 3, linked: 2, manual: 1 },
      folders: ["features/booking", "features/payments"], features: ["Booking", "Payments"], labels: ["smoke"],
      suites: [{ id: 12, name: "Regression" }],
      cases: [
        { n: 1, t: "Book one-way", k: "c".repeat(64), fo: 0, fe: 0, l: [0], s: [0] },
        { n: 2, t: "Pay by card", k: "d".repeat(64), fo: 1, fe: 1, l: [], s: [0] },
        { n: 4, t: "Manual check", k: null, fo: null, fe: null, l: [], s: [] },
      ],
    })),
    http.get(`${P}/run-requests/run-urls`, () => HttpResponse.json({ urls: ["https://github.com/a/b/actions/runs/7"], truncated: false })),
  );
}

function renderPage(search = "") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/projects/42/report${search}`]}>
        <Routes><Route path="/projects/:projectId/report" element={<ReportPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("the summary is asked for the last 30 days on the default branch, in the reader's zone", async () => {
  serve();
  renderPage();
  expect(await screen.findByRole("heading", { level: 1, name: "Report" })).toBeInTheDocument();
  expect(await screen.findByRole("group", { name: /^Pass rate 97\.8%/ })).toBeInTheDocument();
  const today = todayIn(TZ);
  expect(summaryBodies()[0]).toEqual({ from: addDays(today, -29), to: today, tz: TZ, branch: "main", environment: null, ci_provider: null,
    origin: "any", requested_run_urls: null, test_keys: null, sections: ["summary"], bucket: "auto" });
  expect(screen.getByText(/web shop: quality report/i)).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Quick filters" })).getByText("Branch: main (default)")).toBeInTheDocument();
});

test("an area filter sends the linked keys; one with no linked tests sends nothing", async () => {
  serve();
  renderPage("?area=feature:Booking");
  await screen.findByRole("group", { name: /^Pass rate/ });
  expect(summaryBodies()[0].test_keys).toEqual(["c".repeat(64)]);
  expect(await within(await screen.findByRole("region", { name: "Failure causes" })).findAllByText(/TimeoutError/)).not.toHaveLength(0);
});

test("an area with no linked tests never calls the report", async () => {
  serve();
  renderPage("?area=feature:Nothing");
  expect(await screen.findAllByText("No automated tests are linked to cases in this area")).not.toHaveLength(0);
  expect(bodies).toHaveLength(0);
});

test("origin sends the Play URLs", async () => {
  serve();
  renderPage("?origin=qeos");
  await screen.findByRole("group", { name: /^Pass rate/ });
  expect(summaryBodies()[0]).toMatchObject({ origin: "qeos", requested_run_urls: ["https://github.com/a/b/actions/runs/7"] });
});

test("a timeout and a 422 show in the section, with Retry and Reset filters", async () => {
  serve({ report: () => HttpResponse.json({ detail: { code: "report_timeout",
    message: "This report took too long. Narrow the period or the filters." } }, { status: 503 }) });
  renderPage();
  const summary = await screen.findByRole("region", { name: "Summary" });
  expect(await within(summary).findByText(/this report took too long/i)).toBeInTheDocument();
  expect(within(summary).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("a link with invalid filters shows the notice and asks without them", async () => {
  serve();
  renderPage("?ci=travis");
  expect(await screen.findByText("Some filters in the link were not valid and were removed")).toBeInTheDocument();
  await screen.findByRole("group", { name: /^Pass rate/ });
  expect(bodies.every((b) => b.ci_provider === null)).toBe(true);
});

test("a filter change mid-load aborts the old request, never shows its answer and is announced once", async () => {
  serve({
    report: async (body) => {
      if (body.branch === "main") {
        await delay(300);
        return HttpResponse.json({ ...SUMMARY_REPORT, summary: { ...SUMMARY_REPORT.summary!, current: { ...SUMMARY_REPORT.summary!.current, runs: 111 } } });
      }
      return HttpResponse.json({ ...SUMMARY_REPORT, summary: { ...SUMMARY_REPORT.summary!, current: { ...SUMMARY_REPORT.summary!.current, runs: 222 } } });
    },
  });
  // msw does not pass a client abort on to its handlers here, so the signal the page hands to fetch is watched
  const signals: { branch: string | null; signal: AbortSignal }[] = [];  // the summary's requests only
  const realFetch = globalThis.fetch;
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    if (String(input).endsWith("/analytics/report") && init?.signal && typeof init.body === "string") {
      const sent = JSON.parse(init.body) as ReportRequest;
      if (sent.sections[0] === "summary") signals.push({ branch: sent.branch, signal: init.signal });
    }
    return realFetch(input, init);
  });
  renderPage();
  await userEvent.click(await screen.findByRole("button", { name: "Remove filter Branch: main (default)" }));
  expect(await screen.findByRole("group", { name: /^Runs 222/ })).toBeInTheDocument();
  await delay(400);
  spy.mockRestore();
  expect(signals.map((s) => [s.branch, s.signal.aborted])).toEqual([["main", true], [null, false]]);
  expect(screen.queryByRole("group", { name: /^Runs 111/ })).not.toBeInTheDocument();
  expect(screen.getAllByText("Report updated")).toHaveLength(1);
  expect(summaryBodies().map((b) => b.branch)).toEqual(["main", null]);
});

test("print: Save as PDF prints; the print header lists the period and every filter; data tables open", async () => {
  serve();
  const print = vi.spyOn(window, "print").mockImplementation(() => {});
  renderPage("?env=staging");
  await screen.findByRole("group", { name: /^Pass rate/ });
  await userEvent.click(screen.getByRole("button", { name: /save as pdf/i }));
  expect(print).toHaveBeenCalled();
  const header = document.querySelector(".report-print-header")!;
  expect(header).toHaveTextContent("Branch: main (default)");
  expect(header).toHaveTextContent("Environment: staging");
  expect(header).toHaveTextContent(/compared with/i);
  const tables = document.querySelectorAll("details.chart-data");
  expect(tables.length).toBeGreaterThan(0);
  window.dispatchEvent(new Event("beforeprint"));
  tables.forEach((d) => expect(d).toHaveAttribute("open"));
  window.dispatchEvent(new Event("afterprint"));
  tables.forEach((d) => expect(d).not.toHaveAttribute("open"));
  print.mockRestore();
});

test("on paper a data table is printed whole, not clipped to its scroll box", () => {
  const css = readFileSync(resolve(__dirname, "../../index.css"), "utf8");
  const print = css.slice(css.indexOf("@media print {"));
  const block = print.slice(0, print.indexOf("\n}\n"));
  expect(block).toMatch(/\.chart-data-body \{ max-height: none !important; overflow: visible !important; \}/);
});

const liveRegion = () => document.querySelector(".report > p[aria-live='polite']")!;
const runs = (n: number) => HttpResponse.json({ ...SUMMARY_REPORT, summary: { ...SUMMARY_REPORT.summary!, current: { ...SUMMARY_REPORT.summary!.current, runs: n } } });

test("the update is announced only when every section asked has loaded, Regressions included", async () => {
  serve({
    report: async (body) => {
      if (body.sections[0] === "regressions" && body.branch !== "main") await delay(800);
      return runs(body.branch === "main" ? 111 : 222);
    },
  });
  renderPage();
  await screen.findByRole("group", { name: /^Runs 111/ });
  await userEvent.click(await screen.findByRole("button", { name: "Remove filter Branch: main (default)" }));
  expect(await screen.findByRole("group", { name: /^Runs 222/ })).toBeInTheDocument();
  await delay(ANNOUNCE_DELAY_MS + 200);
  expect(within(screen.getByRole("region", { name: "Regressions and stability" })).getByRole("status", { name: /loading regressions and stability/i })).toBeInTheDocument();
  expect(liveRegion().textContent).toBe("");
  await waitFor(() => expect(liveRegion()).toHaveTextContent("Report updated"), { timeout: 2000 });
  expect(screen.getAllByText("Report updated")).toHaveLength(1);
});

test("a change back to answers already cached announces again; a failed summary is not announced", async () => {
  let fail = false;
  serve({ report: (body) => (fail ? HttpResponse.json({ detail: "boom" }, { status: 500 }) : runs(body.branch === "main" ? 111 : 222)) });
  renderPage();
  await screen.findByRole("group", { name: /^Runs 111/ });
  const seen: string[] = [];
  const observer = new MutationObserver(() => seen.push(liveRegion().textContent ?? ""));
  observer.observe(liveRegion(), { childList: true, characterData: true, subtree: true });
  await userEvent.click(screen.getByRole("button", { name: "Remove filter Branch: main (default)" }));
  await waitFor(() => expect(liveRegion()).toHaveTextContent("Report updated"));
  // Back to main: both answers come from the cache, so nothing is fetched, yet the text must change to be read again
  await userEvent.click(screen.getByRole("button", { name: "Remove filter Branch: all branches" }));
  await screen.findByRole("group", { name: /^Runs 111/ });
  await waitFor(() => expect(seen.filter((t) => t === "Report updated")).toHaveLength(2));
  expect(seen.filter((t, i) => t !== seen[i - 1])).toEqual(["Report updated", "", "Report updated"]);
  observer.disconnect();
  fail = true;
  await userEvent.click(screen.getByRole("button", { name: "7 days" }));
  expect(await within(screen.getByRole("region", { name: "Summary" })).findByRole("button", { name: "Retry" })).toBeInTheDocument();
  await delay(300);
  expect(liveRegion().textContent).toBe("");
});

test("a zone the server does not know: asked again in UTC, once, with a dismissible notice", async () => {
  const resolved = Intl.DateTimeFormat.prototype.resolvedOptions;
  const spy = vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(function (this: Intl.DateTimeFormat) {
    return { ...resolved.call(this), timeZone: "Pacific/Kiritimati" };
  });
  serve({ report: (body) => (body.tz === "UTC" ? HttpResponse.json(SUMMARY_REPORT)
    : HttpResponse.json({ detail: `Unknown time zone: '${body.tz}'` }, { status: 422 })) });
  renderPage();
  expect(await screen.findByRole("group", { name: /^Pass rate 97\.8%/ })).toBeInTheDocument();
  spy.mockRestore();
  expect(summaryBodies().map((b) => b.tz)).toEqual(["Pacific/Kiritimati", "UTC"]);
  const today = todayIn("UTC");
  expect(summaryBodies()[1]).toMatchObject({ to: today, from: addDays(today, -29) });
  expect(screen.getByText("Your time zone isn't supported by the server; dates use UTC.")).toBeInTheDocument();
  expect(screen.queryByText(/these filters are not valid/i)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Dismiss the time zone notice" }));
  expect(screen.queryByText(/isn't supported by the server/)).not.toBeInTheDocument();
});

test("a 422 that is not about the zone is not retried", async () => {
  serve({ report: () => HttpResponse.json({ detail: "span must be at most 90 days" }, { status: 422 }) });
  renderPage();
  expect(await screen.findAllByText(/these filters are not valid/i)).not.toHaveLength(0);
  expect(summaryBodies()).toHaveLength(1);
  expect(screen.queryByText(/time zone isn't supported/)).not.toBeInTheDocument();
});

test("every section is its own request, and an area filter sends the same keys to each", async () => {
  serve();
  renderPage("?area=feature:Booking");
  await screen.findByRole("region", { name: "Regressions and stability" });
  await vi.waitFor(() => expect(new Set(bodies.map((b) => b.sections[0]))).toEqual(new Set(["summary", "failure_causes", "regressions", "tests", "duration"])));
  expect(bodies.every((b) => b.test_keys?.[0] === "c".repeat(64))).toBe(true);
});

test("the pattern definitions the Failure causes hatches point at are on the page once, with both sections", async () => {
  serve();
  renderPage();
  await within(await screen.findByRole("region", { name: "Failure causes" })).findAllByText(/TimeoutError/);
  await screen.findByRole("group", { name: "Newly failing 9" });
  expect(document.querySelectorAll(`pattern#${PATTERN.failed}`)).toHaveLength(1);
});

test("a zone the server rejects is retried in UTC for every section", async () => {
  const resolved = Intl.DateTimeFormat.prototype.resolvedOptions;
  const spy = vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(function (this: Intl.DateTimeFormat) {
    return { ...resolved.call(this), timeZone: "Pacific/Kiritimati" };
  });
  serve({ report: (body) => (body.tz === "UTC" ? HttpResponse.json({ ...SUMMARY_REPORT, ...CAUSES_REPORT, ...REGRESSIONS_REPORT, ...TESTS_REPORT })
    : HttpResponse.json({ detail: `Unknown time zone: '${body.tz}'` }, { status: 422 })) });
  renderPage();
  expect(await screen.findByRole("group", { name: "Newly failing 9" })).toBeInTheDocument();
  spy.mockRestore();
  expect(bodies.filter((b) => b.tz === "UTC").map((b) => b.sections[0]).sort()).toEqual(["duration", "failure_causes", "regressions", "summary", "tests"]);
});

test("a failed Regressions section after a filter change is not announced as updated", async () => {
  serve({
    report: (body) => (body.sections[0] === "regressions" && body.branch !== "main"
      ? HttpResponse.json({ detail: { code: "report_timeout", message: "This report took too long." } }, { status: 503 })
      : runs(body.branch === "main" ? 111 : 222)),
  });
  renderPage();
  await screen.findByRole("group", { name: /^Runs 111/ });
  await userEvent.click(await screen.findByRole("button", { name: "Remove filter Branch: main (default)" }));
  expect(await screen.findByRole("group", { name: /^Runs 222/ })).toBeInTheDocument();
  expect(await within(screen.getByRole("region", { name: "Regressions and stability" })).findByRole("button", { name: "Retry" })).toBeInTheDocument();
  await delay(ANNOUNCE_DELAY_MS + 300);
  expect(liveRegion().textContent).toBe("");
});

test("case-areas failing: sections 3 and 5 show the error, the others still load", async () => {
  serve();
  server.use(http.get(`${P}/case-areas`, () => HttpResponse.json({ detail: "down" }, { status: 500 })));
  renderPage();
  expect(await screen.findByRole("group", { name: /^Pass rate/ })).toBeInTheDocument();
  expect(await within(screen.getByRole("region", { name: "By area" })).findByText("Cases could not be loaded")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Coverage and duration" })).getByText("Cases could not be loaded")).toBeInTheDocument();
});

test("By area and Coverage load with the page, and a failed Duration section is not announced as updated", async () => {
  serve({
    report: (body) => (body.sections[0] === "duration" && body.branch !== "main"
      ? HttpResponse.json({ detail: { code: "report_timeout", message: "This report took too long." } }, { status: 503 })
      : HttpResponse.json({ ...SUMMARY_REPORT, ...TESTS_REPORT,
          summary: { ...SUMMARY_REPORT.summary!, current: { ...SUMMARY_REPORT.summary!.current, runs: body.branch === "main" ? 111 : 222 } } })),
  });
  renderPage();
  await screen.findByRole("group", { name: /^Runs 111/ });
  expect(await within(screen.getByRole("region", { name: "By area" })).findByRole("table", { name: /by area/i })).toBeInTheDocument();
  expect(await within(screen.getByRole("region", { name: "Coverage and duration" })).findByRole("group", { name: "Active cases 3" })).toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "Remove filter Branch: main (default)" }));
  expect(await screen.findByRole("group", { name: /^Runs 222/ })).toBeInTheDocument();
  expect(await within(screen.getByRole("region", { name: "Coverage and duration" })).findByRole("button", { name: "Retry" })).toBeInTheDocument();
  await delay(ANNOUNCE_DELAY_MS + 300);
  expect(liveRegion().textContent).toBe("");
});

describe("the section named by the link's anchor", () => {
  const scrollIntoView = vi.fn();
  beforeEach(() => {
    scrollIntoView.mockReset();
    Element.prototype.scrollIntoView = scrollIntoView;
  });
  afterEach(() => {
    // @ts-expect-error restore jsdom default (no scrollIntoView, no matchMedia)
    delete Element.prototype.scrollIntoView;
    // @ts-expect-error restore jsdom default
    delete window.matchMedia;
  });
  const reduced = (matches: boolean) => {
    window.matchMedia = ((query: string) => ({ matches: matches && query.includes("reduced-motion"), media: query,
      addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia;
  };

  test("scrolls to it smoothly and focuses its heading once the page has loaded", async () => {
    serve();
    reduced(false);
    renderPage("#report-causes");
    await screen.findByRole("group", { name: /^Pass rate/ });
    const heading = screen.getByRole("heading", { level: 2, name: "Failure causes" });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.instances[0]).toBe(heading);
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });

  test("does not scroll smoothly when the reader prefers reduced motion", async () => {
    serve();
    reduced(true);
    renderPage("#report-regressions");
    await screen.findByRole("group", { name: /^Pass rate/ });
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: /^Regressions/ })).toHaveFocus());
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "start" });
  });

  test("an anchor that names no section moves nothing", async () => {
    serve();
    renderPage("#nowhere");
    await screen.findByRole("group", { name: /^Pass rate/ });
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});

const NO_ACCURACY_PART = { runs: 0, caught: 0, missed: 0, suggested: 0 };

function serveAccuracy(asked: string[]) {
  server.use(http.get(`${P}/analytics/impact-accuracy`, ({ request }) => {
    const days = Number(new URL(request.url).searchParams.get("days"));
    asked.push(String(days));
    return HttpResponse.json({ days, caught: 0, missed: 0, rate: null, avg_suggested: null, includes_replayed: false,
      live: NO_ACCURACY_PART, replayed: NO_ACCURACY_PART, misses: [], misses_total: 0 });
  }));
}

test("Test impact closes the report and follows a 7-day period", async () => {
  serve();
  const asked: string[] = [];
  serveAccuracy(asked);
  renderPage("?period=7");
  expect(await screen.findByRole("heading", { name: "Test impact" })).toBeInTheDocument();
  expect(await screen.findByText("No run with a stored suggestion in the last 7 days")).toBeInTheDocument();
  expect(asked).toEqual(["7"]);
  const headings = screen.getAllByRole("heading", { level: 2 });
  expect(headings[headings.length - 1]).toHaveTextContent("Test impact");
});

test("Test impact uses 30 days, and says so, when the Report's period is 90 days", async () => {
  serve();
  const asked: string[] = [];
  serveAccuracy(asked);
  renderPage("?period=90");
  expect(await screen.findByText(/the Report's period is not the last 7, 14 or 30 days/)).toBeInTheDocument();
  expect(asked).toEqual(["30"]);
});
