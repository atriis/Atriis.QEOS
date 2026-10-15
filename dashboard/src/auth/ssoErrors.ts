/** What a failed Microsoft sign-in means for the page. MSAL errors carry an `errorCode` (BrowserAuthError,
 *  ServerError...); this module reads that shape without importing MSAL, which the page lazy-loads. */

interface WithErrorCode { errorCode: string }

function errorCodeOf(err: unknown): string | null {
  if (typeof err !== "object" || err === null) return null;
  const code = (err as Partial<WithErrorCode>).errorCode;
  return typeof code === "string" && code !== "" ? code : null;
}

/** The person closed the Microsoft window, or opened a second one: not a failure, nothing to show. */
export function isSsoCancelled(err: unknown): boolean {
  const code = errorCodeOf(err);
  return code === "user_cancelled" || code === "interaction_in_progress";
}

/** Error raised by the page for an MSAL failure: a plain sentence for the banner, the MSAL code for support. */
export class SsoError extends Error {
  readonly code: string;
  constructor(code: string, retry: string) {
    super(`Microsoft sign-in failed (${code}). ${retry}`);
    this.name = "SsoError";
    this.code = code;
  }
}

/** The error the banner shows for a Microsoft failure: unchanged when it came from QEOS's API (its detail is already
 *  the message) or is a cancellation; otherwise an SsoError naming the MSAL code and the way back. */
export function ssoFailure(err: unknown, passwordOffered: boolean): unknown {
  const code = errorCodeOf(err);
  if (code === null) return err;
  const retry = passwordOffered ? "Try again, or sign in with your password." : "Try again.";
  return new SsoError(code, retry);
}
