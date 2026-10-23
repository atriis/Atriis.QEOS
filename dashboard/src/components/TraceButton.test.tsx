import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import TraceButton from "./TraceButton";
import { resetTraceViewerCheck } from "../lib/traceViewer";

const P = "/api/v1/projects/42";

function stubSave() {
  const saved: string[] = [];
  Object.defineProperty(globalThis.URL, "createObjectURL", { value: vi.fn(() => "blob:t"), configurable: true });
  Object.defineProperty(globalThis.URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { saved.push(this.download); });
  return saved;
}

/** navigator.serviceWorker as a browser that can (or cannot) run the trace viewer; jsdom has none. */
function stubServiceWorker(register: () => Promise<unknown> = () => Promise.resolve({})) {
  const spy = vi.fn(register);
  Object.defineProperty(navigator, "serviceWorker", { value: { register: spy }, configurable: true });
  return spy;
}

beforeEach(() => { resetTraceViewerCheck(); stubServiceWorker(); });
afterEach(() => vi.restoreAllMocks());

test("renders nothing for 0 or an absent count", () => {
  const { container, rerender } = render(<TraceButton projectId={42} runId={9} resultId={1} name="t" count={0} />);
  expect(container).toBeEmptyDOMElement();
  rerender(<TraceButton projectId={42} runId={9} resultId={1} name="t" />);
  expect(container).toBeEmptyDOMElement();
});

test("fetches with the Bearer token and saves trace-<id>.zip for each trace", async () => {
  setAccessToken("acc");
  const saved = stubSave();
  const auth: (string | null)[] = [];
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [
      { id: 5, kind: "trace", name: "a.zip", bytes: 4 }, { id: 6, kind: "trace", name: "b.zip", bytes: 4 }] })),
    http.get(`${P}/artifacts/:id`, ({ request }) => { auth.push(request.headers.get("authorization")); return new HttpResponse("PK\x03\x04"); }),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={2} />);
  await userEvent.click(screen.getByRole("button", { name: "Download traces for test_ok" }));
  await waitFor(() => expect(saved).toEqual(["trace-5.zip", "trace-6.zip"]));
  expect(auth).toEqual(["Bearer acc", "Bearer acc"]);
  // Browsers may hold back a second automatic download: the files go one at a time, and the page says what to allow
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("2 traces downloaded"));
  expect(screen.getByText("If the browser blocked any, allow this site to download several files.")).toBeVisible();
});

test("one trace downloads without the several-files note", async () => {
  setAccessToken("acc");
  const saved = stubSave();
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "a.zip", bytes: 4 }] })),
    http.get(`${P}/artifacts/:id`, () => new HttpResponse("PK")),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Download trace for test_ok" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Trace downloaded"));
  expect(saved).toEqual(["trace-5.zip"]);
  expect(screen.queryByText(/download several files/)).toBeNull();
});

test("a failed download says so and the button works again", async () => {
  setAccessToken("acc");
  stubSave();
  server.use(http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ detail: "gone" }, { status: 404 })));
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Download trace for test_ok" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/trace could not be downloaded/i);
  expect(screen.getByRole("button", { name: "Download trace for test_ok" })).toBeEnabled();
});

test("the note says how to open a download, when asked for", () => {
  render(<TraceButton projectId={42} runId={9} resultId={1} name="t" count={1} showNote />);
  expect(screen.getByText("A downloaded trace opens with npx playwright show-trace")).toBeInTheDocument();
});

test("while downloading it is busy and a status says so, then says it is done", async () => {
  setAccessToken("acc");
  stubSave();
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, async () => { await gate; return HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "a.zip", bytes: 4 }] }); }),
    http.get(`${P}/artifacts/:id`, () => new HttpResponse("PK")),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Download trace for test_ok" }));
  expect(screen.getByRole("button", { name: "Download trace for test_ok" })).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("status")).toHaveTextContent("Downloading trace…");
  release();
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Trace downloaded"));
  expect(screen.getByRole("button", { name: "Download trace for test_ok" })).toHaveAttribute("aria-busy", "false");
});

/** A stand-in for the tab window.open returns: records where it is sent and whether it was closed. */
function stubTab() {
  const tab = { opener: {} as unknown, location: { href: "" }, closed: false, close() { this.closed = true; } };
  const open = vi.spyOn(window, "open").mockImplementation(() => tab as unknown as Window);
  return { tab, open };
}

test("Open trace asks for a one-time link and sends a new tab to the self-hosted viewer with it", async () => {
  setAccessToken("acc");
  const { tab, open } = stubTab();
  const asked: { path: string; auth: string | null }[] = [];
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [
      { id: 5, kind: "trace", name: "a.zip", bytes: 4 }, { id: 6, kind: "trace", name: "b.zip", bytes: 4 }] })),
    http.post(`${P}/artifacts/:id/link`, ({ request, params }) => {
      asked.push({ path: String(params.id), auth: request.headers.get("authorization") });
      return HttpResponse.json({ url: "/api/v1/artifact-links/tok-en", expires_at: "2026-10-22T10:00:00Z" }, { status: 201 });
    }),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  const url = `${window.location.origin}/api/v1/artifact-links/tok-en`;
  await waitFor(() => expect(tab.location.href).toBe("/trace-viewer/index.html?trace=" + encodeURIComponent(url)));
  // The tab opens in the click itself (no pop-up blocker), blank, and loses its opener before it is sent anywhere
  expect(open).toHaveBeenCalledTimes(1);
  expect(open).toHaveBeenCalledWith("", "_blank");
  expect(tab.opener).toBeNull();
  // One trace per tab: a count of 1 opens the first
  expect(asked).toEqual([{ path: "5", auth: "Bearer acc" }]);
  expect(screen.getByRole("status")).toHaveTextContent("Trace opened in a new tab");
});

test("a failed link closes the blank tab, says so, and the button works again", async () => {
  setAccessToken("acc");
  const { tab } = stubTab();
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "a.zip", bytes: 4 }] })),
    http.post(`${P}/artifacts/:id/link`, () => HttpResponse.json({ detail: "Not found" }, { status: 404 })),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The trace could not be opened. Try again.");
  expect(tab.closed).toBe(true);
  expect(tab.location.href).toBe("");
  expect(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" })).toHaveAttribute("aria-busy", "false");
});

test("a blocked pop-up asks to allow pop-ups and requests no link", async () => {
  setAccessToken("acc");
  vi.spyOn(window, "open").mockImplementation(() => null);
  let linked = false;
  server.use(http.post(`${P}/artifacts/:id/link`, () => { linked = true; return HttpResponse.json({}, { status: 201 }); }));
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Allow pop-ups for this site to open the trace.");
  expect(linked).toBe(false);
});

test("a result whose list has no trace closes the blank tab and says so", async () => {
  setAccessToken("acc");
  const { tab } = stubTab();
  server.use(http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [] })));
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The trace could not be opened. Try again.");
  expect(tab.closed).toBe(true);
  expect(tab.location.href).toBe("");
});

test("while one button works the other is disabled, so their messages cannot cross", async () => {
  setAccessToken("acc");
  stubSave();
  stubTab();
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, async () => { await gate; return HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "a.zip", bytes: 4 }] }); }),
    http.get(`${P}/artifacts/:id`, () => new HttpResponse("PK")),
    http.post(`${P}/artifacts/:id/link`, () => HttpResponse.json({ url: "/api/v1/artifact-links/t", expires_at: "2026-10-22T10:00:00Z" }, { status: 201 })),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  const openButton = screen.getByRole("button", { name: "Open trace for test_ok in a new tab" });
  const downloadButton = screen.getByRole("button", { name: "Download trace for test_ok" });
  await userEvent.click(downloadButton);
  expect(openButton).toBeDisabled();
  release();
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Trace downloaded"));
  expect(openButton).toBeEnabled();

  let releaseOpen!: () => void;
  const openGate = new Promise<void>((r) => { releaseOpen = r; });
  server.use(http.get(`${P}/runs/9/results/1/artifacts`, async () => { await openGate; return HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "a.zip", bytes: 4 }] }); }));
  await userEvent.click(openButton);
  expect(downloadButton).toBeDisabled();
  releaseOpen();
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Trace opened in a new tab"));
  expect(downloadButton).toBeEnabled();
});

const BLOCKED = "This browser cannot run the trace viewer for this site, usually because it does not trust the site's certificate. Download the trace instead, or ask an administrator for a trusted certificate.";

test("a browser that refuses the viewer's service worker gets a reason instead of a blank tab, and no link", async () => {
  setAccessToken("acc");
  const { tab } = stubTab();
  const register = stubServiceWorker(() => Promise.reject(new DOMException("An SSL certificate error occurred", "SecurityError")));
  let linked = false;
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "a.zip", bytes: 4 }] })),
    http.post(`${P}/artifacts/:id/link`, () => { linked = true; return HttpResponse.json({}, { status: 201 }); }),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(BLOCKED);
  expect(register).toHaveBeenCalledWith("/trace-viewer/sw.bundle.js", { scope: "/trace-viewer/" });
  expect(tab.closed).toBe(true);
  expect(tab.location.href).toBe("");
  expect(linked).toBe(false);
  // Download still works, and the next click checks again (the certificate may be trusted by then)
  expect(screen.getByRole("button", { name: "Download trace for test_ok" })).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  await waitFor(() => expect(register).toHaveBeenCalledTimes(2));
});

test("a browser without service workers gets the same reason", async () => {
  setAccessToken("acc");
  const { tab } = stubTab();
  Object.defineProperty(navigator, "serviceWorker", { value: undefined, configurable: true });
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(BLOCKED);
  expect(tab.closed).toBe(true);
});

test("the viewer check runs once per page when it succeeds", async () => {
  setAccessToken("acc");
  stubTab();
  const register = stubServiceWorker();
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "a.zip", bytes: 4 }] })),
    http.post(`${P}/artifacts/:id/link`, () => HttpResponse.json({ url: "/api/v1/artifact-links/t", expires_at: "2026-10-22T10:00:00Z" }, { status: 201 })),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={1} />);
  const button = screen.getByRole("button", { name: "Open trace for test_ok in a new tab" });
  await userEvent.click(button);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Trace opened in a new tab"));
  await userEvent.click(button);
  await waitFor(() => expect(button).toHaveAttribute("aria-busy", "false"));
  expect(register).toHaveBeenCalledTimes(1);
});

test("several traces: a labelled group of numbered buttons, each opening its own trace", async () => {
  setAccessToken("acc");
  const { tab } = stubTab();
  const asked: string[] = [];
  server.use(
    http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [
      { id: 5, kind: "trace", name: "trace", bytes: 4 }, { id: 6, kind: "trace", name: "trace", bytes: 4 },
      { id: 7, kind: "trace", name: "trace", bytes: 4 }] })),
    http.post(`${P}/artifacts/:id/link`, ({ params }) => {
      asked.push(String(params.id));
      return HttpResponse.json({ url: "/api/v1/artifact-links/t", expires_at: "2026-10-22T10:00:00Z" }, { status: 201 });
    }),
  );
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={3} />);
  const group = screen.getByRole("group", { name: "Traces for test_ok" });
  const buttons = within(group).getAllByRole("button");
  expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([1, 2, 3].map((n) => `Open trace ${n} of 3 for test_ok in a new tab`));
  expect(buttons.map((b) => b.textContent)).toEqual(["1", "2", "3"]);
  expect(screen.queryByRole("button", { name: "Open trace for test_ok in a new tab" })).not.toBeInTheDocument();
  await userEvent.click(buttons[1]);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Trace 2 opened in a new tab"));
  expect(asked).toEqual(["6"]);
  expect(tab.location.href).toContain("/trace-viewer/index.html?trace=");
  // The download still saves every trace
  expect(screen.getByRole("button", { name: "Download traces for test_ok" })).toBeEnabled();
});

test("a trace that is gone since the count closes the tab and says so", async () => {
  setAccessToken("acc");
  const { tab } = stubTab();
  server.use(http.get(`${P}/runs/9/results/1/artifacts`, () => HttpResponse.json({ artifacts: [{ id: 5, kind: "trace", name: "trace", bytes: 4 }] })));
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={2} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace 2 of 2 for test_ok in a new tab" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The trace could not be opened. Try again.");
  expect(tab.closed).toBe(true);
});
