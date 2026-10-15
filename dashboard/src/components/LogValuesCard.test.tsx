import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import LogValuesCard from "./LogValuesCard";

const BASE = "/api/v1/projects/42/log-patterns";
const LINK = "https://backoffice.example.com/trips/{value}";
const TRIP = { id: 1, name: "trip_id", pattern: 'tripId="(\\d+)"', link_template: LINK, created_at: "2026-10-14T10:00:00Z" };
const ROUTE = { id: 2, name: "route_key", pattern: 'routeKey="([^"]+)"', link_template: null, created_at: null };
const IDLE = { state: "idle", since: null };
const list = (patterns: object[], scan: object = IDLE) => HttpResponse.json({ patterns, scan });

function renderCard(canEdit: boolean | undefined = true) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <LogValuesCard projectId={42} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

// userEvent treats { and [ as key descriptors; paste keeps the text literal
async function pasteInto(label: RegExp, text: string) {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.paste(text);
}

async function fill(name: string, pattern: string, link?: string) {
  await userEvent.type(screen.getByLabelText(/^name/i), name);
  await pasteInto(/^regular expression/i, pattern);
  if (link) await pasteInto(/^link/i, link);
}

test("lists each pattern with its expression and its link", async () => {
  server.use(http.get(BASE, () => list([ROUTE, TRIP])));
  renderCard();
  const row = (await screen.findByText("trip_id")).closest("tr")!;
  expect(within(row).getByText('tripId="(\\d+)"')).toBeInTheDocument();
  expect(within(row).getByText(LINK)).toBeInTheDocument();
  expect(within(screen.getByText("route_key").closest("tr")!).getByText("None")).toBeInTheDocument();
});

test("the ? button explains the rule, and an example fills the expression", async () => {
  server.use(http.get(BASE, () => list([])));
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  const help = screen.getByRole("button", { name: "How values are captured" });
  expect(help).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(help);
  expect(help).toHaveAttribute("aria-expanded", "true");
  const popover = screen.getByRole("group", { name: "How values are captured" });
  expect(popover).toHaveTextContent(/one capture group/i);
  expect(popover).toHaveTextContent(/whole match/i);
  expect(popover).toHaveTextContent(/masked log/i);
  expect(within(popover).getAllByRole("button").map((b) => b.textContent))
    .toEqual(['tripId="(\\d+)"', 'routeKey="([^"]+)"', 'status="([^"]+)"']);
  await userEvent.click(within(popover).getByRole("button", { name: 'routeKey="([^"]+)"' }));
  const input = screen.getByLabelText(/^regular expression/i);
  expect(input).toHaveValue('routeKey="([^"]+)"');
  expect(input).toHaveFocus();
  expect(screen.queryByRole("group", { name: "How values are captured" })).toBeNull();
});

test("Escape closes the help and puts focus back on its button", async () => {
  server.use(http.get(BASE, () => list([])));
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  const help = screen.getByRole("button", { name: "How values are captured" });
  await userEvent.click(help);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("group", { name: "How values are captured" })).toBeNull();
  expect(help).toHaveFocus();
});

test("preview shows the values found as name: value chips and their count, saving nothing", async () => {
  let previewed: unknown = null;
  let saved = false;
  server.use(
    http.get(BASE, () => list([])),
    http.post(`${BASE}/preview`, async ({ request }) => {
      previewed = await request.json();
      return HttpResponse.json({ masked: "…", values: ["3960562", "3960563"] });
    }),
    http.post(BASE, () => {
      saved = true;
      return HttpResponse.json(TRIP, { status: 201 });
    }),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"');
  await pasteInto(/^log lines/i, 'INFO tripId="3960562"\nINFO tripId="3960563"');
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));

  const result = await screen.findByRole("status");
  expect(result).toHaveTextContent("2 values found");
  expect(within(result).getAllByRole("listitem").map((c) => c.textContent)).toEqual(["trip_id: 3960562", "trip_id: 3960563"]);
  expect(previewed).toEqual({ name: "trip_id", pattern: 'tripId="(\\d+)"', sample: 'INFO tripId="3960562"\nINFO tripId="3960563"' });
  expect(saved).toBe(false);
});

test("a preview that finds nothing says so", async () => {
  server.use(http.get(BASE, () => list([])), http.post(`${BASE}/preview`, () => HttpResponse.json({ masked: "x", values: [] })));
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"');
  await pasteInto(/^log lines/i, "nothing here");
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByRole("status")).toHaveTextContent("No values found in these lines.");
});

test("adding sends the name, expression and link, lists the pattern and clears the form", async () => {
  let sent: unknown = null;
  let added = false;
  server.use(
    http.get(BASE, () => list(added ? [TRIP] : [])),
    http.post(BASE, async ({ request }) => {
      sent = await request.json();
      added = true;
      return HttpResponse.json(TRIP, { status: 201 });
    }),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"', LINK);
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));

  expect(await screen.findByText("trip_id")).toBeInTheDocument();
  expect(sent).toEqual({ name: "trip_id", pattern: 'tripId="(\\d+)"', link_template: LINK });
  expect(screen.getByLabelText(/^regular expression/i)).toHaveValue("");
  expect(screen.getByLabelText(/^link/i)).toHaveValue("");
});

test("an empty link is sent as null", async () => {
  let sent: { link_template?: unknown } = {};
  server.use(
    http.get(BASE, () => list([])),
    http.post(BASE, async ({ request }) => {
      sent = (await request.json()) as typeof sent;
      return HttpResponse.json({ ...TRIP, link_template: null }, { status: 201 });
    }),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"');
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));
  await waitFor(() => expect(sent.link_template).toBeNull());
});

test.each([
  ["pattern", 422, /^regular expression/i, "A pattern has at most one capture group", /at most one capture group/],
  ["name", 409, /^name/i, "This project already has a log-value pattern named trip_id", /already has a log-value pattern/],
  ["link_template", 422, /^link/i, "The link must be an https:// address with a host", /must be an https:\/\/ address/],
])("a %s refusal is shown at its field", async (code, status, label, message, expected) => {
  server.use(
    http.get(BASE, () => list([])),
    http.post(BASE, () => HttpResponse.json({ detail: { code, message } }, { status })),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", "(a)(b)", "http://backoffice.example.com/{value}");
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));

  const field = screen.getByLabelText(label);
  await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
  expect(field).toHaveAccessibleDescription(expected);
  expect(field).toHaveFocus();
  expect(screen.queryByRole("alert")).toBeNull(); // at the field, not in a banner
  expect(screen.getByLabelText(/^regular expression/i)).toHaveValue("(a)(b)");
});

test("a limit reached is a banner", async () => {
  server.use(
    http.get(BASE, () => list([])),
    http.post(BASE, () => HttpResponse.json(
      { detail: { code: "limit", message: "A project has at most 20 log-value patterns" } }, { status: 422 })),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("p20", "token20");
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("at most 20 log-value patterns");
});

test("while past runs are scanned the card says so", async () => {
  server.use(http.get(BASE, () => list([TRIP], { state: "running", since: "2026-10-14T10:00:00Z" })));
  renderCard();
  expect(await screen.findByText("Scanning past runs…")).toBeInTheDocument();
});

test("removing asks first, then deletes", async () => {
  let removed = false;
  server.use(
    http.get(BASE, () => list(removed ? [] : [TRIP])),
    http.delete(`${BASE}/1`, () => {
      removed = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderCard();
  await screen.findByText("trip_id");
  await userEvent.click(screen.getByRole("button", { name: /remove pattern trip_id/i }));
  expect(removed).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: /^remove$/i }));
  expect(await screen.findByText(/no log-value patterns/i)).toBeInTheDocument();
});

test("viewers read the patterns but cannot change them", async () => {
  server.use(http.get(BASE, () => list([TRIP])));
  renderCard(false);
  const row = (await screen.findByText("trip_id")).closest("tr")!;
  expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/^regular expression/i)).not.toBeInTheDocument();
  expect(screen.getByText(/only owners, admins and members/i)).toBeInTheDocument();
});
