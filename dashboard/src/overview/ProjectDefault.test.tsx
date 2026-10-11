import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import type { StoredLayout } from "./catalog";
import { mockOverviewData, projectState, renderOverview } from "./testing";

const PUT_PROJECT = "/api/v1/projects/42/overview-layout/project";
const TEAM: StoredLayout = { schema: 1, widgets: [
  { id: "t1", type: "latest_run", size: "wide" }, { id: "t2", type: "failing_now", size: "normal", settings: { rows: 10 } },
] };
const MINE: StoredLayout = { schema: 1, widgets: [{ id: "m1", type: "flaky_count", size: "normal" }] };
const titles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

async function openProjectEditor() {
  await userEvent.click(await screen.findByRole("button", { name: "Customise", expanded: false }));
  await userEvent.click(screen.getByRole("button", { name: "Edit project default" }));
}

// In view mode, once the role has loaded: a role that may not manage the project gets a plain Customise button that
// opens its own Overview, never a menu offering the project default
test.each(["member", "viewer", "billing_manager"])("a %s customises their own Overview only", async (role) => {
  mockOverviewData({ role });
  const { qc } = renderOverview();
  await waitFor(() => expect(qc.getQueryData(["project", 42])).toMatchObject({ my_role: role }));
  const customise = await screen.findByRole("button", { name: "Customise" });
  expect(customise).not.toHaveAttribute("aria-expanded");
  expect(screen.queryByRole("button", { name: "Edit project default" })).not.toBeInTheDocument();
  await userEvent.click(customise);
  expect(screen.queryByRole("button", { name: "Edit project default" })).not.toBeInTheDocument();
  expect(await screen.findByText("Editing your Overview")).toBeInTheDocument();
});

test.each(["owner", "admin"])("an %s sees Edit project default in the Customise menu", async (role) => {
  mockOverviewData({ role, layout: projectState(TEAM) });
  renderOverview();
  const customise = await screen.findByRole("button", { name: "Customise", expanded: false });
  await userEvent.click(customise);
  expect(customise).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "Customise your Overview" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit project default" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Edit project default" }));
  expect(await screen.findByText("Editing the project default · everyone without a personal layout sees this")).toBeInTheDocument();
  expect(screen.getByText(/^Last changed by ada@example\.com on /)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reset to built-in default" })).toBeInTheDocument();
});

test("saving the project default asks first, in primary, then sends the default's version", async () => {
  mockOverviewData({ role: "owner", layout: projectState(TEAM) });
  const sent: { version: number; layout: StoredLayout }[] = [];
  server.use(http.put(PUT_PROJECT, async ({ request }) => {
    const body = (await request.json()) as { version: number; layout: StoredLayout };
    sent.push(body);
    return HttpResponse.json({ layout: body.layout, version: 3, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
  }));
  renderOverview();
  await openProjectEditor();
  await userEvent.click(await screen.findByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByText("Everyone without a personal layout will see this layout.")).toBeInTheDocument();
  const confirm = screen.getByRole("button", { name: "Save for everyone" });
  expect(confirm).toHaveClass("primary");
  expect(confirm).not.toHaveClass("danger");
  expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  expect(sent).toHaveLength(0);
  await userEvent.click(confirm);
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].version).toBe(2);
  expect(sent[0].layout.widgets.map((w) => w.id)).toEqual(["t2"]);
});

test("an owner with a personal layout edits the project default, not their own", async () => {
  mockOverviewData({ role: "owner", layout: {
    ...projectState(TEAM), effective: MINE, source: "personal", personal: { version: 1, updated_at: "2026-10-10T10:00:00Z" },
  } });
  renderOverview();
  expect(await screen.findByRole("region", { name: "Flaky tests, last 14 days" })).toBeInTheDocument();
  await openProjectEditor();
  await waitFor(() => expect(titles()).toEqual(["Latest run", "Failing in latest run"]));
});

test("Reset to built-in default then Save deletes the project default", async () => {
  mockOverviewData({ role: "admin", layout: projectState(TEAM) });
  const deleted: string[] = [];
  server.use(http.delete("/api/v1/projects/42/overview-layout/:mode", ({ params }) => {
    deleted.push(String(params.mode));
    return new HttpResponse(null, { status: 204 });
  }));
  renderOverview();
  await openProjectEditor();
  await userEvent.click(await screen.findByRole("button", { name: "Reset to built-in default" }));
  expect(titles()).toEqual(["Latest run", "Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await userEvent.click(screen.getByRole("button", { name: "Save for everyone" }));
  await waitFor(() => expect(deleted).toEqual(["project"]));
});
