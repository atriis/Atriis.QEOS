import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { verifyEmail } from "../api/auth";
import { safeNext, takeAfterVerify } from "../auth/redirect";
import SsoOnlyNotice from "../components/SsoOnlyNotice";
import { isSsoOnly, isSsoOnlyError, useAuthMethods } from "../auth/useAuthMethods";
import AuthShell from "../components/AuthShell";
import ErrorBanner from "../components/ErrorBanner";

export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const nextParam = params.get("next");
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [error, setError] = useState<unknown>(null);
  // The token is single-use: StrictMode's mount-unmount-mount must reuse the
  // one in-flight request, or the second call burns the token and reports a
  // verified person as failed
  // Where to land after verifying: set once in the effect below, kept across re-renders
  const landing = useRef<string | null>(null);
  const inFlight = useRef<{ token: string; promise: Promise<void> } | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    if (inFlight.current?.token !== token) {
      inFlight.current = { token, promise: verifyEmail(token) };
    }
    inFlight.current.promise
      .then(() => {
        if (cancelled) return;
        // Taking the remembered page empties it, so it is read here, once, when the token is accepted: never during render
        landing.current ??= safeNext(nextParam) ?? takeAfterVerify() ?? "/";
        setState("done");
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err);
          setState("failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, nextParam]);
  const methods = useAuthMethods();

  if (isSsoOnly(methods) || isSsoOnlyError(error)) return <SsoOnlyNotice providers={methods?.providers} />;

  if (!token) {
    return (
      <AuthShell title="Verification link incomplete" subtitle={false}>
        <div className="card">
          <p>This verification link is incomplete — it carries no token. Use the full link from the email.</p>
          <Link to="/register">Register</Link>
        </div>
      </AuthShell>
    );
  }
  if (state === "done") return <Navigate to={landing.current ?? "/"} replace />;

  return (
    <AuthShell title={state === "failed" ? "Verification failed" : "Verifying your email"} subtitle={false}>
      <div className="card">
        {state === "working" && <p className="muted">Verifying your email…</p>}
        {state === "failed" && (
          <>
            {error != null && <ErrorBanner error={error} />}
            <p className="muted">
              Verification links expire and work only once. Register again to get a fresh one.
            </p>
            <Link to="/register">Register</Link>
          </>
        )}
      </div>
    </AuthShell>
  );
}
