import { expect, test } from "vitest";
import { ApiError } from "../api/http";
import { SsoError, isSsoCancelled, ssoFailure } from "./ssoErrors";

const msal = (errorCode: string) => Object.assign(new Error(errorCode), { errorCode });

test("closing the Microsoft window, or opening a second one, is a cancellation", () => {
  expect(isSsoCancelled(msal("user_cancelled"))).toBe(true);
  expect(isSsoCancelled(msal("interaction_in_progress"))).toBe(true);
  expect(isSsoCancelled(msal("login_required"))).toBe(false);
  expect(isSsoCancelled(new Error("boom"))).toBe(false);
  expect(isSsoCancelled(null)).toBe(false);
});

test("an MSAL failure becomes a sentence with its code and the way back", () => {
  const got = ssoFailure(msal("popup_window_error"), true);
  expect(got).toBeInstanceOf(SsoError);
  expect((got as SsoError).message).toBe("Microsoft sign-in failed (popup_window_error). Try again, or sign in with your password.");
  expect((got as SsoError).code).toBe("popup_window_error");
  expect((ssoFailure(msal("popup_window_error"), false) as SsoError).message).toBe("Microsoft sign-in failed (popup_window_error). Try again.");
});

test("an error from QEOS's own API, or any other error, passes through unchanged", () => {
  const api = new ApiError(403, "Tenant not allowed");
  expect(ssoFailure(api, true)).toBe(api);
  const plain = new Error("no token");
  expect(ssoFailure(plain, true)).toBe(plain);
});
