import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RunStrip, { RunStripSkeleton, stripSummary, type StripEntry, type StripStatus } from "./RunStrip";

const entries = (statuses: StripStatus[]): StripEntry[] =>
  statuses.map((status, i) => ({ run_id: 433 + i, started_at: `2026-10-06T1${i}:02:00Z`, branch: "main", status }));

const SUMMARY = "Last 4 runs: 1 passed, 1 failed, 1 re-run, 1 skipped";
const LINK_NAME = `${SUMMARY}, opens run #436`;

test("the strip is one link named by the summary plus its target, to the newest run", () => {
  render(<MemoryRouter><RunStrip projectId={5} entries={entries(["passed", "failed", "rerun", "skipped"])} /></MemoryRouter>);
  const link = screen.getByRole("link", { name: LINK_NAME });
  expect(link).toHaveAttribute("href", "/projects/5/runs/436");
  expect(screen.getAllByRole("link")).toHaveLength(1);
});

test("each bar is a span with a title, and a hidden per-run list follows the link", () => {
  const { container } = render(<MemoryRouter><RunStrip projectId={5} entries={entries(["passed", "failed", "rerun", "skipped"])} /></MemoryRouter>);
  const bars = container.querySelectorAll("span.run-bar");
  expect(bars).toHaveLength(4);
  expect(bars[1]).toHaveClass("bar-failed");
  expect(bars[1].getAttribute("title")).toMatch(/run #434.*failed/i);
  expect(bars[2]).toHaveClass("bar-rerun");
  expect(bars[3]).toHaveClass("bar-skipped");
  // Outside the link: the link's aria-label would otherwise hide the list from screen readers.
  expect(container.querySelector("a ol")).toBeNull();
  const items = container.querySelectorAll("ol.sr-only li");
  expect(items).toHaveLength(4);
  expect(items[1].textContent).toMatch(/run #434.*failed/i);
  expect(items[2].textContent).toMatch(/run #435.*re-run/i);
});

test("only runs the test was in show: fewer results mean a shorter strip, never a gap", () => {
  const { container } = render(<MemoryRouter><RunStrip projectId={5} entries={entries(["failed", "passed"])} /></MemoryRouter>);
  expect(container.querySelectorAll("span.run-bar")).toHaveLength(2);
  expect(container.querySelector(".bar-none")).toBeNull();
  expect(screen.getByRole("link", { name: "Last 2 runs: 1 passed, 1 failed, opens run #434" })).toBeInTheDocument();
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

test("bars are hidden from assistive tech, newest run last", () => {
  const { container } = render(<MemoryRouter><RunStrip projectId={5} entries={entries(["passed", "failed", "rerun", "skipped"])} /></MemoryRouter>);
  const bars = container.querySelectorAll("span.run-bar");
  bars.forEach((b) => expect(b).toHaveAttribute("aria-hidden", "true"));
  expect(bars[3].getAttribute("title")).toMatch(/run #436/i);
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
