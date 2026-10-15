import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import LogPanel from "./LogPanel";

const URL = "/api/v1/projects/42/runs/61/results/5/log";
const LOG = 'INFO tripId="3960562"\nINFO routeKey="wasToBos"';
const VALUES = [{ name: "route_key", values: ["wasToBos"] }, { name: "trip_id", values: ["3960562"] }];

function renderPanel() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <LogPanel projectId={42} runId={61} resultId={5} name="Books a trip" />
    </QueryClientProvider>,
  );
}

// jsdom has no object URLs: the download link only needs a href
beforeEach(() => {
  Object.defineProperty(globalThis.URL, "createObjectURL", { value: vi.fn(() => "blob:log"), configurable: true });
  Object.defineProperty(globalThis.URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
});

test("nothing is fetched until Log is pressed; then once, marked, with copy and download", async () => {
  let calls = 0;
  server.use(http.get(URL, () => { calls++; return HttpResponse.json({ log: LOG, values: VALUES }); }));
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  renderPanel();
  const button = screen.getByRole("button", { name: "Log of Books a trip" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(calls).toBe(0);

  await userEvent.click(button);
  const panel = await screen.findByRole("region", { name: "Log of Books a trip" });
  expect(button).toHaveAttribute("aria-expanded", "true");
  const marks = within(panel).getAllByText((_, el) => el?.tagName === "MARK");
  expect(marks.map((m) => [m.textContent, m.getAttribute("title")])).toEqual([["3960562", "trip_id"], ["wasToBos", "route_key"]]);
  expect(within(panel).getByRole("link", { name: "Download" })).toHaveAttribute("download", "Books_a_trip-run-61.txt");
  await userEvent.click(within(panel).getByRole("button", { name: "Copy log" }));
  expect(writeText).toHaveBeenCalledWith(LOG);
  expect(await within(panel).findByText("Copied")).toBeInTheDocument();

  await userEvent.click(button);
  expect(screen.queryByRole("region", { name: "Log of Books a trip" })).toBeNull();
  expect(button).toHaveFocus();
  await userEvent.click(button);
  await screen.findByRole("region", { name: "Log of Books a trip" });
  expect(calls).toBe(1);
});

test("a result without a log says so", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ log: null, values: [] })));
  renderPanel();
  await userEvent.click(screen.getByRole("button", { name: "Log of Books a trip" }));
  expect(await screen.findByText("No log for this result.")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Download" })).toBeNull();
});

test("a 404 reads as no log (an older server)", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ detail: "Not Found" }, { status: 404 })));
  renderPanel();
  await userEvent.click(screen.getByRole("button", { name: "Log of Books a trip" }));
  expect(await screen.findByText("No log for this result.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a failed request shows the error with a retry", async () => {
  let failures = 1;
  server.use(http.get(URL, () => failures-- > 0
    ? HttpResponse.json({ detail: "boom" }, { status: 500 })
    : HttpResponse.json({ log: "ok", values: [] })));
  renderPanel();
  await userEvent.click(screen.getByRole("button", { name: "Log of Books a trip" }));
  const alert = await screen.findByRole("alert");
  await userEvent.click(within(alert).getByRole("button", { name: /retry/i }));
  await waitFor(() => expect(screen.getByText("ok")).toBeInTheDocument());
});
