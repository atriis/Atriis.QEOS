import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import MicrosoftRolesCard from "./MicrosoftRolesCard";

const URL = "/api/v1/organizations/5/sso-role-mappings";
const row = (id: number, app_role: string, role: string) => ({ id, app_role, role, created_at: "2026-10-16T09:00:00Z" });

function renderCard() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MicrosoftRolesCard orgId={5} /></QueryClientProvider>);
}

test("lists the mappings with the lead line", async () => {
  server.use(http.get(URL, () => HttpResponse.json([row(1, "QEOS.Admin", "admin"), row(2, "QEOS.Member", "member")])));
  renderCard();
  expect(screen.getByRole("heading", { name: "Microsoft roles" })).toBeInTheDocument();
  expect(screen.getByText(/Owners are always granted by hand\./)).toBeInTheDocument();
  const table = await screen.findByRole("table");
  expect(within(table).getByText("QEOS.Admin")).toBeInTheDocument();
  expect(within(table).getByText("member")).toBeInTheDocument();
});

test("empty state", async () => {
  server.use(http.get(URL, () => HttpResponse.json([])));
  renderCard();
  expect(await screen.findByText("No app roles mapped yet.")).toBeInTheDocument();
});

test("the role select offers admin, member and viewer only", async () => {
  server.use(http.get(URL, () => HttpResponse.json([])));
  renderCard();
  const select = await screen.findByLabelText("QEOS role");
  expect([...(select as HTMLSelectElement).options].map((o) => o.value)).toEqual(["admin", "member", "viewer"]);
});

test("adds a mapping", async () => {
  let rows = [row(1, "QEOS.Admin", "admin")];
  server.use(
    http.get(URL, () => HttpResponse.json(rows)),
    http.post(URL, async ({ request }) => {
      const body = (await request.json()) as { app_role: string; role: string };
      expect(body).toEqual({ app_role: "QEOS.Viewer", role: "viewer" });
      rows = [...rows, row(2, "QEOS.Viewer", "viewer")];
      return HttpResponse.json(rows[1], { status: 201 });
    }),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("App role"), "QEOS.Viewer");
  await userEvent.selectOptions(screen.getByLabelText("QEOS role"), "viewer");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(await screen.findByText("QEOS.Viewer")).toBeInTheDocument();
  expect(screen.getByLabelText("App role")).toHaveValue("");
});

test("a duplicate shows at the field", async () => {
  server.use(
    http.get(URL, () => HttpResponse.json([row(1, "QEOS.Admin", "admin")])),
    http.post(URL, () => HttpResponse.json({ detail: { code: "duplicate_app_role", message: "This app role is already mapped." } }, { status: 409 })),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("App role"), "qeos.admin");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(await screen.findByText("This app role is already mapped.")).toBeInTheDocument();
});

test("removes a mapping after confirmation", async () => {
  let rows = [row(1, "QEOS.Admin", "admin")];
  server.use(
    http.get(URL, () => HttpResponse.json(rows)),
    http.delete(`${URL}/1`, () => { rows = []; return new HttpResponse(null, { status: 204 }); }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("button", { name: "Remove mapping QEOS.Admin" }));
  expect(screen.getByText(/Members keep their role until their next Microsoft sign-in\./)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(screen.getByText("No app roles mapped yet.")).toBeInTheDocument());
});

test("a failed load shows the error with Retry inside the card", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  renderCard();
  expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
