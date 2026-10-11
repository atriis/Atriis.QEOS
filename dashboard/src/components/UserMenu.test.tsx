import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, test, vi } from "vitest";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { goTo } from "../lib/browser";
import UserMenu from "./UserMenu";

vi.mock("../lib/browser", () => ({ goTo: vi.fn() }));

function renderMenu(me: Record<string, unknown>) {
  setAccessToken("acc");
  server.use(
    http.get("/api/v1/users/me", () =>
      HttpResponse.json({ id: 1, email: "ops@example.com", mfa_enabled: false, ...me }),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openMenu(): Promise<HTMLElement> {
  await userEvent.click(await screen.findByRole("button", { name: "Account menu for ops@example.com" }));
  return document.getElementById("user-menu-popup")!;
}

function items(popup: HTMLElement): (string | undefined)[] {
  return within(popup).getAllByRole("listitem").map((li) => li.textContent?.trim());
}

afterEach(() => {
  vi.mocked(goTo).mockReset();
  sessionStorage.clear();
});

describe("Monitoring item", () => {
  test("is hidden without monitoring_url", async () => {
    renderMenu({ monitoring_url: null });
    const popup = await openMenu();
    expect(within(popup).queryByRole("button", { name: "Monitoring" })).toBeNull();
    expect(items(popup)).toEqual(["Security", "Sign out"]);
  });

  test("shows before Sign out; a click hands over the Grafana cookie, then opens Grafana", async () => {
    let posted = false;
    server.use(
      http.post("/api/v1/auth/grafana-session", () => {
        posted = true;
        return HttpResponse.json({ url: "/grafana/" });
      }),
    );
    renderMenu({ monitoring_url: "/grafana/" });
    const popup = await openMenu();
    expect(items(popup)).toEqual(["Security", "Monitoring", "Sign out"]);
    await userEvent.click(within(popup).getByRole("button", { name: "Monitoring" }));
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/"));
    expect(posted).toBe(true);
    // Marked, so a bounce back to /monitoring asks instead of handing over again
    expect(sessionStorage.getItem("qeos.grafanaHandoff")).not.toBeNull();
  });

  test("a refusal is shown in the menu and nothing opens", async () => {
    server.use(
      http.post("/api/v1/auth/grafana-session", () =>
        HttpResponse.json({ detail: "Monitoring is available to superusers while it is turned on" }, { status: 403 }),
      ),
    );
    renderMenu({ monitoring_url: "/grafana/" });
    const popup = await openMenu();
    await userEvent.click(within(popup).getByRole("button", { name: "Monitoring" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Monitoring is available to superusers while it is turned on");
    expect(goTo).not.toHaveBeenCalled();
  });

  test("a URL the server answers that is not inside Grafana is not followed", async () => {
    server.use(http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ url: "https://evil.example/" })));
    renderMenu({ monitoring_url: "/grafana/" });
    const popup = await openMenu();
    await userEvent.click(within(popup).getByRole("button", { name: "Monitoring" }));
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/"));
  });
});
