import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { clearTokens, getAccessToken } from "../auth/tokens";
import VerifyEmailPage from "./VerifyEmailPage";

function renderPage(query = "?token=tok-123") {
  render(
    <MemoryRouter initialEntries={[`/verify-email${query}`]}>
      <Routes>
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/" element={<div>PICKER</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

test("a valid token verifies, signs in, and lands on the picker", async () => {
  clearTokens();
  server.use(
    http.get("/api/v1/auth/verify-email", ({ request }) => {
      const token = new URL(request.url).searchParams.get("token");
      if (token !== "tok-123") return HttpResponse.json({ detail: "Invalid token" }, { status: 400 });
      return HttpResponse.json({ access_token: "fresh-acc", refresh_token: "r", token_type: "bearer" });
    }),
  );
  renderPage();
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
  expect(getAccessToken()).toBe("fresh-acc");
});

test("a dead token explains itself and offers registration again", async () => {
  server.use(
    http.get("/api/v1/auth/verify-email", () =>
      HttpResponse.json({ detail: "Invalid or expired token" }, { status: 400 })),
  );
  renderPage();
  expect(await screen.findByText(/invalid or expired/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /register/i })).toBeInTheDocument();
});

test("a missing token never calls the API", async () => {
  renderPage("");
  expect(await screen.findByText(/carries no token/i)).toBeInTheDocument();
});

test("StrictMode's double effect never burns the single-use token twice", async () => {
  let calls = 0;
  server.use(
    http.get("/api/v1/auth/verify-email", () => {
      calls += 1;
      if (calls > 1) return HttpResponse.json({ detail: "Invalid token" }, { status: 400 });
      return HttpResponse.json({ access_token: "fresh-acc", refresh_token: "r", token_type: "bearer" });
    }),
  );
  render(
    <StrictMode>
      <MemoryRouter initialEntries={["/verify-email?token=tok-123"]}>
        <Routes>
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/" element={<div>PICKER</div>} />
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  );
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
  expect(calls).toBe(1);
});

function verifyOk() {
  clearTokens();
  server.use(
    http.get("/api/v1/auth/verify-email", () =>
      HttpResponse.json({ access_token: "fresh-acc", refresh_token: "r", token_type: "bearer" })),
  );
}

function renderWithInvitation(query = "?token=tok-123") {
  render(
    <MemoryRouter initialEntries={[`/verify-email${query}`]}>
      <Routes>
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/" element={<div>PICKER</div>} />
        <Route path="/invitations/:token" element={<div>INVITATION</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

test("after verifying, a new invitee returns to the invitation they were following", async () => {
  verifyOk();
  localStorage.setItem("qeos.afterVerify", JSON.stringify({ next: "/invitations/tok-1", at: Date.now() }));
  renderWithInvitation();
  expect(await screen.findByText("INVITATION")).toBeInTheDocument();
  expect(localStorage.getItem("qeos.afterVerify")).toBeNull();
});

test("a next in the verification link works the same", async () => {
  verifyOk();
  renderWithInvitation("?token=tok-123&next=%2Finvitations%2Ftok-2");
  expect(await screen.findByText("INVITATION")).toBeInTheDocument();
});

test("a link opened in another browser, with nothing remembered, still lands on the invitation", async () => {
  verifyOk();
  localStorage.clear();
  renderWithInvitation("?token=tok-123&next=%2Finvitations%2Fx");
  expect(await screen.findByText("INVITATION")).toBeInTheDocument();
});

test("an unsafe next never leaves the app", async () => {
  verifyOk();
  localStorage.setItem("qeos.afterVerify", JSON.stringify({ next: "//evil.example", at: Date.now() }));
  renderWithInvitation("?token=tok-123&next=%2F%2Fevil.example");
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
});

const SSO_ONLY_403 = { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } };

test("in SSO-only mode an old verification link points to sign-in", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.json({ password: false, providers: ["microsoft"] })),
    http.get("/api/v1/auth/verify-email", () => new Promise<Response>(() => {})),
  );
  renderPage();
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /register/i })).not.toBeInTheDocument();
});

test("a 403 sso_only gives the same notice when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.get("/api/v1/auth/verify-email", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage();
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "Sign in with Microsoft" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Go to sign in" })).toBeInTheDocument();
});

test("a 403 sso_only names the providers the server named when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.get("/api/v1/auth/verify-email", () => HttpResponse.json({ detail: { code: "sso_only", message: "Sign-in is through Google only." } }, { status: 403 })),
  );
  renderPage();
  expect(await screen.findByRole("heading", { level: 1, name: "Sign in with Google" })).toBeInTheDocument();
  expect(screen.queryByText(/Microsoft/)).not.toBeInTheDocument();
});
