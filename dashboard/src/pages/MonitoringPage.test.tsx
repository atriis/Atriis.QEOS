import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, test, vi } from "vitest";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { goTo } from "../lib/browser";
import { markHandoff, rawQueryParam } from "../lib/grafanaHandoff";
import MonitoringPage, { grafanaPath } from "./MonitoringPage";

vi.mock("../lib/browser", () => ({ goTo: vi.fn() }));

function renderAt(path: string) {
  setAccessToken("acc");
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/monitoring" element={<MonitoringPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const REFUSAL = "Monitoring is available to superusers while it is turned on";

afterEach(() => {
  vi.mocked(goTo).mockReset();
  sessionStorage.clear();
});

describe("MonitoringPage", () => {
  test("hands over the cookie, then opens the Grafana page the visitor came from", async () => {
    server.use(http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ url: "/grafana/" })));
    renderAt("/monitoring?next=/grafana/d/qeos-postgresql/postgresql");
    expect(screen.getByRole("heading", { level: 1, name: "Monitoring" })).toBeInTheDocument();
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/d/qeos-postgresql/postgresql"));
    expect(goTo).toHaveBeenCalledTimes(1);
  });

  test("next is decoded exactly once, and + stays a +", async () => {
    server.use(http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ url: "/grafana/" })));
    renderAt("/monitoring?next=/grafana/d/a%2Db+c");
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/d/a-b+c"));
  });

  test("a hostile next opens Grafana's home", async () => {
    server.use(http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ url: "/grafana/" })));
    renderAt("/monitoring?next=%2F%2Fevil.example%2Fgrafana%2F");
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/"));
  });

  test("a refusal is shown and nothing opens", async () => {
    server.use(
      http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ detail: REFUSAL }, { status: 403 })),
    );
    renderAt("/monitoring");
    expect(await screen.findByRole("alert")).toHaveTextContent(REFUSAL);
    expect(screen.getByRole("link", { name: "Back to projects" })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(goTo).not.toHaveBeenCalled();
  });

  test("monitoring turned off (404) says so", async () => {
    server.use(
      http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ detail: "Not Found" }, { status: 404 })),
    );
    renderAt("/monitoring");
    expect(await screen.findByRole("alert")).toHaveTextContent("Monitoring is not turned on for this QEOS install.");
    expect(goTo).not.toHaveBeenCalled();
  });

  test("any other failure offers Retry, which hands over again", async () => {
    let calls = 0;
    server.use(
      http.post("/api/v1/auth/grafana-session", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ detail: "Service unavailable" }, { status: 503 })
          : HttpResponse.json({ url: "/grafana/" });
      }),
    );
    renderAt("/monitoring?next=/grafana/d/qeos-overview");
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/d/qeos-overview"));
    expect(calls).toBe(2);
  });

  test("sent straight back after a hand-off: asks instead of handing over again (no loop)", async () => {
    let calls = 0;
    server.use(
      http.post("/api/v1/auth/grafana-session", () => {
        calls += 1;
        return HttpResponse.json({ url: "/grafana/" });
      }),
    );
    markHandoff();
    renderAt("/monitoring?next=/grafana/d/qeos-overview");
    expect(await screen.findByRole("alert")).toHaveTextContent("Grafana sent you back right after the sign-in");
    expect(calls).toBe(0);
    expect(goTo).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/d/qeos-overview"));
    expect(calls).toBe(1);
  });

  test("sessionStorage that throws: asks instead of handing over (no loop)", async () => {
    let calls = 0;
    server.use(
      http.post("/api/v1/auth/grafana-session", () => {
        calls += 1;
        return HttpResponse.json({ url: "/grafana/" });
      }),
    );
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    try {
      renderAt("/monitoring?next=/grafana/d/qeos-overview");
      expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
      await new Promise((r) => setTimeout(r, 50));
      expect(calls).toBe(0);
      expect(goTo).not.toHaveBeenCalled();
    } finally {
      getItem.mockRestore();
    }
  });

  test("an old hand-off mark does not stop a fresh one", async () => {
    server.use(http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ url: "/grafana/" })));
    sessionStorage.setItem("qeos.grafanaHandoff", String(Date.now() - 60_000));
    renderAt("/monitoring");
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/"));
  });
});

describe("grafanaPath", () => {
  test.each([
    [null, "/grafana/"],
    ["", "/grafana/"],
    ["/grafana/", "/grafana/"],
    ["/grafana/d/qeos-overview", "/grafana/d/qeos-overview"],
    ["/grafana/d/qeos-overview/overview%3ForgId%3D1", "/grafana/d/qeos-overview/overview?orgId=1"],
    ["/grafana/d/qeos-postgresql/postgresql", "/grafana/d/qeos-postgresql/postgresql"],
    ["%2Fgrafana%2Fd%2Fx", "/grafana/d/x"],
    ["/projects/1", "/grafana/"],
    ["/grafana", "/grafana/"],
    ["//evil.example/grafana/", "/grafana/"],
    ["//evil.com", "/grafana/"],
    ["https://evil.example/grafana/", "/grafana/"],
    ["https://evil.com/grafana/", "/grafana/"],
    ["javascript:alert(1)", "/grafana/"],
    ["/\\evil", "/grafana/"],
    ["/grafana/\\evil", "/grafana/"],
    ["/grafana/%5Cevil", "/grafana/"],
    ["/grafana//evil.com", "/grafana/"],
    ["/grafana/%2F%2Fevil.com", "/grafana/"],
    ["/grafana/..%2f..%2fx", "/grafana/"],
    ["/grafana/../x", "/grafana/"],
    ["/grafana/./d", "/grafana/"],
    ["/grafana/%252e%252e/x", "/grafana/"],
    ["/grafana/%0d%0a", "/grafana/"],
    ["/grafana/%0D%0ASet-Cookie:x=1", "/grafana/"],
    ["/grafana/\t/x", "/grafana/"],
    ["/grafana/%09/x", "/grafana/"],
    ["/grafana/a%20b", "/grafana/"],
    ["/grafana/%C2%A0", "/grafana/"],
    ["/grafana/%00", "/grafana/"],
    ["/grafana/%E0%A4%A", "/grafana/"],
    ["/grafana/%", "/grafana/"],
    ["/grafana/..%252fprojects/1", "/grafana/"],
    ["/grafana/..%252fmonitoring", "/grafana/"],
    ["/grafana/%252e%252e%252f", "/grafana/"],
    ["/grafana/%255cevil", "/grafana/"],
    ["/grafana/d/x%2541", "/grafana/"],
  ])("%s -> %s", (raw, expected) => {
    expect(grafanaPath(raw)).toBe(expected);
  });
});

describe("rawQueryParam", () => {
  test("keeps the value percent-encoded and takes the first occurrence", () => {
    expect(rawQueryParam("?next=/grafana/a%2Fb+c&next=/x", "next")).toBe("/grafana/a%2Fb+c");
    expect(rawQueryParam("?other=1", "next")).toBeNull();
    expect(rawQueryParam("?next", "next")).toBe("");
    expect(rawQueryParam("", "next")).toBeNull();
  });
});
