import { afterEach, describe, expect, it, vi } from "vitest";
import { runtimeConfig } from "./runtime";

declare global {
  interface Window {
    __QEOS_CONFIG__?: Record<string, string | undefined>;
  }
}

afterEach(() => {
  delete window.__QEOS_CONFIG__;
  vi.unstubAllEnvs();
});

describe("runtimeConfig", () => {
  it("prefers the window config over the build-time values", () => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "build-google");
    vi.stubEnv("VITE_MSAL_CLIENT_ID", "build-msal");
    vi.stubEnv("VITE_MSAL_AUTHORITY", "https://build.example/authority");
    window.__QEOS_CONFIG__ = {
      GOOGLE_CLIENT_ID: "run-google",
      MSAL_CLIENT_ID: "run-msal",
      MSAL_AUTHORITY: "https://run.example/authority",
    };
    expect(runtimeConfig()).toEqual({
      googleClientId: "run-google",
      msalClientId: "run-msal",
      msalAuthority: "https://run.example/authority",
    });
  });

  it("falls back to the build-time value for an empty or missing key", () => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "build-google");
    vi.stubEnv("VITE_MSAL_CLIENT_ID", "build-msal");
    window.__QEOS_CONFIG__ = { GOOGLE_CLIENT_ID: "", MSAL_AUTHORITY: "https://run.example/authority" };
    expect(runtimeConfig()).toEqual({
      googleClientId: "build-google",
      msalClientId: "build-msal",
      msalAuthority: "https://run.example/authority",
    });
  });

  it("uses the build-time values when there is no window config at all", () => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "build-google");
    vi.stubEnv("VITE_MSAL_CLIENT_ID", "build-msal");
    vi.stubEnv("VITE_MSAL_AUTHORITY", "https://build.example/authority");
    expect(runtimeConfig()).toEqual({
      googleClientId: "build-google",
      msalClientId: "build-msal",
      msalAuthority: "https://build.example/authority",
    });
  });

  it("defaults to no client ids and the organizations authority", () => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "");
    vi.stubEnv("VITE_MSAL_CLIENT_ID", "");
    vi.stubEnv("VITE_MSAL_AUTHORITY", "");
    expect(runtimeConfig()).toEqual({
      googleClientId: "",
      msalClientId: "",
      msalAuthority: "https://login.microsoftonline.com/organizations",
    });
  });
});
