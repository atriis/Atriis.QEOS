import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { isAuthenticated } from "../auth/tokens";
import { googleEnabled, initGoogleButton, microsoftEnabled } from "../auth/ssoProviders";
import LoginPage from "./LoginPage";

vi.mock("../auth/ssoProviders", () => ({
  googleEnabled: vi.fn(() => false),
  microsoftEnabled: vi.fn(() => false),
  initGoogleButton: vi.fn(async () => {}),
  getMicrosoftCredential: vi.fn(async () => "ms-id-token"),
}));

beforeEach(() => {
  vi.mocked(googleEnabled).mockReturnValue(false);
  vi.mocked(microsoftEnabled).mockReturnValue(false);
  vi.mocked(initGoogleButton).mockClear();
  vi.mocked(initGoogleButton).mockResolvedValue(undefined);
});

function renderLogin(url = "/login") {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>PICKER</div>} />
        <Route path="/invitations/:token" element={<div>INVITATION</div>} />
        <Route path="/projects/:id/runs" element={<div>RUNS</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function ForgotEcho() {
  const { state, search } = useLocation();
  return <div>FORGOT {(state as { email: string }).email}{search}</div>;
}

test("forgot password carries the typed email to the request page", async () => {
  render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotEcho />} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.type(screen.getByLabelText(/email/i), "ada@example.com");
  await userEvent.click(screen.getByRole("link", { name: /forgot password/i }));
  expect(await screen.findByText("FORGOT ada@example.com")).toBeInTheDocument();
});

test("successful login stores tokens and navigates home", async () => {
  server.use(
    http.post("/api/v1/auth/login", async ({ request }) => {
      expect(await request.json()).toEqual({ email: "a@b.co", password: "pw" });
      return HttpResponse.json({ access_token: "acc", refresh_token: "ref", token_type: "bearer" });
    }),
  );
  renderLogin();
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
  await userEvent.type(screen.getByLabelText(/password/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
  expect(isAuthenticated()).toBe(true);
});

test("no SSO buttons when providers are unconfigured", () => {
  renderLogin();
  expect(screen.queryByRole("button", { name: /microsoft/i })).not.toBeInTheDocument();
  expect(initGoogleButton).not.toHaveBeenCalled();
});

test("Microsoft sign-in posts the ID token and navigates home", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  server.use(
    http.post("/api/v1/sso/microsoft", async ({ request }) => {
      expect(await request.json()).toEqual({ credential: "ms-id-token" });
      return HttpResponse.json({ access_token: "acc", refresh_token: "ref-ms", token_type: "bearer" });
    }),
  );
  renderLogin();
  await userEvent.click(screen.getByRole("button", { name: /microsoft/i }));
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
  expect(isAuthenticated()).toBe(true);
});

test("Microsoft sign-in surfaces the backend's error detail", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  server.use(
    http.post("/api/v1/sso/microsoft", () =>
      HttpResponse.json({ detail: "Tenant not allowed" }, { status: 403 }),
    ),
  );
  renderLogin();
  await userEvent.click(screen.getByRole("button", { name: /microsoft/i }));
  expect(await screen.findByText("Tenant not allowed")).toBeInTheDocument();
});

test("Google button mounts and its credential posts to the API", async () => {
  vi.mocked(googleEnabled).mockReturnValue(true);
  let onCredential: ((credential: string) => void) | undefined;
  vi.mocked(initGoogleButton).mockImplementation(async (_el, cb) => {
    onCredential = cb;
  });
  server.use(
    http.post("/api/v1/sso/google", async ({ request }) => {
      expect(await request.json()).toEqual({ credential: "g-id-token" });
      return HttpResponse.json({ access_token: "acc", refresh_token: "ref-g", token_type: "bearer" });
    }),
  );
  renderLogin();
  await vi.waitFor(() => expect(initGoogleButton).toHaveBeenCalled());
  onCredential!("g-id-token");
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
  expect(isAuthenticated()).toBe(true);
});

test("MFA-enabled login asks for a code, then verify signs in", async () => {
  server.use(
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json({ mfa_required: true, mfa_token: "challenge-1" }),
    ),
    http.post("/api/v1/auth/mfa/verify", async ({ request }) => {
      expect(await request.json()).toEqual({ mfa_token: "challenge-1", code: "123456" });
      return HttpResponse.json({ access_token: "acc", refresh_token: "r", token_type: "bearer" });
    }),
  );
  renderLogin();
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
  await userEvent.type(screen.getByLabelText(/password/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
  await userEvent.type(await screen.findByLabelText(/authentication code/i), "123456");
  await userEvent.click(screen.getByRole("button", { name: /verify/i }));
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
  expect(isAuthenticated()).toBe(true);
});

test("bad credentials show the API detail", async () => {
  server.use(
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json({ detail: "Incorrect email or password" }, { status: 401 }),
    ),
  );
  renderLogin();
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
  await userEvent.type(screen.getByLabelText(/password/i), "nope");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(await screen.findByText("Incorrect email or password")).toBeInTheDocument();
});

test("the sign-in screen shows the product name and what it stands for, under its own h1", () => {
  renderLogin();
  expect(screen.getByText("QEOS")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
  expect(screen.getByText("Quality Engineering OS")).toBeInTheDocument();
});

const tokens = { access_token: "acc", refresh_token: "ref", token_type: "bearer" };

async function signIn() {
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.co");
  await userEvent.type(screen.getByLabelText(/password/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
}

test("sign-in returns to the page the user asked for", async () => {
  server.use(http.post("/api/v1/auth/login", () => HttpResponse.json(tokens)));
  renderLogin("/login?next=%2Finvitations%2Ftok-1");
  await signIn();
  expect(await screen.findByText("INVITATION")).toBeInTheDocument();
});

test("MFA completion returns to the page the user asked for", async () => {
  server.use(
    http.post("/api/v1/auth/login", () => HttpResponse.json({ mfa_required: true, mfa_token: "c" })),
    http.post("/api/v1/auth/mfa/verify", () => HttpResponse.json(tokens)),
  );
  renderLogin("/login?next=%2Fprojects%2F42%2Fruns");
  await signIn();
  await userEvent.type(await screen.findByLabelText(/authentication code/i), "123456");
  await userEvent.click(screen.getByRole("button", { name: /verify/i }));
  expect(await screen.findByText("RUNS")).toBeInTheDocument();
});

test("SSO completion returns to the page the user asked for", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  server.use(http.post("/api/v1/sso/microsoft", () => HttpResponse.json(tokens)));
  renderLogin("/login?next=%2Finvitations%2Ftok-1");
  await userEvent.click(screen.getByRole("button", { name: /microsoft/i }));
  expect(await screen.findByText("INVITATION")).toBeInTheDocument();
});

test.each(["//evil.example", "https://evil.example", "/\\evil.example"])(
  "an unsafe next (%s) is ignored: sign-in goes home",
  async (next) => {
    server.use(http.post("/api/v1/auth/login", () => HttpResponse.json(tokens)));
    renderLogin(`/login?next=${encodeURIComponent(next)}`);
    await signIn();
    expect(await screen.findByText("PICKER")).toBeInTheDocument();
  },
);

test("an expired session says so", () => {
  renderLogin("/login?reason=expired");
  expect(screen.getByRole("status")).toHaveTextContent("Your session expired, sign in again");
});

test("no expiry notice on a plain visit", () => {
  renderLogin();
  expect(screen.queryByText(/session expired/i)).not.toBeInTheDocument();
});

function Where() {
  const { pathname } = useLocation();
  return <output data-testid="where">{pathname}</output>;
}

async function renderGoogleLogin(url: string) {
  vi.mocked(googleEnabled).mockReturnValue(true);
  let callback: (credential: string) => void = () => {};
  vi.mocked(initGoogleButton).mockImplementation(async (_el, onCredential) => { callback = onCredential; });
  render(
    <MemoryRouter initialEntries={[url]}>
      <Link to="/login?next=%2Finvitations%2Ftok-2">switch</Link>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/projects/:id/runs" element={<div>RUNS</div>} />
        <Route path="/invitations/:token" element={<div>INVITATION</div>} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
  await waitFor(() => expect(initGoogleButton).toHaveBeenCalled());
  return (credential: string) => act(async () => { callback(credential); });
}

test("the Google button callback uses the page asked for now, not the one at mount", async () => {
  server.use(http.post("/api/v1/sso/google", () => HttpResponse.json(tokens)));
  const google = await renderGoogleLogin("/login?next=%2Fprojects%2F42%2Fruns");
  await userEvent.click(screen.getByRole("link", { name: "switch" }));
  await google("g-cred");
  expect(await screen.findByText("INVITATION")).toBeInTheDocument();
});

test("a double-encoded next stays an in-app path: it is never decoded into //evil", async () => {
  server.use(http.post("/api/v1/sso/google", () => HttpResponse.json(tokens)));
  const google = await renderGoogleLogin("/login?next=%2F%252F%252Fevil.example");
  await google("g-cred");
  expect((await screen.findByTestId("where")).textContent).toBe("/%2F%2Fevil.example");
  expect(window.location.hostname).not.toBe("evil.example");
});

function methods(body: unknown, init?: ResponseInit) {
  server.use(http.get("/api/v1/auth/methods", () => HttpResponse.json(body as object, init)));
}

test("SSO-only: the Microsoft button and one line, no register or forgot-password links", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  methods({ password: false, providers: ["microsoft"] });
  renderLogin();
  expect(await screen.findByText("Sign-in is through your Microsoft work account.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign in with Microsoft" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /create account/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /forgot password/i })).not.toBeInTheDocument();
  const disclosure = screen.getByText("Administrator sign-in").closest("details")!;
  expect(disclosure).not.toHaveAttribute("open");
  expect(within(disclosure).getByLabelText(/email/i)).toBeInTheDocument();
});

test("SSO-only: an administrator signs in with the password form inside the disclosure", async () => {
  methods({ password: false, providers: ["microsoft"] });
  server.use(http.post("/api/v1/auth/login", () =>
    HttpResponse.json({ access_token: "acc", refresh_token: "r", token_type: "bearer" })));
  renderLogin();
  await userEvent.click(await screen.findByText("Administrator sign-in"));
  await userEvent.type(screen.getByLabelText(/email/i), "root@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
});

test("SSO-only: a refusal from the server shows in the card", async () => {
  methods({ password: false, providers: ["microsoft"] });
  server.use(http.post("/api/v1/auth/login", () => HttpResponse.json(
    { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } }, { status: 403 })));
  renderLogin();
  await userEvent.click(await screen.findByText("Administrator sign-in"));
  await userEvent.type(screen.getByLabelText(/email/i), "ann@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in is through Microsoft only.");
});

test("SSO-only hides a provider the mode does not list", async () => {
  vi.mocked(googleEnabled).mockReturnValue(true);
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  methods({ password: false, providers: ["microsoft"] });
  renderLogin();
  await screen.findByText("Sign-in is through your Microsoft work account.");
  expect(screen.queryByTestId("google-button")).not.toBeInTheDocument();
});

test("normal mode is unchanged when /auth/methods says password", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  let asked = false;
  server.use(http.get("/api/v1/auth/methods", () => {
    asked = true;
    return HttpResponse.json({ password: true, providers: ["microsoft"] });
  }));
  renderLogin();
  await waitFor(() => expect(asked).toBe(true));
  expect(screen.getByRole("link", { name: /forgot password/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /create account/i })).toBeInTheDocument();
  expect(screen.queryByText("Administrator sign-in")).not.toBeInTheDocument();
});

test.each<[string, () => Response]>([
  ["a server error", () => HttpResponse.json({ detail: "boom" }, { status: 500 })],
  ["a network error", () => HttpResponse.error()],
  ["an older server's 404", () => HttpResponse.json({ detail: "Not Found" }, { status: 404 })],
  ["an answer of the wrong shape", () => HttpResponse.json({})],
])("when /auth/methods gives %s, the normal form stays", async (_name, answer) => {
  let asked = false;
  server.use(http.get("/api/v1/auth/methods", () => {
    asked = true;
    return answer();
  }));
  renderLogin();
  await waitFor(() => expect(asked).toBe(true));
  await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
  expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /forgot password/i })).toBeInTheDocument();
  expect(screen.queryByText("Administrator sign-in")).not.toBeInTheDocument();
});
