import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LogValuesLine from "./LogValuesLine";

const PLAIN = [
  { name: "route_key", values: ["wasToBos"], link_template: null },
  { name: "trip_id", values: ["3960562", "3960563"], link_template: null },
];

function setClipboard(writeText: (t: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

test("names each pattern with its values, in a group called Log values", () => {
  render(<LogValuesLine values={PLAIN} />);
  const group = screen.getByRole("group", { name: "Log values" });
  expect(group).toHaveTextContent(/^Log values/);
  expect(group).toHaveTextContent(/route_key:\s*wasToBos/);
  expect(group).toHaveTextContent(/trip_id:\s*3960562,\s*3960563/);
  expect(within(group).queryByRole("link")).toBeNull();
});

test("nothing at all without values", () => {
  const { container } = render(<LogValuesLine values={[{ name: "trip_id", values: [], link_template: null }]} />);
  expect(container).toBeEmptyDOMElement();
  const { container: none } = render(<LogValuesLine values={undefined} />);
  expect(none).toBeEmptyDOMElement();
});

test("with an https template a value is a new-tab link with the value encoded", () => {
  render(<LogValuesLine values={[{ name: "route_key", values: ["a/b c"], link_template: "https://backoffice.example.com/routes/{value}" }]} />);
  const link = screen.getByRole("link", { name: /a\/b c/ });
  expect(link).toHaveAttribute("href", "https://backoffice.example.com/routes/a%2Fb%20c");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(link).toHaveAccessibleName("a/b c (opens in a new tab)");
});

test("a template that is not https, as an old row or a tampered answer might hold, gives no link", () => {
  render(<LogValuesLine values={[{ name: "trip_id", values: ["1"], link_template: "javascript:alert(1)//{value}" }]} />);
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.getByText("1")).toBeInTheDocument();
});

test("Copy writes the value and says Copied, announced politely", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  setClipboard(writeText);
  render(<LogValuesLine values={PLAIN} label="Log values of TC-12" />);
  const group = screen.getByRole("group", { name: "Log values of TC-12" });
  const status = within(group).getByRole("status");
  expect(status).toHaveAttribute("aria-live", "polite");
  expect(status).toHaveTextContent("");
  await userEvent.click(within(group).getByRole("button", { name: "Copy trip_id 3960563" }));
  expect(writeText).toHaveBeenCalledWith("3960563");
  expect(await within(group).findByText("Copied")).toBeInTheDocument();
});

test("a blocked clipboard says so instead of claiming success", async () => {
  setClipboard(vi.fn().mockRejectedValue(new Error("denied")));
  render(<LogValuesLine values={PLAIN} />);
  await userEvent.click(screen.getByRole("button", { name: "Copy route_key wasToBos" }));
  expect(await screen.findByText(/could not copy/i)).toBeInTheDocument();
  expect(screen.queryByText("Copied")).toBeNull();
});

test("with a project each value links to the runs holding it, the value encoded", () => {
  render(
    <MemoryRouter>
      <LogValuesLine projectId={42} values={[{ name: "route_key", values: ["a b&c?#/x"], link_template: null }]} />
    </MemoryRouter>,
  );
  const link = screen.getByRole("link", { name: "Runs with route_key a b&c?#/x" });
  expect(link).toHaveAttribute("href", "/projects/42/runs?value=a%20b%26c%3F%23%2Fx&pattern=route_key");
  expect(screen.getByRole("button", { name: "Copy route_key a b&c?#/x" })).toBeInTheDocument();
});

test("without a project there is no runs link", () => {
  render(<LogValuesLine values={PLAIN} />);
  expect(screen.queryByRole("link")).toBeNull();
});
