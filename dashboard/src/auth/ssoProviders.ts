/* Thin wrappers around the provider SDKs so pages can be tested at this
   boundary. A provider without a configured client id is simply disabled;
   the backend would answer 503 for it anyway. */

import { runtimeConfig } from "../config/runtime";

export function googleEnabled(): boolean {
  return runtimeConfig().googleClientId !== "";
}

export function microsoftEnabled(): boolean {
  return runtimeConfig().msalClientId !== "";
}

interface GoogleAccountsId {
  initialize(config: { client_id: string; callback: (r: { credential: string }) => void }): void;
  renderButton(parent: HTMLElement, options: Record<string, unknown>): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleAccountsId } };
  }
}

let gisLoading: Promise<GoogleAccountsId> | null = null;

function loadGis(): Promise<GoogleAccountsId> {
  gisLoading ??= new Promise((resolve, reject) => {
    if (window.google?.accounts.id) return resolve(window.google.accounts.id);
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      const id = window.google?.accounts.id;
      if (id) resolve(id);
      else reject(new Error("Google Identity Services failed to initialize"));
    };
    script.onerror = () => reject(new Error("Could not load Google Identity Services"));
    document.head.appendChild(script);
  });
  return gisLoading;
}

/** Mounts the official Google button; policy requires their rendered button
    for ID-token sign-in. The callback receives the ID token (credential). */
export async function initGoogleButton(
  container: HTMLElement,
  onCredential: (credential: string) => void,
): Promise<void> {
  const gis = await loadGis();
  gis.initialize({
    client_id: runtimeConfig().googleClientId,
    callback: (response) => onCredential(response.credential),
  });
  // Google draws the button at a fixed pixel width (200-400): the card's, so it does not overflow a phone
  const width = Math.min(400, Math.max(200, container.clientWidth || 320));
  gis.renderButton(container, { theme: "outline", size: "large", width });
}

/** Opens the MSAL popup and resolves with the Entra ID token. MSAL is
    lazy-imported so the login page does not carry it until used. */
export async function getMicrosoftCredential(): Promise<string> {
  const { PublicClientApplication } = await import("@azure/msal-browser");
  const { msalClientId, msalAuthority } = runtimeConfig();
  const app = new PublicClientApplication({
    auth: {
      clientId: msalClientId,
      authority: msalAuthority,
      redirectUri: window.location.origin,
    },
  });
  await app.initialize();
  const result = await app.loginPopup({ scopes: ["openid", "profile", "email"] });
  if (!result.idToken) throw new Error("Microsoft sign-in returned no ID token");
  return result.idToken;
}
