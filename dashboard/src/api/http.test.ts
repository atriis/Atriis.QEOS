import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken, clearTokens, getAccessToken } from "../auth/tokens";
import { apiFetch, ApiError, bootstrapSession, buildQuery, setOnAuthFailure } from "./http";

afterEach(() => {
  clearTokens();
  setOnAuthFailure(() => {});
});

test("buildQuery skips empty values and encodes", () => {
  expect(buildQuery({ days: 30, branch: undefined, search: "" })).toBe("?days=30");
  expect(buildQuery({ q: "a b/c" })).toBe("?q=a%20b%2Fc");
  expect(buildQuery({})).toBe("");
});

test("sends bearer token and parses JSON", async () => {
  setAccessToken("acc-1");
  server.use(
    http.get("/api/v1/thing", ({ request }) => {
      expect(request.headers.get("Authorization")).toBe("Bearer acc-1");
      return HttpResponse.json({ ok: true });
    }),
  );
  await expect(apiFetch("/api/v1/thing")).resolves.toEqual({ ok: true });
});

test("401 triggers one cookie refresh then retries; concurrent calls share it", async () => {
  setAccessToken("stale");
  let refreshes = 0;
  server.use(
    http.get("/api/v1/thing", ({ request }) =>
      request.headers.get("Authorization") === "Bearer fresh"
        ? HttpResponse.json({ ok: true })
        : new HttpResponse(null, { status: 401 }),
    ),
    http.post("/api/v1/auth/refresh-token", async ({ request }) => {
      refreshes += 1;
      // The browser's httpOnly cookie carries the token; the body is empty JSON.
      expect(await request.json()).toEqual({});
      return HttpResponse.json({ access_token: "fresh", refresh_token: "r2", token_type: "bearer" });
    }),
  );
  const [a, b] = await Promise.all([apiFetch("/api/v1/thing"), apiFetch("/api/v1/thing")]);
  expect(a).toEqual({ ok: true });
  expect(b).toEqual({ ok: true });
  expect(refreshes).toBe(1);
  expect(getAccessToken()).toBe("fresh");
});

test("failed refresh clears the session and calls onAuthFailure", async () => {
  setAccessToken("stale");
  const onFail = vi.fn();
  setOnAuthFailure(onFail);
  server.use(
    http.get("/api/v1/thing", () => new HttpResponse(null, { status: 401 })),
    http.post("/api/v1/auth/refresh-token", () => new HttpResponse(null, { status: 401 })),
  );
  await expect(apiFetch("/api/v1/thing")).rejects.toMatchObject({ status: 401 });
  expect(onFail).toHaveBeenCalled();
  expect(getAccessToken()).toBeNull();
});

test.each([
  "/api/v1/auth/login",
  "/api/v1/auth/mfa/verify",
  "/api/v1/auth/logout",
  "/api/v1/sso/google",
])("a 401 from sign-in endpoint %s is its own verdict, not an expired session", async (path) => {
  let refreshes = 0;
  server.use(
    http.post(path, () => HttpResponse.json({ detail: "Incorrect email or password" }, { status: 401 })),
    http.post("/api/v1/auth/refresh-token", () => {
      refreshes += 1;
      return new HttpResponse(null, { status: 401 });
    }),
  );
  await expect(apiFetch(path, { method: "POST", body: "{}" })).rejects.toMatchObject(
    { detail: "Incorrect email or password" },
  );
  expect(refreshes).toBe(0);
});

test.each(["/api/v1/auth/change-password", "/api/v1/auth/mfa/enroll"])(
  "signed-in auth endpoint %s refreshes an expired access token and retries",
  async (path) => {
    setAccessToken("stale");
    server.use(
      http.post(path, ({ request }) =>
        request.headers.get("Authorization") === "Bearer fresh"
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json({ detail: "Could not validate credentials" }, { status: 401 }),
      ),
      http.post("/api/v1/auth/refresh-token", () =>
        HttpResponse.json({ access_token: "fresh", refresh_token: "r2", token_type: "bearer" }),
      ),
    );
    await expect(apiFetch(path, { method: "POST", body: "{}" })).resolves.toEqual({ ok: true });
  },
);

test("bootstrapSession restores the access token from the cookie session", async () => {
  server.use(
    http.post("/api/v1/auth/refresh-token", () =>
      HttpResponse.json({ access_token: "booted", refresh_token: "r", token_type: "bearer" }),
    ),
  );
  await bootstrapSession();
  expect(getAccessToken()).toBe("booted");
});

test("bootstrapSession without a valid cookie resolves quietly", async () => {
  const onFail = vi.fn();
  setOnAuthFailure(onFail);
  server.use(
    http.post("/api/v1/auth/refresh-token", () => new HttpResponse(null, { status: 401 })),
  );
  await expect(bootstrapSession()).resolves.toBeUndefined();
  expect(getAccessToken()).toBeNull();
  expect(onFail).not.toHaveBeenCalled();
});

test("non-JSON error body becomes a readable ApiError", async () => {
  setAccessToken("acc");
  server.use(
    http.get("/api/v1/thing", () => new HttpResponse("<html>Bad Gateway</html>", { status: 502 })),
  );
  const err: ApiError = await apiFetch("/api/v1/thing").then(
    () => {
      throw new Error("expected apiFetch to reject");
    },
    (e: ApiError) => e,
  );
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(502);
  expect(err.detail).toMatch(/502/);
});

test("JSON error detail is surfaced", async () => {
  setAccessToken("acc");
  server.use(
    http.get("/api/v1/thing", () =>
      HttpResponse.json({ detail: "Project not found" }, { status: 404 }),
    ),
  );
  await expect(apiFetch("/api/v1/thing")).rejects.toMatchObject({ detail: "Project not found" });
});

test("an object detail surfaces its message and code", async () => {
  setAccessToken("acc");
  server.use(
    http.post("/api/v1/thing", () =>
      HttpResponse.json({ detail: { code: "plan_changed", message: "Something changed" } }, { status: 409 }),
    ),
  );
  await expect(apiFetch("/api/v1/thing", { method: "POST" })).rejects.toMatchObject({
    status: 409, detail: "Something changed", code: "plan_changed",
  });
});

test("a validation error list surfaces its first message and field", async () => {
  setAccessToken("acc");
  server.use(
    http.post("/api/v1/thing", () =>
      HttpResponse.json(
        { detail: [{ loc: ["body", "files", 0, "path"], msg: "Value error, path not allowed", type: "value_error" }] },
        { status: 422 },
      ),
    ),
  );
  await expect(apiFetch("/api/v1/thing", { method: "POST" })).rejects.toMatchObject({
    status: 422, detail: "path: Value error, path not allowed",
  });
});

test("an error keeps its parsed body for callers that need more than the message", async () => {
  setAccessToken("acc");
  server.use(
    http.put("/api/v1/thing", () => HttpResponse.json(
      { detail: { code: "stale_version", message: "Changed meanwhile", current: { version: 4 } } }, { status: 409 },
    )),
  );
  const error = await apiFetch("/api/v1/thing", { method: "PUT", body: "{}" }).catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).detail).toBe("Changed meanwhile");
  expect((error as ApiError).code).toBe("stale_version");
  expect((error as ApiError).body).toEqual({ detail: { code: "stale_version", message: "Changed meanwhile", current: { version: 4 } } });
});
