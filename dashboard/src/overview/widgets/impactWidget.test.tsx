import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { partialMatchKey } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import type { ImpactAccuracy } from "../../api/impact";
import { mockOverviewData, personalState, renderOverview } from "../testing";
import { TEMPLATES } from "../templates";
import { impactAccuracy } from "./impactAccuracy";
import { addableDefinitions, newRunStaleKeys } from "./registry";

const NO_PART = { runs: 0, caught: 0, missed: 0, suggested: 0 };
const ACCURACY: ImpactAccuracy = {
  days: 7, caught: 9, missed: 3, rate: 0.75, avg_suggested: 6.4, includes_replayed: false,
  live: { runs: 25, caught: 9, missed: 3, suggested: 160 }, replayed: NO_PART, misses: [], misses_total: 3,
};

function accuracyAsked(answer: () => Response) {
  const asked: string[] = [];
  server.use(http.get("/api/v1/projects/42/analytics/impact-accuracy", ({ request }) => {
    asked.push(new URL(request.url).searchParams.get("days") ?? "");
    return answer();
  }));
  return asked;
}

test("Impact accuracy shows the share of new failures the suggestions caught and opens the Report's section", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal", settings: { period: 7 } }) });
  const asked = accuracyAsked(() => HttpResponse.json(ACCURACY));
  renderOverview();
  expect(await screen.findByText("75.0%")).toHaveClass("stat-big");
  expect(screen.getByText("Caught 9 of 12 new failures")).toBeInTheDocument();
  const heading = await screen.findByRole("heading", { name: "Impact accuracy, last 7 days" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/report?period=7&branch=*#report-impact");
  expect(screen.getByRole("link", { name: "Report" })).toHaveAttribute("href", "/projects/42/report?period=7&branch=*#report-impact");
  expect(asked).toEqual(["7"]);
});

test("the average suggestion size sits beside the rate (spec §9)", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal", settings: { period: 7 } }) });
  accuracyAsked(() => HttpResponse.json(ACCURACY));
  renderOverview();
  expect(await screen.findByText("6.4 tests suggested per run, on average")).toBeInTheDocument();
});

test("replayed runs are counted in and said", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  const asked = accuracyAsked(() => HttpResponse.json({ ...ACCURACY, days: 30, includes_replayed: true,
    replayed: { runs: 20, caught: 6, missed: 2, suggested: 90 } }));
  renderOverview();
  expect(await screen.findByText("Includes 20 replayed runs")).toBeInTheDocument();
  expect(asked).toEqual(["30"]);
});

test("no run with a stored suggestion in the period is said plainly, with Change settings", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  accuracyAsked(() => HttpResponse.json({ ...ACCURACY, days: 30, caught: 0, missed: 0, rate: null, avg_suggested: null,
    live: NO_PART }));
  renderOverview();
  expect(await screen.findByText("No run with a stored suggestion in the last 30 days")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Change settings/ })).toBeInTheDocument();
  expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
});

test("runs without new failures show a dash, never 0%", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  accuracyAsked(() => HttpResponse.json({ ...ACCURACY, days: 30, caught: 0, missed: 0, rate: null, avg_suggested: 3,
    live: { runs: 4, caught: 0, missed: 0, suggested: 12 } }));
  renderOverview();
  expect(await screen.findByText("No new failures in 4 runs")).toBeInTheDocument();
  expect(screen.getByText("—")).toHaveClass("stat-big");
  expect(screen.queryByText(/0\.0%/)).not.toBeInTheDocument();
});

test("a failure stays in the card with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  let calls = 0;
  accuracyAsked(() => (++calls === 1
    ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
    : HttpResponse.json(ACCURACY)));
  renderOverview();
  expect(await screen.findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("75.0%")).toBeInTheDocument();
});

test("a new latest run refreshes the figure through the Report's key", () => {
  expect(impactAccuracy.staleKeys?.(42)).toEqual([["report", 42, "impact-accuracy"]]);
  expect(newRunStaleKeys(42).some((key) => partialMatchKey(["report", 42, "impact-accuracy", 7], key))).toBe(true);
});

test("Add widget offers it last, and no template carries it", () => {
  expect(addableDefinitions().map((d) => d.type).at(-1)).toBe("impact_accuracy");
  expect(TEMPLATES.flatMap((t) => t.layout.widgets.map((w) => w.type))).not.toContain("impact_accuracy");
});
