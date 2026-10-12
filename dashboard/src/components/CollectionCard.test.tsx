import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CollectionCard from "./CollectionCard";

const URL = "/api/v1/projects/42/collection-settings";
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
  await userEvent.click(await screen.findByRole("switch"));
  expect(sent).toEqual({ collect_manual: false });
  expect(await screen.findByRole("switch")).toHaveAttribute("aria-checked", "false");
});

test("members see it read-only, with the reason", async () => {
  server.use(http.get(URL, () => HttpResponse.json(DEFAULTS)));
  renderCard(false);
  expect(await screen.findByRole("switch")).toBeDisabled();
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
  await userEvent.click(await screen.findByRole("switch"));
  expect(await screen.findByText(/insufficient role/i)).toBeInTheDocument();
  expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
});
