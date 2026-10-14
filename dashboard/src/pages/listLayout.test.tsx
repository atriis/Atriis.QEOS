import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { http, HttpResponse } from "msw";
import type { ReactElement } from "react";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CasesPage from "./CasesPage";
import RunsPage from "./RunsPage";
import TestsPage from "./TestsPage";
import FlakyPage from "./FlakyPage";
import RequestedRunsPage from "./RequestedRunsPage";

// Layout phase 2: the chips row above each list, and the dense table's number columns and status pills

const P = "/api/v1/projects/42";

function Location() {
  const { search } = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="where">{search}</output>
      <button type="button" data-testid="back" onClick={() => navigate(-1)}>back</button>
    </>
  );
}

function renderAt(path: string, url: string, page: ReactElement) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path={path} element={<>{page}<Location /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const where = () => new URLSearchParams(screen.getByTestId("where").textContent ?? "");
const chips = () => screen.getByRole("group", { name: "Quick filters" });
const chip = (name: string) => within(chips()).getByRole("button", { name });

// --- Cases -----------------------------------------------------------------------------------

const kase = (number: number, extra: object = {}) => ({
  number, key: `TC-${number}`, title: `Case ${number}`, description: null, steps: [], labels: [], priority: "medium",
  status: "draft", automated_test_key: null, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z",
  updated_by: null, updated_at: null, suites: [], source_path: null, gherkin: null, feature_name: null, ...extra,
});

function mockCases(items = [kase(1), kase(2, { status: "ready", priority: "high" })]) {
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "member" })),
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([{ label: "flights", count: 3 }])),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: items.length, items })),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ tests: {} })),
    http.get(`${P}/analytics/latest-keys`, () => HttpResponse.json({ keys: [] })),
    http.post(`${P}/cases/search`, () => HttpResponse.json({ total: items.length, items })),
  );
}
const renderCases = (url = "/projects/42/cases?group=scenario") => renderAt("/projects/:projectId/cases", url, <CasesPage />);

describe("Cases chips", () => {
  beforeEach(() => mockCases());

  test("the Cases quick chips are toggle buttons mapped to existing URL filters", async () => {
    renderCases();
    await screen.findByText("Case 1");
    for (const name of ["Failing", "Never ran", "Linked", "Manual", "Draft", "Ready"]) {
      expect(chip(name)).toHaveAttribute("aria-pressed", "false");
    }
    await userEvent.click(chip("Failing"));
    expect(where().get("result")).toBe("failed");
    expect(chip("Failing")).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(chip("Linked"));
    expect(where().get("linked")).toBe("true");
    expect(where().get("result")).toBe("failed");
  });

  test("Draft and Ready are one choice; pressing the active chip clears it", async () => {
    renderCases("/projects/42/cases?group=scenario&status=draft");
    await screen.findByText("Case 1");
    expect(chip("Draft")).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(chip("Ready"));
    expect(where().get("status")).toBe("ready");
    expect(chip("Draft")).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(chip("Ready"));
    expect(where().has("status")).toBe(false);
  });

  test("a chip resets paging and Back undoes it", async () => {
    renderCases("/projects/42/cases?group=scenario&offset=50");
    await screen.findByText("Case 1");
    await userEvent.click(chip("Never ran"));
    expect(where().get("result")).toBe("never");
    expect(where().has("offset")).toBe(false);
    await userEvent.click(screen.getByTestId("back"));
    await waitFor(() => expect(where().get("offset")).toBe("50"));
    expect(chip("Never ran")).toHaveAttribute("aria-pressed", "false");
  });

  test("other applied filters are removable chips, and Clear all drops them all", async () => {
    renderCases("/projects/42/cases?group=scenario&label=flights&folder=features/hotels&q=legroom&status=ready");
    await screen.findByText("Case 1");
    expect(within(chips()).getByText("Label: flights")).toBeInTheDocument();
    expect(within(chips()).getByText("Folder: features / hotels")).toBeInTheDocument();
    await userEvent.click(within(chips()).getByRole("button", { name: "Remove filter Search: legroom" }));
    expect(where().has("q")).toBe(false);
    expect(where().get("label")).toBe("flights");
    await userEvent.click(within(chips()).getByRole("button", { name: "Clear all" }));
    // The grouping is a view, not a filter: it stays
    expect(where().toString()).toBe("group=scenario");
    expect(within(chips()).queryByRole("button", { name: "Clear all" })).not.toBeInTheDocument();
  });

  test("+ Filter opens the filters disclosure and moves focus to its first control", async () => {
    window.matchMedia = ((query: string) => ({
      matches: true, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    try {
      renderCases();
      await screen.findByText("Case 1");
      const details = screen.getByText(/^Filters/, { selector: "summary" }).closest("details")!;
      expect(details).not.toHaveAttribute("open");
      await userEvent.click(chip("+ Filter"));
      expect(details).toHaveAttribute("open");
      expect(within(details).getByRole("combobox", { name: "Label" })).toHaveFocus();
    } finally {
      // @ts-expect-error restore jsdom default (no matchMedia)
      delete window.matchMedia;
    }
  });

  test("status is a pill; Priority is a word, so it stays left-aligned", async () => {
    renderCases();
    const table = (await screen.findByText("Case 1")).closest("table")!;
    expect(within(table).getByText("Draft").closest(".pill")).toHaveClass("pill-neutral");
    expect(within(table).getByText("Ready").closest(".pill")).toHaveClass("pill-ready");
    expect(within(table).getByRole("columnheader", { name: "Priority" })).not.toHaveClass("num");
    expect(within(table).getAllByRole("row")[2].querySelector("td.num")).toBeNull();
  });
});

// --- Runs ------------------------------------------------------------------------------------

const run = (id: number, extra: object = {}) => ({
  id, project_id: 42, ci_provider: "github_actions", ci_run_url: null, commit_sha: "abcdef1234567890",
  branch: "main", environment: "ci", agent_version: "0.1.0", started_at: "2026-10-01T12:00:00Z",
  finished_at: "2026-10-01T12:04:00Z", duration_ms: 240000, total: 24, passed: 20, failed: 3, skipped: 0, errored: 1,
  created_at: "2026-10-01T12:05:00Z", ...extra,
});

describe("Runs chips and table", () => {
  beforeEach(() => {
    server.use(http.get(`${P}/runs`, () => HttpResponse.json([run(61), run(62, { failed: 0, errored: 0 })])));
  });
  const renderRuns = (url = "/projects/42/runs") => renderAt("/projects/:projectId/runs", url, <RunsPage />);

  test("Failed, Passed and main are quick chips over the status and branch filters", async () => {
    renderRuns();
    await screen.findByRole("link", { name: "#61" });
    await userEvent.click(chip("Failed"));
    expect(where().get("status")).toBe("failing");
    await userEvent.click(chip("Passed"));
    expect(where().get("status")).toBe("passing");
    await userEvent.click(chip("main"));
    expect(where().get("branch")).toBe("main");
  });

  test("advanced filters show as removable chips", async () => {
    renderRuns("/projects/42/runs?environment=staging&branch=release");
    await screen.findByRole("link", { name: "#61" });
    await userEvent.click(within(chips()).getByRole("button", { name: "Remove filter Environment: staging" }));
    expect(where().has("environment")).toBe(false);
    expect(within(chips()).getByText("Branch: release")).toBeInTheDocument();
  });

  test("counts and duration are right-aligned number columns; the verdict is a pill", async () => {
    renderRuns();
    const table = (await screen.findByRole("link", { name: "#61" })).closest("table")!;
    for (const name of ["Passed", "Failed", "Errored", "Skipped", "Duration"]) {
      expect(within(table).getByRole("columnheader", { name: new RegExp(`^${name}`) })).toHaveClass("num");
    }
    const first = within(table).getAllByRole("row")[1];
    expect(within(first).getByText("20").closest("td")).toHaveClass("num");
    expect(within(first).getAllByText("Failed").some((el) => el.closest(".pill-failed"))).toBe(true);
  });
});

// --- Tests and Flaky -------------------------------------------------------------------------

describe("Tests and Flaky", () => {
  test("Tests: the search shows as a removable chip; rate, counts and duration are number columns", async () => {
    server.use(http.get(`${P}/analytics/tests`, () => HttpResponse.json([{
      test_key: "k1", suite: "auth", class_name: "TestLogin", name: "test_ok", runs: 10, passed: 9, failed: 1, errored: 0,
      skipped: 0, pass_rate: 0.9, avg_duration_ms: 420, last_status: "failed", last_seen: "2026-09-30T10:00:00Z",
    }])));
    renderAt("/projects/:projectId/tests", "/projects/42/tests?search=login", <TestsPage />);
    const table = (await screen.findByRole("link", { name: "test_ok" })).closest("table")!;
    for (const name of [/^Runs/, /^Pass rate/, /^Failed/, /^Errored/, /^Avg duration/]) {
      expect(within(table).getByRole("columnheader", { name })).toHaveClass("num");
    }
    await userEvent.click(within(chips()).getByRole("button", { name: "Remove filter Search: login" }));
    expect(where().has("search")).toBe(false);
  });

  test("Flaky: no quick chip (Show quarantined stays the one control); rate and runs are number columns", async () => {
    const seen: (string | null)[] = [];
    server.use(http.get(`${P}/analytics/flaky`, ({ request }) => {
      seen.push(new URL(request.url).searchParams.get("include_muted"));
      return HttpResponse.json([{
        test_key: "k2", suite: "cart", class_name: "TestCart", name: "test_add", reason: "flips", commits: [], flips: 5,
        flip_rate: 0.42, runs: 12, last_status: "failed", last_seen: "2026-09-30T11:00:00Z",
      }]);
    }));
    renderAt("/projects/:projectId/flaky", "/projects/42/flaky", <FlakyPage />);
    const table = (await screen.findByRole("link", { name: "test_add" })).closest("table")!;
    for (const name of [/^Flips/, /^Flip rate/, /^Runs/]) {
      expect(within(table).getByRole("columnheader", { name })).toHaveClass("num");
    }
    expect(screen.queryByRole("button", { name: "Quarantined" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Show quarantined"));
    expect(where().get("muted")).toBe("1");
    await waitFor(() => expect(seen[seen.length - 1]).toBe("true"));
    // Thresholds and the include-quarantined switch are not chips; nothing to list
    expect(chips()).toBeEmptyDOMElement();
  });
});

// --- Requested runs --------------------------------------------------------------------------

test("Requested runs: the status is a pill with its detail beside it, and Cases is a number column", async () => {
  const base = { requested_at: "2026-10-07T10:00:00Z", suite_id: null, conclusion: null, github_run_id: null,
    github_run_url: null, stopped_by: null, stopped_at: null, error: null, checked_at: "2026-10-07T10:05:00Z", refreshing: false, skipped_manual: 0 };
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, name: "Web", organization_id: 1, my_role: "member" })),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([])),
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: 2, items: [
      { ...base, id: 1, requested_by: 7, case_count: 3, status: "completed", conclusion: "success" },
      { ...base, id: 2, requested_by: 7, case_count: 1, status: "failed_to_start", error: "no workflow" },
    ] })),
    http.get(`${P}/runs`, () => HttpResponse.json([])),
  );
  renderAt("/projects/:projectId/runs/requested", "/projects/42/runs/requested", <RequestedRunsPage />);
  const table = (await screen.findByText("Passed")).closest("table")!;
  expect(within(table).getByRole("columnheader", { name: "Cases" })).toHaveClass("num");
  expect(within(table).getByText("Passed").closest(".pill")).toHaveClass("pill-passed");
  const failed = within(table).getByText("Didn't start").closest(".pill")!;
  expect(failed).toHaveClass("pill-errored");
  expect(failed.closest("td")).toHaveTextContent("Didn't start no workflow");
});

// --- Fix round 1 -----------------------------------------------------------------------------

describe("fix round 1", () => {
  const narrow = () => {
    window.matchMedia = ((query: string) => ({
      matches: true, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  };
  afterEach(() => {
    // @ts-expect-error restore jsdom default (no matchMedia)
    delete window.matchMedia;
  });

  test("Cases: a quick chip does not open the Filters disclosure; a filter only the form shows does", async () => {
    mockCases();
    narrow();
    renderCases("/projects/42/cases?group=scenario&status=ready&linked=true");
    await screen.findByText("Case 1");
    const details = () => screen.getByText(/^Filters/, { selector: "summary" }).closest("details")!;
    expect(details()).not.toHaveAttribute("open");
    await userEvent.click(chip("Failing"));
    expect(details()).not.toHaveAttribute("open");
    // The summary still counts every filter inside it
    expect(screen.getByText("Filters (3 active)", { selector: "summary" })).toBeInTheDocument();
  });

  test("Cases: a filter with no quick chip still opens the disclosure on a narrow screen", async () => {
    mockCases();
    narrow();
    renderCases("/projects/42/cases?group=scenario&status=archived");
    await screen.findByText("Case 1");
    expect(screen.getByText(/^Filters/, { selector: "summary" }).closest("details")).toHaveAttribute("open");
  });

  test("Cases: pressing a chip keeps Search text that was typed but not applied", async () => {
    mockCases();
    renderCases();
    await screen.findByText("Case 1");
    await userEvent.type(screen.getByLabelText("Search"), "legroom");
    await userEvent.click(chip("Ready"));
    expect(where().get("status")).toBe("ready");
    expect(screen.getByLabelText("Search")).toHaveValue("legroom");
  });

  test("Runs: the More filters disclosure stays open when its last chip is removed", async () => {
    server.use(http.get(`${P}/runs`, () => HttpResponse.json([run(61)])));
    renderAt("/projects/:projectId/runs", "/projects/42/runs?environment=staging", <RunsPage />);
    await screen.findByRole("link", { name: "#61" });
    const details = screen.getByText(/More filters/, { selector: "summary" }).closest("details")!;
    expect(details).toHaveAttribute("open");
    await userEvent.click(within(chips()).getByRole("button", { name: "Remove filter Environment: staging" }));
    expect(where().has("environment")).toBe(false);
    expect(details).toHaveAttribute("open");
  });

  test("Runs: a filter change announces the count in the existing status line", async () => {
    server.use(http.get(`${P}/runs`, ({ request }) => {
      const failing = new URL(request.url).searchParams.get("status") === "failing";
      return HttpResponse.json(failing ? [run(61)] : [run(61), run(62)]);
    }));
    renderAt("/projects/:projectId/runs", "/projects/42/runs", <RunsPage />);
    await screen.findByRole("link", { name: "#62" });
    // Nothing on first load
    expect(document.querySelector("p.live-note")).toBeEmptyDOMElement();
    await userEvent.click(chip("Failed"));
    expect(await screen.findByText("1 run")).toHaveAttribute("role", "status");
    await userEvent.click(chip("Failed"));
    expect(await screen.findByText("2 runs")).toHaveAttribute("role", "status");
  });
});

// --- Clear all means a blank form ------------------------------------------------------------

describe("Clear all blanks the form drafts", () => {
  test("Cases: Search text typed but not applied is cleared too", async () => {
    mockCases();
    renderCases("/projects/42/cases?group=scenario&status=ready");
    await screen.findByText("Case 1");
    await userEvent.type(screen.getByLabelText("Search"), "legroom");
    await userEvent.click(within(chips()).getByRole("button", { name: "Clear all" }));
    // The grouping is a view, not a filter: it stays
    expect(where().toString()).toBe("group=scenario");
    expect(screen.getByLabelText("Search")).toHaveValue("");
  });

  test("Runs: unapplied text in the form is cleared too", async () => {
    server.use(http.get(`${P}/runs`, () => HttpResponse.json([run(61)])));
    renderAt("/projects/:projectId/runs", "/projects/42/runs?status=failing", <RunsPage />);
    await screen.findByRole("link", { name: "#61" });
    await userEvent.type(screen.getByLabelText(/^branch/i), "release");
    await userEvent.type(screen.getByLabelText(/^author/i), "ana");
    await userEvent.click(within(chips()).getByRole("button", { name: "Clear all" }));
    expect(where().has("status")).toBe(false);
    expect(screen.getByLabelText(/^branch/i)).toHaveValue("");
    expect(screen.getByLabelText(/^author/i)).toHaveValue("");
  });

  test("Tests: an unapplied Search draft is cleared too", async () => {
    server.use(http.get(`${P}/analytics/tests`, () => HttpResponse.json([])));
    renderAt("/projects/:projectId/tests", "/projects/42/tests?days=7", <TestsPage />);
    await within(chips()).findByRole("button", { name: "Clear all" });
    await userEvent.type(screen.getByLabelText("Search"), "login");
    await userEvent.click(within(chips()).getByRole("button", { name: "Clear all" }));
    expect(where().has("days")).toBe(false);
    expect(screen.getByLabelText("Search")).toHaveValue("");
  });

  test("Flaky: unapplied thresholds and branch go back to their defaults", async () => {
    server.use(http.get(`${P}/analytics/flaky`, () => HttpResponse.json([])));
    renderAt("/projects/:projectId/flaky", "/projects/42/flaky?window=30", <FlakyPage />);
    await within(chips()).findByRole("button", { name: "Clear all" });
    await userEvent.type(screen.getByLabelText("Branch"), "dev");
    await userEvent.clear(screen.getByLabelText("Min runs"));
    await userEvent.type(screen.getByLabelText("Min runs"), "9");
    await userEvent.click(within(chips()).getByRole("button", { name: "Clear all" }));
    expect(where().has("window")).toBe(false);
    expect(screen.getByLabelText("Branch")).toHaveValue("");
    expect(screen.getByLabelText("Min runs")).toHaveValue(5);
  });
});
