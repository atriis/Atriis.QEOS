import { apiFetch } from "./http";
import { clearTokens, setAccessToken } from "../auth/tokens";

interface TokenOut {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

interface MfaChallengeOut {
  mfa_required: true;
  mfa_token: string;
}

export interface MfaChallenge {
  mfaToken: string;
}

/** Null means signed in; a challenge means MFA must be completed via mfaVerify. */
export async function login(email: string, password: string): Promise<MfaChallenge | null> {
  const body = await apiFetch<TokenOut | MfaChallengeOut>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if ("mfa_required" in body) return { mfaToken: body.mfa_token };
  // The refresh token arrives as an httpOnly cookie; only the access token is kept.
  setAccessToken(body.access_token);
  return null;
}

export async function register(email: string, password: string, fullName?: string): Promise<void> {
  const body: Record<string, string> = { email, password };
  if (fullName?.trim()) body.full_name = fullName.trim();
  await apiFetch("/api/v1/auth/register", { method: "POST", body: JSON.stringify(body) });
}

/** Completes registration from the emailed link and signs the person in. */
export async function verifyEmail(token: string): Promise<void> {
  const tokens = await apiFetch<TokenOut>(
    `/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`,
  );
  setAccessToken(tokens.access_token);
}

/** Same answer whether or not the address has an account. */
export async function requestPasswordReset(email: string): Promise<void> {
  await apiFetch("/api/v1/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
}

export async function resetPassword(token: string, password: string): Promise<void> {
  await apiFetch("/api/v1/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
}

/** Ends every other session; this one continues on the fresh tokens returned. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const tokens = await apiFetch<TokenOut>("/api/v1/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  setAccessToken(tokens.access_token);
}

export async function mfaVerify(mfaToken: string, code: string): Promise<void> {
  const tokens = await apiFetch<TokenOut>("/api/v1/auth/mfa/verify", {
    method: "POST",
    body: JSON.stringify({ mfa_token: mfaToken, code }),
  });
  setAccessToken(tokens.access_token);
}

/** The signed-in account (GET /users/me). `monitoring_url` is set only for a superuser while monitoring is on
 *  (ADR-027); `linked_providers`, `sso_only` and `has_password` drive the Security page (ADR-031). The newer
 *  fields are optional so an older server's answer still types. */
export interface Me {
  id: number;
  email: string;
  mfa_enabled: boolean;
  full_name?: string | null;
  monitoring_url?: string | null;
  is_superuser?: boolean;
  linked_providers?: string[];
  sso_only?: boolean;
  has_password?: boolean;
}

export function getMe(): Promise<Me> {
  return apiFetch("/api/v1/users/me");
}

/** The signed-in person, under one key for every reader (the user menu, the palette, My recent failures). */
export const meQuery = { queryKey: ["me"] as const, queryFn: getMe, staleTime: 5 * 60_000 };

/** Hands over the qeos_grafana cookie (8 hours, /grafana only); resolves to where Grafana lives. */
export async function startGrafanaSession(): Promise<string> {
  const body = await apiFetch<{ url: string }>("/api/v1/auth/grafana-session", { method: "POST", body: "{}" });
  return body.url;
}

export function mfaEnroll(): Promise<{ secret: string; otpauth_uri: string }> {
  return apiFetch("/api/v1/auth/mfa/enroll", { method: "POST", body: "{}" });
}

export function mfaConfirm(code: string): Promise<{ recovery_codes: string[] }> {
  return apiFetch("/api/v1/auth/mfa/confirm", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export function mfaDisable(code: string): Promise<void> {
  return apiFetch("/api/v1/auth/mfa/disable", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export async function ssoLogin(
  provider: "google" | "microsoft",
  credential: string,
): Promise<void> {
  const tokens = await apiFetch<TokenOut>(`/api/v1/sso/${provider}`, {
    method: "POST",
    body: JSON.stringify({ credential }),
  });
  setAccessToken(tokens.access_token);
}

export async function logout(): Promise<void> {
  try {
    // The cookie identifies the session; the server clears it.
    await apiFetch("/api/v1/auth/logout", { method: "POST", body: "{}" });
  } catch {
    // Best effort: a dead session can't be revoked server-side anyway.
  } finally {
    clearTokens();
  }
}

/** GET /auth/methods (public, ADR-031): `password: false` means SSO-only mode; `providers` are the ones offered. */
export interface AuthMethods {
  password: boolean;
  providers: string[];
}

export function getAuthMethods(): Promise<AuthMethods> {
  return apiFetch("/api/v1/auth/methods");
}

/** Links the Microsoft identity behind `credential` to the signed-in account; an account with a password
 *  must confirm it. */
export async function linkMicrosoft(credential: string, currentPassword?: string): Promise<void> {
  const body: Record<string, string> = { credential };
  if (currentPassword) body.current_password = currentPassword;
  await apiFetch("/api/v1/users/me/link/microsoft", { method: "POST", body: JSON.stringify(body) });
}

/** One active user without a Microsoft link (GET /users/sso-readiness, superusers; ADR-031). */
export interface SsoReadinessEntry {
  id: number;
  email: string;
  full_name: string | null;
  is_superuser: boolean;
  /** Set while a one-time link allowance is valid */
  link_allowed_until: string | null;
}

export interface SsoReadiness {
  active_users: number;
  linked: number;
  unlinked: SsoReadinessEntry[];
}

export function getSsoReadiness(): Promise<SsoReadiness> {
  return apiFetch("/api/v1/users/sso-readiness");
}

/** Lets that account link Microsoft at its next Microsoft sign-in, for 7 days. */
export function allowMicrosoftLink(userId: number): Promise<SsoReadinessEntry> {
  return apiFetch(`/api/v1/users/${userId}/allow-microsoft-link`, { method: "POST", body: "{}" });
}
