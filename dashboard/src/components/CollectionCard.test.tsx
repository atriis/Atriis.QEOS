import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CollectionCard from "./CollectionCard";

const URL = "/api/v1/projects/42/collection-settings";
const MANUAL = /collect runs started manually in ci/i;
const SHOTS = /keep screenshots from uploads/i;
const DEFAULTS = { collect_manual: true, discarded_count: 0, last_discarded_at: null, updated_at: null, updated_by: null };

function renderCard(canManage: boolean | undefined = true) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><CollectionCard projectId={42} canManage={canManage} /></QueryClientProvider>);
}

test("shows the switch on by default and explains what manual means", async () => {
  server.use(http.get(URL, () => HttpResponse.json(DEFAULTS)));
  renderCard();
  const toggle = await screen.findByRole("switch", { name: /collect runs started manually in ci/i });
  expect(toggle).toHaveAttribute("aria-checked", "true");
  expect(screen.getByText(/runs started from qeos are always collected/i)).toBeInTheDocument();
  expect(screen.getByText(/0\.5\.0/)).toBeInTheDocument();
});

test("an admin switches it off and the change is saved", async () => {
  let sent: unknown = null;
  server.use(
    http.get(URL, () => HttpResponse.json(DEFAULTS)),
    http.put(URL, async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ ...DEFAULTS, collect_manual: false, updated_by: 1, updated_at: "2026-10-12T10:00:00Z" });
    }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("switch", { name: MANUAL }));
  expect(sent).toEqual({ collect_manual: false });
  expect(await screen.findByRole("switch", { name: MANUAL })).toHaveAttribute("aria-checked", "false");
});

test("members see it read-only, with the reason", async () => {
  server.use(http.get(URL, () => HttpResponse.json(DEFAULTS)));
  renderCard(false);
  expect(await screen.findByRole("switch", { name: MANUAL })).toBeDisabled();
  expect(screen.getByText(/only owners and admins/i)).toBeInTheDocument();
});

test("says how many manual uploads were not collected", async () => {
  server.use(http.get(URL, () => HttpResponse.json({
    ...DEFAULTS, collect_manual: false, discarded_count: 3, last_discarded_at: new Date(Date.now() - 2 * 3600e3).toISOString(),
  })));
  renderCard();
  expect(await screen.findByText(/3 manual uploads not collected/i)).toBeInTheDocument();
});

test("uses the singular for one manual upload", async () => {
  server.use(http.get(URL, () => HttpResponse.json({
    ...DEFAULTS, collect_manual: false, discarded_count: 1, last_discarded_at: new Date(Date.now() - 2 * 3600e3).toISOString(),
  })));
  renderCard();
  expect(await screen.findByText(/1 manual upload not collected/i)).toBeInTheDocument();
});

test("a failed save shows the error and keeps the old state", async () => {
  server.use(
    http.get(URL, () => HttpResponse.json(DEFAULTS)),
    http.put(URL, () => HttpResponse.json({ detail: "Insufficient role" }, { status: 403 })),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("switch", { name: MANUAL }));
  expect(await screen.findByText(/insufficient role/i)).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: MANUAL })).toHaveAttribute("aria-checked", "true");
});

test("keeping screenshots is off by default, with a plain privacy note", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ ...DEFAULTS, keep_screenshots: false })));
  renderCard();
  const toggle = await screen.findByRole("switch", { name: SHOTS });
  expect(toggle).toHaveAttribute("aria-checked", "false");
  expect(toggle).toHaveAccessibleDescription(/personal data.*never masked.*deleted with the run/i);
});

test("an older server without the field reads as off", async () => {
  server.use(http.get(URL, () => HttpResponse.json(DEFAULTS)));
  renderCard();
  expect(await screen.findByRole("switch", { name: SHOTS })).toHaveAttribute("aria-checked", "false");
});

test("an admin turns screenshots on: only that field is sent", async () => {
  let sent: unknown = null;
  server.use(
    http.get(URL, () => HttpResponse.json({ ...DEFAULTS, keep_screenshots: false })),
    http.put(URL, async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ ...DEFAULTS, keep_screenshots: true });
    }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("switch", { name: SHOTS }));
  expect(sent).toEqual({ keep_screenshots: true });
  expect(await screen.findByRole("switch", { name: SHOTS })).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("switch", { name: MANUAL })).toHaveAttribute("aria-checked", "true");
});

test("members see the screenshots switch read-only", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ ...DEFAULTS, keep_screenshots: true })));
  renderCard(false);
  const toggle = await screen.findByRole("switch", { name: SHOTS });
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  expect(toggle).toBeDisabled();
  expect(toggle).toHaveAccessibleDescription(/only owners and admins/i);
});

const TRACES = /keep traces from uploads/i;
const WARNING = "Traces contain page snapshots and network traffic, which can include cookies, tokens and personal data of your test accounts. QEOS cannot mask them. Turn this on only if every project reader may see that.";

test("keeping traces is off by default, with the exact warning and 14 days", async () => {
  server.use(http.get(URL, () => HttpResponse.json(DEFAULTS)));
  renderCard();
  expect(await screen.findByRole("switch", { name: TRACES })).toHaveAttribute("aria-checked", "false");
  expect(screen.getByText(WARNING)).toBeInTheDocument();
  expect(screen.getByLabelText(/keep them for \(days\)/i)).toHaveValue(14);
});

test("an admin turns traces on: only that field is sent", async () => {
  let sent: unknown = null;
  server.use(
    http.get(URL, () => HttpResponse.json(DEFAULTS)),
    http.put(URL, async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ ...DEFAULTS, keep_traces: true, trace_days: 14 });
    }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("switch", { name: TRACES }));
  expect(sent).toEqual({ keep_traces: true });
  expect(await screen.findByRole("switch", { name: TRACES })).toHaveAttribute("aria-checked", "true");
});

test("changing the days saves trace_days on leaving the field", async () => {
  let sent: unknown = null;
  server.use(
    http.get(URL, () => HttpResponse.json({ ...DEFAULTS, keep_traces: true, trace_days: 14 })),
    http.put(URL, async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ ...DEFAULTS, keep_traces: true, trace_days: 30 });
    }),
  );
  renderCard();
  const days = await screen.findByLabelText(/keep them for \(days\)/i);
  await waitFor(() => expect(days).toBeEnabled());
  await userEvent.clear(days);
  await userEvent.type(days, "30");
  await userEvent.tab();
  await waitFor(() => expect(sent).toEqual({ trace_days: 30 }));
});

test("days outside 1-90 are not sent and say why", async () => {
  let puts = 0;
  server.use(
    http.get(URL, () => HttpResponse.json({ ...DEFAULTS, keep_traces: true, trace_days: 14 })),
    http.put(URL, () => { puts++; return HttpResponse.json(DEFAULTS); }),
  );
  renderCard();
  const days = await screen.findByLabelText(/keep them for \(days\)/i);
  await waitFor(() => expect(days).toBeEnabled());
  await userEvent.clear(days);
  await userEvent.type(days, "91");
  await userEvent.tab();
  expect(await screen.findByText(/between 1 and 90/i)).toBeInTheDocument();
  expect(puts).toBe(0);
});

test("members see the traces switch and days read-only", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ ...DEFAULTS, keep_traces: true, trace_days: 20 })));
  renderCard(false);
  expect(await screen.findByRole("switch", { name: TRACES })).toBeDisabled();
  expect(screen.getByLabelText(/keep them for \(days\)/i)).toBeDisabled();
});
