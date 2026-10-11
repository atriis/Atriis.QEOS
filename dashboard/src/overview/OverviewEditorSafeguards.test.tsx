import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import type { StoredLayout } from "./catalog";
import { BUILTIN_DEFAULT } from "./templates";
import { BUILTIN_STATE, RUN, mockOverviewData, personalState, renderOverview } from "./testing";

/** The editor's safeguards around polls, project switches, conflicts and resets (Task 13 review, fix round 1). */

const PUT_PERSONAL = "/api/v1/projects/42/overview-layout/personal";
type Sent = { layout: StoredLayout; version: number };
const DIALOG = "The layout changed while you were editing";
const BUILTIN_TITLES = ["Latest run", "Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"];
const WITHOUT_LATEST = ["Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"];

const titles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
const stale = (current: object | null) =>
  HttpResponse.json({ detail: { code: "stale_version", message: "Changed", current } }, { status: 409 });

async function startEditing() {
  await userEvent.click(await screen.findByRole("button", { name: "Customise" }));
  expect(await screen.findByText("Editing your Overview")).toBeInTheDocument();
}

test("a failed runs poll leaves the editor and its draft in place, saying so above it", async () => {
  mockOverviewData();
  const { qc } = renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  server.use(http.get("/api/v1/projects/42/runs", () => HttpResponse.json({ detail: "Runs are down" }, { status: 500 })));
  await qc.refetchQueries({ queryKey: ["runs", 42, "latest"] });
  expect(await screen.findByText("Runs are down")).toBeInTheDocument();
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
  expect(titles()).toEqual(WITHOUT_LATEST);
  mockOverviewData();
  await qc.refetchQueries({ queryKey: ["runs", 42, "latest"] });
  await waitFor(() => expect(screen.queryByText("Runs are down")).not.toBeInTheDocument());
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
  expect(titles()).toEqual(WITHOUT_LATEST);
});

test("switching project asks about the draft first, and the other project's editor never holds this one's layout", async () => {
  mockOverviewData({ layout: personalState({ id: "a1", type: "flaky_count", size: "normal" }) });
  const putsTo43: unknown[] = [];
  server.use(
    http.get("/api/v1/projects/43", () => HttpResponse.json({ id: 43, organization_id: 1, name: "App", my_role: "member" })),
    http.get("/api/v1/projects/43/runs", () => HttpResponse.json([{ ...RUN, id: 90, project_id: 43 }])),
    http.get("/api/v1/projects/43/overview-layout", () => HttpResponse.json(BUILTIN_STATE)),
    http.put("/api/v1/projects/43/overview-layout/:mode", async ({ request }) => {
      putsTo43.push(await request.json());
      return HttpResponse.json({ layout: BUILTIN_DEFAULT, version: 1, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
    }),
  );
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Show Flaky tests, last 14 days wide" }));
  await userEvent.click(screen.getByRole("link", { name: "Other project" }));
  expect(await screen.findByRole("alertdialog", { name: "Unsaved changes" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Leave without saving" }));
  // Project 43 shows its own (built-in) layout, outside edit mode
  expect(await screen.findByRole("button", { name: "Customise" })).toBeInTheDocument();
  expect(screen.queryByText("Editing your Overview")).not.toBeInTheDocument();
  await waitFor(() => expect(titles()).toEqual(BUILTIN_TITLES));
  // Editing there starts from its own layout at its own version
  await startEditing();
  expect(titles()).toEqual(BUILTIN_TITLES);
  await userEvent.click(screen.getByRole("button", { name: "Show Failing in latest run wide" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(putsTo43).toHaveLength(1));
  const sent = putsTo43[0] as Sent;
  expect(sent.version).toBe(0);
  expect(sent.layout.widgets.map((w) => [w.id, w.type, w.size])).toEqual([
    ["w1", "latest_run", "wide"], ["w2", "failing_now", "wide"], ["w3", "pass_rate_week", "normal"], ["w4", "flaky_count", "normal"],
  ]);
});

test("Overwrite and Reload are disabled while an Overwrite is in flight; Escape dismisses the conflict", async () => {
  mockOverviewData({ layout: personalState(...BUILTIN_DEFAULT.widgets) });
  let release: () => void = () => {};
  let calls = 0;
  server.use(http.put(PUT_PERSONAL, async () => {
    calls += 1;
    if (calls === 1) return stale({ version: 5, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" });
    await new Promise<void>((resolve) => { release = resolve; });
    return stale({ version: 6, updated_by: 7, updated_at: "2026-10-11T09:30:00Z" });
  }));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const dialog = await screen.findByRole("alertdialog", { name: DIALOG });
  expect(dialog).toHaveAccessibleDescription(/Changed by ada@example\.com on .+ since you started/);
  await userEvent.click(within(dialog).getByRole("button", { name: "Overwrite" }));
  await waitFor(() => expect(calls).toBe(2));
  expect(within(dialog).getByRole("button", { name: "Overwrite" })).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "Reload" })).toBeDisabled();
  release();
  await waitFor(() => expect(within(screen.getByRole("alertdialog", { name: DIALOG })).getByRole("button", { name: "Overwrite" })).toBeEnabled());
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("alertdialog", { name: DIALOG })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save" })).toHaveFocus();
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
});

test("Overwrite after the stored layout was removed says so and sends version 0", async () => {
  mockOverviewData({ layout: personalState(...BUILTIN_DEFAULT.widgets) });
  const versions: number[] = [];
  server.use(http.put(PUT_PERSONAL, async ({ request }) => {
    const body = (await request.json()) as Sent;
    versions.push(body.version);
    if (versions.length === 1) return stale(null);
    return HttpResponse.json({ layout: body.layout, version: 1, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
  }));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const dialog = await screen.findByRole("alertdialog", { name: DIALOG });
  expect(dialog).toHaveTextContent("This layout was removed since you started");
  await userEvent.click(within(dialog).getByRole("button", { name: "Overwrite" }));
  await waitFor(() => expect(versions).toEqual([1, 0]));
  expect(await screen.findByRole("button", { name: "Customise" })).toBeInTheDocument();
});

test("Save after a reset always deletes, even when nothing was stored when editing began", async () => {
  mockOverviewData();
  const deleted: string[] = [];
  server.use(http.delete("/api/v1/projects/42/overview-layout/:mode", ({ params }) => {
    deleted.push(String(params.mode));
    return new HttpResponse(null, { status: 204 });
  }));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Reset to project default" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(deleted).toEqual(["personal"]));
});

test("a Reload that cannot read the stored layout says so and keeps the draft and the conflict", async () => {
  mockOverviewData({ layout: personalState(...BUILTIN_DEFAULT.widgets) });
  server.use(http.put(PUT_PERSONAL, () => stale({ version: 2, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" })));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  server.use(http.get("/api/v1/projects/42/overview-layout", () => HttpResponse.json({ detail: "Layouts are down" }, { status: 500 })));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await userEvent.click(await screen.findByRole("button", { name: "Reload" }));
  expect(await screen.findByText("Layouts are down")).toBeInTheDocument();
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
  expect(screen.getByRole("alertdialog", { name: DIALOG })).toBeInTheDocument();
  expect(titles()).toEqual(WITHOUT_LATEST);
});

test("the same announcement twice still changes the live region, so it is said again", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  const live = () => document.querySelector("[aria-live=polite]")!.textContent;
  async function applyRows() {
    await userEvent.click(screen.getByRole("button", { name: "Failing in latest run settings" }));
    const form = screen.getByRole("form", { name: "Failing in latest run settings" });
    await userEvent.click(within(form).getByRole("button", { name: "Apply" }));
  }
  await applyRows();
  const first = live();
  await applyRows();
  expect(first?.trim()).toBe("Failing in latest run settings applied");
  expect(live()?.trim()).toBe("Failing in latest run settings applied");
  expect(live()).not.toBe(first);
});

test("a card that takes focus from the keyboard shows the focus ring; only pointer focus hides it", () => {
  const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");
  expect(css).toMatch(/\.overview-grid > \.card:focus-visible \{ outline: 2px solid var\(--accent\); outline-offset: 2px; \}/);
  expect(css).not.toMatch(/\.overview-grid > \.card:focus \{ outline: none; \}/);
});
