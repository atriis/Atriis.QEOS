import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WidgetBoundary from "./WidgetBoundary";

let failing = true;
function Fragile() {
  if (failing) throw new Error("render broke");
  return <p>Widget body</p>;
}

beforeEach(() => {
  failing = true;
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

test("a widget that throws shows its own failure with Retry, and its sibling widget keeps working", async () => {
  render(
    <>
      <section aria-label="fragile">
        <WidgetBoundary heading={<h2>Pass-rate trend</h2>} title="Pass-rate trend"><Fragile /></WidgetBoundary>
      </section>
      <section aria-label="sibling">
        <WidgetBoundary heading={<h2>Flaky tests</h2>} title="Flaky tests"><p>Sibling body</p></WidgetBoundary>
      </section>
    </>,
  );
  const fragile = within(screen.getByRole("region", { name: "fragile" }));
  expect(fragile.getByRole("heading", { name: "Pass-rate trend" })).toBeInTheDocument();
  expect(fragile.getByRole("alert")).toHaveTextContent("This widget failed to load");
  expect(fragile.getByRole("alert")).toHaveClass("error-banner");
  const sibling = within(screen.getByRole("region", { name: "sibling" }));
  expect(sibling.getByText("Sibling body")).toBeInTheDocument();
  expect(sibling.queryByRole("alert")).not.toBeInTheDocument();
  failing = false;
  await userEvent.click(fragile.getByRole("button", { name: "Retry" }));
  expect(fragile.getByText("Widget body")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("a failed widget renders again when its settings change", () => {
  const heading = <h2>Pass-rate trend</h2>;
  const { rerender } = render(
    <WidgetBoundary heading={heading} title="Pass-rate trend" resetKey='{"branch":"main"}'><Fragile /></WidgetBoundary>,
  );
  expect(screen.getByRole("alert")).toBeInTheDocument();
  failing = false;
  // The same settings keep the failure: only a change retries on its own
  rerender(<WidgetBoundary heading={heading} title="Pass-rate trend" resetKey='{"branch":"main"}'><Fragile /></WidgetBoundary>);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  rerender(<WidgetBoundary heading={heading} title="Pass-rate trend" resetKey='{"branch":"dev"}'><Fragile /></WidgetBoundary>);
  expect(screen.getByText("Widget body")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
