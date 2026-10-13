import { render, screen } from "@testing-library/react";
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
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("without failed nothing is marked", () => {
  render(<GherkinBlock numbered text={"Scenario: s\n  When a"} />);
  expect(document.querySelector(".gk-failed")).toBeNull();
});
