import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { delay, http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import AppShell from "./AppShell";
import PageHeader from "./PageHeader";

const P = "/api/v1/projects/42";
/** Recent items of the signed-in user (the default /users/me is id 1) */
const RECENT_1 = "qeos.palette.recent.1";

function Where() {
  const { pathname, search } = useLocation();
  return <p data-testid="where">{pathname + search}</p>;
}

const kase = (n: number, title: string) => ({
  number: n, key: `TC-${n}`, title, description: null, steps: [], labels: [], priority: "medium", status: "ready",
  automated_test_key: null, automated_name: null, created_by: 1, created_at: "2026-01-01T00:00:00Z", updated_by: null,
  updated_at: null, source_path: null, gherkin: null, feature_name: null, suites: [],
});
const testRow = (key: string, name: string) => ({
  test_key: key, suite: "web", class_name: "LoginSpec", name, runs: 3, passed: 3, failed: 0, errored: 0, skipped: 0,
  pass_rate: 1, avg_duration_ms: 10, last_status: "passed", last_seen: "2026-01-01T00:00:00Z",
});
const run = (id: number, branch: string) => ({
  id, project_id: 42, ci_provider: "github_actions", ci_run_url: null, commit_sha: null, branch, environment: null,
  agent_version: null, commit_author: null, commit_message: null, pr_number: null, base_branch: null,
  started_at: "2026-01-01T00:00:00Z", finished_at: "2026-01-01T00:01:00Z", duration_ms: 60000, total: 3, passed: 3,
  failed: 0, skipped: 0, errored: 0, change_base_ref: null, changed_files: null, additions: null, deletions: null,
  changes_truncated: null, created_at: "2026-01-01T00:01:00Z",
});

function shell() {
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([{ id: 1, name: "Acme", slug: "acme", role: "owner" }])),
    http.get("/api/v1/organizations/1/projects", () => HttpResponse.json([{ id: 42, name: "Shop E2E" }, { id: 43, name: "Logistics API" }])),
    http.get(P, () => HttpResponse.json({ id: 42, name: "Shop E2E", organization_id: 1 })),
    http.get("/api/v1/projects/43", () => HttpResponse.json({ id: 43, name: "Logistics API", organization_id: 1 })),
  );
}

const suite = (id: number, name: string) => ({
  id, name, description: null, case_count: 3, created_at: "2026-01-01T00:00:00Z", updated_at: null,
});
const summary = (id: number, branch: string, failed = 0) => ({
  id, project_id: 42, started_at: "2026-01-01T00:00:00Z", finished_at: "2026-01-01T00:01:00Z", branch, commit_sha: null,
  environment: null, status: failed > 0 ? "failing" : "passing", counts: { passed: 3, failed, errored: 0, skipped: 0 },
  ci_provider: "github_actions", ci_run_url: null,
});

/** Every remote source answers for "lo"/"log"; tests override what they are about. */
function sources() {
  server.use(
    http.get(`${P}/cases`, ({ request }) => {
      const q = new URL(request.url).searchParams.get("search");
      return HttpResponse.json(q && "login works".includes(q.toLowerCase()) ? { total: 1, items: [kase(1, "Login works")] } : { total: 0, items: [] });
    }),
    http.get(`${P}/analytics/tests`, ({ request }) => {
      const q = new URL(request.url).searchParams.get("search") ?? "";
      return HttpResponse.json("test_login_redirects".includes(q.toLowerCase()) ? [testRow("k1", "test_login_redirects")] : []);
    }),
    http.get(`${P}/runs`, () => HttpResponse.json([])),
    http.get(`${P}/suites`, () => HttpResponse.json([])),
  );
}

function renderAt(path: string) {
  setAccessToken("acc");
  shell();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<PageHeader title="Projects" />} />
            <Route path="/projects/:projectId/*" element={<><PageHeader title="Project page" /><Where /></>} />
          </Route>
          <Route path="/login" element={<p>LOGIN</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const trigger = () => screen.getByRole("button", { name: /search cases, runs, tests/i });
const dialog = () => screen.getByRole("dialog", { name: "Search" });
const input = () => within(dialog()).getByRole("combobox", { name: "Search" });
const group = (name: string) => within(dialog()).getByRole("group", { name });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("opening and closing", () => {
  test("the top bar button opens it; Esc closes it and focus returns to the button", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/runs");
    await user.click(trigger());
    expect(dialog()).toHaveAttribute("aria-modal", "true");
    expect(input()).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Search" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger()).toHaveFocus());
  });

  test("Ctrl K opens it from anywhere and Esc gives focus back", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/runs");
    await user.keyboard("{Control>}k{/Control}");
    expect(input()).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger()).toHaveFocus());
  });

  test("Cmd K opens it too, and the button shows the platform's hint", async () => {
    const user = userEvent.setup();
    renderAt("/");
    expect(trigger()).toHaveAttribute("aria-keyshortcuts", expect.stringContaining("Control+K"));
    await user.keyboard("{Meta>}k{/Meta}");
    expect(input()).toHaveFocus();
  });

  test("\"/\" opens it, but not while typing in a field", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/runs");
    const field = document.createElement("input");
    document.body.appendChild(field);
    field.focus();
    await user.keyboard("/");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    field.blur();
    field.remove();
    await user.keyboard("/");
    expect(input()).toHaveFocus();
    expect(input()).toHaveValue("");
  });

  test("while open it is a real modal: portalled to the body, the app inert and not scrolling; both restored on close", async () => {
    const user = userEvent.setup();
    const { container } = renderAt("/projects/42/runs");
    await user.click(trigger());
    expect(container).not.toContainElement(dialog());
    expect(document.body).toContainElement(dialog());
    expect(container).toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("hidden");
    await user.keyboard("{Escape}");
    expect(container).not.toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("");
    await waitFor(() => expect(trigger()).toHaveFocus());
  });

  test("Esc closes it even when focus has left the field", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/runs");
    await user.click(trigger());
    input().blur();
    expect(input()).not.toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("a shortcut another handler already took, or typed mid-composition, is left alone", async () => {
    renderAt("/projects/42/runs");
    const takeIt = (e: KeyboardEvent) => e.preventDefault();
    document.addEventListener("keydown", takeIt, { capture: true });
    try {
      fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
    } finally {
      document.removeEventListener("keydown", takeIt, { capture: true });
    }
    fireEvent.keyDown(document.body, { key: "/", isComposing: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("a slash typed with AltGr (Ctrl+Alt) opens it", async () => {
    renderAt("/projects/42/runs");
    fireEvent.keyDown(document.body, { key: "/", ctrlKey: true, altKey: true });
    expect(await screen.findByRole("dialog", { name: "Search" })).toBeInTheDocument();
  });

  test("Tab stays inside the dialog", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/runs");
    await user.click(trigger());
    await user.tab();
    expect(input()).toHaveFocus();
    await user.tab({ shift: true });
    expect(input()).toHaveFocus();
  });

  test("on phones the trigger is an icon button named Search", async () => {
    window.matchMedia = ((query: string) => ({
      matches: /max-width:\s*(640|1023)px/.test(query), media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    try {
      renderAt("/projects/42/runs");
      expect(screen.getByRole("button", { name: "Search" })).toBeInTheDocument();
    } finally {
      // @ts-expect-error restore jsdom default (no matchMedia)
      delete window.matchMedia;
    }
  });
});

describe("keyboard navigation", () => {
  test("arrows, Home and End move the active option; Enter opens it", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/runs");
    await user.click(trigger());
    const options = within(group("Pages")).getAllByRole("option");
    expect(options.length).toBeGreaterThan(3);
    expect(input()).toHaveAttribute("aria-activedescendant", options[0].id);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}");
    expect(input()).toHaveAttribute("aria-activedescendant", options[1].id);
    await user.keyboard("{ArrowUp}{ArrowUp}");
    // Up from the first wraps to the last
    const all = within(dialog()).getAllByRole("option");
    expect(input()).toHaveAttribute("aria-activedescendant", all[all.length - 1].id);
    await user.keyboard("{Home}");
    expect(input()).toHaveAttribute("aria-activedescendant", all[0].id);
    await user.keyboard("{End}");
    expect(input()).toHaveAttribute("aria-activedescendant", all[all.length - 1].id);
    await user.keyboard("{Home}{ArrowDown}{Enter}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/runs");
  });

  test("pages match on their name, even with one letter typed", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/runs");
    await user.click(trigger());
    await user.keyboard("flak");
    sources();
    const option = await within(group("Pages")).findByRole("option", { name: /Flaky/ });
    expect(option.querySelector("mark")).toHaveTextContent(/^Flak$/);
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/flaky");
  });
});

describe("sources", () => {
  test("cases, tests and projects come back in their own groups, matches marked", async () => {
    sources();
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("lo");
    const cases = await screen.findByRole("group", { name: "Test cases" });
    const kaseOption = within(cases).getByRole("option", { name: /TC-1/ });
    expect(kaseOption).toHaveTextContent("Login works");
    expect(kaseOption.querySelector("mark")).toHaveTextContent("Lo");
    expect(within(await screen.findByRole("group", { name: "Test results" })).getByRole("option", { name: /test_login_redirects/ })).toBeInTheDocument();
    expect(within(group("Projects")).getByRole("option", { name: /Logistics API/ })).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent(/^3 results$/);
    await user.click(kaseOption);
    expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/cases/1");
  });

  test("a project result switches project", async () => {
    sources();
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("logis");
    await user.click(await within(await screen.findByRole("group", { name: "Projects" })).findByRole("option", { name: /Logistics API/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/projects/43/overview");
  });

  test("remote sources wait for two characters, ask for 5, and use the runs branch filter", async () => {
    const asked: string[] = [];
    server.use(
      http.get(`${P}/cases`, ({ request }) => { asked.push(request.url); return HttpResponse.json({ total: 0, items: [] }); }),
      http.get(`${P}/analytics/tests`, ({ request }) => { asked.push(request.url); return HttpResponse.json([]); }),
      http.get(`${P}/runs`, ({ request }) => {
        asked.push(request.url);
        return HttpResponse.json(new URL(request.url).searchParams.get("branch_contains") === "main" ? [run(9, "feature/main-fix")] : []);
      }),
      http.get(`${P}/suites`, ({ request }) => { asked.push(request.url); return HttpResponse.json([]); }),
    );
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("m");
    await act(() => new Promise((r) => setTimeout(r, 300)));
    expect(asked).toEqual([]);
    await user.keyboard("ain");
    const runs = await screen.findByRole("group", { name: "Runs" });
    expect(within(runs).getByRole("option", { name: /Run #9/ })).toBeInTheDocument();
    const params = asked.map((u) => new URL(u).searchParams);
    expect(params.filter((p) => p.has("limit")).every((p) => p.get("limit") === "5")).toBe(true);
    expect(params.some((p) => p.get("search") === "main")).toBe(true);
    expect(params.some((p) => p.get("branch_contains") === "main")).toBe(true);
    expect(params.some((p) => p.has("branch"))).toBe(false);
    // The suites list takes no limit; the palette keeps 5
    expect(params.some((p) => p.get("search") === "main" && !p.has("limit"))).toBe(true);
  });

  test("a Suites group lists matching suites (5 at most) and opens the suite", async () => {
    sources();
    server.use(http.get(`${P}/suites`, ({ request }) => {
      const q = new URL(request.url).searchParams.get("search");
      return HttpResponse.json(q === "smoke" ? [1, 2, 3, 4, 5, 6, 7].map((i) => suite(i, `Smoke ${i}`)) : []);
    }));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("smoke");
    const group = await screen.findByRole("group", { name: "Suites" });
    expect(within(group).getAllByRole("option")).toHaveLength(5);
    await user.click(within(group).getByRole("option", { name: /Smoke 3/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/suites/3");
  });

  test("a failing suites source is a notice in its own group", async () => {
    sources();
    server.use(http.get(`${P}/suites`, () => HttpResponse.json({ detail: "down" }, { status: 503 })));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("login");
    expect(await screen.findByText("Couldn't search suites right now")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Login works/ })).toBeInTheDocument();
  });

  test("a stale request is cancelled and its answer never shows", async () => {
    const signals = new Map<string, AbortSignal>();
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/cases?") && init?.signal) signals.set(new URL(url, "http://x").searchParams.get("search") ?? "", init.signal);
      return realFetch(input, init);
    });
    server.use(
      http.get(`${P}/cases`, async ({ request }) => {
        const q = new URL(request.url).searchParams.get("search");
        if (q === "lo") await delay(600);
        return HttpResponse.json({ total: 1, items: [kase(q === "lo" ? 2 : 3, q === "lo" ? "Lo stale" : "Log fresh")] });
      }),
      http.get(`${P}/analytics/tests`, () => HttpResponse.json([])),
      http.get(`${P}/runs`, () => HttpResponse.json([])),
      http.get(`${P}/suites`, () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("lo");
    await waitFor(() => expect(signals.has("lo")).toBe(true));
    await user.keyboard("g");
    expect(await screen.findByRole("option", { name: /Log fresh/ })).toBeInTheDocument();
    expect(signals.get("lo")!.aborted).toBe(true);
    await act(() => new Promise((r) => setTimeout(r, 700)));
    expect(screen.queryByRole("option", { name: /Lo stale/ })).not.toBeInTheDocument();
  });

  test("#433 opens run 433 directly once it exists", async () => {
    sources();
    let asked = 0;
    server.use(http.get(`${P}/runs/433/summary`, () => { asked += 1; return HttpResponse.json(summary(433, "main", 3)); }));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("#433");
    const option = await within(await screen.findByRole("group", { name: "Runs" })).findByRole("option", { name: /Run #433/ });
    expect(asked).toBe(1);
    expect(option).toHaveTextContent(/main.+3 failed/);
    expect(input()).toHaveAttribute("aria-activedescendant", option.id);
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/runs/433");
  });

  test("a run number that does not exist offers no run", async () => {
    sources();
    server.use(http.get(`${P}/runs/9999/summary`, () => HttpResponse.json({ detail: "Run not found" }, { status: 404 })));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("9999");
    expect(await screen.findByText('No matches for "9999"', { selector: ".palette-empty" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Runs" })).not.toBeInTheDocument();
  });

  test("a run number the reader may not see (403) offers no run, not an error", async () => {
    sources();
    server.use(http.get(`${P}/runs/77/summary`, () => HttpResponse.json({ detail: "Run not found" }, { status: 403 })));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("77");
    expect(await screen.findByText('No matches for "77"', { selector: ".palette-empty" })).toBeInTheDocument();
    expect(screen.queryByText(/Couldn't search runs/)).not.toBeInTheDocument();
  });

  test("an error in one source is a notice in its group; the others still work", async () => {
    sources();
    server.use(http.get(`${P}/analytics/tests`, () => HttpResponse.json({ detail: "down" }, { status: 503 })));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("lo");
    const tests = await screen.findByRole("group", { name: "Test results" });
    expect(await within(tests).findByText("Couldn't search tests right now")).toBeInTheDocument();
    expect(within(group("Test cases")).getByRole("option", { name: /Login works/ })).toBeInTheDocument();
    // The notice is not a result: the arrows skip it
    await user.keyboard("{End}");
    expect(input().getAttribute("aria-activedescendant")).not.toBe(within(tests).getByText(/Couldn't search/).id);
  });

  test("no matches says so", async () => {
    server.use(
      http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })),
      http.get(`${P}/analytics/tests`, () => HttpResponse.json([])),
      http.get(`${P}/runs`, () => HttpResponse.json([])),
      http.get(`${P}/suites`, () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    await user.keyboard("zzz");
    expect(await within(dialog()).findByText('No matches for "zzz"', { selector: ".palette-empty" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent('No matches for "zzz"');
  });

  test("outside a project only pages and projects are searched", async () => {
    // Any project-scoped request would fail the test (unhandled)
    const user = userEvent.setup();
    renderAt("/");
    await user.click(trigger());
    expect(within(group("Pages")).getByRole("option", { name: /All projects/ })).toBeInTheDocument();
    expect(within(group("Pages")).queryByRole("option", { name: /Flaky/ })).not.toBeInTheDocument();
    await user.keyboard("shop");
    expect(within(await screen.findByRole("group", { name: "Projects" })).getByRole("option", { name: /Shop E2E/ })).toBeInTheDocument();
    await act(() => new Promise((r) => setTimeout(r, 300)));
    expect(screen.queryByRole("group", { name: "Test cases" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Runs" })).not.toBeInTheDocument();
  });
});

describe("recent", () => {
  test("opened items are kept and offered first on an empty query", async () => {
    sources();
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await screen.findByRole("button", { name: /Account menu for/ });
    await user.click(trigger());
    await user.keyboard("lo");
    await user.click(await screen.findByRole("option", { name: /Login works/ }));
    expect(JSON.parse(localStorage.getItem(RECENT_1) ?? "[]")[0]).toMatchObject({ href: "/projects/42/cases/1" });
    await user.keyboard("{Control>}k{/Control}");
    const recent = group("Recent");
    expect(within(recent).getByRole("option", { name: /Login works/ })).toBeInTheDocument();
    expect(group("Pages")).toBeInTheDocument();
  });

  test("keeps the last 5, newest first, without repeats", async () => {
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await screen.findByRole("button", { name: /Account menu for/ });
    for (const page of ["Runs", "Test results", "Flaky", "Branches", "Trends", "Report", "Runs"]) {
      await user.keyboard("{Control>}k{/Control}");
      await user.click(within(group("Pages")).getByRole("option", { name: new RegExp(`^${page}`) }));
    }
    const stored = JSON.parse(localStorage.getItem(RECENT_1) ?? "[]").map((r: { label: string }) => r.label);
    expect(stored).toEqual(["Runs", "Report", "Trends", "Branches", "Flaky"]);
  });

  test("recent items of another project are not offered here", async () => {
    localStorage.setItem(RECENT_1, JSON.stringify([
      { id: "case:43:5", kind: "case", label: "Elsewhere", detail: "TC-5", href: "/projects/43/cases/5", projectId: 43 },
      { id: "case:42:6", kind: "case", label: "Here", detail: "TC-6", href: "/projects/42/cases/6", projectId: 42 },
    ]));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await screen.findByRole("button", { name: /Account menu for/ });
    await user.click(trigger());
    expect(within(group("Recent")).getAllByRole("option").map((o) => o.textContent)).toEqual([expect.stringContaining("Here")]);
  });

  test("recent items belong to the signed-in user", async () => {
    localStorage.setItem("qeos.palette.recent.2", JSON.stringify([
      { id: "page:42:flaky", kind: "page", label: "Not mine", href: "/projects/42/flaky", projectId: 42 },
    ]));
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await screen.findByRole("button", { name: /Account menu for/ });
    await user.click(trigger());
    expect(screen.queryByRole("group", { name: "Recent" })).not.toBeInTheDocument();
    await user.click(within(group("Pages")).getByRole("option", { name: /^Runs/ }));
    expect(JSON.parse(localStorage.getItem(RECENT_1) ?? "[]").map((r: { label: string }) => r.label)).toEqual(["Runs"]);
    expect(localStorage.getItem("qeos.palette.recent.2")).toContain("Not mine");
  });

  test("signing out forgets every recent list", async () => {
    server.use(http.post("/api/v1/auth/logout", () => new HttpResponse(null, { status: 200 })));
    localStorage.setItem("qeos.palette.recent", "[]");
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await screen.findByRole("button", { name: /Account menu for/ });
    await user.click(trigger());
    await user.click(within(group("Pages")).getByRole("option", { name: /^Runs/ }));
    expect(localStorage.getItem(RECENT_1)).not.toBeNull();
    await user.click(screen.getByRole("button", { name: /Account menu for/ }));
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByText("LOGIN")).toBeInTheDocument();
    expect(localStorage.getItem(RECENT_1)).toBeNull();
    expect(localStorage.getItem("qeos.palette.recent")).toBeNull();
  });

  test("storage that throws leaves the palette working", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const user = userEvent.setup();
    renderAt("/projects/42/overview");
    await user.click(trigger());
    expect(screen.queryByRole("group", { name: "Recent" })).not.toBeInTheDocument();
    await user.click(within(group("Pages")).getByRole("option", { name: /^Flaky/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/flaky");
  });
});
