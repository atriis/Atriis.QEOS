import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../../../test/server";
import { setAccessToken } from "../../../auth/tokens";
import type { ImpactAccuracy } from "../../../api/impact";
import ImpactSection from "./ImpactSection";

const ACCURACY_URL = "/api/v1/projects/42/analytics/impact-accuracy";
const key = (name: string) => name.padEnd(64, "0");
const NO_PART = { runs: 0, caught: 0, missed: 0, suggested: 0 };

function accuracy(extra: Partial<ImpactAccuracy> = {}): ImpactAccuracy {
  return {
    days: 30, caught: 9, missed: 3, rate: 0.75, avg_suggested: 6.4, includes_replayed: false,
    live: { runs: 25, caught: 9, missed: 3, suggested: 160 }, replayed: NO_PART,
    misses: [{ test_key: key("refunds"), suite: "s", class_name: "C", name: "refunds", run_id: 70,
      started_at: "2026-10-10T09:00:00Z", branch: "main", replayed: false }],
    misses_total: 3, ...extra,
  };
}

function renderSection(answer: () => Response, days: 7 | 14 | 30 = 30, followsReport = true) {
  const asked: string[] = [];
  server.use(http.get(ACCURACY_URL, ({ request }) => {
    asked.push(new URL(request.url).searchParams.get("days") ?? "");
    return answer();
  }));
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ImpactSection projectId={42} days={days} followsReport={followsReport} onResetFilters={() => undefined} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return asked;
}

const region = () => screen.findByRole("region", { name: "Test impact" });

test("the figure, what it counts, and the misses with links", async () => {
  const asked = renderSection(() => HttpResponse.json(accuracy()));
  const section = await region();
  expect(await within(section).findByText("75.0%")).toHaveClass("stat-big");
  expect(within(section).getByText("Suggestions caught 9 of 12 new failures")).toBeInTheDocument();
  expect(within(section).getByText(/^Last 30 days, every branch/)).toBeInTheDocument();
  expect(within(section).getByRole("link", { name: "refunds" })).toHaveAttribute("href", `/projects/42/tests/${key("refunds")}?branch=main`);
  expect(within(section).getByRole("link", { name: "#70" })).toHaveAttribute("href", "/projects/42/runs/70");
  expect(within(section).getByText("And 2 more.")).toBeInTheDocument();
  expect(asked).toEqual(["30"]);
});

test("the average suggestion size sits beside the catch rate (spec §9)", async () => {
  renderSection(() => HttpResponse.json(accuracy()));
  const section = await region();
  const figures = (await within(section).findByText("75.0%")).closest(".impact-figures") as HTMLElement;
  expect(within(figures).getByText("6.4")).toHaveClass("stat-big");
  expect(within(figures).getByText("tests suggested per run, on average")).toBeInTheDocument();
});

test("replayed and live parts are told apart", async () => {
  renderSection(() => HttpResponse.json(accuracy({
    includes_replayed: true, live: { runs: 10, caught: 3, missed: 1, suggested: 50 }, replayed: { runs: 15, caught: 6, missed: 2, suggested: 110 },
    misses: [{ test_key: key("refunds"), suite: "s", class_name: "C", name: "refunds", run_id: 70,
      started_at: "2026-10-10T09:00:00Z", branch: null, replayed: true }],
  })), 7);
  const section = await region();
  expect(await within(section).findByText("caught 3 of 4 new failures in 10 runs")).toBeInTheDocument();
  expect(within(section).getByText("caught 6 of 8 new failures in 15 runs")).toBeInTheDocument();
  expect(within(section).getByText("Replayed", { selector: ".pill" })).toBeInTheDocument();
  expect(within(section).getByText("no branch")).toBeInTheDocument();
  expect(within(section).getByRole("link", { name: "refunds" })).toHaveAttribute("href", `/projects/42/tests/${key("refunds")}`);
});

test("no run with a stored suggestion says so plainly", async () => {
  renderSection(() => HttpResponse.json(accuracy({ caught: 0, missed: 0, rate: null, avg_suggested: null, live: NO_PART,
    misses: [], misses_total: 0 })), 7);
  expect(await within(await region()).findByText("No run with a stored suggestion in the last 7 days")).toBeInTheDocument();
});

test("runs without new failures have no rate: a dash, never 0%", async () => {
  renderSection(() => HttpResponse.json(accuracy({ caught: 0, missed: 0, rate: null, avg_suggested: 3,
    live: { runs: 4, caught: 0, missed: 0, suggested: 12 }, misses: [], misses_total: 0 })));
  const section = await region();
  expect(await within(section).findByText("No new failures in 4 runs with a stored suggestion")).toBeInTheDocument();
  expect(within(section).getByText("—")).toHaveClass("stat-big");
  expect(within(section).queryByText(/0\.0%/)).not.toBeInTheDocument();
});

test("a Report period that is not the last 7, 14 or 30 days falls back to 30 and says so", async () => {
  renderSection(() => HttpResponse.json(accuracy()), 30, false);
  expect(await within(await region()).findByText(/^Last 30 days, every branch \(the Report's period is not the last 7, 14 or 30 days\)/))
    .toBeInTheDocument();
});

test("a failure shows in the section with Retry", async () => {
  let calls = 0;
  renderSection(() => (++calls === 1
    ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
    : HttpResponse.json(accuracy())));
  const section = await region();
  expect(await within(section).findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  await userEvent.click(within(section).getByRole("button", { name: "Retry" }));
  expect(await within(section).findByText("75.0%")).toBeInTheDocument();
});
