import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import RunStrip, { RunStripSkeleton, stripSummary, type StripEntry, type StripStatus } from "./RunStrip";

const entries = (statuses: StripStatus[]): StripEntry[] =>
  statuses.map((status, i) => ({ run_id: 433 + i, started_at: `2026-10-06T1${i}:02:00Z`, branch: "main", status }));

const SUMMARY = "Last 4 runs: 1 passed, 1 failed, 1 re-run, 1 skipped";
const FOUR = entries(["passed", "failed", "rerun", "skipped"]);

test("each bar is a link to its own run, in a group named by the summary", () => {
  render(<MemoryRouter><RunStrip projectId={5} entries={FOUR} /></MemoryRouter>);
  expect(screen.getByRole("group", { name: SUMMARY })).toBeInTheDocument();
  const links = screen.getAllByRole("link");
  expect(links).toHaveLength(4);
  expect(links[1]).toHaveAccessibleName(/^Run #434, .+: failed$/);
  expect(links[1]).toHaveAttribute("href", "/projects/5/runs/434");
  expect(links[2]).toHaveAccessibleName(/^Run #435, .+: re-run$/);
});

test("with href, a bar opens what the caller names for that run", () => {
  render(<MemoryRouter><RunStrip projectId={5} entries={FOUR} href={(run) => `/projects/5/cases/12?run=${run}`} /></MemoryRouter>);
  expect(screen.getAllByRole("link")[1]).toHaveAttribute("href", "/projects/5/cases/12?run=434");
});

test("the strip is one tab stop, on the newest run; arrow keys, Home and End move between bars", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter><RunStrip projectId={5} entries={FOUR} /></MemoryRouter>);
  const links = screen.getAllByRole("link");
  expect(links.map((l) => l.getAttribute("tabindex"))).toEqual(["-1", "-1", "-1", "0"]);
  await user.tab();
  expect(links[3]).toHaveFocus();
  await user.keyboard("{ArrowLeft}");
  expect(links[2]).toHaveFocus();
  expect(links[2]).toHaveAttribute("tabindex", "0");
  expect(links[3]).toHaveAttribute("tabindex", "-1");
  await user.keyboard("{Home}");
  expect(links[0]).toHaveFocus();
  await user.keyboard("{ArrowLeft}");
  expect(links[0]).toHaveFocus();
  await user.keyboard("{End}{ArrowRight}");
  expect(links[3]).toHaveFocus();
});

test("bars keep their status classes, a tooltip, and are hidden inside their link", () => {
  const { container } = render(<MemoryRouter><RunStrip projectId={5} entries={FOUR} /></MemoryRouter>);
  const bars = container.querySelectorAll("a span.run-bar");
  expect(bars).toHaveLength(4);
  expect(bars[1]).toHaveClass("bar-failed");
  expect(bars[2]).toHaveClass("bar-rerun");
  expect(bars[3]).toHaveClass("bar-skipped");
  bars.forEach((b) => expect(b).toHaveAttribute("aria-hidden", "true"));
  expect(screen.getAllByRole("link")[1].getAttribute("title")).toMatch(/run #434.*failed/i);
});

test("only runs the test was in show: fewer results mean a shorter strip, never a gap", () => {
  const { container } = render(<MemoryRouter><RunStrip projectId={5} entries={entries(["failed", "passed"])} /></MemoryRouter>);
  expect(container.querySelectorAll("span.run-bar")).toHaveLength(2);
  expect(container.querySelector(".bar-none")).toBeNull();
  expect(screen.getByRole("group", { name: "Last 2 runs: 1 passed, 1 failed" })).toBeInTheDocument();
});

test("summary only names kinds that occur", () => {
  expect(stripSummary(["passed", "passed"])).toBe("Last 2 runs: 2 passed");
});

test("the skeleton is ten hidden bars with a hidden-text label", () => {
  const { container } = render(<RunStripSkeleton />);
  expect(container.querySelectorAll(".run-bar.bar-loading")).toHaveLength(10);
  container.querySelectorAll(".run-bar").forEach((b) => expect(b).toHaveAttribute("aria-hidden", "true"));
  expect(screen.getByText("Loading last runs")).toHaveClass("sr-only");
});

test("no results is plain text, not an image", () => {
  const { container } = render(<MemoryRouter><RunStrip projectId={5} entries={[]} /></MemoryRouter>);
  expect(screen.getByText("No runs yet")).toHaveClass("muted");
  expect(screen.queryByRole("img")).toBeNull();
  expect(container.querySelector(".run-bar")).toBeNull();
});

test("singular summary", () => {
  expect(stripSummary(["failed"])).toBe("Last 1 run: 1 failed");
});
