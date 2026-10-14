import { Link } from "react-router-dom";
import AuthShell from "./AuthShell";
import { providerNames } from "../auth/useAuthMethods";

/** What Register, Forgot password, Reset password and Verify email show in SSO-only mode (ADR-031),
 *  for bookmarks and old emails: no form, the way to sign in. */
export default function SsoOnlyNotice({ providers, names: named }: { providers?: readonly string[]; names?: string }) {
  // /auth/methods first, then what the server's 403 said, Microsoft only when neither is known
  const names = providers ? providerNames(providers) : (named ?? "Microsoft");
  return (
    <AuthShell title={`Sign in with ${names}`} subtitle={false}>
      <div className="card">
        <p role="status">{`Sign-in is through ${names} only.`}</p>
        <Link to="/login">Go to sign in</Link>
      </div>
    </AuthShell>
  );
}
