import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import ResetPasswordPage from "./ResetPasswordPage";

function renderPage(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<div>LOGIN</div>} />
        <Route path="/forgot-password" element={<div>FORGOT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fill(password: string, confirm: string) {
  await userEvent.type(screen.getByLabelText(/^new password/i), password);
  await userEvent.type(screen.getByLabelText(/confirm/i), confirm);
  await userEvent.click(screen.getByRole("button", { name: /set new password/i }));
}

test("a valid link sets the new password and offers sign in", async () => {
  let sent: unknown = null;
  server.use(
    http.post("/api/v1/auth/reset-password", async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ message: "Password has been reset." });
    }),
  );
  renderPage("/reset-password?token=tok-123");
  await fill("brand-new-password", "brand-new-password");

  expect(await screen.findByRole("status")).toHaveTextContent(/password has been changed/i);
  expect(sent).toEqual({ token: "tok-123", password: "brand-new-password" });
  await userEvent.click(screen.getByRole("link", { name: /sign in/i }));
  expect(await screen.findByText("LOGIN")).toBeInTheDocument();
});

test("a mismatched confirmation is caught before anything is sent", async () => {
  let called = false;
  server.use(
    http.post("/api/v1/auth/reset-password", () => {
      called = true;
      return HttpResponse.json({});
    }),
  );
  renderPage("/reset-password?token=tok-123");
  await fill("brand-new-password", "brand-new-passwerd");
  expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/confirm/i)).toHaveAttribute("aria-invalid", "true");
  expect(called).toBe(false);
});

test("an expired or used link explains and points to a new one", async () => {
  server.use(
    http.post("/api/v1/auth/reset-password", () =>
      HttpResponse.json({ detail: "Invalid or expired reset token" }, { status: 400 })),
  );
  renderPage("/reset-password?token=old");
  await fill("brand-new-password", "brand-new-password");
  expect(await screen.findByText(/invalid or expired/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: /request a new link/i }));
  expect(await screen.findByText("FORGOT")).toBeInTheDocument();
});

test("a link without a token says so instead of showing a form", () => {
  renderPage("/reset-password");
  expect(screen.getByText(/link is incomplete/i)).toBeInTheDocument();
  expect(screen.queryByLabelText(/^new password/i)).not.toBeInTheDocument();
});

const SSO_ONLY_403 = { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } };

test("in SSO-only mode an old reset link points to sign-in", async () => {
  server.use(http.get("/api/v1/auth/methods", () => HttpResponse.json({ password: false, providers: ["microsoft"] })));
  renderPage("/reset-password?token=t");
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.queryByLabelText(/^new password/i)).not.toBeInTheDocument();
});

test("a 403 sso_only gives the same notice when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.post("/api/v1/auth/reset-password", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage("/reset-password?token=t");
  await fill("securepassword123", "securepassword123");
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "Sign in with Microsoft" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Go to sign in" })).toBeInTheDocument();
});

test("a 403 sso_only names the providers the server named when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.post("/api/v1/auth/reset-password", () => HttpResponse.json({ detail: { code: "sso_only", message: "Sign-in is through Google only." } }, { status: 403 })),
  );
  renderPage("/reset-password?token=t");
  await fill("securepassword123", "securepassword123");
  expect(await screen.findByRole("heading", { level: 1, name: "Sign in with Google" })).toBeInTheDocument();
  expect(screen.queryByText(/Microsoft/)).not.toBeInTheDocument();
});
