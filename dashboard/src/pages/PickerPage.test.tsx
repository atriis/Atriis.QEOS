import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import PickerPage from "./PickerPage";

function renderPicker() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<PickerPage />} />
          <Route path="/projects/:projectId/overview" element={<div>OVERVIEW</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const org = { id: 1, name: "Acme", slug: "acme", role: "owner", plan_tier: "free", created_at: "2026-01-01T00:00:00Z", updated_at: null };

test("zero organizations shows an empty state", async () => {
  server.use(http.get("/api/v1/organizations", () => HttpResponse.json([])));
  renderPicker();
  expect(await screen.findByText(/not a member of any organization/i)).toBeInTheDocument();
});

test("every organization lists its projects; a project opens on its overview", async () => {
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([org])),
    http.get("/api/v1/organizations/1/projects", () =>
      HttpResponse.json([{ id: 42, name: "Web Tests" }]),
    ),
  );
  renderPicker();
  // no org to click first: projects are visible straight away
  await userEvent.click(await screen.findByRole("link", { name: "Web Tests" }));
  expect(await screen.findByText("OVERVIEW")).toBeInTheDocument();
});


test("creating an organization refreshes the list", async () => {
  const orgs: object[] = [];
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json(orgs)),
    http.post("/api/v1/organizations", async ({ request }) => {
      const body = (await request.json()) as { name: string; slug: string };
      orgs.push({ ...org, id: 9, name: body.name, slug: body.slug });
      return HttpResponse.json({ id: 9, name: body.name, slug: body.slug }, { status: 201 });
    }),
  );
  renderPicker();
  await screen.findByText(/not a member of any organization/i);
  await userEvent.click(screen.getByRole("button", { name: /new organization/i }));
  await userEvent.type(screen.getByLabelText(/name/i), "Minha Org!");
  // the slug is derived from the name, lowercased and dash-safe, but editable
  expect(screen.getByLabelText(/slug/i)).toHaveValue("minha-org");
  await userEvent.click(screen.getByRole("button", { name: /^create organization$/i }));
  expect(await screen.findByText("Minha Org!")).toBeInTheDocument();
});

test("creating a project in an organization", async () => {
  const projects: object[] = [];
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([org])),
    http.get("/api/v1/organizations/1/projects", () => HttpResponse.json(projects)),
    http.post("/api/v1/organizations/1/projects", async ({ request }) => {
      const body = (await request.json()) as { name: string };
      projects.push({ id: 5, name: body.name });
      return HttpResponse.json({ id: 5, name: body.name }, { status: 201 });
    }),
  );
  renderPicker();
  await screen.findByText(/no projects/i);
  await userEvent.click(screen.getByRole("button", { name: /new project/i }));
  await userEvent.type(screen.getByLabelText(/project name/i), "Web Tests");
  await userEvent.click(screen.getByRole("button", { name: /^create project$/i }));
  expect(await screen.findByText("Web Tests")).toBeInTheDocument();
});

test("cancelling the new-project form returns focus to the button that opened it", async () => {
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([org])),
    http.get("/api/v1/organizations/1/projects", () => HttpResponse.json([])),
  );
  renderPicker();
  await screen.findByText(/no projects/i);
  await userEvent.click(screen.getByRole("button", { name: /new project/i }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: /new project/i })).toHaveFocus();
});

const PENDING = { id: 2, name: "Old", deletion: { deleted_at: "2026-10-16T13:05:00Z", deleted_by: 9, purge_at: "2026-10-23T13:05:00Z" } };

test("owners and admins see a pending project greyed with the purge date, who deleted it, and Restore", async () => {
  let pendingNow = true;
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([org])),
    http.get("/api/v1/organizations/1/projects", ({ request }) => {
      const asked = new URL(request.url).searchParams.get("include_pending") === "true";
      const old = pendingNow ? (asked ? [PENDING] : []) : [{ id: 2, name: "Old" }];
      return HttpResponse.json([{ id: 1, name: "Live" }, ...old]);
    }),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([
      { id: 1, organization_id: 1, user_id: 9, email: "ana@example.com", role: "admin", status: "active" },
    ])),
    http.post("/api/v1/projects/2/restore", () => {
      pendingNow = false;
      return HttpResponse.json({ id: 2, name: "Old", deletion: null });
    }),
  );
  renderPicker();
  const row = await screen.findByRole("group", { name: "Old, deletion pending" });
  expect(row).toHaveTextContent(/removed on \d+ Oct 2026/);
  expect(await within(row).findByText(/deleted by ana@example.com/)).toBeInTheDocument();
  expect(within(row).queryByRole("link")).toBeNull();
  await userEvent.click(within(row).getByRole("button", { name: "Restore Old" }));
  expect(await screen.findByRole("link", { name: "Old" })).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Old, deletion pending" })).toBeNull();
});

test("a restore refused because the name was reused shows why", async () => {
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([org])),
    http.get("/api/v1/organizations/1/projects", () => HttpResponse.json([{ id: 1, name: "Old" }, PENDING])),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([])),
    http.post("/api/v1/projects/2/restore", () => HttpResponse.json(
      { detail: "A live project already uses this name or slug; rename it first" }, { status: 409 })),
  );
  renderPicker();
  const row = await screen.findByRole("group", { name: "Old, deletion pending" });
  await userEvent.click(within(row).getByRole("button", { name: "Restore Old" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("rename it first");
});

test("members never ask for pending projects", async () => {
  const asked: string[] = [];
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([{ ...org, role: "member" }])),
    http.get("/api/v1/organizations/1/projects", ({ request }) => {
      asked.push(request.url);
      return HttpResponse.json([{ id: 1, name: "Live" }]);
    }),
  );
  renderPicker();
  await screen.findByRole("link", { name: "Live" });
  expect(asked.length).toBeGreaterThan(0);
  expect(asked.every((u) => !u.includes("include_pending"))).toBe(true);
});
