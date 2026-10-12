import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import type { RunImpact, SuggestedTest } from "../api/impact";
import { IMPACT_POLL_MAX, IMPACT_POLL_MS } from "../lib/impactQueries";
import ImpactCard from "./ImpactCard";

const IMPACT_URL = "/api/v1/projects/42/runs/61/impact";
const key = (name: string) => name.padEnd(64, "0");
const ref = (name: string) => ({ test_key: key(name), suite: "s", class_name: "C", name });
const statistical = (name: string): SuggestedTest => ({ ...ref(name), kind: "statistical",
  evidence: { path_unit: "src/payment/", changed_runs: 6, new_failures: 4, confidence: 0.6667, lift: 22.2, base_rate: 0.03 } });
const labelled = (name: string, kind: SuggestedTest["kind"]): SuggestedTest => ({ ...ref(name), kind, evidence: null });

function impact(extra: Partial<RunImpact> = {}): RunImpact {
  return {
    run_id: 61, state: "ok", changed_paths: ["src/payment/api.py"], replayed: false, scored_at: "2026-10-12T10:00:00Z",
    suggestion: {
      state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20, statistical_total: 1,
      tests: [statistical("pays"), labelled("checkout_spec", "test_file_changed"), labelled("brand_new", "no_history"),
        labelled("cart", "failing_on_branch")],
    },
    outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [ref("pays")], missed: [] },
    ...extra,
  };
}

function mount() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><ImpactCard projectId={42} runId={61} /></MemoryRouter></QueryClientProvider>);
}

function renderCard(answer: RunImpact) {
  server.use(http.get(IMPACT_URL, () => HttpResponse.json(answer)));
  mount();
}

const card = () => screen.findByRole("region", { name: "Likely affected tests" });

test("each suggestion links its history and shows its evidence or its label", async () => {
  renderCard(impact());
  const region = await card();
  expect(await within(region).findByRole("link", { name: "pays" })).toHaveAttribute("href", `/projects/42/tests/${key("pays")}`);
  expect(within(region).getByText(/newly failed in/)).toHaveTextContent(
    "newly failed in 4 of 6 runs that changed src/payment/ (normally 3%)");
  expect(within(region).getByText("src/payment/").tagName).toBe("CODE");
  expect(within(region).getByText("test file changed")).toBeInTheDocument();
  expect(within(region).getByText("no history yet")).toBeInTheDocument();
  expect(within(region).getByText("failing on this branch")).toBeInTheDocument();
});

test("evidence without a base rate leaves the normally part out", async () => {
  const rare = statistical("rare");
  rare.evidence = { ...rare.evidence!, lift: null, base_rate: null };
  renderCard(impact({ suggestion: { state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20,
    statistical_total: 1, tests: [rare] } }));
  const region = await card();
  expect(await within(region).findByText(/newly failed in/)).toHaveTextContent(
    /^newly failed in 4 of 6 runs that changed src\/payment\/$/);
});

test("the outcome says every new failure was suggested, with a word as well as a colour", async () => {
  renderCard(impact());
  expect(await screen.findByText("Suggested 4 tests · 1 newly failed · it was suggested")).toBeInTheDocument();
  expect(screen.getByText("All caught")).toBeInTheDocument();
});

test("a new failure that was not suggested is named as missed", async () => {
  renderCard(impact({ outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [ref("pays")], missed: [ref("refunds")] } }));
  expect(await screen.findByText("Suggested 4 tests · 2 newly failed · 1 not suggested:")).toBeInTheDocument();
  expect(screen.getByText("Missed")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "refunds" })).toHaveAttribute("href", `/projects/42/tests/${key("refunds")}`);
});

test("not enough history still lists the tests that are always included; a pending outcome says so", async () => {
  renderCard(impact({
    state: "not_enough_history", outcome: null,
    suggestion: { state: "not_enough_history", model_version: "stats-v1", history_runs: 7, needed_runs: 20, statistical_total: 0,
      tests: [labelled("cart", "failing_on_branch")] },
  }));
  expect(await screen.findByText("Not enough history yet: 7 runs with changed files, needs 20")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "cart" })).toBeInTheDocument();
  expect(screen.getByText("Suggested 1 test · outcome not recorded yet")).toBeInTheDocument();
});

test("a run without changed files says so", async () => {
  renderCard(impact({ state: "no_change_data", changed_paths: [], scored_at: null, suggestion: null, outcome: null }));
  expect(await screen.findByText("No change data for this run")).toBeInTheDocument();
});

test("a run with changes but no stored suggestion says why", async () => {
  renderCard(impact({ state: "not_scored", suggestion: null, outcome: null, scored_at: null }));
  expect(await screen.findByText(
    "No suggestion was stored for this run: it was uploaded before test impact analysis, or scoring failed.")).toBeInTheDocument();
});

test("a replayed suggestion is marked", async () => {
  renderCard(impact({ replayed: true }));
  const heading = await screen.findByRole("heading", { name: "Likely affected tests" });
  expect(await within(heading.parentElement!).findByText("Replayed")).toHaveClass("pill");
  expect(screen.getByText("Replayed: scored later from the runs before this one, not at upload.")).toBeInTheDocument();
});

test("no likely affected tests and no new failures", async () => {
  renderCard(impact({
    suggestion: { state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20, statistical_total: 0, tests: [] },
    outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [], missed: [] },
  }));
  expect(await screen.findByText("No tests are likely affected by this change")).toBeInTheDocument();
  expect(screen.getByText("Suggested 0 tests · no new failures")).toBeInTheDocument();
});

test("long lists fold behind Show all", async () => {
  const tests = Array.from({ length: 20 }, (_, i) => statistical(`t${String(i).padStart(2, "0")}`));
  renderCard(impact({
    suggestion: { state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20, statistical_total: 64, tests },
    outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [], missed: [] },
  }));
  const region = await card();
  expect(await within(region).findAllByRole("link")).toHaveLength(15);
  expect(within(region).getByText("Showing the 20 strongest of 64 statistical suggestions")).toBeInTheDocument();
  const toggle = within(region).getByRole("button", { name: "Show all 20" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(toggle);
  expect(within(region).getAllByRole("link")).toHaveLength(20);
  const fewer = within(region).getByRole("button", { name: "Show fewer" });
  expect(fewer).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(fewer);
  expect(within(region).getAllByRole("link")).toHaveLength(15);
  expect(within(region).getByRole("button", { name: "Show all 20" })).toBeInTheDocument();
});

test("capped statistical rows beside always-included ones say how many were left out", async () => {
  const tests = [...Array.from({ length: 20 }, (_, i) => statistical(`s${String(i).padStart(2, "0")}`)),
    labelled("checkout_spec", "test_file_changed"), labelled("cart", "failing_on_branch")];
  renderCard(impact({
    suggestion: { state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20, statistical_total: 57, tests },
    outcome: null,
  }));
  const region = await card();
  expect(await within(region).findByText("Showing the 20 strongest of 57 statistical suggestions")).toBeInTheDocument();
  expect(within(region).getByText("Suggested 22 tests · outcome not recorded yet")).toBeInTheDocument();
  expect(within(region).getByRole("button", { name: "Show all 22" })).toBeInTheDocument();
});

test("too little history and no labelled tests: nothing to suggest yet", async () => {
  renderCard(impact({
    state: "not_enough_history", outcome: null,
    suggestion: { state: "not_enough_history", model_version: "stats-v1", history_runs: 2, needed_runs: 20, statistical_total: 0,
      tests: [] },
  }));
  expect(await screen.findByText("Nothing to suggest yet.")).toBeInTheDocument();
  expect(screen.queryByText("No tests are likely affected by this change")).not.toBeInTheDocument();
});

test("loading is a status of the card's own", async () => {
  server.use(http.get(IMPACT_URL, () => new Promise<never>(() => {})));
  mount();
  const region = await card();
  expect(within(region).getByRole("heading", { name: "Likely affected tests" })).toBeInTheDocument();
  expect(within(region).getByRole("status", { name: "Loading likely affected tests…" })).toBeInTheDocument();
});

test("a failed load shows the error with Retry, and Retry asks again", async () => {
  let calls = 0;
  server.use(http.get(IMPACT_URL, () => (++calls === 1
    ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
    : HttpResponse.json(impact()))));
  mount();
  const region = await card();
  expect(await within(region).findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  expect(within(region).getByRole("heading", { name: "Likely affected tests" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("link", { name: "pays" })).toBeInTheDocument();
});

describe("a pending outcome", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  test("is asked for again every few seconds until it arrives", async () => {
    let calls = 0;
    server.use(http.get(IMPACT_URL, () => HttpResponse.json(++calls === 1 ? impact({ outcome: null }) : impact())));
    mount();
    expect(await screen.findByText("Suggested 4 tests · outcome not recorded yet")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(IMPACT_POLL_MS));
    expect(await screen.findByText("All caught")).toBeInTheDocument();
    const after = calls;
    await act(() => vi.advanceTimersByTimeAsync(IMPACT_POLL_MS * 5));
    expect(calls).toBe(after); // written: no more asking
  });

  test("stops asking at the cap, and keeps saying it is not recorded yet", async () => {
    let calls = 0;
    server.use(http.get(IMPACT_URL, () => { calls += 1; return HttpResponse.json(impact({ outcome: null })); }));
    mount();
    expect(await screen.findByText("Suggested 4 tests · outcome not recorded yet")).toBeInTheDocument();
    for (let i = 0; i < IMPACT_POLL_MAX + 10; i += 1) await act(() => vi.advanceTimersByTimeAsync(IMPACT_POLL_MS));
    expect(calls).toBe(IMPACT_POLL_MAX);
    expect(screen.getByText("Suggested 4 tests · outcome not recorded yet")).toBeInTheDocument();
  });

  test("is not asked for when the run has no suggestion", async () => {
    let calls = 0;
    server.use(http.get(IMPACT_URL, () => { calls += 1;
      return HttpResponse.json(impact({ state: "not_scored", suggestion: null, outcome: null })); }));
    mount();
    expect(await screen.findByText(/No suggestion was stored/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(IMPACT_POLL_MS * 3));
    expect(calls).toBe(1);
  });
});
