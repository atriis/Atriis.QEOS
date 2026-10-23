import { useState } from "react";
import { Download, ExternalLink } from "lucide-react";
import { createArtifactLink, downloadArtifact, listResultArtifacts, traceViewerUrl } from "../api/artifacts";
import { downloadBlob } from "../lib/csv";
import { canRunTraceViewer } from "../lib/traceViewer";

interface Props {
  projectId: number;
  runId: number;
  resultId: number;
  /** The test's or case's name, for the accessible name. */
  name: string;
  /** Traces of the result; nothing shows for 0 or absent (an older server). */
  count?: number;
  /** The "open it with" note, for a page that has no note of its own. */
  showNote?: boolean;
}

export const TRACE_NOTE = "A downloaded trace opens with npx playwright show-trace";

// Browsers may hold back a page's second automatic download; a pause between files and a note make that visible
const SAVE_GAP_MS = 400;
const SEVERAL_NOTE = "If the browser blocked any, allow this site to download several files.";

const VIEWER_BLOCKED = "This browser cannot run the trace viewer for this site, usually because it does not trust the "
  + "site's certificate. Download the trace instead, or ask an administrator for a trusted certificate.";

type Status = "" | "Opening trace…" | `Trace${string} opened in a new tab` | "Downloading trace…" | "Trace downloaded"
  | `${number} traces downloaded`;

/**
 * A result's Playwright traces (ADR-037): "Trace" opens it in the self-hosted trace viewer in a new tab (several get
 * one numbered button each, as the viewer shows one trace per tab),
 * the download button saves each as trace-<id>.zip. Nothing is requested until a button is pressed. While one works
 * the other is disabled, so their status and error lines cannot cross.
 */
export default function TraceButton({ projectId, runId, resultId, name, count, showNote }: Props) {
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<Status>("");
  const [savedSeveral, setSavedSeveral] = useState(false);
  const total = count ?? 0;
  if (total <= 0) return null;
  // The viewer opens one trace per tab: several traces get one numbered button each
  const several = total > 1;

  /** The id of the result's trace at `index` (0-based, in the result's order), undefined when it is gone. */
  async function nthTrace(index: number): Promise<number | undefined> {
    const { artifacts } = await listResultArtifacts(projectId, runId, resultId);
    return artifacts.filter((a) => a.kind === "trace")[index]?.id;
  }

  /**
   * The tab opens blank inside the click, so no pop-up blocker stops it after the awaits below (Safari blocks a
   * window.open that follows an await). It loses its opener (as noopener would) before it is sent to the viewer.
   */
  function open(index: number) {
    setError("");
    const tab = window.open("", "_blank");
    if (!tab) {
      setStatus("");
      setError("Allow pop-ups for this site to open the trace.");
      return;
    }
    tab.opener = null;
    setOpening(true);
    setStatus("Opening trace…");
    void (async () => {
      try {
        if (!(await canRunTraceViewer())) {
          tab.close();
          setStatus("");
          setError(VIEWER_BLOCKED);
          return;
        }
        const id = await nthTrace(index);
        if (id === undefined) throw new Error("no trace");
        // The link lasts 60 s: ask for it last, just before the viewer reads it
        const { url } = await createArtifactLink(projectId, id);
        tab.location.href = traceViewerUrl(url);
        setStatus(several ? `Trace ${index + 1} opened in a new tab` : "Trace opened in a new tab");
      } catch {
        tab.close();
        setStatus("");
        setError("The trace could not be opened. Try again.");
      } finally {
        setOpening(false);
      }
    })();
  }

  async function download() {
    setBusy(true);
    setError("");
    setSavedSeveral(false);
    setStatus("Downloading trace…");
    try {
      const { artifacts } = await listResultArtifacts(projectId, runId, resultId);
      const traces = artifacts.filter((x) => x.kind === "trace");
      for (const [i, a] of traces.entries()) {
        if (i > 0) await new Promise((r) => setTimeout(r, SAVE_GAP_MS));
        downloadBlob(`trace-${a.id}.zip`, await downloadArtifact(projectId, a.id));
      }
      setStatus(traces.length > 1 ? `${traces.length} traces downloaded` : "Trace downloaded");
      setSavedSeveral(traces.length > 1);
    } catch {
      setStatus("");
      setError("The trace could not be downloaded. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {several ? (
        <span role="group" aria-label={`Traces for ${name}`} className="trace-group">
          <span className="trace-group-label" aria-hidden="true">
            <ExternalLink size={14} aria-hidden="true" />{opening ? "Opening…" : "Traces"}
          </span>
          {Array.from({ length: total }, (_, i) => (
            <button key={i} type="button" className="shot-button trace-button trace-number"
              aria-label={`Open trace ${i + 1} of ${total} for ${name} in a new tab`}
              aria-busy={opening} disabled={busy} onClick={() => { if (!opening) open(i); }}>
              {i + 1}
            </button>
          ))}
        </span>
      ) : (
        <button type="button" className="shot-button trace-button" aria-label={`Open trace for ${name} in a new tab`}
          aria-busy={opening} disabled={busy} onClick={() => { if (!opening) open(0); }}>
          <ExternalLink size={14} aria-hidden="true" />
          <span>{opening ? "Opening…" : "Trace"}</span>
        </button>
      )}
      <button type="button" className="shot-button trace-button"
        aria-label={`Download ${several ? "traces" : "trace"} for ${name}`} title={several ? "Download traces" : "Download trace"}
        aria-busy={busy} disabled={opening} onClick={() => { if (!busy) void download(); }}>
        <Download size={14} aria-hidden="true" />
        {busy && <span>Downloading…</span>}
      </button>
      {showNote && <span className="muted trace-note">{TRACE_NOTE}</span>}
      {savedSeveral && <span className="muted trace-note">{SEVERAL_NOTE}</span>}
      <span role="status" className="sr-only">{status}</span>
      {error && <span role="alert" className="trace-error">{error}</span>}
    </>
  );
}
