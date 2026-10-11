import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { emptyReport } from "../pages/report/testFixtures";
import { mockOverviewData, renderOverview } from "./testing";

const titles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

beforeEach(() => {
  // What the template widgets ask for, answered quietly
  server.use(
    http.post("/api/v1/projects/42/analytics/report", () => HttpResponse.json(emptyReport())),
    http.get("/api/v1/projects/42/cases", () => HttpResponse.json({ total: 0, items: [] })),
    http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json({
      generated_at: "v1", counts: { cases: 0, linked: 0, manual: 0 }, folders: [], features: [], labels: [], suites: [], cases: [],
    })),
    http.get("/api/v1/projects/42/analytics/branches", () => HttpResponse.json([])),
  );
});

async function useTemplate(label: string) {
  await userEvent.click(await screen.findByRole("button", { name: "Customise" }));
  await userEvent.click(screen.getByRole("button", { name: "Add widget" }));
  await userEvent.click(within(screen.getByRole("region", { name: "Add a widget" })).getByRole("button", { name: `Use the ${label} layout` }));
}

test("a template replaces the draft, says so, and Cancel still undoes it", async () => {
  mockOverviewData();
  renderOverview();
  await useTemplate("QA lead");
  expect(titles()).toEqual(["Pass-rate trend", "Failure causes", "Regressions and flips", "Coverage", "Test cases"]);
  expect(screen.getByText("QA lead layout applied: 5 widgets")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Add a widget" })).not.toBeInTheDocument();
  // The widget code loads on demand; on a slow machine its card settles after the first render
  const trend = await screen.findByRole("region", { name: "Pass-rate trend" });
  await waitFor(() => expect(trend).toHaveFocus());
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(titles()).toEqual(["Latest run", "Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
});

test("the template list names each template's widgets", async () => {
  mockOverviewData();
  renderOverview();
  await userEvent.click(await screen.findByRole("button", { name: "Customise" }));
  await userEvent.click(screen.getByRole("button", { name: "Add widget" }));
  const panel = screen.getByRole("region", { name: "Add a widget" });
  expect(within(panel).getByText("Flaky tests, last 30 days, Regressions and flips, Slowest tests, Pass-rate trend")).toBeInTheDocument();
});

test.each([
  ["Developer", ["Latest run", "Failing in latest run", "Branch health", "Recent runs", "My recent failures"]],
  ["Flaky hunt", ["Flaky tests, last 30 days", "Regressions and flips", "Slowest tests", "Pass-rate trend"]],
])("the %s template holds the widgets the spec names", async (label, expected) => {
  mockOverviewData();
  renderOverview();
  await useTemplate(label);
  expect(titles()).toEqual(expected);
});
