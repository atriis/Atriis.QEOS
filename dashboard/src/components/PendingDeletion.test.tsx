import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import PendingDeletion from "./PendingDeletion";

const INFO = { code: "pending_deletion", message: "x", organization_id: 1, deleted_at: "2026-10-16T13:05:00Z",
  deleted_by: 9, purge_at: "2026-10-23T13:05:00Z" };

function renderIt(canRestore: boolean) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><PendingDeletion projectId={42} info={INFO} canRestore={canRestore} /></QueryClientProvider>);
}

test("a member sees the deletion notice with the date", () => {
  renderIt(false);
  expect(screen.getByRole("heading", { name: "This project is scheduled for deletion" })).toBeInTheDocument();
  expect(screen.getByText(/\d+ Oct 2026/)).toBeInTheDocument();
  expect(screen.getByText(/ask an owner or admin if this is a mistake/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /restore/i })).toBeNull();
});

test("an owner can restore from the notice", async () => {
  let restored = false;
  server.use(http.post("/api/v1/projects/42/restore", () => {
    restored = true;
    return HttpResponse.json({ id: 42, name: "Web", deletion: null });
  }));
  renderIt(true);
  await userEvent.click(screen.getByRole("button", { name: "Restore project" }));
  await vi.waitFor(() => expect(restored).toBe(true));
});

test("a refused restore says why", async () => {
  server.use(http.post("/api/v1/projects/42/restore", () => HttpResponse.json(
    { detail: "The purge has started; this project can no longer be restored" }, { status: 409 })));
  renderIt(true);
  await userEvent.click(screen.getByRole("button", { name: "Restore project" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("purge has started");
});
