import { screen } from "@testing-library/react";
import { mockOverviewData, personalState, renderOverview } from "./testing";

test("a stored widget of an unknown type is skipped and logged once", async () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  mockOverviewData({ layout: personalState(
    { id: "x1", type: "from_a_newer_dashboard", size: "wide" },
    { id: "x2", type: "from_a_newer_dashboard", size: "normal" },
    { id: "w1", type: "latest_run", size: "wide" },
  ) });
  renderOverview();
  expect(await screen.findByRole("region", { name: "Latest run" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
  expect(warn.mock.calls.filter(([message]) => String(message).includes("from_a_newer_dashboard"))).toHaveLength(1);
  warn.mockRestore();
});
