import { useState } from "react";
import { Download, ExternalLink } from "lucide-react";
import { createArtifactLink, downloadArtifact, listResultArtifacts, traceViewerUrl } from "../api/artifacts";
import { downloadBlob } from "../lib/csv";

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

type Status = "" | "Opening trace…" | "Trace opened in a new tab" | "Downloading trace…" | "Trace downloaded";

/**
 * A result's Playwright traces (ADR-037): "Trace" opens the first one in the self-hosted trace viewer in a new tab,
 * the download button saves each as trace-<id>.zip. Nothing is requested until a button is pressed.
 */
export default function TraceButton({ projectId, runId, resultId, name, count, showNote }: Props) {
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<Status>("");
  if ((count ?? 0) <= 0) return null;

  async function firstTrace(): Promise<number | undefined> {
    const { artifacts } = await listResultArtifacts(projectId, runId, resultId);
    return artifacts.find((a) => a.kind === "trace")?.id;
  }

  /**
   * The tab opens blank inside the click, so no pop-up blocker stops it after the awaits below (Safari blocks a
   * window.open that follows an await). It loses its opener (as noopener would) before it is sent to the viewer.
   */
  function open() {
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
        const id = await firstTrace();
        if (id === undefined) throw new Error("no trace");
        // The link lasts 60 s: ask for it last, just before the viewer reads it
        const { url } = await createArtifactLink(projectId, id);
        tab.location.href = traceViewerUrl(url);
        setStatus("Trace opened in a new tab");
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
    setStatus("Downloading trace…");
    try {
      const { artifacts } = await listResultArtifacts(projectId, runId, resultId);
      for (const a of artifacts.filter((x) => x.kind === "trace")) {
        downloadBlob(`trace-${a.id}.zip`, await downloadArtifact(projectId, a.id));
      }
      setStatus("Trace downloaded");
    } catch {
      setStatus("");
      setError("The trace could not be downloaded. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="shot-button trace-button" aria-label={`Open trace for ${name}`} aria-busy={opening}
        onClick={() => { if (!opening) open(); }}>
        <ExternalLink size={14} aria-hidden="true" />
        <span>{opening ? "Opening…" : "Trace"}</span>
      </button>
      <button type="button" className="shot-button trace-button" aria-label={`Download trace for ${name}`} title="Download trace"
        aria-busy={busy} onClick={() => { if (!busy) void download(); }}>
        <Download size={14} aria-hidden="true" />
        {busy && <span>Downloading…</span>}
      </button>
      {showNote && <span className="muted trace-note">{TRACE_NOTE}</span>}
      <span role="status" className="sr-only">{status}</span>
      {error && <span role="alert" className="trace-error">{error}</span>}
    </>
  );
}
