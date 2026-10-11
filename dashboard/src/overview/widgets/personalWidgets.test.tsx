import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { FAILING_RUN, RUN, mockOverviewData, personalState, renderOverview } from "../testing";

const me = (full_name: string | null) =>
  server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ id: 7, email: "ada@example.com", mfa_enabled: false, full_name })));

function failingRunsAsked(answer: object[]) {
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/runs", ({ request }) => {
    const params = new URL(request.url).searchParams;
    if (params.get("status") !== "failing") return HttpResponse.json([RUN]);
    asked.push(params);
    return HttpResponse.json(answer);
  }));
  return asked;
}

const headingLink = async (name: string) => within(await screen.findByRole("heading", { name })).getByRole("link");

test("My recent failures matches the commit author by the user's full name", async () => {
  mockOverviewData({ layout: personalState({ id: "f", type: "my_failures", size: "normal" }) });
  me("Ada Lovelace");
  const asked = failingRunsAsked([{ ...FAILING_RUN, errored: 2 }]);
  renderOverview();
  expect(await screen.findByRole("link", { name: "Run #61" })).toHaveAttribute("href", "/projects/42/runs/61");
  expect(screen.getByText(/main · .* · 3 failed, 2 errored/)).toBeInTheDocument();
  expect(asked[0].get("author")).toBe("Ada Lovelace");
  expect(asked[0].get("status")).toBe("failing");
  expect(asked[0].get("limit")).toBe("50");
  // No author setting: the full name is not known to the link, so the link names none (plan Ruling 19)
  expect(await headingLink("My recent failures")).toHaveAttribute("href", "/projects/42/runs?status=failing");
});

test("with no full name and no setting, My recent failures asks for a name and sends nothing", async () => {
  mockOverviewData({ layout: personalState({ id: "f", type: "my_failures", size: "normal" }) });
  me(null);
  const asked = failingRunsAsked([FAILING_RUN]);
  renderOverview();
  expect(await screen.findByText(/Your QEOS profile has no full name/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Change settings" }));
  expect(await screen.findByRole("form", { name: "My recent failures settings" })).toBeInTheDocument();
  expect(asked).toHaveLength(0);
});

test("when nothing matches, My recent failures says so and names the setting", async () => {
  mockOverviewData({ layout: personalState({ id: "f", type: "my_failures", size: "normal", settings: { author: "A. Lovelace", rows: 5 } }) });
  me("Ada Lovelace");
  const asked = failingRunsAsked([]);
  renderOverview();
  expect(await screen.findByText(/No failed runs by “A\. Lovelace”/)).toBeInTheDocument();
  expect(screen.getByText(/Your name in git/)).toBeInTheDocument();
  expect(asked[0].get("author")).toBe("A. Lovelace");
  expect(await headingLink("My recent failures")).toHaveAttribute("href", "/projects/42/runs?status=failing&author=A.%20Lovelace");
  await userEvent.click(screen.getByRole("button", { name: "Change settings" }));
  expect(await screen.findByRole("form", { name: "My recent failures settings" })).toBeInTheDocument();
});

test("My suites lists the caller's own suites and links to Suites", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "my_suites", size: "normal" }) });
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/suites", ({ request }) => {
    asked.push(new URL(request.url).searchParams);
    return HttpResponse.json([
      { id: 5, name: "Smoke", description: null, case_count: 1200, created_at: "2026-10-01T00:00:00Z", updated_at: null },
      { id: 6, name: "Edge", description: null, case_count: 1, created_at: "2026-10-01T00:00:00Z", updated_at: null },
    ]);
  }));
  renderOverview();
  expect(await screen.findByRole("link", { name: "Smoke" })).toHaveAttribute("href", "/projects/42/suites/5");
  expect(screen.getByText("1,200 cases")).toBeInTheDocument();
  expect(screen.getByText("1 case")).toBeInTheDocument();
  expect(asked[0].get("created_by")).toBe("me");
  expect(await headingLink("My suites")).toHaveAttribute("href", "/projects/42/suites");
  expect(screen.getByRole("link", { name: "Suites" })).toHaveAttribute("href", "/projects/42/suites");
});

test("My suites says when there are none yet", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "my_suites", size: "normal" }) });
  server.use(http.get("/api/v1/projects/42/suites", () => HttpResponse.json([])));
  renderOverview();
  expect(await screen.findByText("You have not created a suite in this project yet.")).toBeInTheDocument();
});

test("My suites shows its error with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "my_suites", size: "normal" }) });
  server.use(http.get("/api/v1/projects/42/suites", () => HttpResponse.json({ detail: "Suites are down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "My suites" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Suites are down");
  expect(within(card).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("Test cases shows the Cases tiles under their own keys, links to Cases, and is wide by default", async () => {
  mockOverviewData({ layout: personalState({ id: "c", type: "case_tiles", size: "wide" }) });
  server.use(http.get("/api/v1/projects/42/cases", ({ request }) =>
    HttpResponse.json({ total: new URL(request.url).searchParams.get("origin") === "imported" ? 4 : 12, items: [] })));
  const { qc } = renderOverview();
  expect(await screen.findByRole("group", { name: "Cases 12, 4 imported" })).toBeInTheDocument();
  expect(await headingLink("Test cases")).toHaveAttribute("href", "/projects/42/cases");
  await waitFor(() => expect(screen.getByRole("region", { name: "Test cases" })).toHaveClass("wide"));
  expect(qc.getQueryData(["cases-total", 42])).toBe(12);
});
