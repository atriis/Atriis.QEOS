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

test("the note says how to open it, when asked for", () => {
  render(<TraceButton projectId={42} runId={9} resultId={1} name="t" count={1} showNote />);
  expect(screen.getByText(/open it with npx playwright show-trace/i)).toBeInTheDocument();
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
