import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import AddToSuiteDialog from "./AddToSuiteDialog";

const P = "/api/v1/projects/42";
const suite = (id: number, name: string, extra: object = {}) => ({
  id, name, description: null, case_count: 0, created_at: "2026-10-01T10:00:00Z", updated_at: null, origin: "manual", ...extra,
});

function renderIt(numbers = [1, 2, 3], onDone = vi.fn()) {
  setAccessToken("acc");
  server.use(http.get(`${P}/suites`, () => HttpResponse.json([
    suite(1, "Smoke"), suite(2, "From CI", { origin: "repository" }), suite(3, "Regression"),
  ])));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter>
    <AddToSuiteDialog projectId={42} numbers={numbers} onDone={onDone} />
  </MemoryRouter></QueryClientProvider>);
  return onDone;
}

const open = async () => {
  await userEvent.click(screen.getByRole("button", { name: "Add to suite" }));
  return screen.getByRole("dialog", { name: "Add 3 cases to a suite" });
};

test("the dialog lists only manual suites, then New suite", async () => {
  renderIt();
  const dialog = await open();
  const select = await within(dialog).findByRole("combobox", { name: "Suite" });
  await within(dialog).findByRole("option", { name: "Smoke" });
  const names = within(select).getAllByRole("option").map((o) => o.textContent);
  expect(names).toEqual(["Choose a suite", "Smoke", "Regression", "New suite…"]);
  expect(select).toHaveFocus();
});

test("choosing a suite sends the numbers and reports added and already there, with a link", async () => {
  let sent: unknown = null;
  server.use(http.post(`${P}/suites/1/cases/append`, async ({ request }) => {
    sent = await request.json();
    return HttpResponse.json({ added: 3, already: 2, suite: { ...suite(1, "Smoke"), cases: [] } });
  }));
  const onDone = renderIt();
  const dialog = await open();
  await within(dialog).findByRole("option", { name: "Smoke" });
  await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Suite" }), "Smoke");
  await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));
  expect(await within(dialog).findByRole("status")).toHaveTextContent("Added 3 cases to Smoke (2 were already there).");
  expect(sent).toEqual({ cases: [1, 2, 3] });
  expect(within(dialog).getByRole("link", { name: "Open Smoke" })).toHaveAttribute("href", "/projects/42/suites/1");
  expect(onDone).toHaveBeenCalled();
});

test("New suite with a name creates it, then appends", async () => {
  const calls: string[] = [];
  server.use(
    http.post(`${P}/suites`, async ({ request }) => {
      calls.push(`create ${JSON.stringify(await request.json())}`);
      return HttpResponse.json(suite(9, "Nightly"), { status: 201 });
    }),
    http.post(`${P}/suites/9/cases/append`, async ({ request }) => {
      calls.push(`append ${JSON.stringify(await request.json())}`);
      return HttpResponse.json({ added: 3, already: 0, suite: { ...suite(9, "Nightly"), cases: [] } });
    }),
  );
  renderIt();
  const dialog = await open();
  await within(dialog).findByRole("option", { name: "Smoke" });
  await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Suite" }), "New suite…");
  await userEvent.type(within(dialog).getByRole("textbox", { name: "Name" }), "Nightly");
  await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));
  expect(await within(dialog).findByRole("status")).toHaveTextContent("Added 3 cases to Nightly.");
  expect(calls).toEqual(['create {"name":"Nightly"}', 'append {"cases":[1,2,3]}']);
});

test("an empty name shows a field error tied to the field and sends nothing", async () => {
  let posted = 0;
  server.use(http.post(`${P}/suites`, () => { posted += 1; return HttpResponse.json(suite(9, "x"), { status: 201 }); }));
  renderIt();
  const dialog = await open();
  await within(dialog).findByRole("option", { name: "Smoke" });
  await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Suite" }), "New suite…");
  await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));
  const field = within(dialog).getByRole("textbox", { name: "Name" });
  expect(within(dialog).getByRole("alert")).toHaveTextContent("Enter a name for the suite.");
  expect(field).toHaveAttribute("aria-invalid", "true");
  expect(field.getAttribute("aria-describedby")).toBe(within(dialog).getByRole("alert").id);
  expect(field).toHaveFocus();
  expect(posted).toBe(0);
});

test("a name that is taken shows the clash under the field", async () => {
  server.use(http.post(`${P}/suites`, () => HttpResponse.json({ detail: "Suite name already exists" }, { status: 409 })));
  renderIt();
  const dialog = await open();
  await within(dialog).findByRole("option", { name: "Smoke" });
  await userEvent.selectOptions(within(dialog).getByRole("combobox", { name: "Suite" }), "New suite…");
  await userEvent.type(within(dialog).getByRole("textbox", { name: "Name" }), "Smoke");
  await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("A suite with this name already exists.");
  expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveAttribute("aria-invalid", "true");
});

test("Escape and Cancel close the dialog and give focus back to Add to suite", async () => {
  renderIt();
  const trigger = screen.getByRole("button", { name: "Add to suite" });
  await open();
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(trigger).toHaveFocus();
  await open();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(trigger).toHaveFocus();
});
