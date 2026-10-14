import { FormEvent, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { MailCheck } from "lucide-react";
import { requestPasswordReset } from "../api/auth";
import SsoOnlyNotice from "../components/SsoOnlyNotice";
import { isSsoOnly, isSsoOnlyError, useAuthMethods } from "../auth/useAuthMethods";
import AuthShell from "../components/AuthShell";
import TextField from "../components/TextField";
import ErrorBanner from "../components/ErrorBanner";

export default function ForgotPasswordPage() {
  const { state } = useLocation();
  const [email, setEmail] = useState(() => (state as { email?: string } | null)?.email ?? "");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const methods = useAuthMethods();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await requestPasswordReset(email.trim());
      setSentTo(email.trim());
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (isSsoOnly(methods) || isSsoOnlyError(error)) return <SsoOnlyNotice providers={methods?.providers} />;

  if (sentTo !== null) {
    return (
      <AuthShell title="Check your email" subtitle={false}>
        <div className="card">
          <p className="success-note" role="status">
            <MailCheck size={18} aria-hidden="true" />
            <span>
              If <strong>{sentTo}</strong> has a QEOS password, a reset link is on its way.
              It works once and expires in 30 minutes.
            </span>
          </p>
          <p className="muted">
            If no email arrives, this deployment has no mail server configured: ask your
            administrator for the reset link (it appears in the auth service's log). Accounts
            that sign in with Google or Microsoft have no password here to reset.
          </p>
          <Link to="/login">Back to sign in</Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Reset your password" subtitle={false}>
      <form className="card" onSubmit={onSubmit}>
        <p className="muted">Enter the email you sign in with and we'll send you a link to choose a new password.</p>
        {error != null && <ErrorBanner error={error} />}
        <TextField label="Email" type="email" required autoComplete="email" autoFocus value={email} onChange={setEmail} />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Sending…" : "Send reset link"}
        </button>
        <p className="muted" style={{ marginBottom: 0 }}>
          <Link to="/login">Back to sign in</Link>
        </p>
      </form>
    </AuthShell>
  );
}
