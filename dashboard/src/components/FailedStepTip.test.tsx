import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import FailedStepTip from "./FailedStepTip";

test("shows the error, branch, environment, time and a run link", () => {
  render(<MemoryRouter><FailedStepTip projectId={3} result={{ status: "failed", run_id: 9, branch: "main",
    environment: "staging", started_at: new Date().toISOString(), message: "boom", failed_step: { text: "When a" } }} /></MemoryRouter>);
  expect(screen.getByText("boom")).toBeInTheDocument();
  expect(screen.getByText(/main/)).toBeInTheDocument();
  expect(screen.getByText(/staging/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /open run/i })).toHaveAttribute("href", "/projects/3/runs/9");
});

test("says so when there is no message", () => {
  render(<MemoryRouter><FailedStepTip projectId={3} result={{ status: "failed", run_id: 9, branch: null, environment: null, started_at: new Date().toISOString(), message: null }} /></MemoryRouter>);
  expect(screen.getByText("No error message")).toBeInTheDocument();
});
