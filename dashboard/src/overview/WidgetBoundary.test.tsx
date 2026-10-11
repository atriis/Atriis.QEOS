import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WidgetBoundary from "./WidgetBoundary";

let failing = true;
function Fragile() {
  if (failing) throw new Error("render broke");
  return <p>Widget body</p>;
}

test("a widget that throws shows its own failure with Retry, and the rest keeps working", async () => {
  const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <>
      <section aria-label="fragile">
        <WidgetBoundary heading={<h2>Pass-rate trend</h2>} title="Pass-rate trend"><Fragile /></WidgetBoundary>
      </section>
      <p>Another widget</p>
    </>,
  );
  expect(screen.getByRole("heading", { name: "Pass-rate trend" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("This widget failed to load");
  expect(screen.getByRole("alert")).toHaveClass("error-banner");
  expect(screen.getByText("Another widget")).toBeInTheDocument();
  failing = false;
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(screen.getByText("Widget body")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  quiet.mockRestore();
});
