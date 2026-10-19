import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CasesPage from "./CasesPage";

const P = "/api/v1/projects/42";

function mockNarrow(matches: boolean) {
  window.matchMedia = ((query: string) => ({
    matches, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "member" })),
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })),
  );
});
afterEach(() => {
  // @ts-expect-error restore jsdom default (no matchMedia)
  delete window.matchMedia;
});

function renderCases(url = "/projects/42/cases?group=scenario") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/projects/:projectId/cases" element={<CasesPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const disclosure = () => screen.getByText(/^Filters/, { selector: "summary" }).closest("details")!;

test("on a wide screen the filters are open; Search and Folder are outside the disclosure", async () => {
  mockNarrow(false);
  renderCases();
  await screen.findByLabelText("Search");
  expect(disclosure()).toHaveAttribute("open");
  expect(disclosure()).toContainElement(screen.getByRole("combobox", { name: "Priority" }));
  expect(disclosure()).not.toContainElement(screen.getByLabelText("Search"));
  expect(disclosure()).not.toContainElement(screen.getByRole("button", { name: "Apply" }));
});

test("on a narrow screen the filters start closed, show how many are active, and the choice is remembered", async () => {
  mockNarrow(true);
  renderCases();
  await screen.findByLabelText("Search");
  expect(disclosure()).not.toHaveAttribute("open");
  expect(screen.getByText("Filters", { selector: "summary" })).toBeInTheDocument();
  await userEvent.click(screen.getByText("Filters", { selector: "summary" }));
  expect(disclosure()).toHaveAttribute("open");
  expect(sessionStorage.getItem("qeos.filters.cases")).toBe("open");
});

test("a narrow screen reopens the disclosure the reader left open", async () => {
  mockNarrow(true);
  sessionStorage.setItem("qeos.filters.cases", "open");
  renderCases();
  await screen.findByLabelText("Search");
  expect(disclosure()).toHaveAttribute("open");
});

test("active filters are counted in the summary, and a narrow screen opens to show them", async () => {
  mockNarrow(true);
  renderCases("/projects/42/cases?group=scenario&priority=high&status=ready&q=login");
  await screen.findByLabelText("Search");
  expect(screen.getByText("Filters (2 active)", { selector: "summary" })).toBeInTheDocument();
  expect(disclosure()).toHaveAttribute("open");
});

test("active filters open the disclosure even when the reader last left it closed", async () => {
  mockNarrow(false);
  sessionStorage.setItem("qeos.filters.cases", "closed");
  renderCases("/projects/42/cases?group=scenario&priority=high&status=ready");
  await screen.findByLabelText("Search");
  expect(disclosure()).toHaveAttribute("open");
});

const kase = (number: number) => ({
  number, key: `TC-${number}`, title: `Case ${number}`, description: null, steps: [], labels: [], priority: "medium",
  status: "draft", automated_test_key: null, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z",
  updated_by: null, updated_at: null, suites: [], source_path: "tests/features/a.feature", gherkin: "Scenario: x", feature_name: "A",
});

test("the Suite filter offers Not in any suite and lists with suite=none", async () => {
  mockNarrow(false);
  let asked: URLSearchParams | null = null;
  server.use(http.get(`${P}/cases`, ({ request }) => {
    asked = new URL(request.url).searchParams;
    return HttpResponse.json({ total: 1, items: [kase(1)] });
  }));
  renderCases();
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Suite" }), "Not in any suite");
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  await screen.findByRole("checkbox", { name: "Select TC-1 Case 1" });
  expect(asked!.get("suite")).toBe("none");
});

test("with a latest-result filter, Not in any suite goes in the search body", async () => {
  mockNarrow(false);
  // The Failing tile searches too (without the suite): look at every body
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.get(`${P}/analytics/latest-keys`, () => HttpResponse.json({ keys: ["t1"] })),
    http.post(`${P}/cases/search`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ total: 1, items: [kase(1)] });
    }),
  );
  renderCases("/projects/42/cases?group=scenario&suite=none&result=failed");
  await screen.findByRole("checkbox", { name: "Select TC-1 Case 1" });
  await vi.waitFor(() => expect(bodies.some((b) => b.suite === "none")).toBe(true));
});

test("Add to suite sits next to Run selected, and the selection survives the dialog closing", async () => {
  mockNarrow(false);
  server.use(
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 2, items: [kase(1), kase(2)] })),
    http.get(`${P}/suites`, () => HttpResponse.json([])),
  );
  renderCases();
  await userEvent.click(await screen.findByRole("checkbox", { name: "Select TC-1 Case 1" }));
  const bar = screen.getByRole("region", { name: "Selected cases" });
  expect(within(bar).getByRole("button", { name: "Run selected (1)" })).toBeInTheDocument();
  await userEvent.click(within(bar).getByRole("button", { name: "Add to suite" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(within(bar).getByRole("button", { name: "Run selected (1)" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Select TC-1 Case 1" })).toBeChecked();
});

test("a viewer sees no Add to suite", async () => {
  mockNarrow(false);
  server.use(http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: "viewer" })));
  renderCases();
  await screen.findByRole("heading", { name: "Test cases" });
  expect(screen.queryByRole("button", { name: "Add to suite" })).not.toBeInTheDocument();
});
