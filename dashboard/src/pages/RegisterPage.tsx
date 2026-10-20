import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { register } from "../api/auth";
import { rememberAfterVerify, safeNext, withNext } from "../auth/redirect";
import SsoOnlyNotice from "../components/SsoOnlyNotice";
import { isSsoOnly, isSsoOnlyError, ssoOnlyNames, useAuthMethods } from "../auth/useAuthMethods";
import AuthShell from "../components/AuthShell";
import ErrorBanner from "../components/ErrorBanner";
import TextField from "../components/TextField";

export default function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  // A visitor who came from an invitation returns to it after signing in or verifying (same-origin paths only)
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const loginLink = withNext("/login", next);
  const methods = useAuthMethods();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // In the emailed link too: it is often opened in another browser, where this tab's storage is not
      await register(email, password, fullName, next && next !== "/" ? next : null);
      rememberAfterVerify(next);
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (isSsoOnly(methods) || isSsoOnlyError(error)) return <SsoOnlyNotice providers={methods?.providers} names={ssoOnlyNames(error)} />;

  if (done) {
    return (
      <AuthShell title="Check your email">
        <div className="card">
          <p role="status">Check your email to complete registration.</p>
          <p className="muted">
            If no email arrives, this deployment has no mail server configured: ask your
            administrator for the verification link (it appears in the auth service's log).
          </p>
          <Link to={loginLink}>Back to sign in</Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Create account">
      <form className="card" onSubmit={onSubmit}>
        {error != null && <ErrorBanner error={error} />}
        <TextField label="Full name" autoComplete="name" value={fullName} onChange={setFullName} />
        <TextField label="Email" type="email" required autoComplete="email" value={email} onChange={setEmail} />
        <TextField
          label="Password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          hint="At least 8 characters."
          value={password}
          onChange={setPassword}
          validate={(v) => (v.length > 0 && v.length < 8 ? "Use at least 8 characters." : null)}
        />
        <button className="primary" type="submit" disabled={busy}>
          Create account
        </button>
        <p className="muted" style={{ marginBottom: 0 }}>
          Already have an account? <Link to={loginLink}>Sign in</Link>
        </p>
      </form>
    </AuthShell>
  );
}
