import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import ScreenshotViewer from "./ScreenshotViewer";

const LIST = "/api/v1/projects/42/runs/61/results/5/screenshots";
const SHOTS = [
  { id: 1, step_text: "", step_line: null, hook: "before", media_type: "image/png", bytes: 10 },
  { id: 2, step_text: "Given a trip", step_line: 4, hook: null, media_type: "image/png", bytes: 10 },
  { id: 3, step_text: "Then the booking is confirmed", step_line: 6, hook: null, media_type: "image/png", bytes: 10 },
  { id: 4, step_text: "Then the booking is confirmed", step_line: 6, hook: null, media_type: "image/png", bytes: 10 },
  { id: 5, step_text: "", step_line: null, hook: "after", media_type: "image/png", bytes: 10 },
];

let imageCalls: number[];
let created: string[];
let revoked: string[];

beforeEach(() => {
  imageCalls = [];
  created = [];
  revoked = [];
  let n = 0;
  Object.defineProperty(globalThis.URL, "createObjectURL", {
    value: vi.fn(() => { const u = `blob:img-${++n}`; created.push(u); return u; }), configurable: true,
  });
  Object.defineProperty(globalThis.URL, "revokeObjectURL", {
    value: vi.fn((u: string) => { revoked.push(u); }), configurable: true,
  });
  server.use(
    http.get(LIST, () => HttpResponse.json({ screenshots: SHOTS })),
    http.get("/api/v1/projects/42/screenshots/:id", ({ params }) => {
      imageCalls.push(Number(params.id));
      return new HttpResponse(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "image/png" } });
    }),
  );
});

function renderViewer(props: Partial<React.ComponentProps<typeof ScreenshotViewer>> = {}) {
  setAccessToken("acc");
  const onClose = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = (open: boolean) => (
    <QueryClientProvider client={qc}>
      <ScreenshotViewer projectId={42} runId={61} resultId={5} open={open} onClose={onClose} {...props} />
    </QueryClientProvider>
  );
  const view = render(ui(props.open ?? true));
  return { onClose, rerender: (open: boolean) => view.rerender(ui(open)) };
}

test("lists the steps, hooks labelled Start and End of scenario", async () => {
  renderViewer();
  expect(await screen.findByRole("button", { name: /Start of scenario/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Given a trip/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Then the booking is confirmed.*2/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /End of scenario/ })).toBeInTheDocument();
});

test("opens on the initial step and fetches only the image shown", async () => {
  renderViewer({ initialStep: { text: "Then the booking is confirmed", line: 6 } });
  const img = await screen.findByRole("img", { name: /Then the booking is confirmed/ });
  expect(img).toHaveAttribute("src", "blob:img-1");
  expect(imageCalls).toEqual([3]);
});

test("falls back to the line when the text does not match", async () => {
  renderViewer({ initialStep: { text: "edited since", line: 4 } });
  await screen.findByRole("img", { name: /Given a trip/ });
  expect(imageCalls).toEqual([2]);
});

test("nothing is fetched while closed", async () => {
  let listCalls = 0;
  server.use(http.get(LIST, () => { listCalls += 1; return HttpResponse.json({ screenshots: SHOTS }); }));
  renderViewer({ open: false });
  await new Promise((r) => setTimeout(r, 30));
  expect(listCalls).toBe(0);
  expect(imageCalls).toEqual([]);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("arrow keys page through the images and Escape closes", async () => {
  const user = userEvent.setup();
  const { onClose } = renderViewer();
  await screen.findByRole("img", { name: /Start of scenario/ });
  await user.keyboard("{ArrowRight}");
  await screen.findByRole("img", { name: /Given a trip/ });
  await user.keyboard("{ArrowRight}{ArrowLeft}");
  await screen.findByRole("img", { name: /Given a trip/ });
  expect(screen.getByText("2 of 5")).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});

test("Open full size links to the blob in a new tab", async () => {
  renderViewer();
  const link = await screen.findByRole("link", { name: /Open full size/ });
  await waitFor(() => expect(link).toHaveAttribute("href", "blob:img-1"));
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
});

test("object URLs are revoked when it closes", async () => {
  const { rerender } = renderViewer();
  await screen.findByRole("img");
  expect(revoked).toEqual([]);
  rerender(false);
  await waitFor(() => expect(revoked).toEqual(created));
  expect(created.length).toBeGreaterThan(0);
});

test("a failed image shows an error with retry", async () => {
  server.use(http.get("/api/v1/projects/42/screenshots/:id", () => new HttpResponse(null, { status: 404 })));
  renderViewer();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Retry/ })).toBeInTheDocument();
});

test("a failed list shows an error", async () => {
  server.use(http.get(LIST, () => new HttpResponse(null, { status: 500 })));
  renderViewer();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});

function useShots(shots: object[]) {
  server.use(http.get(LIST, () => HttpResponse.json({ screenshots: shots })));
}
const shot = (id: number, text: string, line: number | null, hook: "before" | "after" | null = null) =>
  ({ id, step_text: text, step_line: line, hook, media_type: "image/png", bytes: 10 });

test("a step with only a hook image opens on that image", async () => {
  useShots([shot(1, "Given a trip", 4), shot(2, "Then it ends", 6, "after")]);
  renderViewer({ initialStep: { text: "Then it ends", line: 6 } });
  await screen.findByRole("img", { name: /End of scenario/ });
  expect(imageCalls).toEqual([2]);
});

test("a step's own image comes before a hook image on it", async () => {
  useShots([shot(1, "Then it ends", 6, "before"), shot(2, "Then it ends", 6), shot(3, "Then it ends", 6, "after")]);
  renderViewer({ initialStep: { text: "Then it ends", line: 6 } });
  await screen.findByRole("img", { name: /Then it ends/ });
  expect(imageCalls).toEqual([2]);
});

test("repeated step text opens on the matching line", async () => {
  useShots([shot(1, "And I wait", 4), shot(2, "And I wait", 9)]);
  renderViewer({ initialStep: { text: "And I wait", line: 9 } });
  await screen.findByRole("img");
  expect(imageCalls).toEqual([2]);
});

test("the image paged away from is revoked, not kept until close", async () => {
  const user = userEvent.setup();
  renderViewer();
  await screen.findByRole("img", { name: /Start of scenario/ });
  await user.keyboard("{ArrowRight}");
  await screen.findByRole("img", { name: /Given a trip/ });
  expect(revoked).toEqual(["blob:img-1"]);
  expect(screen.getByRole("img")).toHaveAttribute("src", "blob:img-2");
});

test("the title names the test", async () => {
  renderViewer({ name: "Books a trip" });
  expect(await screen.findByRole("dialog", { name: "Screenshots — Books a trip" })).toBeInTheDocument();
});

test("Tab cycles inside the dialog", async () => {
  const user = userEvent.setup();
  renderViewer();
  await screen.findByRole("img");
  const dialog = screen.getByRole("dialog");
  const close = screen.getByRole("button", { name: "Close screenshots" });
  expect(close).toHaveFocus();
  for (let i = 0; i < 20; i++) {
    await user.tab();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  }
  await user.tab({ shift: true });
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
});

test("the page is inert and does not scroll while open, and focus returns to the opener", async () => {
  const opener = document.createElement("button");
  const page = document.createElement("div");
  page.append(opener);
  document.body.append(page);
  opener.focus();
  const { rerender } = renderViewer();
  await screen.findByRole("img");
  expect(page).toHaveAttribute("inert");
  expect(document.body.style.overflow).toBe("hidden");
  rerender(false);
  await waitFor(() => expect(opener).toHaveFocus());
  expect(page).not.toHaveAttribute("inert");
  expect(document.body.style.overflow).not.toBe("hidden");
  page.remove();
});

test("Previous is aria-disabled, not disabled, on the first image", async () => {
  renderViewer();
  await screen.findByRole("img");
  const prev = screen.getByRole("button", { name: "Previous screenshot" });
  expect(prev).toHaveAttribute("aria-disabled", "true");
  expect(prev).not.toBeDisabled();
});
