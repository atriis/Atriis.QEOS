import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import ProjectLayout from "./ProjectLayout";

function renderAt(path: string) {
  setAccessToken("acc");
  server.use(http.get("/api/v1/projects/42", () => HttpResponse.json({ id: 42, name: "Shop E2E" })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectLayout />}>
            <Route path="runs" element={<h1>Runs</h1>} />
            <Route path="runs/requested" element={<h1>Requested runs</h1>} />
            <Route path="settings" element={<h1>Settings</h1>} />
            <Route path="cases/import" element={<h1>Import view</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("the title names the view and the project", async () => {
  renderAt("/projects/42/runs");
  await waitFor(() => expect(document.title).toBe("Runs · Shop E2E · QEOS"));
});

test("the project heading block is gone: the view's own h1 is the only one", async () => {
  renderAt("/projects/42/runs");
  await waitFor(() => expect(document.title).toBe("Runs · Shop E2E · QEOS"));
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.queryByRole("heading", { name: "Shop E2E" })).not.toBeInTheDocument();
});

test("the import page is titled as such, not as a case number", async () => {
  renderAt("/projects/42/cases/import");
  await waitFor(() => expect(document.title).toBe("Import from Gherkin · Shop E2E · QEOS"));
});

test("requested runs are titled as such, not as a run number", async () => {
  renderAt("/projects/42/runs/requested");
  await waitFor(() => expect(document.title).toBe("Requested runs · Shop E2E · QEOS"));
});

const PENDING_BODY = { detail: { code: "pending_deletion", message: "This project is scheduled for deletion", organization_id: 1,
  deleted_at: "2026-10-16T13:05:00Z", deleted_by: 9, purge_at: "2026-10-23T13:05:00Z" } };

function renderPending(role: string) {
  setAccessToken("acc");
  server.use(
    http.get("/api/v1/projects/42", () => HttpResponse.json(PENDING_BODY, { status: 410 })),
    http.get("/api/v1/organizations/1/members/me", () => HttpResponse.json({ role })),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/projects/42/runs"]}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectLayout />}>
            <Route path="runs" element={<h1>Runs</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("a member who opens a pending project sees the deletion notice, not the view", async () => {
  renderPending("member");
  expect(await screen.findByRole("heading", { name: "This project is scheduled for deletion" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Runs" })).not.toBeInTheDocument();
  expect(screen.getByText(/ask an owner or admin/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Restore project" })).not.toBeInTheDocument();
});

test("an owner who opens a pending project can restore it there", async () => {
  renderPending("owner");
  expect(await screen.findByRole("button", { name: "Restore project" })).toBeInTheDocument();
});
