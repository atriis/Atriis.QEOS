import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import LastResultPill from "./LastResultPill";

test.each([["failed", /failed/i], ["errored", /errored/i], ["passed", /passed/i], ["skipped", /skipped/i]])(
  "shows %s", (status, text) => {
    render(<LastResultPill result={{ status, run_id: 1, branch: null, environment: null, started_at: new Date().toISOString(), message: null }} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
test("no runs yet", () => {
  render(<LastResultPill result={null} />);
  expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
});
