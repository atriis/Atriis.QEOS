import { useEffect, useState } from "react";
import { getAuthMethods, type AuthMethods } from "../api/auth";
import { ApiError } from "../api/http";

function wellFormed(value: unknown): value is AuthMethods {
  const v = value as AuthMethods | null;
  return typeof v?.password === "boolean" && Array.isArray(v.providers) && v.providers.every((p) => typeof p === "string");
}

/** How this deployment signs people in (ADR-031), read once per mount. Null while loading, and when the
 *  request fails or answers something unexpected: the page then shows its normal form, and the server
 *  still enforces the mode. */
export function useAuthMethods(): AuthMethods | null {
  const [methods, setMethods] = useState<AuthMethods | null>(null);
  useEffect(() => {
    let cancelled = false;
    getAuthMethods()
      .then((answer) => {
        if (!cancelled && wellFormed(answer)) setMethods(answer);
      })
      .catch(() => {
        // Normal form: see above
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return methods;
}

export function isSsoOnly(methods: AuthMethods | null): boolean {
  return methods !== null && !methods.password;
}

/** The server's SSO-only refusal: 403 {"detail": {"code": "sso_only", ...}} */
export function isSsoOnlyError(error: unknown): boolean {
  return error instanceof ApiError && error.code === "sso_only";
}

/** The provider names inside the server's 403 message ("Sign-in is through Google or Microsoft only."), for when
 *  /auth/methods was unavailable; undefined when the error is not that refusal or the message has another shape. */
export function ssoOnlyNames(error: unknown): string | undefined {
  if (!isSsoOnlyError(error)) return undefined;
  return /through (.+) only\.?$/.exec((error as ApiError).detail)?.[1];
}

const LABELS: Record<string, string> = { microsoft: "Microsoft", google: "Google" };

export function providerNames(providers: readonly string[]): string {
  const names = providers.map((p) => LABELS[p] ?? p);
  return names.length > 0 ? names.join(" or ") : "single sign-on";
}

/** The login page's one line in SSO-only mode. */
export function ssoOnlyLine(providers: readonly string[]): string {
  if (providers.length === 1 && providers[0] === "microsoft") return "Sign-in is through your Microsoft work account.";
  return `Sign-in is through ${providerNames(providers)}.`;
}
