/** The Grafana sign-in hand-off (ADR-027): where `/monitoring?next=` may lead, and the guard that stops a
 *  hand-off loop when Grafana sends the browser straight back. */

const GRAFANA_HOME = "/grafana/";

/**
 * A query parameter exactly as it appears in `search`, still percent-encoded (null when absent).
 * URLSearchParams would decode it (and turn "+" into a space), and grafanaPath must decode exactly once.
 */
export function rawQueryParam(search: string, name: string): string | null {
  for (const part of search.replace(/^\?/, "").split("&")) {
    const eq = part.indexOf("=");
    const key = eq === -1 ? part : part.slice(0, eq);
    if (key === name) return eq === -1 ? "" : part.slice(eq + 1);
  }
  return null;
}

/**
 * Where a raw (percent-encoded) `next` may lead: the decoded path when it is plainly inside Grafana on this
 * site, else Grafana's home. Anyone can craft a /monitoring?next= link, so the gateway's own restriction is
 * not relied on. Decoded exactly once; refused when the result does not start with "/grafana/", or still
 * holds a "%" (a second decode downstream could turn it into "../" or "/"), "//" after the first character,
 * a backslash, a "." or ".." segment, or any whitespace or control character.
 */
export function grafanaPath(raw: string | null): string {
  if (!raw) return GRAFANA_HOME;
  let path: string;
  try {
    path = decodeURIComponent(raw);
  } catch {
    return GRAFANA_HOME; // malformed percent-encoding
  }
  // The prefix is the guard against other sites and schemes: nothing before it can name a host
  if (!path.startsWith(GRAFANA_HOME)) return GRAFANA_HOME;
  // A "%" left after the one decode would be decoded again by the gateway ("..%2f" -> "../", leaving the
  // gated location). Grafana's uid/slug paths never need one, and the gateway drops the query anyway
  if (path.includes("%")) return GRAFANA_HOME;
  if (path.indexOf("//", 1) !== -1) return GRAFANA_HOME;
  // eslint-disable-next-line no-control-regex
  if (/[\\\s\u0000-\u001f\u007f-\u009f]/.test(path)) return GRAFANA_HOME;
  const segments = path.split(/[?#]/)[0].split("/");
  if (segments.some((s) => s === "." || s === "..")) return GRAFANA_HOME;
  return path;
}

const HANDOFF_KEY = "qeos.grafanaHandoff";
/** A bounce comes back within a second or two; a later visit is a fresh hand-off (another tab, the 8 h cookie
 *  ended). Short, so a cookie lost moments after a hand-off only costs one Try again click. */
const HANDOFF_WINDOW_MS = 10_000;

/** Notes that the cookie was just handed over and the browser is leaving for Grafana. */
export function markHandoff(): void {
  try {
    sessionStorage.setItem(HANDOFF_KEY, String(Date.now()));
  } catch { /* without storage, takeRecentHandoff says true and the page asks */ }
}

/** True when a hand-off ran moments ago, so Grafana sent the browser straight back: the page then asks
 *  instead of handing over again (no loop). Also true when storage cannot tell. The mark is used once. */
export function takeRecentHandoff(): boolean {
  try {
    const value = sessionStorage.getItem(HANDOFF_KEY);
    sessionStorage.removeItem(HANDOFF_KEY);
    if (value === null) return false;
    const age = Date.now() - Number(value);
    return age >= 0 && age < HANDOFF_WINDOW_MS;
  } catch {
    return true;
  }
}
