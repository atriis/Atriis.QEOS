import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { CircleAlert } from "lucide-react";
import PageHeader from "../components/PageHeader";
import ErrorBanner from "../components/ErrorBanner";
import { startGrafanaSession } from "../api/auth";
import { ApiError } from "../api/http";
import { goTo } from "../lib/browser";
import { grafanaPath, markHandoff, rawQueryParam, takeRecentHandoff } from "../lib/grafanaHandoff";

export { grafanaPath };

type State =
  | { kind: "opening" }
  | { kind: "refused"; message: string }
  | { kind: "failed"; error: unknown }
  | { kind: "bounced" };

const OFF_MESSAGE = "Monitoring is not turned on for this QEOS install.";

/** Where the gateway sends a visitor whose Grafana cookie is missing or expired (ADR-027): signed in by
 *  RequireAuth, it hands over the cookie and opens the Grafana page they were going to (`next`, validated by
 *  grafanaPath). A superuser-only refusal is said plainly; any other failure offers Retry. When Grafana sends
 *  the browser straight back after a hand-off, the page asks instead of handing over again, so it never loops. */
export default function MonitoringPage() {
  const { search } = useLocation();
  const next = grafanaPath(rawQueryParam(search, "next"));
  const [state, setState] = useState<State>({ kind: "opening" });
  const started = useRef(false);

  const handOff = useCallback(() => {
    setState({ kind: "opening" });
    startGrafanaSession().then(
      () => {
        markHandoff();
        goTo(next);
      },
      (error: unknown) => {
        if (error instanceof ApiError && error.status === 403) setState({ kind: "refused", message: error.detail });
        else if (error instanceof ApiError && error.status === 404) setState({ kind: "refused", message: OFF_MESSAGE });
        else setState({ kind: "failed", error });
      },
    );
  }, [next]);

  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice; one hand-off is enough
    started.current = true;
    if (takeRecentHandoff()) setState({ kind: "bounced" });
    else handOff();
  }, [handOff]);

  return (
    <div className="page" style={{ maxWidth: 560 }}>
      <PageHeader title="Monitoring" subtitle="Grafana dashboards and alerts for this QEOS install" />
      {state.kind === "opening" && (
        <p className="muted" role="status">Opening Grafana…</p>
      )}
      {state.kind === "refused" && (
        <>
          <p className="note warn-note" role="alert">
            <CircleAlert size={16} aria-hidden="true" />
            <span>{state.message}</span>
          </p>
          <p><Link to="/">Back to projects</Link></p>
        </>
      )}
      {state.kind === "failed" && <ErrorBanner error={state.error} onRetry={handOff} />}
      {state.kind === "bounced" && (
        <>
          <p className="note warn-note" role="alert">
            <CircleAlert size={16} aria-hidden="true" />
            <span>
              Grafana sent you back right after the sign-in was handed over, so QEOS stopped instead of trying
              again on its own. Your account may have changed, or this browser may be blocking the Grafana cookie.
            </span>
          </p>
          <div className="button-row monitoring-actions">
            <button type="button" className="primary" onClick={handOff}>Try again</button>
            <Link to="/">Back to projects</Link>
          </div>
        </>
      )}
    </div>
  );
}
