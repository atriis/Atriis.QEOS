import { render, screen } from "@testing-library/react";
import ScreenshotButton from "./ScreenshotButton";

test("a step's camera shows its count up to 9, then 9+; the accessible name keeps the number", () => {
  const { rerender } = render(<ScreenshotButton kind="step" count={7} onOpen={() => {}} />);
  expect(screen.getByRole("button", { name: "Screenshots for this step (7)" })).toHaveTextContent("7");
  rerender(<ScreenshotButton kind="step" count={120} onOpen={() => {}} />);
  const button = screen.getByRole("button", { name: "Screenshots for this step (120)" });
  expect(button).toHaveTextContent("9+");
  expect(button).not.toHaveTextContent("120");
});

test("the other cameras show the whole count", () => {
  render(<ScreenshotButton kind="link" name="TC-1" count={120} onOpen={() => {}} />);
  expect(screen.getByRole("button", { name: "Screenshots of TC-1 (120)" })).toHaveTextContent("120");
});
