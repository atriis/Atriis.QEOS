import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CasesPage from "./CasesPage";
import CaseEditorPage from "./CaseEditorPage";
import SuitesPage from "./SuitesPage";
import SuiteDetailPage from "./SuiteDetailPage";

const P = "/api/v1/projects/42";
const KEY = "b".repeat(64);

const kase = (number: number, extra: object = {}) => ({
  number, key: `TC-${number}`, title: `Case ${number}`, description: null, steps: [], labels: [], priority: "medium",
  status: "draft", automated_test_key: null, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z",
  updated_by: null, updated_at: null, suites: [], source_path: null, gherkin: null, feature_name: null, ...extra,
});

function asRole(role: string) {
  server.use(http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: role })));
}

function Location() {
  const { pathname, search } = useLocation();
  return <output data-testid="where">{pathname + search}</output>;
}

// The page also asks for a one-case list to learn the project total; tests only care about the real list calls
const listParams = (request: Request) => {
  const sp = new URL(request.url).searchParams;
  return sp.get("limit") === "1" ? null : sp;
};

// The feature list loads on every Cases page; tests that don't care get an empty one
beforeEach(() => {
  server.use(
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ tests: {} })),
  );
});

function renderAt(url: string) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/cases" element={<><CasesPage /><Location /></>} />
          <Route path="/projects/:projectId/cases/new" element={<><CaseEditorPage /><Location /></>} />
          <Route path="/projects/:projectId/cases/:caseNumber" element={<><CaseEditorPage /><Location /></>} />
          <Route path="/projects/:projectId/suites" element={<><SuitesPage /><Location /></>} />
          <Route path="/projects/:projectId/suites/:suiteId" element={<><SuiteDetailPage /><Location /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// --- cases list ----------------------------------------------------------------------------

test("lists cases with their key, labels and whether they are automated; filters reach the API", async () => {
  asRole("member");
  const seen: URLSearchParams[] = [];
  server.use(
    http.get(`${P}/cases`, ({ request }) => {
      const sp = listParams(request); if (sp) seen.push(sp);
      return HttpResponse.json({ total: 2, items: [kase(1, { labels: ["smoke"], automated_test_key: KEY }), kase(2)] });
    }),
    http.get(`${P}/case-labels`, () => HttpResponse.json([{ label: "smoke", count: 1 }])),
  );
  renderAt("/projects/42/cases?group=scenario");
  const row = (await screen.findByRole("link", { name: "Case 1" })).closest("tr")!;
  expect(within(row).getByText("smoke")).toBeInTheDocument();
  expect(within(row).getAllByText(/linked/i).length).toBeGreaterThan(0); // column and narrow line
  expect(within(screen.getByRole("link", { name: "Case 2" }).closest("tr")!).getAllByText(/manual/i).length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: /new case/i })).toHaveAttribute("href", "/projects/42/cases/new");

  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Label" }), "smoke");
  await userEvent.selectOptions(screen.getByLabelText(/^status/i), "ready");
  await userEvent.click(screen.getByRole("button", { name: /apply/i }));
  await vi.waitFor(() => expect(seen[seen.length - 1].get("label")).toBe("smoke"));
  expect(seen[seen.length - 1].get("status")).toBe("ready");
  expect(screen.getByTestId("where")).toHaveTextContent("label=smoke");
});

test("an empty project invites editors to write the first case; viewers just read", async () => {
  asRole("viewer");
  server.use(
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
  );
  renderAt("/projects/42/cases?group=scenario");
  expect(await screen.findByText(/no test cases yet/i)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /write the first case|new case/i })).not.toBeInTheDocument();
});

// --- case editor ---------------------------------------------------------------------------

test("a new case is created with its steps and labels, then opens", async () => {
  asRole("member");
  let sent: Record<string, unknown> | null = null;
  server.use(
    http.post(`${P}/cases`, async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(kase(7, { title: "Pays" }), { status: 201 });
    }),
    http.get(`${P}/cases/7`, () => HttpResponse.json(kase(7, { title: "Pays" }))),
  );
  renderAt("/projects/42/cases/new");
  await userEvent.type(await screen.findByLabelText(/^title/i), "Pays");
  await userEvent.type(screen.getByLabelText(/^action 1/i), "Open the cart");
  await userEvent.type(screen.getByLabelText(/^expected result 1/i), "The total shows");
  await userEvent.click(screen.getByRole("button", { name: /add step/i }));
  await userEvent.type(screen.getByLabelText(/^action 2/i), "Pay");
  await userEvent.type(screen.getByLabelText(/^labels/i), "Checkout, smoke");
  await userEvent.click(screen.getByRole("button", { name: /create case/i }));
  await vi.waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/cases/7"));
  expect(sent).toMatchObject({
    title: "Pays", labels: ["checkout", "smoke"], priority: "medium", status: "draft",
    steps: [{ action: "Open the cart", expected: "The total shows" }, { action: "Pay", expected: "" }],
  });
});

test("steps can be reordered before saving an edit", async () => {
  asRole("member");
  let sent: Record<string, unknown> | null = null;
  const existing = kase(3, { steps: [{ action: "First", expected: "" }, { action: "Second", expected: "" }] });
  server.use(
    http.get(`${P}/cases/3`, () => HttpResponse.json(existing)),
    http.patch(`${P}/cases/3`, async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ ...existing, ...sent });
    }),
  );
  renderAt("/projects/42/cases/3");
  await userEvent.click(await screen.findByRole("button", { name: /move step 2 up/i }));
  await userEvent.click(screen.getByRole("button", { name: /save changes/i }));
  expect(await screen.findByText("Saved.")).toBeInTheDocument();
  expect((sent as unknown as { steps: { action: string }[] }).steps.map((s) => s.action)).toEqual(["Second", "First"]);
});

test("viewers see a case read-only", async () => {
  asRole("viewer");
  server.use(http.get(`${P}/cases/3`, () => HttpResponse.json(kase(3, { title: "Pays" }))));
  renderAt("/projects/42/cases/3");
  expect(await screen.findByDisplayValue("Pays")).toBeDisabled();
  expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();
  expect(screen.getByText(/only owners, admins and members/i)).toBeInTheDocument();
});

test("a case is linked to an automated test found by name, then shows its latest result", async () => {
  asRole("member");
  let linked: Record<string, unknown> | null = null;
  server.use(
    http.get(`${P}/cases/3`, () => HttpResponse.json(linked ? kase(3, linked) : kase(3))),
    http.get(`${P}/analytics/tests`, () => HttpResponse.json([
      { test_key: KEY, suite: "checkout", class_name: "Cart", name: "pays", runs: 3, passed: 3, failed: 0, errored: 0,
        skipped: 0, pass_rate: 1, avg_duration_ms: 10, last_status: "passed", last_seen: "2026-10-06T10:00:00Z" },
    ])),
    http.patch(`${P}/cases/3`, async ({ request }) => {
      linked = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(kase(3, linked));
    }),
    http.get(`${P}/analytics/tests/${KEY}/history`, () => HttpResponse.json({
      test_key: KEY, suite: "checkout", class_name: "Cart", name: "pays",
      summary: { runs: 1, passed: 1, failed: 0, errored: 0, skipped: 0, pass_rate: 1, avg_duration_ms: 10 },
      executions: [{ run_id: 88, started_at: "2026-10-06T10:00:00Z", branch: "main", commit_sha: null, environment: null,
                     status: "passed", duration_ms: 10, message: null }],
    })),
  );
  renderAt("/projects/42/cases/3");
  await userEvent.type(await screen.findByLabelText(/find an automated test/i), "pays");
  await userEvent.click(screen.getByRole("button", { name: /^search$/i }));
  await userEvent.click(await screen.findByRole("button", { name: /link checkout › cart › pays/i }));
  expect(linked).toEqual({ automated_test_key: KEY, automated_name: "checkout › Cart › pays" });
  expect(await screen.findByText(/in run #88/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /unlink/i })).toBeInTheDocument();
});

// --- suites --------------------------------------------------------------------------------

test("a suite is created from the suites list", async () => {
  asRole("member");
  let created = false;
  server.use(
    http.get(`${P}/suites`, () => HttpResponse.json(created ? [{ id: 5, name: "Smoke", description: null, case_count: 0,
      created_at: "2026-10-06T10:00:00Z", updated_at: null }] : [])),
    http.post(`${P}/suites`, () => {
      created = true;
      return HttpResponse.json({ id: 5, name: "Smoke", description: null, case_count: 0, created_at: "2026-10-06T10:00:00Z", updated_at: null }, { status: 201 });
    }),
  );
  renderAt("/projects/42/suites");
  await userEvent.type(await screen.findByLabelText(/^name/i), "Smoke");
  await userEvent.click(screen.getByRole("button", { name: /create suite/i }));
  expect(await screen.findByRole("link", { name: "Smoke" })).toHaveAttribute("href", "/projects/42/suites/5");
});

test("a suite's cases are added, reordered and saved as one ordered list", async () => {
  asRole("member");
  let order: number[] | null = null;
  const sc = (n: number) => ({ number: n, key: `TC-${n}`, title: `Case ${n}`, status: "draft", priority: "medium", labels: [], automated_test_key: null });
  server.use(
    http.get(`${P}/suites/5`, () => HttpResponse.json({ id: 5, name: "Smoke", description: null, case_count: 2,
      created_at: "2026-10-06T10:00:00Z", updated_at: null, cases: [sc(1), sc(2)] })),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 2, items: [kase(2), kase(3)] })),
    http.put(`${P}/suites/5/cases`, async ({ request }) => {
      order = ((await request.json()) as { cases: number[] }).cases;
      return HttpResponse.json({ id: 5, name: "Smoke", description: null, case_count: 3, created_at: "", updated_at: null, cases: [] });
    }),
  );
  renderAt("/projects/42/suites/5");
  await userEvent.click(await screen.findByRole("button", { name: /move tc-2 up/i }));
  await userEvent.click(screen.getByRole("button", { name: /^search$/i }));
  expect(await screen.findByRole("button", { name: /add tc-2 to the suite/i })).toBeDisabled();   // already in it
  await userEvent.click(screen.getByRole("button", { name: /add tc-3 to the suite/i }));
  await userEvent.click(screen.getByRole("button", { name: /save order and cases/i }));
  await vi.waitFor(() => expect(order).toEqual([2, 1, 3]));
});

test("an imported case shows its source and Gherkin read-only", async () => {
  asRole("member");
  server.use(http.get(`${P}/cases/7`, () => HttpResponse.json(kase(7, {
    source_path: "tests/features/a.feature", gherkin: "Scenario: Pay\n  Given a cart", labels: ["smoke"],
  }))));
  renderAt("/projects/42/cases/7");
  expect(await screen.findByText(/imported from/i)).toHaveTextContent("tests/features/a.feature");
  expect(screen.getByText("Given")).toBeInTheDocument();
  expect(screen.getByLabelText(/title/i)).toHaveAttribute("readonly");
  expect(screen.queryByRole("button", { name: /add step/i })).not.toBeInTheDocument();
});

test("saving an imported case sends only the fields QEOS owns", async () => {
  asRole("member");
  let sent: Record<string, unknown> | null = null;
  server.use(
    http.get(`${P}/cases/7`, () => HttpResponse.json(kase(7, { source_path: "a.feature", gherkin: "Scenario: x" }))),
    http.patch(`${P}/cases/7`, async ({ request }) => { sent = (await request.json()) as Record<string, unknown>; return HttpResponse.json(kase(7)); }),
  );
  renderAt("/projects/42/cases/7");
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText(/priority/i), "high");
  await user.click(screen.getByRole("button", { name: /save/i }));
  await vi.waitFor(() => expect(sent).not.toBeNull());
  expect(Object.keys(sent ?? {}).sort()).toEqual(["description", "priority", "status"]);
});

test("the filter form offers neither Origin, Feature nor Azure DevOps (removed 2026-10-16)", async () => {
  asRole("member");
  renderAt("/projects/42/cases?group=scenario");
  await screen.findByLabelText("Search");
  expect(screen.queryByLabelText(/^origin/i)).toBeNull();
  expect(screen.queryByLabelText(/^feature$/i)).toBeNull();
  expect(screen.queryByLabelText(/azure devops/i)).toBeNull();
  expect(screen.getByLabelText("Latest result")).toBeInTheDocument();
});

// --- case filters --------------------------------------------------------------------------

/** Lets the facet queries land, so no state update arrives after the test ends. */
async function settled() {
  await screen.findByRole("option", { name: "smoke (1)" });
}

function facets() {
  server.use(
    http.get(`${P}/case-labels`, () => HttpResponse.json([{ label: "smoke", count: 1 }, { label: "ado-81284", count: 1 }])),
    http.get(`${P}/case-features`, () => HttpResponse.json([{ feature: "Hotels", count: 2 }])),
  );
}

test("a folder in the URL reaches the API", async () => {
  asRole("member"); facets();
  const seen: URLSearchParams[] = [];
  server.use(http.get(`${P}/cases`, ({ request }) => { const sp = listParams(request); if (sp) seen.push(sp); return HttpResponse.json({ total: 0, items: [] }); }));
  renderAt("/projects/42/cases?group=scenario&folder=tests%2Ffeatures");
  await waitFor(() => expect(seen.at(-1)?.get("folder")).toBe("tests/features"));
  await screen.findByRole("option", { name: "smoke (1)" });
});

test("picking a folder from the dropdown puts it in the URL and the API call, keeping other filters", async () => {
  asRole("member");
  const seen: URLSearchParams[] = [];
  server.use(
    http.get(`${P}/case-folders`, () => HttpResponse.json([
      { path: "tests", count: 3 }, { path: "tests/hotels", count: 2 }, { path: "tests/flights", count: 1 },
    ])),
    http.get(`${P}/cases`, ({ request }) => {
      const sp = listParams(request); if (sp) seen.push(sp);
      return HttpResponse.json({ total: 3, items: [kase(1)] });
    }),
  );
  renderAt("/projects/42/cases?group=scenario&priority=high");
  await userEvent.click(await screen.findByRole("button", { name: /^folder/i }));
  expect(screen.getByRole("dialog", { name: "Folder" })).toBeInTheDocument();
  await userEvent.type(await screen.findByRole("searchbox", { name: "Search folders" }), "hotels");
  await userEvent.click(await screen.findByRole("treeitem", { name: /hotels 2/i }));
  await vi.waitFor(() => expect(seen[seen.length - 1].get("folder")).toBe("tests/hotels"));
  expect(seen[seen.length - 1].get("priority")).toBe("high");
  expect(screen.getByTestId("where")).toHaveTextContent("folder=tests%2Fhotels");
  expect(screen.getByRole("button", { name: /^folder/i })).toHaveTextContent("hotels");
});

test("picking a folder also applies edits made to the other filters but not yet applied", async () => {
  asRole("member");
  server.use(http.get(`${P}/case-folders`, () => HttpResponse.json([{ path: "tests", count: 3 }, { path: "tests/hotels", count: 2 }])));
  renderAt("/projects/42/cases?group=scenario");
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Priority" }), "high");
  await userEvent.click(screen.getByRole("button", { name: /^folder/i }));
  await userEvent.click(await screen.findByRole("treeitem", { name: /hotels 2/i }));
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("folder=tests%2Fhotels"));
  expect(screen.getByTestId("where")).toHaveTextContent("priority=high");
});

test("Clear all is only shown while a filter is active", async () => {
  asRole("member");
  renderAt("/projects/42/cases?group=scenario");
  await screen.findByRole("button", { name: "Apply" });
  expect(screen.queryByRole("button", { name: "Clear all" })).not.toBeInTheDocument();
});

test("Clear all appears with a filter and resets the URL; the form has no second clear button", async () => {
  asRole("member");
  renderAt("/projects/42/cases?group=scenario&priority=high");
  await screen.findByRole("button", { name: "Clear all" });
  expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "Clear all" }));
  await waitFor(() => expect(screen.getByTestId("where")).not.toHaveTextContent("priority"));
});

test("the link filter reaches the API; feature and ado keys in an old link are ignored", async () => {
  asRole("member"); facets();
  const seen: URLSearchParams[] = [];
  server.use(http.get(`${P}/cases`, ({ request }) => { const sp = listParams(request); if (sp) seen.push(sp); return HttpResponse.json({ total: 0, items: [] }); }));
  renderAt("/projects/42/cases?group=scenario&linked=false&feature=Hotels&ado=81284");
  await waitFor(() => expect(seen.at(-1)?.get("linked")).toBe("false"));
  expect(seen.at(-1)?.get("feature")).toBeNull();
  expect(seen.at(-1)?.get("ado")).toBeNull();
  await settled();
});

test("a latest-result filter asks ingestion for keys, then searches with them", async () => {
  asRole("member"); facets();
  let body: Record<string, unknown> | null = null;
  server.use(
    http.get(`${P}/analytics/latest-keys`, ({ request }) => HttpResponse.json({ keys: [new URL(request.url).searchParams.get("status") === "failed" ? "f".repeat(64) : "a".repeat(64)] })),
    // The list's search carries the folder; the Failing KPI tile's does not
    http.post(`${P}/cases/search`, async ({ request }) => {
      const sent = (await request.json()) as Record<string, unknown>;
      if (sent.folder) body = sent;
      return HttpResponse.json({ total: 1, items: [kase(1)] });
    }),
  );
  renderAt("/projects/42/cases?group=scenario&result=failed&folder=tests%2Ffeatures");
  await waitFor(() => expect(body).not.toBeNull());
  expect(body).toMatchObject({ test_keys: ["f".repeat(64)], keys_mode: "include", folder: "tests/features" });
  await settled();
});

test("never ran asks for any result and excludes those keys", async () => {
  asRole("member"); facets();
  let status = ""; let body: Record<string, unknown> | null = null;
  server.use(
    // The Failing KPI tile asks for "failed" keys on its own; this test is about the list's request
    http.get(`${P}/analytics/latest-keys`, ({ request }) => {
      const asked = new URL(request.url).searchParams.get("status") ?? "";
      if (asked !== "failed") status = asked;
      return HttpResponse.json({ keys: [] });
    }),
    http.post(`${P}/cases/search`, async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ total: 0, items: [] }); }),
  );
  renderAt("/projects/42/cases?group=scenario&result=never");
  await waitFor(() => expect(body).not.toBeNull());
  expect(status).toBe("any");
  expect(body).toMatchObject({ test_keys: [], keys_mode: "exclude" });
  await settled();
});

test("when ingestion is down the result filter is skipped with a banner", async () => {
  asRole("member"); facets();
  const seen: URLSearchParams[] = [];
  server.use(
    http.get(`${P}/analytics/latest-keys`, () => HttpResponse.json({ detail: "down" }, { status: 503 })),
    http.get(`${P}/cases`, ({ request }) => { const sp = listParams(request); if (sp) seen.push(sp); return HttpResponse.json({ total: 1, items: [kase(1)] }); }),
  );
  renderAt("/projects/42/cases?group=scenario&result=passed&label=smoke");
  expect(await screen.findByText(/latest result filter unavailable right now/i)).toBeInTheDocument();
  expect(seen.at(-1)?.get("label")).toBe("smoke");
});

test("clear filters resets everything", async () => {
  asRole("member"); facets();
  server.use(http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })));
  renderAt("/projects/42/cases?group=scenario&status=ready&folder=tests&linked=true");
  await userEvent.setup().click(await screen.findByRole("button", { name: "Clear all" }));
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/projects\/42\/cases\?group=scenario$/);
});

test("more than 20000 latest keys fall back to the plain list with a notice", async () => {
  asRole("member"); facets();
  let searched = false; let listed = 0;
  server.use(
    http.get(`${P}/analytics/latest-keys`, () => HttpResponse.json({ keys: Array.from({ length: 20001 }, (_, i) => i.toString(16).padStart(64, "0")) })),
    http.post(`${P}/cases/search`, () => { searched = true; return HttpResponse.json({ detail: "too many" }, { status: 422 }); }),
    http.get(`${P}/cases`, () => { listed += 1; return HttpResponse.json({ total: 1, items: [kase(1)] }); }),
  );
  renderAt("/projects/42/cases?group=scenario&result=passed");
  expect(await screen.findByText(/too many tests for the latest-result filter/i)).toBeInTheDocument();
  expect(searched).toBe(false);
  expect(listed).toBeGreaterThan(0);
  await settled();
});

test("a failing search falls back to the plain list with the unavailable notice", async () => {
  asRole("member"); facets();
  server.use(
    http.get(`${P}/analytics/latest-keys`, () => HttpResponse.json({ keys: ["a".repeat(64)] })),
    http.post(`${P}/cases/search`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [kase(1)] })),
  );
  renderAt("/projects/42/cases?group=scenario&result=passed");
  expect(await screen.findByText(/latest result filter unavailable right now/i)).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: "Case 1" })).toBeInTheDocument();
  await settled();
});

test("an unknown result value is ignored: the list does not ask ingestion (only the Failing tile does, for its count)", async () => {
  asRole("member"); facets();
  let asked = false; let listed = false;
  server.use(
    http.get(`${P}/analytics/latest-keys`, ({ request }) => {
      if (new URL(request.url).searchParams.get("status") !== "failed") asked = true;
      return HttpResponse.json({ keys: [] });
    }),
    http.get(`${P}/cases`, () => { listed = true; return HttpResponse.json({ total: 0, items: [] }); }),
  );
  renderAt("/projects/42/cases?group=scenario&result=foo");
  await waitFor(() => expect(listed).toBe(true));
  expect(asked).toBe(false);
  await settled();
});

test("linked cases show their last runs; unlinked say not linked", async () => {
  asRole("member");
  const stripKey = "b".repeat(64);
  let asked: string[] = [];
  server.use(
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 2, items: [kase(1, { automated_test_key: stripKey }), kase(2)] })),
    http.post(`${P}/analytics/run-strip`, async ({ request }) => {
      asked = ((await request.json()) as { test_keys: string[] }).test_keys;
      return HttpResponse.json({ tests: { [stripKey]: [{ run_id: 9, started_at: "2026-10-06T10:00:00Z", branch: "main", status: "failed" }] } });
    }),
  );
  renderAt("/projects/42/cases?group=scenario");
  const strip = await screen.findByRole("group", { name: /^Last 1 runs?: 1 failed/ });
  // A bar opens the case as of its run
  expect(within(strip).getByRole("link")).toHaveAttribute("href", "/projects/42/cases/1?run=9");
  expect(asked).toEqual([stripKey]);
  expect(screen.getByText("not linked")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: /last runs/i })).toBeInTheDocument();
  const legend = screen.getByRole("list", { name: "Last runs legend" });
  expect(within(legend).getAllByRole("listitem").map((li) => li.textContent?.trim())).toEqual(["Passed", "Failed", "Re-run", "Skipped"]);
  expect(screen.queryByText("Didn't run")).toBeNull(); // the strip only holds runs the case was in
});

test("the run-strip request keys are deduplicated and sorted, and the skeleton shows while loading", async () => {
  asRole("member");
  const a = "a".repeat(64), z = "z".repeat(64);
  let body: { test_keys: string[] } | undefined;
  let release: () => void = () => {};
  const gate = new Promise<void>((r) => { release = r; });
  server.use(
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 3, items: [kase(1, { automated_test_key: z }), kase(2, { automated_test_key: a }), kase(3, { automated_test_key: z })] })),
    http.post(`${P}/analytics/run-strip`, async ({ request }) => {
      body = (await request.json()) as { test_keys: string[] };
      await gate;
      return HttpResponse.json({ tests: {} });
    }),
  );
  renderAt("/projects/42/cases?group=scenario");
  expect((await screen.findAllByText("Loading last runs")).length).toBe(3);
  release();
  await waitFor(() => expect(body?.test_keys).toEqual([a, z]));
});

test("the legend is hidden when no case on the page is linked", async () => {
  asRole("member");
  server.use(http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [kase(1)] })));
  renderAt("/projects/42/cases?group=scenario");
  await screen.findByText("not linked");
  expect(screen.queryByRole("list", { name: "Last runs legend" })).toBeNull();
});

test("no linked cases means no run-strip request", async () => {
  asRole("member");
  let called = false;
  server.use(
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [kase(1)] })),
    http.post(`${P}/analytics/run-strip`, () => { called = true; return HttpResponse.json({ tests: {} }); }),
  );
  renderAt("/projects/42/cases?group=scenario");
  await screen.findByText("not linked");
  expect(called).toBe(false);
});

test("a failing run-strip leaves the list usable", async () => {
  asRole("member");
  const stripKey = "c".repeat(64);
  server.use(
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [kase(1, { automated_test_key: stripKey })] })),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({ detail: "down" }, { status: 503 })),
  );
  renderAt("/projects/42/cases?group=scenario");
  expect(await screen.findByRole("link", { name: "Case 1" })).toBeInTheDocument();
  expect(await screen.findByLabelText(/last runs unavailable/i)).toBeInTheDocument();
});

test("the page of cases is in the URL: read on load, written by Next", async () => {
  asRole("member");
  const seen: URLSearchParams[] = [];
  server.use(http.get(`${P}/cases`, ({ request }) => {
    const sp = listParams(request);
    if (sp) seen.push(sp);
    return HttpResponse.json({ total: 200, items: [kase(51)] });
  }));
  renderAt("/projects/42/cases?group=scenario&offset=50&priority=high");
  await waitFor(() => expect(seen.at(-1)?.get("offset")).toBe("50"));
  await userEvent.click(await screen.findByRole("button", { name: "Next" }));
  expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/cases?group=scenario&offset=100&priority=high");
  await waitFor(() => expect(seen.at(-1)?.get("offset")).toBe("100"));
});

test("on phones the last runs come back as a count under the title", async () => {
  asRole("member");
  const stripKey = "c".repeat(64);
  server.use(
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 1, items: [kase(1, { automated_test_key: stripKey })] })),
    http.post(`${P}/analytics/run-strip`, () => HttpResponse.json({
      tests: { [stripKey]: [{ run_id: 7, started_at: "2026-10-04T10:00:00Z", branch: "main", status: "failed" }, { run_id: 8, started_at: "2026-10-05T10:00:00Z", branch: "main", status: "passed" }, { run_id: 9, started_at: "2026-10-06T10:00:00Z", branch: "main", status: "passed" }] },
    })),
  );
  renderAt("/projects/42/cases?group=scenario");
  const link = await screen.findByRole("link", { name: "Case 1" });
  const meta = await waitFor(() => {
    const el = link.closest("td")!.querySelector(".narrow-meta")!;
    expect(el).toHaveTextContent("Last runs 1 failed, 2 passed of the last 3");
    return el;
  });
  expect(meta.querySelector("a")).toBeNull(); // a count, not a second strip of links
});

// --- period (2026-10-16): only cases that ran in the period ----------------------------------------------------

function periodServer() {
  const asked: URLSearchParams[] = [];
  let body: Record<string, unknown> | null = null;
  server.use(
    http.get(`${P}/analytics/latest-keys`, ({ request }) => {
      const sp = new URL(request.url).searchParams;
      if (sp.get("status") !== "failed" || sp.get("since")) asked.push(sp); // the Failing tile's own request has no period
      return HttpResponse.json({ keys: ["a".repeat(64)] });
    }),
    http.post(`${P}/cases/search`, async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return HttpResponse.json({ total: 1, items: [kase(1)] }); }),
  );
  return { asked, body: () => body };
}

test("a period chip asks ingestion for the tests that ran in it, then searches with their keys", async () => {
  asRole("member"); facets();
  const s = periodServer();
  renderAt("/projects/42/cases?group=scenario&period=7");
  await waitFor(() => expect(s.body()).not.toBeNull());
  const sp = s.asked.at(-1)!;
  expect(sp.get("status")).toBe("any");
  expect(sp.get("since")).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  expect(sp.get("until")).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  expect(Date.parse(sp.get("until")!) - Date.parse(sp.get("since")!)).toBe(7 * 86_400_000);
  expect(s.body()).toMatchObject({ test_keys: ["a".repeat(64)], keys_mode: "include" });
  expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  await settled();
});

test("a latest-result filter with a period means the latest within the period", async () => {
  asRole("member"); facets();
  const s = periodServer();
  renderAt("/projects/42/cases?group=scenario&result=failed&period=30");
  await waitFor(() => expect(s.body()).not.toBeNull());
  const sp = s.asked.at(-1)!;
  expect(sp.get("status")).toBe("failed");
  expect(sp.get("since")).not.toBeNull();
  await settled();
});

test("Custom… shows the range row; an applied range is one Custom chip whose removal clears both dates", async () => {
  asRole("member"); facets();
  const s = periodServer();
  const user = userEvent.setup();
  renderAt("/projects/42/cases?group=scenario");
  await screen.findByLabelText("Search");
  await user.click(screen.getByRole("button", { name: "Custom…" }));
  const row = screen.getByRole("form", { name: "Custom period" });
  expect(within(row).getByLabelText("From")).toHaveFocus();
  await user.type(within(row).getByLabelText("From"), "2026-10-01");
  await user.type(within(row).getByLabelText("To"), "2026-10-08");
  await user.click(within(row).getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("from=2026-10-01&to=2026-10-08"));
  const chip = screen.getByRole("button", { name: "Custom: 1 Oct – 8 Oct 2026" });
  expect(chip).toHaveAttribute("aria-pressed", "true");
  await waitFor(() => expect(s.body()).not.toBeNull());
  expect(s.asked.at(-1)!.get("since")).toBe(new Date(2026, 9, 1).toISOString());
  expect(s.asked.at(-1)!.get("until")).toBe(new Date(2026, 9, 9).toISOString());
  await user.click(chip);
  await waitFor(() => expect(screen.getByTestId("where")).not.toHaveTextContent("from="));
  expect(screen.getByTestId("where")).not.toHaveTextContent("to=");
  await settled();
});
