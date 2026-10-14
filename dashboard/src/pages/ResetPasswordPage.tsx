import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, CircleCheck } from "lucide-react";
import { resetPassword } from "../api/auth";
import { ApiError } from "../api/http";
import SsoOnlyNotice from "../components/SsoOnlyNotice";
import { isSsoOnly, isSsoOnlyError, ssoOnlyNames, useAuthMethods } from "../auth/useAuthMethods";
import AuthShell from "../components/AuthShell";
import ErrorBanner from "../components/ErrorBanner";
import NewPasswordFields from "../components/NewPasswordFields";

export default function ResetPasswordPage() {
  const [params, setParams] = useSearchParams();
  // Read once, then dropped from the address bar so it does not linger in
  // history or get copied along with the URL
  const [token] = useState(() => params.get("token"));
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (params.has("token")) setParams({}, { replace: true });
  }, [params, setParams]);
  const methods = useAuthMethods();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setMismatch(true);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await resetPassword(token!, password);
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (isSsoOnly(methods) || isSsoOnlyError(error)) return <SsoOnlyNotice providers={methods?.providers} names={ssoOnlyNames(error)} />;

  if (!token) {
    return (
      <AuthShell title="Reset link incomplete" subtitle={false}>
        <div className="card">
          <p>This reset link is incomplete — it carries no token. Use the full link from the email.</p>
          <Link to="/forgot-password">Request a new link</Link>
        </div>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell title="Password changed" subtitle={false}>
        <div className="card">
          <p className="success-note" role="status">
            <CircleCheck size={18} aria-hidden="true" />
            <span>Your password has been changed. Every device that was signed in has been signed out.</span>
          </p>
          <Link className="link-arrow" to="/login">
            Sign in with the new password <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
      </AuthShell>
    );
  }

  // Retrying cannot revive a used or expired link: offer only the way out
  if (error instanceof ApiError && error.status === 400) {
    return (
      <AuthShell title="This link no longer works" subtitle={false}>
        <div className="card">
          <ErrorBanner error={error} />
          <p className="muted">Reset links work once and expire after 30 minutes. Your password has not changed.</p>
          <Link className="link-arrow" to="/forgot-password">
            Request a new link <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Choose a new password" subtitle={false}>
      <form className="card" onSubmit={onSubmit}>
        {error != null && <ErrorBanner error={error} />}
        <NewPasswordFields
          password={password}
          confirm={confirm}
          onPassword={setPassword}
          onConfirm={(value) => {
            setConfirm(value);
            setMismatch(false);
          }}
          mismatch={mismatch}
        />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Set new password"}
        </button>
      </form>
    </AuthShell>
  );
}
