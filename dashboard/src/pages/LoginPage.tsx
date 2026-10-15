import { FormEvent, useEffect, useEffectEvent, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { login, mfaVerify, ssoLogin } from "../api/auth";
import {
  getMicrosoftCredential,
  googleEnabled,
  initGoogleButton,
  microsoftEnabled,
} from "../auth/ssoProviders";
import { isSsoOnly, ssoOnlyLine, useAuthMethods } from "../auth/useAuthMethods";
import { isSsoCancelled, ssoFailure } from "../auth/ssoErrors";
import { safeNext, withNext } from "../auth/redirect";
import AuthShell from "../components/AuthShell";
import ErrorBanner from "../components/ErrorBanner";
import MicrosoftButton from "../components/MicrosoftButton";
import TextField from "../components/TextField";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Back to the page the user asked for (validated: same-origin paths only), else the front page
  const next = safeNext(params.get("next")) ?? "/";
  const expired = params.get("reason") === "expired";
  const methods = useAuthMethods();
  const ssoOnly = isSsoOnly(methods);
  // The Google button renders into whichever slot is mounted: the layout changes once /auth/methods answers
  const [googleSlot, setGoogleSlot] = useState<HTMLDivElement | null>(null);
  // The Google button is created once, on mount: its callback must read where to go when it fires, not at mount
  const nextRef = useRef(next);
  nextRef.current = next;

  async function finishSso(provider: "google" | "microsoft", credential: string) {
    setError(null);
    try {
      await ssoLogin(provider, credential);
      navigate(nextRef.current, { replace: true });
    } catch (err) {
      setError(err);
    }
  }

  // The Google button's callback fires long after mount: it must run the current finishSso, not the mount-time one
  const onGoogleCredential = useEffectEvent((credential: string) => {
    void finishSso("google", credential);
  });

  useEffect(() => {
    if (googleSlot) {
      initGoogleButton(googleSlot, (credential) => onGoogleCredential(credential)).catch((err) => setError(err));
    }
  }, [googleSlot]);

  // The Microsoft window is open: the button waits, so a second click cannot start a second window
  const [ssoBusy, setSsoBusy] = useState(false);

  async function onMicrosoft() {
    setError(null);
    setSsoBusy(true);
    try {
      const credential = await getMicrosoftCredential();
      await finishSso("microsoft", credential);
    } catch (err) {
      // Closing the Microsoft window is not a failure; an MSAL failure names its code and the way back
      if (!isSsoCancelled(err)) setError(ssoFailure(err, !ssoOnly));
    } finally {
      setSsoBusy(false);
    }
  }

  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const challenge = await login(email, password);
      if (challenge) {
        setMfaToken(challenge.mfaToken);
        return;
      }
      navigate(next, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onMfaSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await mfaVerify(mfaToken!, mfaCode.trim());
      navigate(next, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (mfaToken !== null) {
    return (
      <AuthShell title="Two-step verification">
        <form className="card" onSubmit={onMfaSubmit}>
          <p>Enter the code from your authenticator app, or a recovery code.</p>
          <TextField
            label="Authentication code"
            value={mfaCode}
            onChange={setMfaCode}
            autoComplete="one-time-code"
            autoFocus
            required
          />
          {error != null && <ErrorBanner error={error} />}
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Verifying…" : "Verify"}
          </button>
        </form>
      </AuthShell>
    );
  }

  // In SSO-only mode only the providers the mode lists; otherwise every provider this build has a client id for
  const offered = (provider: string) => !ssoOnly || methods!.providers.includes(provider);
  const showGoogle = googleEnabled() && offered("google");
  const showMicrosoft = microsoftEnabled() && offered("microsoft");
  const anySso = showGoogle || showMicrosoft;

  const credentials = (
    <>
      <TextField label="Email" type="email" autoComplete="email" value={email} onChange={setEmail} required />
      <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={setPassword} required />
    </>
  );

  if (ssoOnly) {
    return (
      <AuthShell title="Sign in">
        <div className="card">
          {expired && <p role="status" className="muted">Your session expired, sign in again.</p>}
          <p>{ssoOnlyLine(methods!.providers)}</p>
          {error != null && <ErrorBanner error={error} />}
          {showMicrosoft && <MicrosoftButton primary onClick={onMicrosoft} busy={ssoBusy} />}
          {showGoogle && <div ref={setGoogleSlot} data-testid="google-button" className="sso-google" />}
          {/* Break-glass for superusers (ADR-031): closed by default, not advertised */}
          <details className="more-filters sso-admin">
            <summary>
              <ChevronRight size={14} aria-hidden="true" className="chevron" />
              Administrator sign-in
            </summary>
            <form onSubmit={onSubmit}>
              {credentials}
              <button className="primary" type="submit" disabled={busy}>
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </details>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Sign in">
      <form className="card" onSubmit={onSubmit}>
        {expired && <p role="status" className="muted">Your session expired, sign in again.</p>}
        {credentials}
        {/* Router state, not a query string: an address in the URL ends up in history and access logs */}
        <Link className="field-link" to="/forgot-password" state={{ email }}>
          Forgot password?
        </Link>
        {error != null && <ErrorBanner error={error} />}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {anySso && (
          <>
            {/* A hairline each side of the word, so the two ways in read as alternatives */}
            <p className="auth-divider muted" aria-hidden="true"><span>or</span></p>
            {showGoogle && <div ref={setGoogleSlot} data-testid="google-button" className="sso-google" />}
            {showMicrosoft && <MicrosoftButton onClick={onMicrosoft} busy={ssoBusy} />}
          </>
        )}
        <p className="muted" style={{ marginBottom: 0 }}>
          New here? <Link to={withNext("/register", next)}>Create account</Link>
        </p>
      </form>
    </AuthShell>
  );
}
