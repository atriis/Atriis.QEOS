import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import DeleteProjectDialog from "./DeleteProjectDialog";

const PROJECT = { id: 42, name: "Web Checkout", organization_id: 1, my_role: "owner", legal_hold: null };
const NAME_FIELD = /type the project name/i;

function renderIt(project: object = PROJECT, onDeleted = vi.fn()) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><DeleteProjectDialog project={project as never} onDeleted={onDeleted} /></QueryClientProvider>);
  return onDeleted;
}

test("Delete project asks in place, says what goes and when, and focuses the name field", async () => {
  renderIt();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  const ask = screen.getByRole("group", { name: "Delete Web Checkout?" });
  expect(ask).toHaveTextContent(/runs, results, logs, test cases, suites, API keys and settings/);
  expect(ask).toHaveTextContent(/7 days/);
  expect(ask).toHaveTextContent(/any owner or admin can restore it/i);
  expect(ask).toHaveTextContent(/Download all results/);
  expect(screen.getByLabelText(NAME_FIELD)).toHaveFocus();
});

test("the danger button stays disabled until the name is typed exactly, then deletes", async () => {
  let deleted = false;
  server.use(http.delete("/api/v1/projects/42", () => { deleted = true; return new HttpResponse(null, { status: 204 }); }));
  const onDeleted = renderIt();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  const confirm = screen.getByRole("button", { name: "Delete permanently in 7 days" });
  expect(confirm).toBeDisabled();
  await userEvent.type(screen.getByLabelText(NAME_FIELD), "web checkout");
  expect(confirm).toBeDisabled(); // case matters
  await userEvent.clear(screen.getByLabelText(NAME_FIELD));
  await userEvent.type(screen.getByLabelText(NAME_FIELD), "Web Checkout");
  expect(confirm).toBeEnabled();
  await userEvent.click(confirm);
  await vi.waitFor(() => expect(onDeleted).toHaveBeenCalled());
  expect(deleted).toBe(true);
});

test("Enter in the name field deletes only when the name matches", async () => {
  let calls = 0;
  server.use(http.delete("/api/v1/projects/42", () => { calls += 1; return new HttpResponse(null, { status: 204 }); }));
  const onDeleted = renderIt();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  await userEvent.type(screen.getByLabelText(NAME_FIELD), "Web{Enter}");
  expect(calls).toBe(0);
  await userEvent.type(screen.getByLabelText(NAME_FIELD), " Checkout{Enter}");
  await vi.waitFor(() => expect(onDeleted).toHaveBeenCalled());
  expect(calls).toBe(1);
});

test("Escape and Cancel back out without deleting and give focus back to the trigger", async () => {
  renderIt();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("group", { name: "Delete Web Checkout?" })).toBeNull();
  expect(screen.getByRole("button", { name: "Delete project" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("group", { name: "Delete Web Checkout?" })).toBeNull();
  expect(screen.getByRole("button", { name: "Delete project" })).toHaveFocus();
});

test("under a legal hold the trigger is disabled with the reason", () => {
  renderIt({ ...PROJECT, legal_hold: { since: "2026-10-01T00:00:00Z", by: 1, reason: "audit" } });
  expect(screen.getByRole("button", { name: "Delete project" })).toBeDisabled();
  expect(screen.getByText("Release the legal hold before deleting this project.")).toBeInTheDocument();
});

test("a refusal from the server is shown next to the confirmation", async () => {
  server.use(http.delete("/api/v1/projects/42", () => HttpResponse.json(
    { detail: "Release the legal hold before deleting this project" }, { status: 409 })));
  renderIt();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  await userEvent.type(screen.getByLabelText(NAME_FIELD), "Web Checkout");
  await userEvent.click(screen.getByRole("button", { name: "Delete permanently in 7 days" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Release the legal hold");
});
