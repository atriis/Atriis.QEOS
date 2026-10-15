import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../api/http";
import { getResultLog } from "../api/runs";
import { logFileName, markValues } from "../lib/logValues";
import ErrorBanner from "./ErrorBanner";

/** How long "Copied" stays. */
const NOTE_MS = 2000;

/** A result's whole masked log, on demand (spec 2026-10-15 §2.2): a "Log" button that fetches once when pressed and
 *  opens the text inline with its values marked, a copy button and a download link. A 404 (an older server, a result
 *  that is gone) reads as no log. */
export default function LogPanel({ projectId, runId, resultId, name }: {
  projectId: number; runId: number; resultId: number; name: string;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const id = useId();
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const query = useQuery({
    queryKey: ["result-log", projectId, runId, resultId],
    queryFn: () => getResultLog(projectId, runId, resultId),
    enabled: open,
    staleTime: Infinity,
  });
  const missing = query.error instanceof ApiError && query.error.status === 404;
  const log = query.data?.log ?? null;
  const values = query.data?.values;
  const segments = useMemo(() => (log == null ? [] : markValues(log, values ?? [])), [log, values]);
  const href = useMemo(() => (log == null ? null : URL.createObjectURL(new Blob([log], { type: "text/plain" }))), [log]);
  useEffect(() => () => { if (href) URL.revokeObjectURL(href); }, [href]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(log ?? "");
      setNote("Copied");
    } catch {
      setNote("Could not copy. Select the log and copy it by hand.");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNote(""), NOTE_MS);
  }

  const label = `Log of ${name}`;
  return (
    <div className="log-panel">
      <button type="button" className="log-panel-toggle" aria-expanded={open} aria-controls={id} aria-label={label}
        onClick={() => setOpen((v) => !v)}>
        {open ? "Hide log" : "Log"}
      </button>
      {open && (
        <div id={id} className="log-panel-body" role="region" aria-label={label}>
          {query.isPending && <p className="muted">Loading log…</p>}
          {query.error != null && !missing && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
          {(missing || (query.data != null && log == null)) && <p className="muted">No log for this result.</p>}
          {log != null && (
            <>
              <div className="log-panel-tools">
                <button type="button" onClick={copy}>Copy log</button>
                {href && <a href={href} download={logFileName(name, runId)}>Download</a>}
                <span className="log-values-note" role="status" aria-live="polite">{note}</span>
              </div>
              <pre className="log-full">
                {segments.map((s, i) => (s.name ? <mark key={i} title={s.name}>{s.text}</mark> : s.text))}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
