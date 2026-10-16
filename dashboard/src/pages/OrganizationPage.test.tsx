import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { microsoftEnabled } from "../auth/ssoProviders";
import OrganizationPage from "./OrganizationPage";

vi.mock("../auth/ssoProviders", () => ({ microsoftEnabled: vi.fn(() => false) }));
beforeEach(() => vi.mocked(microsoftEnabled).mockReturnValue(false));

const MEMBERS = [
  { id: 1, organization_id: 7, user_id: 10, email: "owner@example.com", role: "owner", status: "active", created_at: "2026-10-01T10:00:00Z", updated_at: null, managed_by: null },
  { id: 2, organization_id: 7, user_id: 11, email: null, role: "member", status: "active", created_at: "2026-10-02T10:00:00Z", updated_at: null, managed_by: null },
];

const MANAGED = { id: 3, organization_id: 7, user_id: 12, email: "eve@example.com", role: "member", status: "active",
  created_at: "2026-10-04T10:00:00Z", updated_at: null, managed_by: "entra" };

const INVITATIONS = [
  { id: 5, organization_id: 7, email: "carol@example.com", role: "member", invited_by_user_id: 10,
    expires_at: "2026-10-10T10:00:00Z", created_at: "2026-10-03T10:00:00Z", accepted_at: null },
];

function mockOrg(role = "owner", invitations = INVITATIONS) {
  server.use(
    http.get("/api/v1/organizations", () =>
      HttpResponse.json([{ id: 7, name: "Acme QA", slug: "acme", role }])),
    http.get("/api/v1/organizations/7/members", () => HttpResponse.json(MEMBERS)),
    http.get("/api/v1/organizations/7/members/me", () => HttpResponse.json({ role })),
    http.get("/api/v1/organizations/7/invitations", () => HttpResponse.json(invitations)),
  );
}

function renderPage(state?: unknown) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[{ pathname: "/organizations/7", state }]}>
        <Routes>
          <Route path="/organizations/:orgId" element={<OrganizationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("lists members and pending invitations", async () => {
  mockOrg();
  renderPage();
  // The page name is the one h1; the org and project live in the breadcrumb
  expect(await screen.findByRole("heading", { level: 1, name: "Acme QA" })).toBeInTheDocument();
  expect(await screen.findByText("Acme QA")).toBeInTheDocument();
  expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  expect(screen.getByText("user 11")).toBeInTheDocument(); // auth had no email: honest fallback
  expect(screen.getByText("carol@example.com")).toBeInTheDocument();
});

test("inviting shows the single-use link with the token", async () => {
  mockOrg();
  server.use(
    http.post("/api/v1/organizations/7/invitations", async ({ request }) => {
      const body = (await request.json()) as { email: string; role: string };
      return HttpResponse.json(
        { id: 6, organization_id: 7, email: body.email, role: body.role, invited_by_user_id: 10,
          token: "tok-abc123", expires_at: "2026-10-10T10:00:00Z", created_at: "2026-10-03T11:00:00Z",
          accepted_at: null },
        { status: 201 },
      );
    }),
  );
  renderPage();
  await screen.findByText("Acme QA");
  await userEvent.type(screen.getByLabelText(/email/i), "dave@example.com");
  await userEvent.selectOptions(screen.getByLabelText(/role/i), "admin");
  await userEvent.click(screen.getByRole("button", { name: /invite/i }));
  const link = await screen.findByText(/\/invitations\/tok-abc123/);
  expect(link).toBeInTheDocument();
  expect(screen.getByText(/shown once/i)).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Invitation for dave@example.com" })).toHaveClass("secret-block");

  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  await userEvent.click(screen.getByRole("button", { name: /copy the invitation link/i }));
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("/invitations/tok-abc123"));
  expect(await screen.findByRole("button", { name: /copy the invitation link/i })).toHaveTextContent("Copied");
});

test("revoking an invitation calls the API", async () => {
  mockOrg();
  let revoked = false;
  server.use(
    http.delete("/api/v1/organizations/7/invitations/5", () => {
      revoked = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderPage();
  await screen.findByText("carol@example.com");
  await userEvent.click(screen.getByRole("button", { name: "Revoke invitation for carol@example.com" }));
  expect(revoked).toBe(false); // the first click only asks
  await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
  expect(await screen.findByText(/invitation revoked/i)).toBeInTheDocument();
  expect(revoked).toBe(true);
});

test("removing a member calls the API", async () => {
  mockOrg();
  let removed = false;
  server.use(
    http.delete("/api/v1/organizations/7/members/2", () => {
      removed = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderPage();
  await screen.findByText("user 11");
  await userEvent.click(screen.getByRole("button", { name: "Remove user 11" }));
  expect(removed).toBe(false); // the first click only asks
  await userEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(await screen.findByText(/member removed/i)).toBeInTheDocument();
  expect(removed).toBe(true);
});

test("a viewer sees no management controls", async () => {
  mockOrg("viewer", []);
  renderPage();
  await screen.findByText("Acme QA");
  expect(screen.queryByRole("button", { name: /invite/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
});

test("arriving from an accepted invitation shows the welcome in the status region, once", async () => {
  mockOrg();
  renderPage({ notice: "You joined Acme QA as member." });
  expect(await screen.findByRole("status")).toHaveTextContent("You joined Acme QA as member.");
});

test("the status region exists before there is anything to say", async () => {
  mockOrg();
  renderPage();
  await screen.findByText("Acme QA");
  expect(screen.getByRole("status")).toHaveTextContent("");
});

test("an Entra-managed member shows the badge and cannot be removed", async () => {
  mockOrg();
  server.use(http.get("/api/v1/organizations/7/members", () => HttpResponse.json([...MEMBERS, MANAGED])));
  renderPage();
  const row = (await screen.findByText("eve@example.com")).closest("tr")!;
  const badge = within(row).getByText("Entra", { exact: false, selector: "span.badge" });
  expect(badge).toHaveAttribute("title", "Managed by Entra");
  expect(badge).toHaveTextContent("Entra, managed by Entra");
  const remove = await within(row).findByRole("button", { name: "Remove eve@example.com" });
  expect(remove).not.toBeDisabled();
  expect(remove).toHaveAttribute("aria-disabled", "true");
  expect(remove).toHaveAttribute("title", "Managed by Entra: remove the app role instead.");
  expect(remove).toHaveAccessibleDescription("Managed by Entra: remove the app role instead.");
  remove.focus();
  expect(remove).toHaveFocus();
  let deleted = false;
  server.use(http.delete("/api/v1/organizations/7/members/3", () => { deleted = true; return new HttpResponse(null, { status: 204 }); }));
  await userEvent.click(remove);
  expect(deleted).toBe(false);
  // A hand-made member keeps the normal Remove
  const handMade = screen.getByText("user 11").closest("tr")!;
  expect(within(handMade).getByRole("button", { name: /Remove user 11/ })).toBeEnabled();
});

test("the Microsoft roles card shows for owners when the build has Microsoft sign-in", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  mockOrg("owner");
  server.use(http.get("/api/v1/organizations/7/sso-role-mappings", () => HttpResponse.json([])));
  renderPage();
  expect(await screen.findByRole("heading", { name: "Microsoft roles" })).toBeInTheDocument();
});

test("the card is hidden for admins", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  mockOrg("admin");
  renderPage();
  await screen.findByText("owner@example.com");
  await screen.findByRole("button", { name: /Remove user 11/ });
  expect(screen.queryByRole("heading", { name: "Microsoft roles" })).not.toBeInTheDocument();
});

test("the card is hidden when the build has no Microsoft sign-in", async () => {
  mockOrg("owner");
  renderPage();
  await screen.findByText("owner@example.com");
  await screen.findByRole("button", { name: /Remove user 11/ });
  expect(screen.queryByRole("heading", { name: "Microsoft roles" })).not.toBeInTheDocument();
});
