import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { CiTarget } from "../api/runRequests";
import CiTargetCard, { ExpiryWarning } from "./CiTargetCard";

const P = "/api/v1/projects/42";
const NONE = { available: true, configured: false, provider: null, repo: null, workflow: null, ref: null,
  token_last4: null, token_expires_at: null, updated_at: null, last_change: null };
const CONNECTED = { ...NONE, configured: true, provider: "github", repo: "acme/obt", workflow: "qeos-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: "2027-03-12T00:00:00Z", updated_at: "2026-10-07T10:00:00Z",
  last_change: { action: "created", user_id: 7, at: "2026-10-07T10:00:00Z" } };
const TOKEN = "github_pat_xyz0000000000000000a1b2";

function renderCard() {
  setAccessToken("acc");
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, name: "Web", organization_id: 1, my_role: "owner" })),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([
      { id: 1, organization_id: 1, user_id: 7, email: "ana@example.com", role: "owner", status: "active",
        created_at: "2026-01-01T00:00:00Z", updated_at: null }])),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><CiTargetCard projectId={42} /></MemoryRouter></QueryClientProvider>);
  return qc;
}

test("a first save sends repo, workflow, branch and token, then shows the connection", async () => {
  let sent: unknown = null;
  let target: typeof NONE | typeof CONNECTED = NONE;
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(target)),
    http.put(`${P}/ci-target`, async ({ request }) => {
      sent = await request.json();
      target = CONNECTED;
      return HttpResponse.json(CONNECTED);
    }),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("Repository"), "acme/obt");
  expect(screen.getByLabelText("Workflow file")).toHaveValue("qeos-run.yml");
  expect(screen.getByLabelText("Branch")).toHaveValue("main");
  await userEvent.type(screen.getByLabelText("Token"), TOKEN);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Connected: acme/obt · token …a1b2 · expires 12 Mar 2027")).toBeInTheDocument();
  expect(sent).toEqual({ repo: "acme/obt", workflow: "qeos-run.yml", ref: "main", token: TOKEN });
  expect(await screen.findByText("Last changed by ana@example.com on 7 Oct 2026")).toBeInTheDocument();
  expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Replace token" })).toBeInTheDocument();
});

test("GitHub's specific refusal shows next to the form", async () => {
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(NONE)),
    http.put(`${P}/ci-target`, () =>
      HttpResponse.json({ detail: "token has no Actions access to this repository" }, { status: 422 })),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("Repository"), "acme/obt");
  await userEvent.type(screen.getByLabelText("Token"), TOKEN);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("token has no Actions access to this repository");
});

test("saving keeps the stored token; Replace token sends a new one", async () => {
  const bodies: unknown[] = [];
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(CONNECTED)),
    http.put(`${P}/ci-target`, async ({ request }) => { bodies.push(await request.json()); return HttpResponse.json(CONNECTED); }),
  );
  renderCard();
  const branch = await screen.findByLabelText("Branch");
  await userEvent.clear(branch);
  await userEvent.type(branch, "release");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(bodies).toEqual([{ repo: "acme/obt", workflow: "qeos-run.yml", ref: "release" }]));
  await userEvent.click(screen.getByRole("button", { name: "Replace token" }));
  expect(screen.getByLabelText("Token")).toHaveFocus();
  await userEvent.type(screen.getByLabelText("Token"), "github_pat_new0000000000000000zzzz");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies[1]).toMatchObject({ token: "github_pat_new0000000000000000zzzz" });
});

test("disconnect asks first, then removes the target", async () => {
  let deleted = false;
  let target: typeof NONE | typeof CONNECTED = CONNECTED;
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(target)),
    http.delete(`${P}/ci-target`, () => { deleted = true; target = NONE; return new HttpResponse(null, { status: 204 }); }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  expect(deleted).toBe(false);
  expect(screen.getByText(/Disconnect acme\/obt\?/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(deleted).toBe(true));
  await waitFor(() => expect(screen.getByLabelText("Repository")).toHaveValue(""));
});

test("a server without TM_SECRETS_KEY says so and shows no form", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...NONE, available: false })));
  renderCard();
  expect(await screen.findByText(/not configured on this server/i)).toBeInTheDocument();
  expect(screen.queryByLabelText("Repository")).not.toBeInTheDocument();
});

test("within 14 days of expiry the card warns", async () => {
  const soon = new Date(Date.now() + 5 * 86_400_000).toISOString();
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, token_expires_at: soon })));
  renderCard();
  expect(await screen.findByText(/^The GitHub token expires on .+\. Replace it in Settings$/)).toBeInTheDocument();
});

test("an expired token says so", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, token_expires_at: "2020-01-01T00:00:00Z" })));
  renderCard();
  expect(await screen.findByText("The GitHub token expired on 1 Jan 2020. Replace it in Settings")).toBeInTheDocument();
});

test("a token far from expiry shows no warning", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json(CONNECTED)));
  renderCard();
  await screen.findByText("Connected: acme/obt · token …a1b2 · expires 12 Mar 2027"); // loaded
  expect(screen.queryByText(/Replace it in Settings/)).not.toBeInTheDocument();
});

test("the help block holds the workflow for the configured branch and the script, ready to copy", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, ref: "release" })));
  renderCard();
  await userEvent.click(await screen.findByText("How to set it up"));
  const workflow = screen.getByLabelText("qeos-run.yml");
  expect(workflow).toHaveTextContent("if: github.ref == 'refs/heads/release'");
  expect(workflow).toHaveTextContent('run-name: "QEOS #${{ inputs.request_id }}"');
  expect(screen.getByLabelText("qeos-run.mjs")).toHaveTextContent('"--retry", "0"');
  expect(screen.getByText(/Actions: Read and write/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy qeos-run.yml" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy qeos-run.mjs" })).toBeInTheDocument();
});

test("a branch with $& and a quote reaches the workflow guard literally, the quote doubled", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, ref: "feat/it's-$&" })));
  renderCard();
  await userEvent.click(await screen.findByText("How to set it up"));
  expect(screen.getByLabelText("qeos-run.yml"))
    .toHaveTextContent("if: github.ref == 'refs/heads/feat/it''s-$&'");
});

test("the help block names the configured workflow file, not the default", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, workflow: "other.yml" })));
  renderCard();
  await userEvent.click(await screen.findByText("How to set it up"));
  expect(screen.getByLabelText("other.yml")).toHaveTextContent("name: QEOS run");
  expect(screen.getByRole("button", { name: "Copy other.yml" })).toBeInTheDocument();
  expect(screen.getByText(".github/workflows/other.yml")).toBeInTheDocument();
  expect(screen.queryByLabelText("qeos-run.yml")).not.toBeInTheDocument();
});

test("the help block says the workflow and the script must exist on the configured branch too", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, ref: "release" })));
  renderCard();
  await userEvent.click(await screen.findByText("How to set it up"));
  expect(screen.getByText(/also on the branch set above \(release\)/)).toBeInTheDocument();
});

test("an expired token reads Expired on the date, not Connected", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, token_expires_at: "2020-01-01T00:00:00Z" })));
  renderCard();
  expect(await screen.findByText("acme/obt · token …a1b2 · Expired on 1 Jan 2020")).toBeInTheDocument();
  expect(screen.queryByText(/Connected/)).not.toBeInTheDocument();
});

const refuse = () => http.put(`${P}/ci-target`, () => HttpResponse.json({ detail: "GitHub refused the token" }, { status: 422 }));

test("a failed save's error goes when the token is replaced", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json(CONNECTED)), refuse());
  renderCard();
  await userEvent.click(await screen.findByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("GitHub refused the token");
  await userEvent.click(screen.getByRole("button", { name: "Replace token" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("a failed save's error goes when the target is disconnected", async () => {
  let target: typeof NONE | typeof CONNECTED = CONNECTED;
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(target)), refuse(),
    http.delete(`${P}/ci-target`, () => { target = NONE; return new HttpResponse(null, { status: 204 }); }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("button", { name: "Save" }));
  await screen.findByRole("alert");
  await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(screen.getByLabelText("Repository")).toHaveValue(""));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("a refetch does not overwrite what the owner is typing", async () => {
  let reads = 0;
  server.use(http.get(`${P}/ci-target`, () => { reads += 1; return HttpResponse.json({ ...CONNECTED, updated_at: `2026-10-07T10:0${reads}:00Z` }); }));
  const qc = renderCard();
  const branch = await screen.findByLabelText("Branch");
  await userEvent.clear(branch);
  await userEvent.type(branch, "release");
  await qc.invalidateQueries({ queryKey: ["ci-target", 42] });
  expect(reads).toBe(2);
  expect(screen.getByLabelText("Branch")).toHaveValue("release");
});

test.each([
  ["Workflow file", "my workflow.yml"],
  ["Workflow file", "build.txt"],
  ["Branch", "a..b"],
  ["Branch", "has space"],
  ["Branch", "-lead"],
  ["Branch", "end."],
  ["Branch", "x.lock"],
  ["Branch", "/lead"],
  ["Branch", "trail/"],
  ["Branch", "a//b"],
  ["Branch", "a@{b"],
  ["Branch", "a~b"],
  ["Branch", "a^b"],
  ["Branch", "a:b"],
  ["Branch", "a?b"],
  ["Branch", "a*b"],
  ["Branch", "a[b"],
  ["Branch", "a\\b"],
  ["Branch", "a.lock/b"],
  ["Branch", "x".repeat(256)],
])("%s %j is refused in the form, with its error linked to the field", async (label, value) => {
  let puts = 0;
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json(CONNECTED)), http.put(`${P}/ci-target`, () => { puts += 1; return HttpResponse.json(CONNECTED); }));
  renderCard();
  const field = await screen.findByLabelText(label);
  await userEvent.clear(field);
  await userEvent.click(field);
  await userEvent.paste(value);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const described = field.getAttribute("aria-describedby");
  expect(described).toBeTruthy();
  expect(document.getElementById(described as string)).toHaveTextContent(/./);
  expect(field).toHaveAttribute("aria-invalid", "true");
  expect(puts).toBe(0);
});

test("a branch with a slash and a dot is accepted", async () => {
  const bodies: unknown[] = [];
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json(CONNECTED)),
    http.put(`${P}/ci-target`, async ({ request }) => { bodies.push(await request.json()); return HttpResponse.json(CONNECTED); }));
  renderCard();
  const branch = await screen.findByLabelText("Branch");
  await userEvent.clear(branch);
  await userEvent.type(branch, "release/1.2-rc");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(bodies).toEqual([{ repo: "acme/obt", workflow: "qeos-run.yml", ref: "release/1.2-rc" }]));
});

test("the expiry warning sits in a live region that exists before the warning does", () => {
  const { container, rerender } = render(<ExpiryWarning target={CONNECTED as CiTarget} />);
  const region = container.querySelector('[role="status"]');
  expect(region).not.toBeNull();
  expect(region).toBeEmptyDOMElement();
  rerender(<ExpiryWarning target={{ ...CONNECTED, token_expires_at: "2020-01-01T00:00:00Z" } as CiTarget} />);
  expect(container.querySelector('[role="status"]')).toBe(region);
  expect(region).toHaveTextContent("The GitHub token expired on 1 Jan 2020");
});

test("only the block copied last says Copied, and the copy is announced", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json(CONNECTED)));
  const user = userEvent.setup();
  renderCard();
  await user.click(await screen.findByText("How to set it up"));
  const workflowButton = screen.getByRole("button", { name: "Copy qeos-run.yml" });
  const scriptButton = screen.getByRole("button", { name: "Copy qeos-run.mjs" });
  await user.click(workflowButton);
  await waitFor(() => expect(workflowButton).toHaveTextContent("Copied"));
  expect(scriptButton).toHaveTextContent(/^Copy$/);
  expect(await navigator.clipboard.readText()).toContain("name: QEOS run");
  expect(screen.getByText("qeos-run.yml copied", { selector: "[role=status]" })).toBeInTheDocument();
  await user.click(scriptButton);
  await waitFor(() => expect(scriptButton).toHaveTextContent("Copied"));
  expect(workflowButton).toHaveTextContent(/^Copy$/);
});
