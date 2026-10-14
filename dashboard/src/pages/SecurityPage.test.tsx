import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { getAccessToken, setAccessToken } from "../auth/tokens";
import { microsoftEnabled } from "../auth/ssoProviders";
import SecurityPage from "./SecurityPage";

vi.mock("qrcode", () => ({
  default: { toCanvas: vi.fn(async () => {}) },
}));

vi.mock("../auth/ssoProviders", () => ({
  microsoftEnabled: vi.fn(() => false),
  getMicrosoftCredential: vi.fn(async () => "ms-id-token"),
}));

let mfaOn = false;
beforeEach(() => {
  mfaOn = false;
  vi.mocked(microsoftEnabled).mockReturnValue(false);
  server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ id: 1, email: "a@b.co", mfa_enabled: mfaOn })));
});

function renderSecurity() {
  setAccessToken("acc");
  render(
    <MemoryRouter initialEntries={["/account/security"]}>
      <SecurityPage />
    </MemoryRouter>,
  );
}

test("enroll shows the secret and confirm reveals recovery codes", async () => {
  server.use(
    http.post("/api/v1/auth/mfa/enroll", () =>
      HttpResponse.json({ secret: "BASE32SECRET", otpauth_uri: "otpauth://totp/QA%20Vision:a@b.co?secret=BASE32SECRET" }),
    ),
    http.post("/api/v1/auth/mfa/confirm", async ({ request }) => {
      expect(await request.json()).toEqual({ code: "123456" });
      return HttpResponse.json({ recovery_codes: ["aaaa-1111", "bbbb-2222"] });
    }),
  );
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: /set up/i }));
  expect(await screen.findByText("BASE32SECRET")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText(/code/i), "123456");
  await userEvent.click(screen.getByRole("button", { name: /confirm code/i }));
  expect(await screen.findByText("aaaa-1111")).toBeInTheDocument();
  expect(screen.getByText(/shown only once/i)).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Recovery codes" })).toHaveTextContent("bbbb-2222");
  expect(screen.getByRole("button", { name: "Copy recovery codes" })).toBeInTheDocument();
});

test("a wrong confirm code surfaces the error", async () => {
  server.use(
    http.post("/api/v1/auth/mfa/enroll", () =>
      HttpResponse.json({ secret: "S", otpauth_uri: "otpauth://totp/x" }),
    ),
    http.post("/api/v1/auth/mfa/confirm", () =>
      HttpResponse.json({ detail: "Invalid code" }, { status: 400 }),
    ),
  );
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: /set up/i }));
  await screen.findByText("S");
  await userEvent.type(screen.getByLabelText(/code/i), "000000");
  await userEvent.click(screen.getByRole("button", { name: /confirm code/i }));
  expect(await screen.findByText("Invalid code")).toBeInTheDocument();
});

async function fillChange(current: string, next: string, confirm = next) {
  await userEvent.type(await screen.findByLabelText(/current password/i), current);
  await userEvent.type(screen.getByLabelText(/^new password/i), next);
  await userEvent.type(screen.getByLabelText(/confirm new password/i), confirm);
  await userEvent.click(screen.getByRole("button", { name: /change password/i }));
}

test("changing the password sends both and confirms", async () => {
  let sent: unknown = null;
  server.use(
    http.post("/api/v1/auth/change-password", async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ access_token: "new-acc", refresh_token: "r", token_type: "bearer" });
    }),
  );
  renderSecurity();
  await fillChange("old-password-1", "new-password-22");

  expect(await screen.findByText(/password changed/i)).toBeInTheDocument();
  expect(sent).toEqual({ current_password: "old-password-1", new_password: "new-password-22" });
  expect(getAccessToken()).toBe("new-acc");
  // Cleared, so the passwords do not linger in the page
  expect(screen.getByLabelText(/current password/i)).toHaveValue("");
});

test("a wrong current password is reported next to the form", async () => {
  server.use(
    http.post("/api/v1/auth/change-password", () =>
      HttpResponse.json({ detail: "Current password is incorrect" }, { status: 400 })),
  );
  renderSecurity();
  await fillChange("nope-nope-nope", "new-password-22");
  expect(await screen.findByText("Current password is incorrect")).toBeInTheDocument();
});

test("a mismatched confirmation never reaches the server", async () => {
  let called = false;
  server.use(
    http.post("/api/v1/auth/change-password", () => {
      called = true;
      return HttpResponse.json({});
    }),
  );
  renderSecurity();
  await fillChange("old-password-1", "new-password-22", "new-password-23");
  expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
  expect(called).toBe(false);
});

const enrollHandlers = () => [
  http.post("/api/v1/auth/mfa/enroll", () => HttpResponse.json({ secret: "S3CRET", otpauth_uri: "otpauth://totp/x" })),
  http.post("/api/v1/auth/mfa/confirm", () => HttpResponse.json({ recovery_codes: ["aaaa-1111", "bbbb-2222"] })),
  http.post("/api/v1/auth/mfa/disable", () => new HttpResponse(null, { status: 204 })),
];

test("two-factor status comes from the account and is refreshed after enrolling", async () => {
  server.use(...enrollHandlers());
  renderSecurity();
  expect(await screen.findByText("Two-factor authentication: Off")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /set up/i }));
  await userEvent.type(await screen.findByLabelText(/code from the app/i), "123456");
  mfaOn = true;
  await userEvent.click(screen.getByRole("button", { name: /confirm code/i }));
  expect(await screen.findByText("Two-factor authentication: On")).toBeInTheDocument();
});

test("an account with two-factor on says so at once", async () => {
  mfaOn = true;
  renderSecurity();
  expect(await screen.findByText("Two-factor authentication: On")).toBeInTheDocument();
});

test("enrolling can be cancelled, and focus returns to the button that started it", async () => {
  server.use(...enrollHandlers());
  renderSecurity();
  const setup = await screen.findByRole("button", { name: /set up/i });
  await userEvent.click(setup);
  await screen.findByText("S3CRET");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByText("S3CRET")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /set up/i })).toHaveFocus();
});

test("disabling is a danger action that can be cancelled", async () => {
  server.use(...enrollHandlers());
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: /^disable two-factor/i }));
  const submit = screen.getByRole("button", { name: /^disable two-factor/i });
  expect(submit).toHaveClass("danger");
  expect(submit).not.toHaveClass("primary");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: /^disable two-factor/i })).toHaveFocus();
  expect(screen.getByRole("button", { name: /^disable two-factor/i })).not.toHaveClass("danger");
  // And completing it turns the status off
  await userEvent.click(screen.getByRole("button", { name: /^disable two-factor/i }));
  await userEvent.type(screen.getByLabelText(/current code/i), "123456");
  await userEvent.click(screen.getByRole("button", { name: /^disable two-factor/i }));
  expect(await screen.findByText("Two-factor authentication: Off")).toBeInTheDocument();
});

test("recovery codes can be copied and must be acknowledged before they go away", async () => {
  server.use(...enrollHandlers());
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: /set up/i }));
  await userEvent.type(await screen.findByLabelText(/code from the app/i), "123456");
  mfaOn = true;
  await userEvent.click(screen.getByRole("button", { name: /confirm code/i }));
  expect(await screen.findByRole("button", { name: "Copy recovery codes" })).toBeInTheDocument();
  expect(screen.getByText("aaaa-1111")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /i saved these codes/i }));
  expect(screen.queryByText("aaaa-1111")).not.toBeInTheDocument();
  expect(screen.getByText("Two-factor authentication: On")).toBeInTheDocument();
});

type MeBody = Record<string, unknown>;
function meIs(body: MeBody) {
  server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ id: 1, email: "a@b.co", mfa_enabled: false, ...body })));
}
async function microsoftCard() {
  return (await screen.findByRole("heading", { name: "Microsoft account" })).closest("form")!;
}

test("a password account links Microsoft after confirming its password", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  let linked = false;
  server.use(
    http.get("/api/v1/users/me", () => HttpResponse.json({ id: 1, email: "a@b.co", mfa_enabled: false,
      has_password: true, sso_only: false, linked_providers: linked ? ["microsoft"] : [] })),
    http.post("/api/v1/users/me/link/microsoft", async ({ request }) => {
      expect(await request.json()).toEqual({ credential: "ms-id-token", current_password: "my-password-1" });
      linked = true;
      return HttpResponse.json({ id: 1, email: "a@b.co" });
    }),
  );
  renderSecurity();
  const card = await microsoftCard();
  await userEvent.type(within(card).getByLabelText(/your qeos password/i), "my-password-1");
  await userEvent.click(within(card).getByRole("button", { name: "Link Microsoft account" }));
  expect(await within(card).findByText(/microsoft account linked/i)).toBeInTheDocument();
  expect(await within(card).findByText("Linked to Microsoft")).toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: "Link Microsoft account" })).not.toBeInTheDocument();
});

test("a passwordless account links without a password prompt", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  meIs({ has_password: false, linked_providers: ["google"] });
  server.use(http.post("/api/v1/users/me/link/microsoft", async ({ request }) => {
    expect(await request.json()).toEqual({ credential: "ms-id-token" });
    return HttpResponse.json({ id: 1, email: "a@b.co" });
  }));
  renderSecurity();
  const card = await microsoftCard();
  expect(within(card).queryByLabelText(/your qeos password/i)).not.toBeInTheDocument();
  await userEvent.click(within(card).getByRole("button", { name: "Link Microsoft account" }));
  expect(await within(card).findByText(/microsoft account linked/i)).toBeInTheDocument();
});

test("a link refusal is shown in the card", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  meIs({ has_password: true, linked_providers: [] });
  server.use(http.post("/api/v1/users/me/link/microsoft", () =>
    HttpResponse.json({ detail: "This Microsoft account is already linked to a different user" }, { status: 409 })));
  renderSecurity();
  const card = await microsoftCard();
  await userEvent.type(within(card).getByLabelText(/your qeos password/i), "my-password-1");
  await userEvent.click(within(card).getByRole("button", { name: "Link Microsoft account" }));
  expect(await within(card).findByRole("alert")).toHaveTextContent("already linked to a different user");
});

test("a linked account says so and offers no button", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  meIs({ has_password: true, linked_providers: ["microsoft"] });
  renderSecurity();
  const card = await microsoftCard();
  expect(within(card).getByText("Linked to Microsoft")).toBeInTheDocument();
  expect(within(card).queryByRole("button")).not.toBeInTheDocument();
});

test("without Microsoft configured and outside the mode there is no Microsoft card", async () => {
  meIs({ has_password: true, linked_providers: [], sso_only: false });
  renderSecurity();
  await screen.findByText(/two-factor authentication: off/i);
  expect(screen.queryByRole("heading", { name: "Microsoft account" })).not.toBeInTheDocument();
});

test("in SSO-only mode the Password card is hidden for a non-superuser", async () => {
  meIs({ has_password: true, linked_providers: ["microsoft"], sso_only: true, is_superuser: false });
  renderSecurity();
  await screen.findByRole("heading", { name: "Microsoft account" });
  expect(screen.queryByRole("heading", { name: "Password" })).not.toBeInTheDocument();
});

test("in SSO-only mode a superuser keeps the Password card", async () => {
  meIs({ has_password: true, linked_providers: [], sso_only: true, is_superuser: true });
  server.use(http.get("/api/v1/users/sso-readiness", () => HttpResponse.json({ active_users: 1, linked: 0, unlinked: [] })));
  renderSecurity();
  await screen.findByRole("heading", { name: "Microsoft account" });
  expect(screen.getByRole("heading", { name: "Password" })).toBeInTheDocument();
});

test("the Password card waits for the account, so an SSO-only non-superuser never sees it flash", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  server.use(http.get("/api/v1/users/me", async () => {
    await gate;
    return HttpResponse.json({ id: 1, email: "a@b.co", mfa_enabled: false, has_password: true,
      linked_providers: ["microsoft"], sso_only: true, is_superuser: false });
  }));
  renderSecurity();
  expect(screen.getByText(/checking two-factor status/i)).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Password" })).not.toBeInTheDocument();
  release();
  await screen.findByRole("heading", { name: "Microsoft account" });
  expect(screen.queryByRole("heading", { name: "Password" })).not.toBeInTheDocument();
});

const READINESS = {
  active_users: 15,
  linked: 12,
  unlinked: [
    { id: 7, email: "ana@example.com", full_name: "Ana", is_superuser: false, link_allowed_until: null },
    { id: 1, email: "root@example.com", full_name: null, is_superuser: true, link_allowed_until: "2026-10-21T10:00:00+00:00" },
  ],
};

test("a superuser sees the mode, the readiness and who has not linked", async () => {
  meIs({ is_superuser: true, sso_only: false, has_password: true, linked_providers: [] });
  server.use(http.get("/api/v1/users/sso-readiness", () => HttpResponse.json(READINESS)));
  renderSecurity();
  const card = (await screen.findByRole("heading", { name: "Microsoft-only sign-in" })).closest("section")!;
  expect(within(card).getByText("Microsoft-only sign-in: Off")).toBeInTheDocument();
  expect(within(card).getByText("AUTH_SSO_ONLY=true")).toBeInTheDocument();
  expect(await within(card).findByText("12 of 15 active users have linked Microsoft.")).toBeInTheDocument();
  expect(within(card).getByRole("button", { name: "Allow link at next sign-in for ana@example.com" })).toBeInTheDocument();
  const rootRow = within(card).getByText("root@example.com").closest("tr")!;
  expect(within(rootRow).getByText(/allowed until/i)).toBeInTheDocument();
  expect(within(rootRow).getByText(/superuser/i)).toBeInTheDocument();
});

test("allowing a link shows until when", async () => {
  meIs({ is_superuser: true, sso_only: true, has_password: true, linked_providers: ["microsoft"] });
  server.use(
    http.get("/api/v1/users/sso-readiness", () => HttpResponse.json(READINESS)),
    http.post("/api/v1/users/7/allow-microsoft-link", () => HttpResponse.json(
      { ...READINESS.unlinked[0], link_allowed_until: "2026-10-21T12:00:00+00:00" })),
  );
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: "Allow link at next sign-in for ana@example.com" }));
  const anaRow = (await screen.findByText("ana@example.com")).closest("tr")!;
  expect(await within(anaRow).findByText(/allowed until/i)).toBeInTheDocument();
  expect(screen.getByText("Microsoft-only sign-in: On")).toBeInTheDocument();
});

test("an allow refusal is shown in the card", async () => {
  meIs({ is_superuser: true, sso_only: true, has_password: true, linked_providers: ["microsoft"] });
  server.use(
    http.get("/api/v1/users/sso-readiness", () => HttpResponse.json(READINESS)),
    http.post("/api/v1/users/7/allow-microsoft-link", () =>
      HttpResponse.json({ detail: "User has already linked Microsoft" }, { status: 409 })),
  );
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: "Allow link at next sign-in for ana@example.com" }));
  const card = screen.getByRole("heading", { name: "Microsoft-only sign-in" }).closest("section")!;
  expect(await within(card).findByRole("alert")).toHaveTextContent("User has already linked Microsoft");
});

test("a non-superuser neither sees the card nor asks for readiness", async () => {
  let asked = false;
  meIs({ is_superuser: false, sso_only: true, has_password: false, linked_providers: ["microsoft"] });
  server.use(http.get("/api/v1/users/sso-readiness", () => {
    asked = true;
    return HttpResponse.json(READINESS);
  }));
  renderSecurity();
  await screen.findByRole("heading", { name: "Microsoft account" });
  // /users/me has answered (the two-factor status comes from the same response), so the card would be mounted by now
  expect(await screen.findByText("Two-factor authentication: Off")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Microsoft-only sign-in" })).not.toBeInTheDocument();
  expect(asked).toBe(false);
});

test("a refused allow refreshes the list so the stale row goes", async () => {
  meIs({ is_superuser: true, sso_only: true, has_password: true, linked_providers: ["microsoft"] });
  let reads = 0;
  server.use(
    http.get("/api/v1/users/sso-readiness", () => {
      reads += 1;
      return HttpResponse.json(reads === 1 ? READINESS
        : { active_users: 15, linked: 13, unlinked: [READINESS.unlinked[1]] });
    }),
    http.post("/api/v1/users/7/allow-microsoft-link", () =>
      HttpResponse.json({ detail: "User has already linked Microsoft" }, { status: 409 })),
  );
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: "Allow link at next sign-in for ana@example.com" }));
  const card = screen.getByRole("heading", { name: "Microsoft-only sign-in" }).closest("section")!;
  expect(await within(card).findByText("13 of 15 active users have linked Microsoft.")).toBeInTheDocument();
  expect(within(card).queryByText("ana@example.com")).not.toBeInTheDocument();
  expect(within(card).getByRole("alert")).toHaveTextContent("User has already linked Microsoft");
  expect(reads).toBe(2);
});
