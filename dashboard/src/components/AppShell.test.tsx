import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import AppShell from "./AppShell";
import PageHeader from "./PageHeader";
import ProjectLayout from "../pages/ProjectLayout";

let loggedOut = false;
let qc: QueryClient;

function renderAt(path: string) {
  setAccessToken("acc");
  loggedOut = false;
  server.use(
    http.get("/api/v1/organizations", () => HttpResponse.json([{ id: 1, name: "Acme", slug: "acme", role: "owner" }])),
    http.get("/api/v1/organizations/1/projects", () => HttpResponse.json([{ id: 42, name: "Shop E2E" }, { id: 43, name: "API" }])),
    http.get("/api/v1/projects/42", () => HttpResponse.json({ id: 42, name: "Shop E2E", organization_id: 1 })),
    http.get("/api/v1/users/me", () => HttpResponse.json({ id: 7, email: "pedro.carneiro@example.com", mfa_enabled: false })),
    http.post("/api/v1/auth/logout", () => {
      loggedOut = true;
      return new HttpResponse(null, { status: 200 });
    }),
  );
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<PageHeader title="Projects" />} />
            <Route path="/account/security" element={<PageHeader title="Security" />} />
            <Route path="/projects/:projectId" element={<ProjectLayout />}>
              <Route path="runs" element={<PageHeader title="Runs" />} />
              <Route path="runs/:runId" element={<PageHeader title="Run" />} />
              <Route path="settings" element={<PageHeader title="Settings" />} />
              <Route path="overview" element={<PageHeader title="Overview" />} />
            </Route>
          </Route>
          <Route path="/login" element={<div>LOGIN</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Answers min-width / max-width queries for a viewport of the given width (phone 400, desktop 1100, wide 1440). */
function mockScreen({ narrow = false, wide = false, width }: { narrow?: boolean; wide?: boolean; width?: number }) {
  const w = width ?? (narrow ? 400 : wide ? 1440 : 1100);
  const answer = (query: string) => {
    const max = /max-width:\s*(\d+)px/.exec(query);
    const min = /min-width:\s*(\d+)px/.exec(query);
    return (max ? w <= Number(max[1]) : true) && (min ? w >= Number(min[1]) : true);
  };
  window.matchMedia = ((query: string) => ({
    matches: answer(query), media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  // @ts-expect-error restore jsdom default (no matchMedia)
  delete window.matchMedia;
  localStorage.clear();
});

describe("breadcrumb", () => {
  test("inside a project: org, project switcher, then the page as the current item", async () => {
    renderAt("/projects/42/runs");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(await within(crumbs).findByRole("link", { name: "Acme" })).toHaveAttribute("href", "/organizations/1");
    const items = within(crumbs).getAllByRole("listitem");
    expect(within(items[1]).getByRole("combobox", { name: "Project" })).toBeInTheDocument();
    const last = items[items.length - 1];
    expect(last).toHaveTextContent("Runs");
    expect(within(last).getByText("Runs")).toHaveAttribute("aria-current", "page");
    expect(crumbs.querySelectorAll("[aria-current]")).toHaveLength(1);
  });

  test("a detail page links its section and ends on the detail", async () => {
    renderAt("/projects/42/runs/7");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Runs" })).toHaveAttribute("href", "/projects/42/runs");
    expect(within(crumbs).getByText("Run #7")).toHaveAttribute("aria-current", "page");
  });

  test("outside a project the page is the only item", async () => {
    renderAt("/account/security");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getAllByRole("listitem")).toHaveLength(1);
    expect(within(crumbs).getByText("Security")).toHaveAttribute("aria-current", "page");
    expect(within(crumbs).queryByRole("combobox")).not.toBeInTheDocument();
  });

  test("the project switcher lives in the breadcrumb and opens the chosen project's overview", async () => {
    renderAt("/projects/42/runs");
    server.use(http.get("/api/v1/projects/43", () => HttpResponse.json({ id: 43, name: "API", organization_id: 1 })));
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await within(crumbs).findByRole("option", { name: "API" });
    const select = within(crumbs).getByLabelText("Project");
    expect(select).toHaveValue("42");
    await userEvent.selectOptions(select, "43");
    expect(screen.getByLabelText("Project")).toHaveValue("43");
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(within(document.getElementById("sidebar")!).queryByLabelText("Project")).not.toBeInTheDocument();
  });

  test("the switcher shows the current project even when the loaded lists do not include it", async () => {
    renderAt("/projects/42/runs");
    server.use(http.get("/api/v1/organizations/1/projects", () => HttpResponse.json([{ id: 43, name: "API" }])));
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await within(crumbs).findByRole("option", { name: "API" });
    await within(crumbs).findByRole("option", { name: "Shop E2E" });
    expect(within(crumbs).getByLabelText("Project")).toHaveValue("42");
  });

  test("the org crumb keeps its place while the project loads, so the trail does not shift", () => {
    renderAt("/projects/42/runs");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    const first = within(crumbs).getAllByRole("listitem")[0];
    expect(first).toHaveClass("crumb-org");
  });

  test("the brand links to the project picker", () => {
    renderAt("/projects/42/runs");
    expect(within(screen.getByRole("banner")).getByRole("link", { name: "QEOS, all projects" })).toHaveAttribute("href", "/");
  });
});

describe("user menu", () => {
  test("the avatar is a disclosure: initials, aria-expanded, then the email, Security, Organization and Sign out last", async () => {
    renderAt("/projects/42/runs");
    const button = await screen.findByRole("button", { name: "Account menu for pedro.carneiro@example.com" });
    expect(button).toHaveTextContent("PC");
    expect(button).not.toHaveAttribute("aria-haspopup");
    expect(button).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const popup = document.getElementById(button.getAttribute("aria-controls")!)!;
    expect(within(popup).getByText("pedro.carneiro@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await within(popup).findByRole("link", { name: "Organization" });
    const items = within(within(popup).getByRole("list")).getAllByRole("listitem").map((li) => li.textContent?.trim());
    expect(items).toEqual(["Security", "Organization", "Sign out"]);
    expect(within(popup).getAllByRole("listitem")[2]).toHaveClass("menu-signout");
  });

  test("Tab moves through the items in order; Escape closes and returns focus to the avatar", async () => {
    renderAt("/projects/42/runs");
    const button = await screen.findByRole("button", { name: /account menu/i });
    await userEvent.click(button);
    const popup = document.getElementById(button.getAttribute("aria-controls")!)!;
    await within(popup).findByRole("link", { name: "Organization" });
    await userEvent.tab();
    expect(within(popup).getByRole("link", { name: "Security" })).toHaveFocus();
    await userEvent.tab();
    expect(within(popup).getByRole("link", { name: "Organization" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("user-menu-popup")).toBeNull();
    expect(button).toHaveFocus();
  });

  test("a click outside closes it, and so does focus moving out", async () => {
    renderAt("/");
    const button = await screen.findByRole("button", { name: /account menu/i });
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("heading", { name: "Projects" }));
    expect(button).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(button);
    act(() => screen.getByRole("link", { name: "QEOS, all projects" }).focus());
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  test("Sign out calls logout, forgets the cached account data and returns to login", async () => {
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: /account menu/i }));
    expect(qc.getQueryData(["me"])).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByText("LOGIN")).toBeInTheDocument();
    expect(loggedOut).toBe(true);
    expect(qc.getQueryData(["me"])).toBeUndefined();
    expect(qc.getQueryCache().getAll()).toHaveLength(0);
  });

  test("following an item closes the menu, even a link to the page already open", async () => {
    renderAt("/account/security");
    const button = await screen.findByRole("button", { name: /account menu/i });
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("link", { name: "Security" }));
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  test("there is no sidebar footer any more: Security and Sign out live only in the user menu", () => {
    renderAt("/");
    const sidebar = document.getElementById("sidebar")!;
    expect(within(sidebar).queryByRole("link", { name: "Security" })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
  });
});

describe("icon rail", () => {
  test("lists the project views then the workspace items, each named, the active one current", async () => {
    renderAt("/projects/42/runs");
    const rail = screen.getByRole("navigation", { name: "Main" });
    await within(rail).findByRole("link", { name: "Organization" });
    const names = within(rail).getAllByRole("link").map((a) => a.textContent?.trim());
    expect(names).toEqual(["Overview", "Runs", "Test results", "Flaky", "Branches", "Trends", "Report", "Test cases", "Settings", "All projects", "Organization"]);
    expect(within(rail).getByRole("link", { name: "Runs" })).toHaveAttribute("aria-current", "page");
    expect(within(rail).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  test("outside a project only the workspace items show", async () => {
    renderAt("/");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).queryByRole("link", { name: "Runs" })).not.toBeInTheDocument();
    expect(within(rail).getByRole("link", { name: "All projects" })).toHaveAttribute("aria-current", "page");
  });

  test("following a rail link moves focus to the new page's h1 and sets the title", async () => {
    renderAt("/projects/42/runs");
    await userEvent.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Settings" }));
    const h1 = await screen.findByRole("heading", { level: 1, name: "Settings" });
    expect(h1).toHaveFocus();
    await waitFor(() => expect(document.title).toBe("Settings · Shop E2E · QEOS"));
  });

  test("keyboard focus inside the rail expands it as an overlay; leaving collapses it", async () => {
    renderAt("/projects/42/runs");
    const sidebar = document.getElementById("sidebar")!;
    expect(sidebar).not.toHaveClass("expanded");
    act(() => within(sidebar).getByRole("link", { name: "Overview" }).focus());
    await waitFor(() => expect(sidebar).toHaveClass("expanded"));
    act(() => screen.getByRole("heading", { level: 1 }).focus());
    await waitFor(() => expect(sidebar).not.toHaveClass("expanded"));
  });

  test("a mouse click inside the rail does not hold it open: after unpinning it collapses when the pointer leaves", async () => {
    renderAt("/");
    const sidebar = document.getElementById("sidebar")!;
    await userEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    await userEvent.unhover(sidebar);
    await waitFor(() => expect(sidebar).not.toHaveClass("expanded"));
  });

  test("Escape hides the collapsed rail's tooltips until the pointer or focus moves again", async () => {
    renderAt("/");
    const sidebar = document.getElementById("sidebar")!;
    await userEvent.hover(within(sidebar).getByRole("link", { name: "All projects" }));
    await userEvent.keyboard("{Escape}");
    expect(sidebar).toHaveClass("tips-off");
    await userEvent.unhover(sidebar);
    expect(sidebar).not.toHaveClass("tips-off");
  });

  test("the pin toggle keeps the rail expanded and is remembered", async () => {
    const view = renderAt("/");
    const pin = screen.getByRole("button", { name: "Expand sidebar" });
    expect(pin).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(pin);
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".shell")).toHaveClass("rail-pinned");
    expect(localStorage.getItem("qeos.rail.pinned")).toBe("1");
    view.unmount();
    renderAt("/");
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(localStorage.getItem("qeos.rail.pinned")).toBe("0");
  });

  test("a new visitor gets the rail pinned on a wide screen and collapsed below 1280px", () => {
    mockScreen({ wide: true });
    const view = renderAt("/");
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute("aria-pressed", "true");
    view.unmount();
    mockScreen({ wide: false });
    renderAt("/");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-pressed", "false");
  });

  test("a stored pin is ignored below 1024px (it stays stored for wider screens)", () => {
    localStorage.setItem("qeos.rail.pinned", "1");
    mockScreen({ width: 900 });
    renderAt("/");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-pressed", "false");
    expect(document.querySelector(".shell")).not.toHaveClass("rail-pinned");
    expect(localStorage.getItem("qeos.rail.pinned")).toBe("1");
  });

  test("a stored choice beats the screen-width default", () => {
    localStorage.setItem("qeos.rail.pinned", "0");
    mockScreen({ wide: true });
    renderAt("/");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });
});

describe("mobile drawer", () => {
  test("the drawer opens from the menu button and Escape closes it, returning focus", async () => {
    mockScreen({ narrow: true });
    renderAt("/");
    const menu = screen.getByRole("button", { name: /open navigation/i });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("sidebar")).toHaveClass("open");
    await userEvent.keyboard("{Escape}");
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
  });

  test("a closed drawer is inert and hidden from assistive tech on narrow screens", async () => {
    mockScreen({ narrow: true });
    renderAt("/projects/42/runs");
    const sidebar = document.getElementById("sidebar")!;
    expect(sidebar).toHaveAttribute("inert");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");
    await userEvent.click(screen.getByRole("button", { name: /open navigation/i }));
    expect(sidebar).not.toHaveAttribute("inert");
    expect(sidebar).not.toHaveAttribute("aria-hidden");
  });

  test("the rail stays available on wide screens", () => {
    mockScreen({ narrow: false });
    renderAt("/");
    const sidebar = document.getElementById("sidebar")!;
    expect(sidebar).not.toHaveAttribute("inert");
    expect(sidebar).not.toHaveAttribute("aria-hidden");
  });

  test("an open drawer is a modal: focus moves to the first link, Tab wraps, Escape returns focus", async () => {
    mockScreen({ narrow: true });
    renderAt("/projects/42/runs");
    const menu = screen.getByRole("button", { name: /open navigation/i });
    await userEvent.click(menu);
    const sidebar = document.getElementById("sidebar")!;
    expect(sidebar).toHaveAttribute("aria-modal", "true");
    expect(sidebar).toHaveAttribute("role", "dialog");
    const links = sidebar.querySelectorAll<HTMLElement>("a");
    expect(links[0]).toHaveFocus();
    // The pin toggle has no meaning in the drawer
    expect(within(sidebar).queryByRole("button", { name: /sidebar/i })).not.toBeInTheDocument();
    const focusables = Array.from(sidebar.querySelectorAll<HTMLElement>("a[href], button:not(:disabled), select"));
    act(() => focusables[focusables.length - 1].focus());
    await userEvent.tab();
    expect(focusables[0]).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(focusables[focusables.length - 1]).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(menu).toHaveFocus();
    expect(sidebar).toHaveAttribute("inert");
  });

  test("following a link in the drawer puts focus on the new page's heading, not the menu button", async () => {
    mockScreen({ narrow: true });
    renderAt("/projects/42/runs");
    const menu = screen.getByRole("button", { name: /open navigation/i });
    await userEvent.click(menu);
    await userEvent.click(within(document.getElementById("sidebar")!).getByRole("link", { name: /overview/i }));
    const h1 = await screen.findByRole("heading", { level: 1, name: "Overview" });
    expect(document.getElementById("sidebar")).not.toHaveClass("open");
    expect(menu).not.toHaveFocus();
    expect(h1).toHaveFocus();
  });

  test("Escape closes the open drawer even when focus is outside it", async () => {
    mockScreen({ narrow: true });
    renderAt("/projects/42/runs");
    const menu = screen.getByRole("button", { name: /open navigation/i });
    await userEvent.click(menu);
    act(() => screen.getByRole("main").focus());
    await userEvent.keyboard("{Escape}");
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  test("on a wide layout the open class is not a dialog: no role, no modal", async () => {
    mockScreen({ narrow: false });
    renderAt("/");
    const sidebar = document.getElementById("sidebar")!;
    await userEvent.click(screen.getByRole("button", { name: /open navigation/i }));
    expect(sidebar).not.toHaveAttribute("role", "dialog");
    expect(sidebar).not.toHaveAttribute("aria-modal");
  });
});

test("landmarks: a banner, the main navigation and main", () => {
  renderAt("/");
  expect(screen.getByRole("banner")).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveAttribute("id", "main");
});
