import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import QRCode from "qrcode";
import { CircleCheck, CircleSlash } from "lucide-react";
import {
  allowMicrosoftLink, changePassword, getMe, getSsoReadiness, linkMicrosoft, mfaConfirm, mfaDisable, mfaEnroll,
  type Me, type SsoReadiness,
} from "../api/auth";
import { getMicrosoftCredential, microsoftEnabled } from "../auth/ssoProviders";
import { downloadCsv } from "../lib/csv";
import ErrorBanner from "../components/ErrorBanner";
import NewPasswordFields from "../components/NewPasswordFields";
import SecretBlock from "../components/SecretBlock";
import TextField from "../components/TextField";
import PageHeader from "../components/PageHeader";

type Step = "idle" | "enrolling" | "enrolled" | "disabling";
/** From GET /users/me; "unknown" until it answers (or if it cannot) */
type Known = "unknown" | "on" | "off";

function ChangePasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [changed, setChanged] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setChanged(false);
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setChanged(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form-stack" onSubmit={onSubmit}>
      <h3>Password</h3>
      <p className="muted">
        Changing it signs out every other device. Accounts that sign in with Google or
        Microsoft manage their password with that provider.
      </p>
      {error != null && <ErrorBanner error={error} />}
      {changed && (
        <p className="success-note" role="status">
          <CircleCheck size={18} aria-hidden="true" />
          <span>Password changed. Other devices have been signed out.</span>
        </p>
      )}
      <TextField
        label="Current password"
        type="password"
        required
        autoComplete="current-password"
        value={current}
        onChange={setCurrent}
      />
      <NewPasswordFields
        password={next}
        confirm={confirm}
        onPassword={setNext}
        onConfirm={(value) => {
          setConfirm(value);
          setMismatch(false);
        }}
        mismatch={mismatch}
      />
      <div>
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Changing…" : "Change password"}
        </button>
      </div>
    </form>
  );
}

/** Link a Microsoft work account (ADR-031). Every user in SSO-only mode; otherwise only when this build has
 *  Microsoft sign-in. */
function MicrosoftAccountCard({ me, onLinked }: { me: Me; onLinked: () => void }) {
  const linked = me.linked_providers?.includes("microsoft") ?? false;
  const needsPassword = me.has_password === true;
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const credential = await getMicrosoftCredential();
      await linkMicrosoft(credential, needsPassword ? password : undefined);
      setPassword("");
      setDone(true);
      onLinked();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form-stack" onSubmit={onSubmit}>
      <h3>Microsoft account</h3>
      {done && (
        <p className="success-note" role="status">
          <CircleCheck size={18} aria-hidden="true" />
          <span>Microsoft account linked. You can sign in with Microsoft from now on.</span>
        </p>
      )}
      {linked ? (
        <p className="mfa-status">
          <CircleCheck size={16} aria-hidden="true" /> <strong>Linked to Microsoft</strong>
        </p>
      ) : (
        <>
          <p className="muted">
            {me.sso_only ? "Sign-in here is through Microsoft. " : ""}
            Link your Microsoft work account to sign in with it.
          </p>
          {error != null && <ErrorBanner error={error} />}
          {/* Without Microsoft sign-in in this build the link cannot be submitted: no field asks for a password */}
          {microsoftEnabled() ? (
            <>
              {needsPassword && (
                <TextField label="Your QEOS password" type="password" required autoComplete="current-password"
                  value={password} onChange={setPassword} />
              )}
              <div>
                <button className="primary" type="submit" disabled={busy}>
                  {busy ? "Linking…" : "Link Microsoft account"}
                </button>
              </div>
            </>
          ) : (
            <p className="muted">This build has no Microsoft sign-in configured. Ask your administrator.</p>
          )}
        </>
      )}
    </form>
  );
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Superusers only (ADR-031): whether the mode is on and how to change it (never from here, so a stolen
 *  session cannot switch it), who has linked Microsoft, and the one-time link allowance. */
function SsoOnlyAdminCard({ ssoOnly }: { ssoOnly: boolean }) {
  const [readiness, setReadiness] = useState<SsoReadiness | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [allowing, setAllowing] = useState<number | null>(null);

  useEffect(() => {
    getSsoReadiness().then(setReadiness).catch((err) => setError(err));
  }, []);

  async function onAllow(userId: number) {
    setError(null);
    setAllowing(userId);
    try {
      const entry = await allowMicrosoftLink(userId);
      setReadiness((current) => current && {
        ...current,
        unlinked: current.unlinked.map((user) => (user.id === userId ? entry : user)),
      });
    } catch (err) {
      setError(err);
      // The row may be stale (already linked, gone): refresh so no Allow button keeps failing the same way
      await getSsoReadiness().then(setReadiness).catch(() => undefined);
    } finally {
      setAllowing(null);
    }
  }

  return (
    <section className="card" aria-labelledby="sso-only-heading">
      <h3 id="sso-only-heading">Microsoft-only sign-in</h3>
      <p className="mfa-status" role="status">
        {ssoOnly
          ? <><CircleCheck size={16} aria-hidden="true" /> <strong>Microsoft-only sign-in: On</strong></>
          : <><CircleSlash size={16} aria-hidden="true" /> <strong>Microsoft-only sign-in: Off</strong></>}
      </p>
      <p className="muted">
        {ssoOnly ? (
          <>Only superusers can still sign in with a password. To turn it off, set <code>AUTH_SSO_ONLY=false</code> in <code>.env</code> and restart auth-service.</>
        ) : (
          <>Link everyone first. Then set <code>AUTH_SSO_ONLY=true</code> in <code>.env</code> and restart auth-service: everyone who is not a superuser is signed out once.</>
        )}
      </p>
      {error != null && <ErrorBanner error={error} />}
      {readiness && (
        <>
          <p>{`${readiness.linked} of ${readiness.active_users} active users have linked Microsoft.`}</p>
          {readiness.unlinked.length > 0 && (
            <table className="data">
              <caption className="sr-only">Active users who have not linked Microsoft</caption>
              <thead>
                <tr>
                  <th scope="col">User</th>
                  <th scope="col">Next sign-in</th>
                </tr>
              </thead>
              <tbody>
                {readiness.unlinked.map((user) => (
                  <tr key={user.id}>
                    <td>
                      {user.full_name && <>{user.full_name}<br /></>}
                      <span className={user.full_name ? "muted" : undefined}>{user.email}</span>
                      {user.is_superuser && <span className="muted"> · superuser</span>}
                    </td>
                    <td>
                      {user.link_allowed_until ? (
                        `Allowed until ${formatDay(user.link_allowed_until)}`
                      ) : (
                        <button type="button" onClick={() => void onAllow(user.id)} disabled={allowing !== null}
                          aria-label={`Allow link at next sign-in for ${user.email}`}>
                          Allow link at next sign-in
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

export default function SecurityPage() {
  const [step, setStep] = useState<Step>("idle");
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [known, setKnown] = useState<Known>("unknown");
  const [me, setMe] = useState<Me | null>(null);
  const [meFailed, setMeFailed] = useState(false);
  const loadStatus = () =>
    getMe().then((account) => {
      setMe(account);
      setMeFailed(false);
      setKnown(account.mfa_enabled ? "on" : "off");
    }).catch(() => {
      // The line stays "unknown" rather than guessing
      setMeFailed(true);
    });
  useEffect(() => {
    void loadStatus();
  }, []);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Leaving a step by Cancel puts focus back on the button that opened it
  const setupRef = useRef<HTMLButtonElement>(null);
  const disableRef = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<"setup" | "disable" | null>(null);
  useEffect(() => {
    if (step !== "idle" || !returnTo.current) return;
    (returnTo.current === "setup" ? setupRef : disableRef).current?.focus();
    returnTo.current = null;
  }, [step]);

  function cancel() {
    returnTo.current = step === "disabling" ? "disable" : "setup";
    setError(null);
    setCode("");
    setSecret("");
    setUri("");
    setStep("idle");
  }

  useEffect(() => {
    if (uri && canvasRef.current) {
      QRCode.toCanvas(canvasRef.current, uri, { width: 192 }).catch(() => {
        // The secret below covers manual entry when the QR cannot render.
      });
    }
  }, [uri]);

  async function onStart() {
    setError(null);
    setBusy(true);
    try {
      const enrollment = await mfaEnroll();
      setSecret(enrollment.secret);
      setUri(enrollment.otpauth_uri);
      setStep("enrolling");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await mfaConfirm(code.trim());
      setRecovery(result.recovery_codes);
      setKnown("on");
      void loadStatus();
      setStep("enrolled");
      setCode("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onDisable(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await mfaDisable(code.trim());
      setKnown("off");
      void loadStatus();
      setStep("idle");
      setSecret("");
      setUri("");
      setCode("");
      setRecovery(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 560 }}>
      <PageHeader title="Security" actions={<Link to="/">Back to projects</Link>} />
      <h2 className="sr-only">Sign-in settings</h2>
      {me !== null && (me.sso_only === true || microsoftEnabled()) && (
        <MicrosoftAccountCard me={me} onLinked={() => void loadStatus()} />
      )}
      {/* SSO-only mode: only superusers keep a password (ADR-031). Hidden while the account loads, so a
          non-superuser never sees it flash. If the account cannot be loaded it is shown, as before the mode
          existed: the server still refuses a non-superuser in the mode, and the card shows that refusal. */}
      {(me !== null ? !(me.sso_only === true && me.is_superuser !== true) : meFailed) && <ChangePasswordCard />}
      <div className="card">
        <h3>Two-factor authentication (TOTP)</h3>
        {error != null && <ErrorBanner error={error} />}

        <p className="mfa-status" role="status">
          {known === "on" && <><CircleCheck size={16} aria-hidden="true" /> <strong>Two-factor authentication: On</strong></>}
          {known === "off" && <><CircleSlash size={16} aria-hidden="true" /> <strong>Two-factor authentication: Off</strong></>}
          {known === "unknown" && <span className="muted">Checking two-factor status…</span>}
        </p>

        {step === "idle" && (
          <>
            <p className="muted">
              Adds an authenticator-app code to your password sign-in. SSO
              sign-ins keep their provider's own MFA.
            </p>
            <div className="button-row">
              <button className="primary" ref={setupRef} onClick={onStart} disabled={busy}>
                Set up two-factor authentication
              </button>
              <button ref={disableRef} onClick={() => setStep("disabling")}>
                Disable two-factor authentication
              </button>
            </div>
          </>
        )}

        {step === "enrolling" && (
          <form onSubmit={onConfirm} className="form-stack">
            <p>Scan the QR code with your authenticator app, or enter the secret manually:</p>
            <canvas ref={canvasRef} />
            <p>
              <code>{secret}</code>
            </p>
            <TextField
              label="Code from the app"
              value={code}
              onChange={setCode}
              autoComplete="one-time-code"
              inputMode="numeric"
              required
            />
            <div className="button-row">
              <button className="primary" type="submit" disabled={busy}>
                Confirm code
              </button>
              <button type="button" onClick={cancel} disabled={busy}>Cancel</button>
            </div>
          </form>
        )}

        {step === "enrolled" && recovery && (
          <>
            <p>
              Two-factor authentication is on. These recovery codes are shown
              only once — store them somewhere safe. Each works a single time
              if you lose the authenticator.
            </p>
            <SecretBlock label="Recovery codes" value={recovery.join("\n")} copyLabel="Copy recovery codes" copyText="Copy codes"
              note="Copy them now: this list cannot be shown again."
              display={(
                <ul>
                  {recovery.map((c) => (
                    <li key={c}>
                      <code>{c}</code>
                    </li>
                  ))}
                </ul>
              )} />
            <div className="button-row">
              <button onClick={() => downloadCsv("qeos-recovery-codes.txt", recovery.join("\n"))}>
                Download codes
              </button>
              <button className="primary" onClick={() => { setRecovery(null); returnTo.current = "setup"; setStep("idle"); }}>
                I saved these codes
              </button>
            </div>
          </>
        )}

        {step === "disabling" && (
          <form onSubmit={onDisable} className="form-stack">
            <p>
              Disabling removes the authenticator-app code from your sign-in. Enter a current code, or a recovery code, to confirm.
            </p>
            <TextField
              label="Current code (or a recovery code)"
              value={code}
              onChange={setCode}
              autoComplete="one-time-code"
              required
            />
            <div className="button-row">
              <button className="danger" type="submit" disabled={busy}>
                Disable two-factor authentication
              </button>
              <button type="button" onClick={cancel} disabled={busy}>Cancel</button>
            </div>
          </form>
        )}
      </div>
      {me?.is_superuser === true && <SsoOnlyAdminCard ssoOnly={me.sso_only === true} />}
    </div>
  );
}
