/** Where a signed-out visitor was going, kept in `?next=` so sign-in can return there. */

/**
 * The `next` value when it is a same-origin relative path, else null: it must start with a single "/",
 * and carry no backslash, whitespace or control character (browsers strip tabs and newlines, so
 * "/\t/evil.example" would otherwise become "//evil.example"), so it can never leave the site.
 */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return null;
  // U+0085 and U+FEFF are named because JS and Python disagree on which of them "\s" covers: the
  // auth-service's RegisterRequest.next check refuses exactly the same characters
  // eslint-disable-next-line no-control-regex
  if (/[\\\s\u0000-\u001f\u007f\u0085\ufeff]/.test(raw)) return null;
  // Back to the login page would loop
  if (raw === "/login" || raw.startsWith("/login?") || raw.startsWith("/login/") || raw.startsWith("/login#")) return null;
  return raw;
}

interface Where {
  pathname: string;
  search: string;
  hash: string;
}

/** The login URL for a visitor who was at `from`; `reason: "expired"` makes the page say the session ended. */
export function loginPath(from: Where, reason?: "expired"): string {
  const params = new URLSearchParams();
  const target = from.pathname + from.search + from.hash;
  if (target !== "/") params.set("next", target);
  if (reason) params.set("reason", reason);
  const query = params.toString();
  return query ? `/login?${query}` : "/login";
}

/** `path` carrying `next` when it is a safe in-app path, else `path` alone. */
export function withNext(path: string, next: string | null | undefined): string {
  const safe = safeNext(next);
  return safe && safe !== "/" ? `${path}?next=${encodeURIComponent(safe)}` : path;
}

const AFTER_VERIFY_KEY = "qeos.afterVerify";
const AFTER_VERIFY_TTL_MS = 24 * 60 * 60 * 1000;

/** Registration ends with an emailed link, often opened in another tab: the page the person was going to is kept
 *  (validated) until they verify. localStorage, because that tab shares it; it expires with the link. */
export function rememberAfterVerify(next: string | null | undefined): void {
  const safe = safeNext(next);
  try {
    if (safe && safe !== "/") localStorage.setItem(AFTER_VERIFY_KEY, JSON.stringify({ next: safe, at: Date.now() }));
    else localStorage.removeItem(AFTER_VERIFY_KEY);
  } catch { /* storage is optional */ }
}

/** The remembered page, once: validated again on the way out, never trusted from storage. */
export function takeAfterVerify(): string | null {
  try {
    const raw = localStorage.getItem(AFTER_VERIFY_KEY);
    localStorage.removeItem(AFTER_VERIFY_KEY);
    if (!raw) return null;
    const { next, at } = JSON.parse(raw) as { next?: unknown; at?: unknown };
    if (typeof next !== "string" || typeof at !== "number" || Date.now() - at > AFTER_VERIFY_TTL_MS) return null;
    return safeNext(next);
  } catch {
    return null;
  }
}
