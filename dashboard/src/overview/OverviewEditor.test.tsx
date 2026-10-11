import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import type { OverviewLayoutState } from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";
import { BUILTIN_DEFAULT } from "./templates";
import { BUILTIN_STATE, mockOverviewData, personalState, projectState, renderOverview } from "./testing";

const PUT_PERSONAL = "/api/v1/projects/42/overview-layout/personal";
type Sent = { layout: StoredLayout; version: number };

/** Records personal saves; the layout GET then answers what was saved last (the refetch after Save reads it). */
function capturePuts(): Sent[] {
  const bodies: Sent[] = [];
  server.use(
    http.put(PUT_PERSONAL, async ({ request }) => {
      const body = (await request.json()) as Sent;
      bodies.push(body);
      return HttpResponse.json({ layout: body.layout, version: body.version + 1, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
    }),
    http.get("/api/v1/projects/42/overview-layout", () => {
      const last = bodies[bodies.length - 1];
      if (last === undefined) return HttpResponse.json(BUILTIN_STATE);
      return HttpResponse.json({ ...personalState(...last.layout.widgets), personal: { version: last.version + 1, updated_at: "2026-10-11T10:00:00Z" } });
    }),
  );
  return bodies;
}

async function startEditing() {
  await userEvent.click(await screen.findByRole("button", { name: "Customise" }));
  expect(await screen.findByText("Editing your Overview")).toBeInTheDocument();
}

const titles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
const MINE = { id: "m1", type: "flaky_count", size: "normal" as const };
const mineOverDefault = (personalUpdatedAt: string): OverviewLayoutState => ({
  ...projectState(BUILTIN_DEFAULT), effective: { schema: 1, widgets: [MINE] }, source: "personal",
  personal: { version: 3, updated_at: personalUpdatedAt },
});

test("Customise edits a draft and Save sends it with the version editing started from", async () => {
  mockOverviewData();
  const puts = capturePuts();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Move Pass rate this week up" }));
  expect(titles()).toEqual(["Latest run", "Pass rate this week", "Failing in latest run", "Flaky tests, last 14 days"]);
  expect(puts).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0].version).toBe(0);
  expect(puts[0].layout.widgets.map((w) => w.id)).toEqual(["w1", "w3", "w2", "w4"]);
  expect(await screen.findByRole("button", { name: "Customise" })).toHaveFocus();
  expect(screen.queryByText("Editing your Overview")).not.toBeInTheDocument();
  expect(titles()).toEqual(["Latest run", "Pass rate this week", "Failing in latest run", "Flaky tests, last 14 days"]);
});

test("a move keeps focus on the moved widget and is announced in one polite live region", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  const name = "Move Flaky tests, last 14 days up";
  await userEvent.click(screen.getByRole("button", { name }));
  expect(screen.getByRole("button", { name })).toHaveFocus();
  expect(screen.getByText("Flaky tests, last 14 days moved to position 3 of 4")).toHaveAttribute("aria-live", "polite");
  await userEvent.click(screen.getByRole("button", { name }));
  await userEvent.click(screen.getByRole("button", { name }));
  // At the top its Move up is disabled, so focus rests on the widget itself
  expect(screen.getByRole("region", { name: "Flaky tests, last 14 days" })).toHaveFocus();
  expect(screen.getByText("Flaky tests, last 14 days moved to position 1 of 4")).toBeInTheDocument();
});

test("Wide and Normal resize a widget in the draft", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  const toggle = screen.getByRole("button", { name: "Show Pass rate this week wide" });
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(toggle);
  expect(screen.getByRole("region", { name: "Pass rate this week" })).toHaveClass("wide");
  expect(screen.getByRole("button", { name: "Show Pass rate this week wide" })).toHaveAttribute("aria-pressed", "true");
});

test("Remove and Add change the draft, move focus sensibly and say so", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Flaky tests, last 14 days" }));
  expect(screen.queryByRole("region", { name: "Flaky tests, last 14 days" })).not.toBeInTheDocument();
  expect(screen.getByText("Flaky tests, last 14 days removed")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Pass rate this week" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Add widget" }));
  const panel = screen.getByRole("region", { name: "Add a widget" });
  await userEvent.click(within(panel).getByRole("button", { name: "Add Flaky tests" }));
  expect(await screen.findByRole("region", { name: "Flaky tests, last 14 days" })).toHaveFocus();
  expect(screen.getByText("Flaky tests added at position 4 of 4")).toBeInTheDocument();
});

test("Settings change a widget's settings, which Save sends", async () => {
  mockOverviewData();
  const puts = capturePuts();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Failing in latest run settings" }));
  const form = screen.getByRole("form", { name: "Failing in latest run settings" });
  await userEvent.selectOptions(within(form).getByLabelText("Rows"), "10");
  await userEvent.click(within(form).getByRole("button", { name: "Apply" }));
  expect(screen.getByRole("button", { name: "Failing in latest run settings" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0].layout.widgets[1]).toEqual({ id: "w2", type: "failing_now", size: "normal", settings: { rows: 10 } });
});

test("leaving with changes asks first: Cancel asks in place, navigation and closing the tab are guarded", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByText("Editing your Overview")).not.toBeInTheDocument(); // nothing changed: it leaves at once
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Discard" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  await userEvent.click(screen.getByRole("link", { name: "Elsewhere" }));
  expect(await screen.findByRole("alertdialog", { name: "Unsaved changes" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Stay" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(screen.queryByText("Editing your Overview")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Latest run" })).toBeInTheDocument();
});

test("a background refetch while editing keeps the draft", async () => {
  mockOverviewData();
  const { qc } = renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  server.use(http.get("/api/v1/projects/42/overview-layout", () =>
    HttpResponse.json(personalState({ id: "z", type: "flaky_count", size: "normal" }))));
  await qc.invalidateQueries({ queryKey: ["overview-layout", 42] });
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
  expect(titles()).toEqual(["Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
});

test("Reset to project default puts the default in the draft, and Save then deletes the personal layout", async () => {
  mockOverviewData({ layout: mineOverDefault("2026-10-10T10:00:00Z") });
  const deleted: string[] = [];
  server.use(http.delete("/api/v1/projects/42/overview-layout/:mode", ({ params }) => {
    deleted.push(String(params.mode));
    return new HttpResponse(null, { status: 204 });
  }));
  renderOverview();
  await startEditing();
  expect(titles()).toEqual(["Flaky tests, last 14 days"]);
  await userEvent.click(screen.getByRole("button", { name: "Reset to project default" }));
  expect(titles()).toEqual(["Latest run", "Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(deleted).toEqual(["personal"]));
  expect(await screen.findByRole("button", { name: "Customise" })).toBeInTheDocument();
});

test("the editor notes when the project default changed after the personal layout was saved", async () => {
  mockOverviewData({ layout: mineOverDefault("2026-10-01T10:00:00Z") });
  renderOverview();
  await startEditing();
  expect(screen.getByText(/^The project default changed on /)).toBeInTheDocument();
});

test("a layout of 24 widgets cannot take another", async () => {
  const many = Array.from({ length: 24 }, (_, i) => ({ id: `w${i + 1}`, type: "flaky_count", size: "normal" as const }));
  mockOverviewData({ layout: personalState(...many) });
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Add widget" }));
  const panel = screen.getByRole("region", { name: "Add a widget" });
  expect(within(panel).getByText(/at most 24 widgets/)).toBeInTheDocument();
  expect(within(panel).getByRole("button", { name: "Add Latest run" })).toBeDisabled();
});

test("a stale save shows who changed it; Overwrite resends with their version", async () => {
  mockOverviewData({ layout: personalState(...BUILTIN_DEFAULT.widgets) });
  const versions: number[] = [];
  server.use(http.put(PUT_PERSONAL, async ({ request }) => {
    const body = (await request.json()) as Sent;
    versions.push(body.version);
    if (versions.length === 1) {
      return HttpResponse.json({ detail: { code: "stale_version", message: "Changed",
        current: { version: 5, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" } } }, { status: 409 });
    }
    return HttpResponse.json({ layout: body.layout, version: 6, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
  }));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const dialog = await screen.findByRole("alertdialog", { name: "The layout changed while you were editing" });
  expect(dialog).toHaveTextContent(/Changed by ada@example\.com on .+ since you started/);
  expect(within(dialog).getByRole("button", { name: "Reload" })).toHaveFocus();
  await userEvent.click(within(dialog).getByRole("button", { name: "Overwrite" }));
  await waitFor(() => expect(versions).toEqual([1, 5]));
  expect(await screen.findByRole("button", { name: "Customise" })).toBeInTheDocument();
});

test("Reload after a conflict starts editing again from the stored layout", async () => {
  mockOverviewData({ layout: personalState(...BUILTIN_DEFAULT.widgets) });
  server.use(http.put(PUT_PERSONAL, () => HttpResponse.json({ detail: { code: "stale_version", message: "Changed",
    current: { version: 2, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" } } }, { status: 409 })));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  server.use(http.get("/api/v1/projects/42/overview-layout", () => HttpResponse.json({
    ...personalState({ id: "n1", type: "flaky_count", size: "wide" }), personal: { version: 2, updated_at: "2026-10-11T09:00:00Z" },
  })));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await userEvent.click(await screen.findByRole("button", { name: "Reload" }));
  await waitFor(() => expect(titles()).toEqual(["Flaky tests, last 14 days"]));
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
});

test("All branches removes the branch setting: no branch is every branch", async () => {
  // Registered first, so the layout below answers the GET until something is saved
  const puts = capturePuts();
  mockOverviewData({ layout: personalState({ id: "p1", type: "pass_rate_week", size: "normal", settings: { branch: "main" } }) });
  server.use(http.get("/api/v1/projects/42/analytics/branches", () => HttpResponse.json([
    { branch: "main", runs: 3, total: 9, passed: 9, failed: 0, errored: 0 },
    { branch: "all", runs: 1, total: 3, passed: 3, failed: 0, errored: 0 },
  ])));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Pass rate this week settings" }));
  const form = screen.getByRole("form", { name: "Pass rate this week settings" });
  const branch = within(form).getByLabelText("Branch");
  expect(branch).toHaveValue("main");
  // A git branch named "all" is an ordinary choice, separate from All branches
  expect(await within(form).findByRole("option", { name: "all" })).toBeInTheDocument();
  await userEvent.selectOptions(branch, "All branches");
  await userEvent.click(within(form).getByRole("button", { name: "Apply" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0].layout.widgets[0]).toEqual({ id: "p1", type: "pass_rate_week", size: "normal", settings: {} });
});
