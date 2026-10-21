/* Sign-in settings. The container writes /config.js at start (window.__QEOS_CONFIG__, from its environment) so one
   image serves every environment; a missing or empty key falls back to the build-time VITE_* value (compose, dev). */

export interface RuntimeConfig {
  googleClientId: string;
  msalClientId: string;
  msalAuthority: string;
}

declare global {
  interface Window {
    __QEOS_CONFIG__?: Record<string, string | undefined>;
  }
}

const DEFAULT_MSAL_AUTHORITY = "https://login.microsoftonline.com/organizations";

function pick(runtime: string | undefined, build: string | undefined, fallback = ""): string {
  return runtime || build || fallback;
}

export function runtimeConfig(): RuntimeConfig {
  const injected = window.__QEOS_CONFIG__ ?? {};
  return {
    googleClientId: pick(injected.GOOGLE_CLIENT_ID, import.meta.env.VITE_GOOGLE_CLIENT_ID),
    msalClientId: pick(injected.MSAL_CLIENT_ID, import.meta.env.VITE_MSAL_CLIENT_ID),
    msalAuthority: pick(injected.MSAL_AUTHORITY, import.meta.env.VITE_MSAL_AUTHORITY, DEFAULT_MSAL_AUTHORITY),
  };
}
