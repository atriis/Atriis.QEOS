import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import type { CaseAreas } from "../../api/cases";
import { ApiError } from "../../api/http";
import ReportFilterBar from "./ReportFilterBar";
import { describeFilters, formatPeriod } from "./describeFilters";
import { addDays, parseReportFilters, todayIn, useReportFilters } from "./useReportFilters";

const AREAS: CaseAreas = {
  generatedAt: "v1", counts: { cases: 2, linked: 2, manual: 0 },
  folders: ["features/booking"], features: ["Booking", "Payments"], labels: ["smoke"], suites: [{ id: 12, name: "Regression" }],
  cases: [
    { number: 1, title: "a", testKey: "a".repeat(64), folder: "features/booking", feature: "Booking", labels: ["smoke"], suiteIds: [12] },
    { number: 2, title: "b", testKey: "b".repeat(64), folder: "features/booking", feature: "Payments", labels: [], suiteIds: [] },
  ],
};
const ok = { data: AREAS, error: null, isPending: false, refetch: vi.fn() };

type AreasProp = { data?: CaseAreas; error: unknown; isPending: boolean; refetch: () => unknown };

function Harness({ caseAreas = ok, runUrlsError = null }: { caseAreas?: AreasProp; runUrlsError?: unknown }) {
  const { filters, update, clearAll } = useReportFilters("UTC");
  const location = useLocation();
  return (
    <>
      <ReportFilterBar filters={filters} update={update} clearAll={clearAll} today={todayIn("UTC")} defaultBranch="main"
        caseAreas={caseAreas} runUrls={{ error: runUrlsError, refetch: vi.fn() }}
        facets={{ branches: ["main", "release/2.4"], environments: ["staging"] }} />
      <output data-testid="search">{location.search}</output>
    </>
  );
}

function renderAt(search = "", props: Parameters<typeof Harness>[0] = {}) {
  render(
    <MemoryRouter initialEntries={[`/projects/42/report${search}`]}>
      <Routes><Route path="/projects/:projectId/report" element={<Harness {...props} />} /></Routes>
    </MemoryRouter>,
  );
}
const search = () => screen.getByTestId("search").textContent;

test("period chips; Custom shows the range row with From focused, and Cancel hides it", async () => {
  renderAt();
  const chips = screen.getByRole("group", { name: "Quick filters" });
  expect(within(chips).getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(chips).getByRole("button", { name: "7 days" }));
  expect(search()).toBe("?period=7");
  await userEvent.click(within(chips).getByRole("button", { name: "7 days" }));  // pressing the pressed preset keeps it
  expect(search()).toBe("?period=7");
  await userEvent.click(within(chips).getByRole("button", { name: "Custom…" }));
  const row = screen.getByRole("form", { name: "Custom period" });
  expect(within(row).getByLabelText("From")).toHaveFocus();
  // The dates live in the row, not in the Filters form
  expect(screen.getByText(/^Filters/, { selector: "summary" }).closest("details")).not.toContainElement(row);
  await userEvent.click(within(row).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("form", { name: "Custom period" })).toBeNull();
  expect(search()).toBe("?period=7");
});

test("an applied custom range shows the row with its dates and no Cancel", () => {
  renderAt("?from=2026-09-01&to=2026-09-10");
  const row = screen.getByRole("form", { name: "Custom period" });
  expect(within(row).getByLabelText("From")).toHaveValue("2026-09-01");
  expect(within(row).getByLabelText("To")).toHaveValue("2026-09-10");
  expect(within(row).queryByRole("button", { name: "Cancel" })).toBeNull();
  expect(screen.getByRole("button", { name: "Custom: 1 Sep – 10 Sep 2026" })).toHaveAttribute("aria-pressed", "true");
});

test("the default branch is a chip; removing it means every branch, and removing that returns to the default", async () => {
  renderAt();
  await userEvent.click(screen.getByRole("button", { name: "Remove filter Branch: main (default)" }));
  expect(search()).toBe("?branch=*");
  await userEvent.click(screen.getByRole("button", { name: "Remove filter Branch: all branches" }));
  expect(search()).toBe("");
});

test("applied chips name each filter; removing one moves focus to the next chip", async () => {
  renderAt("?env=staging&ci=jenkins&origin=qeos&area=feature:Booking&suite=12");
  for (const name of ["Environment: staging", "CI: Jenkins", "Origin: Requested from QEOS", "Feature: Booking", "Suite: Regression"]) {
    expect(screen.getByText(name)).toBeInTheDocument();
  }
  expect(screen.getByText("Feature: Booking").closest(".fchip")).toHaveAttribute("title", "Only automated tests linked to a case are counted");
  await userEvent.click(screen.getByRole("button", { name: "Remove filter Environment: staging" }));
  expect(search()).not.toContain("env=");
  expect(screen.getByRole("button", { name: "Remove filter CI: Jenkins" })).toHaveFocus();
});

test("Clear all keeps the period", async () => {
  renderAt("?period=90&env=staging");
  await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
  expect(search()).toBe("?period=90");
});

test("the area is chosen in two steps, by keyboard", async () => {
  renderAt();
  await userEvent.click(screen.getByRole("button", { name: "+ Filter" }));
  await userEvent.selectOptions(screen.getByLabelText("Area"), "feature");
  await userEvent.selectOptions(screen.getByLabelText("Feature"), "Payments");
  expect(search()).toBe("?area=feature%3APayments");
  await userEvent.selectOptions(screen.getByLabelText("Area"), "folder");
  expect(search()).toBe("");                                           // a new kind clears the old value
  expect(screen.getByRole("button", { name: /folder/i })).toBeInTheDocument();  // FolderSelect's trigger
});

test("a custom range is checked before it is applied", async () => {
  renderAt();
  await userEvent.click(screen.getByRole("button", { name: "Custom…" }));
  const today = todayIn("UTC");
  await userEvent.type(screen.getByLabelText("From"), today);
  await userEvent.type(screen.getByLabelText("To"), "2020-01-01");
  await userEvent.click(within(screen.getByRole("form", { name: "Custom period" })).getByRole("button", { name: "Apply" }));
  expect(screen.getByRole("alert")).toHaveTextContent("From must be on or before To");
  expect(search()).toBe("");
});

test("case-areas failing disables area and suite with Retry; a run-urls failure shows on the origin filter", async () => {
  renderAt("?origin=ci", { caseAreas: { data: undefined, error: new ApiError(409, "x", "too_many_cases"), isPending: false, refetch: vi.fn() },
    runUrlsError: new ApiError(500, "down") });
  await userEvent.click(screen.getByRole("button", { name: "+ Filter" }));
  expect(screen.getByLabelText("Area")).toBeDisabled();
  expect(screen.getByText("This project has more cases than the report can join (50,000)")).toBeInTheDocument();
  expect(screen.getByText(/play requests could not be loaded/i)).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(2);
});

test("describeFilters and formatPeriod", () => {
  const f = parseReportFilters(new URLSearchParams("branch=*&ci=github_actions"), "2026-10-08").filters;
  expect(describeFilters(f, "main").map((a) => `${a.name}: ${a.value}`)).toEqual(["Branch: all branches", "CI: GitHub Actions"]);
  expect(formatPeriod("2026-09-09", "2026-10-08")).toBe("9 Sep – 8 Oct 2026");
  expect(formatPeriod("2025-12-20", "2026-01-05")).toBe("20 Dec 2025 – 5 Jan 2026");
});

async function applyRange(from: string, to: string) {
  await userEvent.click(screen.getByRole("button", { name: "Custom…" }));
  if (from) await userEvent.type(screen.getByLabelText("From"), from);
  if (to) await userEvent.type(screen.getByLabelText("To"), to);
  await userEvent.click(within(screen.getByRole("form", { name: "Custom period" })).getByRole("button", { name: "Apply" }));
}

test.each([
  ["only one date", (t: string) => [t, ""], "Give both From and To", ["To"]],
  ["span over 90 days", (t: string) => [addDays(t, -100), t], "The period can be at most 90 days", ["From", "To"]],
  ["to after today", (t: string) => [t, addDays(t, 1)], "To cannot be after today", ["To"]],
  ["from older than 400 days", (t: string) => [addDays(t, -420), addDays(t, -410)], "From can be at most 400 days ago", ["From"]],
])("range check: %s", async (_name, dates, message, invalid) => {
  renderAt();
  const [from, to] = dates(todayIn("UTC"));
  await applyRange(from, to);
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent(message);
  for (const label of ["From", "To"]) {
    const input = screen.getByLabelText(label);
    if (invalid.includes(label)) {
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input).toHaveAttribute("aria-describedby", alert.id);
    } else {
      expect(input).not.toHaveAttribute("aria-invalid");
    }
  }
  expect(search()).toBe("");
});

test("the range error goes away when a date is edited", async () => {
  renderAt();
  await applyRange("2026-01-02", "2026-01-01");
  expect(screen.getByRole("alert")).toBeInTheDocument();
  await userEvent.clear(screen.getByLabelText("From"));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByLabelText("From")).not.toHaveAttribute("aria-invalid");
});

test("Retry inside the form does not submit it", async () => {
  const refetch = vi.fn();
  renderAt("", { caseAreas: { data: undefined, error: new ApiError(500, "down"), isPending: false, refetch } });
  await userEvent.click(screen.getByRole("button", { name: "+ Filter" }));
  await userEvent.type(screen.getByLabelText("Environment"), "staging");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(refetch).toHaveBeenCalledTimes(1);
  expect(search()).toBe("");
});
