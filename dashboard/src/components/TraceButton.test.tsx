import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import TraceButton from "./TraceButton";

const P = "/api/v1/projects/42";

function stubSave() {
  const saved: string[] = [];
  Object.defineProperty(globalThis.URL, "createObjectURL", { value: vi.fn(() => "blob:t"), configurable: true });
  Object.defineProperty(globalThis.URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { saved.push(this.download); });
  return saved;
}

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
  await userEvent.click(screen.getByRole("button", { name: "Download trace for test_ok" }));
  await waitFor(() => expect(saved).toEqual(["trace-5.zip", "trace-6.zip"]));
  expect(auth).toEqual(["Bearer acc", "Bearer acc"]);
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
  render(<TraceButton projectId={42} runId={9} resultId={1} name="test_ok" count={2} />);
  await userEvent.click(screen.getByRole("button", { name: "Open trace for test_ok in a new tab" }));
  const url = `${window.location.origin}/api/v1/artifact-links/tok-en`;
  await waitFor(() => expect(tab.location.href).toBe("/trace-viewer/index.html?trace=" + encodeURIComponent(url)));
  // The tab opens in the click itself (no pop-up blocker), blank, and loses its opener before it is sent anywhere
  expect(open).toHaveBeenCalledTimes(1);
  expect(open).toHaveBeenCalledWith("", "_blank");
  expect(tab.opener).toBeNull();
  // The first trace only: the viewer opens one trace per tab
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
