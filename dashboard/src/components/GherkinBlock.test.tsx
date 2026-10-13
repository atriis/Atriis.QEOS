import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import GherkinBlock from "./GherkinBlock";

// The tokenizer splits a step into a keyword and its text, so the line is found by the failed marker instead of by its words
const failedLine = () => document.querySelector(".gk-failed");

test.each([true, false])("marks the failed line and shows its tip on focus (numbered=%s)", async (numbered) => {
  render(<GherkinBlock numbered={numbered} text={"Scenario: s\n  When a\n  Then b"} failed={{ line: 2, tip: <span>boom</span> }} />);
  const line = failedLine() as HTMLElement;
  expect(line).toHaveTextContent(/failed/i);
  expect(document.querySelectorAll(".gk-failed")).toHaveLength(1);
  line.focus();
  expect(await screen.findByRole("tooltip")).toHaveTextContent("boom");
  expect(line).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("shows the tip on hover and hides it on leave", async () => {
  render(<GherkinBlock text={"Scenario: s\n  When a"} failed={{ line: 2, tip: <span>boom</span> }} />);
  const line = failedLine() as HTMLElement;
  await userEvent.hover(line);
  expect(await screen.findByRole("tooltip")).toBeInTheDocument();
  await userEvent.unhover(line);
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
});

test("without failed nothing is marked", () => {
  render(<GherkinBlock numbered text={"Scenario: s\n  When a"} />);
  expect(document.querySelector(".gk-failed")).toBeNull();
});

test("plain mode: one line per Gherkin line, no blank line after the failed one", () => {
  const text = "Scenario: s\n  Given x\n  When a\n  Then b";
  render(<GherkinBlock text={text} failed={{ line: 3, tip: <span>boom</span> }} />);
  const pre = document.querySelector("pre") as HTMLElement;
  expect((pre.textContent ?? "").replace("Failed step: ", "").replace(" failed", "")).toBe(text);
});

test("the tip is a portal on the body, so it is neither clipped by nor copied with the block", async () => {
  render(<GherkinBlock text={"Scenario: s\n  When a"} failed={{ line: 2, tip: <span>boom</span> }} />);
  (failedLine() as HTMLElement).focus();
  const tip = await screen.findByRole("tooltip");
  expect(tip.parentElement).toBe(document.body);
  expect(tip.closest("pre")).toBeNull();
  expect(tip).toHaveStyle({ position: "fixed" });
});

test("Escape inside the tip returns focus to the failed line and closes the tip", async () => {
  render(<GherkinBlock text={"Scenario: s\n  When a"} failed={{ line: 2, tip: <a href="#run">Open run</a> }} />);
  const line = failedLine() as HTMLElement;
  line.focus();
  const link = await screen.findByRole("link", { name: "Open run" });
  link.focus();
  expect(screen.getByRole("tooltip")).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).toBeNull();
  expect(document.activeElement).toBe(line);
});

test("the tip stays open while the pointer moves from the line onto it", async () => {
  render(<GherkinBlock text={"Scenario: s\n  When a"} failed={{ line: 2, tip: <span>boom</span> }} />);
  const line = failedLine() as HTMLElement;
  await userEvent.hover(line);
  const tip = await screen.findByRole("tooltip");
  await userEvent.unhover(line);
  await userEvent.hover(tip);
  await new Promise((r) => setTimeout(r, 250));
  expect(screen.getByRole("tooltip")).toBeInTheDocument();
  await userEvent.unhover(tip);
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
});

test("numbered: a failed line keeps its annotation next to the marker, and is announced as the failed step", () => {
  render(<GherkinBlock numbered text={"Scenario: s\n  When a"} annotations={new Map([[2, <span>case 7</span>]])} failed={{ line: 2, tip: <span>boom</span> }} />);
  const end = document.querySelector(".gk-failed-end") as HTMLElement;
  expect(end).toHaveTextContent(/failed/);
  expect(end).toHaveTextContent("case 7");
  expect(failedLine()).toHaveTextContent("Failed step:");
});

function withNeighbours() {
  render(
    <div>
      <button>before</button>
      <GherkinBlock text={"Scenario: s\n  When a"} failed={{ line: 2, tip: <a href="#run">Open run</a> }} />
      <button>after</button>
    </div>,
  );
}

test("Tab goes from the failed line into the tip, Shift+Tab back, and out of the tip to the next element after the block", async () => {
  withNeighbours();
  const line = failedLine() as HTMLElement;
  await userEvent.click(screen.getByRole("button", { name: "before" }));
  await userEvent.tab(); // the block itself
  await userEvent.tab(); // the failed line
  expect(document.activeElement).toBe(line);
  await userEvent.tab();
  expect(document.activeElement).toBe(screen.getByRole("link", { name: "Open run" }));
  await userEvent.tab({ shift: true });
  expect(document.activeElement).toBe(line);
  await userEvent.tab();
  await userEvent.tab();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "after" }));
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("after Escape the tip stays closed when the pointer leaves and comes back while the line has focus", async () => {
  render(<GherkinBlock text={"Scenario: s\n  When a"} failed={{ line: 2, tip: <span>boom</span> }} />);
  const line = failedLine() as HTMLElement;
  line.focus();
  await screen.findByRole("tooltip");
  await userEvent.keyboard("{Escape}");
  await userEvent.hover(line);
  await userEvent.unhover(line);
  await new Promise((r) => setTimeout(r, 250));
  await userEvent.hover(line);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("Tab out of the tip skips hidden, inert and disabled elements after the block", async () => {
  render(
    <>
      <GherkinBlock text={"Scenario: s\n  When a"} failed={{ line: 2, tip: <a href="#run">Open run</a> }} />
      <button hidden>hidden attr</button>
      <div style={{ display: "none" }}><button>display none</button></div>
      <div style={{ visibility: "hidden" }}><button>visibility hidden</button></div>
      <div inert><button>inert</button></div>
      <span tabIndex={0} {...{ disabled: true }}>disabled tabindex</span>
      <button>real next</button>
    </>,
  );
  const line = failedLine() as HTMLElement;
  line.focus();
  await userEvent.tab();
  expect(document.activeElement).toBe(screen.getByRole("link", { name: "Open run" }));
  await userEvent.tab();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "real next" }));
});
