import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setAccessToken, clearTokens } from "./auth/tokens";
import { AppRoutes } from "./App";
import { MemoryRouter, RouterProvider, createMemoryRouter, useLocation } from "react-router-dom";

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("unauthenticated project route redirects to login", () => {
  clearTokens();
  renderAt("/projects/42/trends");
  expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
});

test("project index redirects to the overview", async () => {
  setAccessToken("acc");
  renderAt("/projects/42");
  expect(await screen.findByText(/loading overview/i)).toBeInTheDocument();
});

test("a skip link jumps past the header straight to the main content", async () => {
  clearTokens();
  renderAt("/login");
  const skip = screen.getByRole("link", { name: /skip to content/i });
  await (await import("@testing-library/user-event")).default.click(skip);
  expect(screen.getByRole("main")).toHaveFocus();
});

test("each view has its own document title", () => {
  clearTokens();
  renderAt("/register");
  expect(document.title).toBe("Create account · QEOS");
});

function Here() {
  const { pathname, search } = useLocation();
  return <output data-testid="here">{pathname + search}</output>;
}

test("an unauthenticated deep link sends the user to login and remembers the page", () => {
  clearTokens();
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/invitations/tok-1?x=1"]}>
        <AppRoutes />
        <Here />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByTestId("here")).toHaveTextContent("/login?next=%2Finvitations%2Ftok-1%3Fx%3D1");
});

test("under the data router, following a link moves focus to the new view", async () => {
  clearTokens();
  const router = createMemoryRouter([{ path: "*", element: <AppRoutes /> }], { initialEntries: ["/login"] });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await (await import("@testing-library/user-event")).default.click(screen.getByRole("link", { name: /create account/i }));
  const heading = await screen.findByRole("heading", { level: 1, name: "Create account" });
  expect(router.state.location.pathname).toBe("/register");
  // The new page's h1, inside main
  expect(heading).toHaveFocus();
  expect(screen.getByRole("main")).toContainElement(heading);
});

test("a session that fails to refresh returns to login, remembering the page and saying why", async () => {
  setAccessToken("acc");
  const { http, HttpResponse } = await import("msw");
  const { server } = await import("./test/server");
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json({ detail: "expired" }, { status: 401 })),
    http.post("/api/v1/auth/refresh", () => HttpResponse.json({ detail: "expired" }, { status: 401 })),
    http.get("/api/v1/projects/42", () => HttpResponse.json({ detail: "expired" }, { status: 401 })),
  );
  const router = createMemoryRouter([{ path: "*", element: <AppRoutes /> }], { initialEntries: ["/account/security"] });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  expect(router.state.location.search).toBe("?next=%2Faccount%2Fsecurity&reason=expired");
  expect(await screen.findByText(/your session expired, sign in again/i)).toBeInTheDocument();
});

test("a signed-in invitee with no organization yet reaches the invitation, not the first-project setup", async () => {
  setAccessToken("acc");
  const { http, HttpResponse } = await import("msw");
  const { server } = await import("./test/server");
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([])),
    http.get("/api/v1/projects", () => HttpResponse.json([])),
    http.get("/api/v1/invitations/tok-1", () =>
      HttpResponse.json({ organization_id: 7, organization_name: "Acme QA", email: "dave@example.com", role: "member", expires_at: "2099-01-01T00:00:00Z" })),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/invitations/tok-1"]}>
        <AppRoutes />
        <Here />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("button", { name: /accept invitation/i })).toBeInTheDocument();
  expect(screen.getByTestId("here")).toHaveTextContent("/invitations/tok-1");
});
