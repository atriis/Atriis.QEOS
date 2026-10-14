import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import RegisterPage from "./RegisterPage";

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/register"]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/login" element={<div>LOGIN</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

test("registering asks the person to check their email", async () => {
  let sent: { email: string; password: string; full_name?: string } | null = null;
  server.use(
    http.post("/api/v1/auth/register", async ({ request }) => {
      sent = (await request.json()) as typeof sent;
      return HttpResponse.json({ message: "Check your email to complete registration" }, { status: 202 });
    }),
  );
  renderPage();
  await userEvent.type(screen.getByLabelText(/full name/i), "Pedro");
  await userEvent.type(screen.getByLabelText(/email/i), "pedro@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "UmaPasswordForte123");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));

  expect(await screen.findByText(/check your email to complete/i)).toBeInTheDocument();
  expect(sent).toEqual({ email: "pedro@example.com", password: "UmaPasswordForte123", full_name: "Pedro" });
  // self-hosted deployments often have no SMTP: say where the link ends up
  expect(screen.getByText(/no email arrives/i)).toBeInTheDocument();
});

test("an already registered email is explained in place", async () => {
  server.use(
    http.post("/api/v1/auth/register", () =>
      HttpResponse.json({ detail: "Email already registered" }, { status: 400 })),
  );
  renderPage();
  await userEvent.type(screen.getByLabelText(/email/i), "pedro@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "UmaPasswordForte123");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));
  expect(await screen.findByText(/already registered/i)).toBeInTheDocument();
});

test("links back to sign in", async () => {
  renderPage();
  await userEvent.click(screen.getByRole("link", { name: /sign in/i }));
  expect(await screen.findByText("LOGIN")).toBeInTheDocument();
});

test("the register screen shows the product name and what it stands for, under its own h1", () => {
  renderPage();
  expect(screen.getByText("QEOS")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "Create account" })).toBeInTheDocument();
  expect(screen.getByText("Quality Engineering OS")).toBeInTheDocument();
});

test("the page the person was heading to survives registration and verification", async () => {
  localStorage.clear();
  server.use(http.post("/api/v1/auth/register", () => HttpResponse.json({ message: "ok" }, { status: 202 })));
  render(
    <MemoryRouter initialEntries={["/register?next=%2Finvitations%2Ftok-1"]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login?next=%2Finvitations%2Ftok-1");
  await userEvent.type(screen.getByLabelText(/email/i), "pedro@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "UmaPasswordForte123");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));
  await screen.findByText(/check your email to complete/i);
  expect(JSON.parse(localStorage.getItem("qeos.afterVerify")!).next).toBe("/invitations/tok-1");
  expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute("href", "/login?next=%2Finvitations%2Ftok-1");
});

test("an unsafe next is ignored", async () => {
  localStorage.clear();
  server.use(http.post("/api/v1/auth/register", () => HttpResponse.json({ message: "ok" }, { status: 202 })));
  render(
    <MemoryRouter initialEntries={["/register?next=%2F%2Fevil.example"]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  await userEvent.type(screen.getByLabelText(/email/i), "pedro@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "UmaPasswordForte123");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));
  await screen.findByText(/check your email to complete/i);
  expect(localStorage.getItem("qeos.afterVerify")).toBeNull();
});

const SSO_ONLY = { password: false, providers: ["microsoft"] };
const SSO_ONLY_403 = { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } };

test("in SSO-only mode the page points to sign-in instead of a form", async () => {
  server.use(http.get("/api/v1/auth/methods", () => HttpResponse.json(SSO_ONLY)));
  renderPage();
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "Go to sign in" }));
  expect(await screen.findByText("LOGIN")).toBeInTheDocument();
});

test("a 403 sso_only gives the same notice when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.post("/api/v1/auth/register", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage();
  await userEvent.type(screen.getByLabelText(/email/i), "pedro@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "UmaPasswordForte123");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "Sign in with Microsoft" })).toBeInTheDocument();
});
