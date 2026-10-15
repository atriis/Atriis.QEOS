import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import ProjectSettingsPage, { isLocalOrigin } from "./ProjectSettingsPage";

const KEYS = [
  { id: 1, name: "ci", key_prefix: "qeos_abcdefgh", can_read_impact: false, created_at: "2026-10-01T10:00:00Z",
    last_used_at: "2026-10-03T10:00:00Z", revoked_at: null },
  { id: 2, name: "old", key_prefix: "qeos_zzzzzzzz", can_read_impact: true, created_at: "2026-09-01T10:00:00Z",
    last_used_at: null, revoked_at: "2026-09-15T10:00:00Z" },
];

function renderPage(role = "member") {
  setAccessToken("acc");
  server.use(
    http.get("/api/v1/projects/42", () =>
      HttpResponse.json({ id: 42, name: "Web", organization_id: 1, my_role: role })),
    http.get("/api/v1/projects/42/repositories", () => HttpResponse.json([])),
    http.get("/api/v1/projects/42/masking-patterns", () => HttpResponse.json([])),
    http.get("/api/v1/projects/42/notification-channels", () => HttpResponse.json([])),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/projects/42/settings"]}>
        <Routes>
          <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("repositories come first, editable for members", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage("member");
  expect(screen.getAllByRole("heading", { level: 2 })[0]).toHaveTextContent("Repositories");
  expect(await screen.findByLabelText(/repository url/i)).toBeInTheDocument();
});

test("a viewer gets the repositories read-only", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage("viewer");
  expect(await screen.findByText(/only owners, admins and members can add or remove repositories/i)).toBeInTheDocument();
  expect(screen.queryByLabelText(/repository url/i)).not.toBeInTheDocument();
});

test("lists keys with prefix, last use, and revoked state", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json(KEYS)));
  renderPage();
  expect(await screen.findByText("qeos_abcdefgh…")).toBeInTheDocument();
  expect(screen.getByText("ci")).toBeInTheDocument();
  expect(screen.getByText(/revoked/i)).toBeInTheDocument();
  // a revoked key offers no revoke action
  expect(screen.getAllByRole("button", { name: /revoke/i })).toHaveLength(1);
});

test("creating a key shows the full key exactly once", async () => {
  server.use(
    http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])),
    http.post("/api/v1/projects/42/api-keys", () =>
      HttpResponse.json(
        { id: 3, name: "new-ci", key_prefix: "qeos_newnewne", key: "qeos_newnewnewFULLSECRET",
          created_at: "2026-10-03T12:00:00Z" },
        { status: 201 },
      )),
  );
  renderPage();
  await screen.findByText(/no api keys/i);
  await userEvent.type(screen.getByPlaceholderText("e.g. github-actions"), "new-ci");
  await userEvent.click(screen.getByRole("button", { name: /create key/i }));
  expect(await screen.findByText("qeos_newnewnewFULLSECRET")).toBeInTheDocument();
  expect(screen.getByText(/this is shown once/i)).toBeInTheDocument();
  const block = screen.getByRole("group", { name: "API key new-ci" });
  expect(block).toHaveClass("secret-block");
  expect(within(block).getByText("qeos_newnewnewFULLSECRET")).toHaveClass("secret-value");

  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  await userEvent.click(screen.getByRole("button", { name: /copy key new-ci/i }));
  expect(writeText).toHaveBeenCalledWith("qeos_newnewnewFULLSECRET");
  expect(await within(block).findByText("Copied", { selector: "[role=status]" })).toHaveAttribute("aria-live", "polite");
});

test("revoking a key calls the API and refreshes", async () => {
  let revoked = false;
  server.use(
    http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json(revoked ? [] : [KEYS[0]])),
    http.delete("/api/v1/projects/42/api-keys/1", () => {
      revoked = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderPage();
  await screen.findByText("ci");
  await userEvent.click(screen.getByRole("button", { name: "Revoke key ci" }));
  expect(revoked).toBe(false); // the first click only asks
  await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
  expect(await screen.findByText(/no api keys/i)).toBeInTheDocument();
  expect(revoked).toBe(true);
});


test("on localhost the CLI snippet leads, with the self-signed certificate step", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage();
  await screen.findByText(/no api keys/i);

  // the test page itself is served from http://localhost:3000
  expect(screen.getByLabelText(/ci platform/i)).toHaveValue("cli");
  const snippet = screen.getByTestId("ci-snippet");
  expect(snippet).toHaveTextContent("qeos-collector upload");
  expect(snippet).toHaveTextContent("--ca-file");
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
});

test("hosted CI runners on localhost get a warning, not a silent snippet", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage();
  await screen.findByText(/no api keys/i);

  await userEvent.selectOptions(screen.getByLabelText(/ci platform/i), "github");
  const github = screen.getByTestId("ci-snippet");
  expect(github).toHaveTextContent("collector-action@collector-v0");
  // the variable, guarded, so the same step is safe in a repository without QEOS; Cucumber JSON by default
  expect(github).toHaveTextContent("if: always() && vars.QEOS_URL != ''");
  expect(github).toHaveTextContent("url: ${{ vars.QEOS_URL }}");
  expect(github).toHaveTextContent("patterns: test-results/cucumber-report.json");
  expect(github).not.toHaveTextContent("localhost:3000");
  expect(github.textContent?.startsWith("- name: Upload results to QEOS")).toBe(true);
  expect(screen.getByText(/In the repository, Settings/)).toHaveTextContent("variable QEOS_URL (this QEOS address), secret QEOS_API_KEY");
  expect(screen.getByRole("note")).toHaveTextContent(/cannot reach localhost/i);

  await userEvent.selectOptions(screen.getByLabelText(/ci platform/i), "gitlab");
  expect(screen.getByRole("note")).toHaveTextContent(/cannot reach localhost/i);

  await userEvent.selectOptions(screen.getByLabelText(/ci platform/i), "azure");
  expect(screen.getByTestId("ci-snippet")).toHaveTextContent("QEOS_API_KEY: $(QEOS_API_KEY)");
  expect(screen.getByTestId("ci-snippet")).toHaveTextContent("condition: always()");
  expect(screen.getByRole("note")).toHaveTextContent(/cannot reach localhost/i);

  await userEvent.selectOptions(screen.getByLabelText(/ci platform/i), "jenkins");
  expect(screen.getByTestId("ci-snippet")).toHaveTextContent("qeosCollectorUpload");

  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  await userEvent.click(screen.getByRole("button", { name: /copy snippet for ci/i }));
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("qeosCollectorUpload"));
});

test.each([
  ["http://localhost:8080", true],
  ["https://localhost:8443", true],
  ["http://127.0.0.1:5173", true],
  ["http://[::1]:8443", true],
  ["https://qeos.example.com", false],
  ["https://localhost.example.com", false],
])("isLocalOrigin(%s) is %s", (origin, expected) => {
  expect(isLocalOrigin(origin)).toBe(expected);
});

test("the upload snippet only uploads; the sync snippet syncs test cases with the pinned collector", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage();
  await screen.findByText(/no api keys/i);

  const kind = screen.getByLabelText(/what to add/i);
  expect(kind).toHaveValue("upload");
  for (const platform of ["github", "gitlab", "azure", "jenkins", "cli"]) {
    await userEvent.selectOptions(screen.getByLabelText(/ci platform/i), platform);
    await userEvent.selectOptions(kind, "upload");
    expect(screen.getByTestId("ci-snippet")).not.toHaveTextContent("import-features");

    await userEvent.selectOptions(kind, "sync");
    const snippet = screen.getByTestId("ci-snippet");
    expect(snippet).toHaveTextContent("import-features");
    expect(snippet).toHaveTextContent("collector-v0");
    expect(snippet).not.toHaveTextContent("collector-v0.");
    expect(snippet).not.toHaveTextContent("qeos-collector upload");
    if (platform === "jenkins") {
      // Groovy comments are //, never #
      const lines = (snippet.textContent ?? "").split(/\r?\n/).map((l) => l.trim());
      expect(lines.filter((l) => l.startsWith("#"))).toEqual([]);
      // reuses the venv qeosCollectorUpload creates; no bare pip / qeos-collector (PEP 668 agents)
      expect(snippet).toHaveTextContent('.qeos-venv/bin/python -m qeos_collector import-features "tests/features/**/*.feature"');
      expect(snippet.textContent).not.toMatch(/^\s*pip install/m);
      expect(snippet.textContent).not.toMatch(/^\s*qeos-collector/m);
    }
  }
});

test("the GitHub sync snippet is the standalone workflow with the first_sync input", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage("owner");
  await screen.findByText(/no api keys/i);

  await userEvent.selectOptions(screen.getByLabelText(/ci platform/i), "github");
  await userEvent.selectOptions(screen.getByLabelText(/what to add/i), "sync");
  const snippet = screen.getByTestId("ci-snippet");
  expect(snippet).toHaveTextContent("qeos-sync-cases.yml");
  expect(snippet).toHaveTextContent("name: QEOS sync test cases");
  expect(snippet).toHaveTextContent('paths: ["tests/features/**"]');
  expect(snippet).toHaveTextContent("first_sync");
  expect(snippet).toHaveTextContent("--allow-mass-archive");
  expect(snippet).toHaveTextContent("QEOS_URL: ${{ vars.QEOS_URL }}");
  expect(snippet).not.toHaveTextContent("localhost:3000"); // the address lives in the variable, never in the file
  expect(screen.getByText(/commit this as/i)).toHaveTextContent("run it once by hand");

  // the copy button follows the kind
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  await userEvent.click(screen.getByRole("button", { name: /copy snippet for ci/i }));
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("QEOS sync test cases"));

  // the card tells owners where the Play workflow lives; it is not one of its snippets
  expect(screen.getByRole("link", { name: "Run from QEOS" })).toHaveAttribute("href", "#run-from-qeos");

  // switching back to the upload step clears the "Copied" state
  await userEvent.selectOptions(screen.getByLabelText(/what to add/i), "upload");
  expect(screen.getByRole("button", { name: /copy snippet for ci/i })).toHaveTextContent("Copy snippet");
  expect(screen.getByTestId("ci-snippet")).toHaveTextContent("collector-action@collector-v0");
});

test("Run from QEOS is shown to owners and admins", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage("admin");
  expect(await screen.findByRole("heading", { name: "Run from QEOS" })).toBeInTheDocument();
});

test("members do not see Run from QEOS", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage("member");
  await screen.findByLabelText(/repository url/i); // the member role has loaded: editing is enabled
  expect(screen.queryByRole("heading", { name: "Run from QEOS" })).not.toBeInTheDocument();
});

test.each(["owner", "admin", "member"])("a %s can create and revoke API keys", async (role) => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([KEYS[0]])));
  renderPage(role);
  expect(await screen.findByRole("button", { name: "Revoke key ci" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /create key/i })).toBeInTheDocument();
  expect(screen.queryByText(/only owners, admins and members manage api keys/i)).not.toBeInTheDocument();
});

test("a viewer sees the keys read-only, with a note", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([KEYS[0]])));
  renderPage("viewer");
  // positive signals first: the list and the note have loaded, so the absences below are real
  expect(await screen.findByText("qeos_abcdefgh…")).toBeInTheDocument();
  expect(await screen.findByText(/only owners, admins and members manage api keys/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /create key/i })).not.toBeInTheDocument();
  expect(screen.queryByPlaceholderText("e.g. github-actions")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /revoke/i })).not.toBeInTheDocument();
});

test("copy buttons carry their visible text in the name and announce Copied politely", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage();
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  const snippet = await screen.findByRole("button", { name: /copy snippet/i });
  expect(snippet).toHaveAccessibleName(expect.stringContaining("Copy snippet"));
  await userEvent.click(snippet);
  expect(await screen.findByText("Copied", { selector: "[role=status]" })).toBeInTheDocument();
});

describe("the test suggestions permission", () => {
  const HELP = "Lets qeos-collector impact and run-impact read this project's test suggestions.";

  function captureCreate() {
    const bodies: unknown[] = [];
    server.use(
      http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])),
      http.post("/api/v1/projects/42/api-keys", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ id: 3, name: "impact-ci", key_prefix: "qeos_newnewne", key: "qeos_newnewnewFULLSECRET",
          can_read_impact: true, created_at: "2026-10-03T12:00:00Z" }, { status: 201 });
      }),
    );
    return bodies;
  }

  test.each(["owner", "admin"])("a %s may create a key that reads them; the box starts off", async (role) => {
    const bodies = captureCreate();
    renderPage(role);
    const box = await screen.findByRole("checkbox", { name: "Can read test suggestions" });
    expect(box).not.toBeChecked();
    expect(box).toHaveAccessibleDescription(HELP);
    await userEvent.type(screen.getByPlaceholderText("e.g. github-actions"), "impact-ci");
    await userEvent.click(box);
    await userEvent.click(screen.getByRole("button", { name: /create key/i }));
    await screen.findByText("qeos_newnewnewFULLSECRET");
    expect(bodies).toEqual([{ name: "impact-ci", can_read_impact: true }]);
    expect(screen.getByRole("checkbox", { name: "Can read test suggestions" })).not.toBeChecked(); // reset for the next key
  });

  test("a member creates upload-only keys and has no box", async () => {
    const bodies = captureCreate();
    renderPage("member");
    await userEvent.type(await screen.findByPlaceholderText("e.g. github-actions"), "ci-2");
    expect(screen.queryByRole("checkbox", { name: "Can read test suggestions" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /create key/i }));
    await screen.findByText("qeos_newnewnewFULLSECRET");
    expect(bodies).toEqual([{ name: "ci-2", can_read_impact: false }]);
  });

  test.each(["member", "viewer"])("a %s sees On or Off as words, with no switch", async (role) => {
    server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([KEYS[0], { ...KEYS[1], revoked_at: null }])));
    renderPage(role);
    expect(await screen.findByRole("columnheader", { name: "Test suggestions" })).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /^ci / })).getByText("Off")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /^old / })).getByText("On")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /^Test suggestions/ })).not.toBeInTheDocument();
    expect(screen.getByText((_, el) => el?.tagName === "P" && el.textContent === `${HELP} Only owners and admins allow test suggestions.`))
      .toBeInTheDocument();
  });

  test.each(["owner", "admin"])("a %s turns it on with PATCH, and the row says On", async (role) => {
    const bodies: unknown[] = [];
    server.use(
      http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([KEYS[0]])),
      http.patch("/api/v1/projects/42/api-keys/1", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ ...KEYS[0], can_read_impact: true });
      }),
    );
    renderPage(role);
    const toggle = await screen.findByRole("switch", { name: "Test suggestions for key ci" });
    expect(toggle).not.toBeChecked();
    expect(within(toggle).getByText("Off")).toBeInTheDocument();
    await userEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("switch", { name: "Test suggestions for key ci" })).toBeChecked());
    expect(within(screen.getByRole("switch", { name: "Test suggestions for key ci" })).getByText("On")).toBeInTheDocument();
    expect(bodies).toEqual([{ can_read_impact: true }]);
  });

  test("a revoked key shows its value, with no switch", async () => {
    server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json(KEYS)));
    renderPage("owner");
    expect(await screen.findByRole("switch", { name: "Test suggestions for key ci" })).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Test suggestions for key old" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /^old / })).getByText("On")).toBeInTheDocument();
  });

  test("a key revoked meanwhile answers 409, and its message is shown", async () => {
    let revoked = false;
    server.use(
      http.get("/api/v1/projects/42/api-keys", () =>
        HttpResponse.json([revoked ? { ...KEYS[0], revoked_at: "2026-10-13T10:00:00Z" } : KEYS[0]])),
      http.patch("/api/v1/projects/42/api-keys/1", () => {
        revoked = true;
        return HttpResponse.json({ detail: "API key is revoked" }, { status: 409 });
      }),
    );
    renderPage("admin");
    await userEvent.click(await screen.findByRole("switch", { name: "Test suggestions for key ci" }));
    expect((await screen.findByText("API key is revoked")).closest("[role=alert]")).toBeInTheDocument();
    // the list is read again, so the row now shows the key as revoked, without a switch
    await waitFor(() => expect(screen.queryByRole("switch", { name: "Test suggestions for key ci" })).not.toBeInTheDocument());
  });
});

test("the Log values card follows Masking", async () => {
  renderPage();
  await screen.findByRole("heading", { level: 2, name: "Log values" });
  const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
  expect(headings.indexOf("Log values")).toBe(headings.indexOf("Masking") + 1);
});
