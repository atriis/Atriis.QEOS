import { loginPath, rememberAfterVerify, safeNext, takeAfterVerify, withNext } from "./redirect";

describe("safeNext accepts only same-origin relative paths", () => {
  test.each([
    ["/projects/42/runs?status=failing#top", "/projects/42/runs?status=failing#top"],
    ["/invitations/abc123", "/invitations/abc123"],
    ["/", "/"],
  ])("%s", (raw, expected) => expect(safeNext(raw)).toBe(expected));

  test.each([
    ["protocol-relative", "//evil.example/x"],
    ["absolute http", "http://evil.example"],
    ["absolute https", "https://evil.example/projects/1"],
    ["javascript scheme", "javascript:alert(1)"],
    ["data scheme", "data:text/html,x"],
    ["backslash trick", "/\\evil.example"],
    ["backslash after path", "/projects\\..\\..\\x"],
    ["tab inside, which browsers strip to //", "/\t/evil.example"],
    ["newline inside", "/\n/evil.example"],
    ["no leading slash", "projects/42"],
    ["bare host", "evil.example"],
    ["empty", ""],
    ["login itself, which would loop", "/login?next=/x"],
    // Named in the rule because JS "\s" and Python "\s" disagree on them; the auth-service refuses them too
    ["a next-line character (U+0085)", "/a\u0085b"],
    ["a byte-order mark (U+FEFF)", "/a\ufeffb"],
  ])("rejects %s", (_name, raw) => expect(safeNext(raw)).toBeNull());

  test("rejects a missing value", () => {
    expect(safeNext(null)).toBeNull();
    expect(safeNext(undefined)).toBeNull();
  });
});

describe("loginPath", () => {
  test("remembers where the user was going", () => {
    expect(loginPath({ pathname: "/projects/42/runs", search: "?status=failing", hash: "" }))
      .toBe("/login?next=%2Fprojects%2F42%2Fruns%3Fstatus%3Dfailing");
  });
  test("marks an expired session", () => {
    expect(loginPath({ pathname: "/invitations/t", search: "", hash: "" }, "expired"))
      .toBe("/login?next=%2Finvitations%2Ft&reason=expired");
  });
  test("the front page is not worth remembering", () => {
    expect(loginPath({ pathname: "/", search: "", hash: "" })).toBe("/login");
    expect(loginPath({ pathname: "/", search: "", hash: "" }, "expired")).toBe("/login?reason=expired");
  });
});

describe("carrying next through registration and verification", () => {
  beforeEach(() => localStorage.clear());

  test("withNext adds a safe next and drops an unsafe or root one", () => {
    expect(withNext("/register", "/invitations/abc")).toBe("/register?next=%2Finvitations%2Fabc");
    expect(withNext("/register", "//evil.example")).toBe("/register");
    expect(withNext("/register", "/")).toBe("/register");
    expect(withNext("/register", null)).toBe("/register");
  });

  test("a remembered page is returned once", () => {
    rememberAfterVerify("/invitations/abc");
    expect(takeAfterVerify()).toBe("/invitations/abc");
    expect(takeAfterVerify()).toBeNull();
  });

  test("remembering an unsafe page forgets the previous one", () => {
    rememberAfterVerify("/invitations/abc");
    rememberAfterVerify("https://evil.example");
    expect(takeAfterVerify()).toBeNull();
  });

  test("storage is validated again on the way out, and expires", () => {
    localStorage.setItem("qeos.afterVerify", JSON.stringify({ next: "//evil.example", at: Date.now() }));
    expect(takeAfterVerify()).toBeNull();
    localStorage.setItem("qeos.afterVerify", JSON.stringify({ next: "/invitations/abc", at: Date.now() - 25 * 3600 * 1000 }));
    expect(takeAfterVerify()).toBeNull();
    localStorage.setItem("qeos.afterVerify", "not json");
    expect(takeAfterVerify()).toBeNull();
  });
});
