import { useState } from "react";
import { Download } from "lucide-react";
import { downloadArtifact, listResultArtifacts } from "../api/artifacts";
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

export const TRACE_NOTE = "Open it with npx playwright show-trace";

/** Downloads a result's Playwright traces (ADR-037) as trace-<id>.zip; nothing is requested until it is pressed. */
export default function TraceButton({ projectId, runId, resultId, name, count, showNote }: Props) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  if ((count ?? 0) <= 0) return null;

  async function download() {
    setBusy(true);
    setFailed(false);
    try {
      const { artifacts } = await listResultArtifacts(projectId, runId, resultId);
      for (const a of artifacts.filter((x) => x.kind === "trace")) {
        downloadBlob(`trace-${a.id}.zip`, await downloadArtifact(projectId, a.id));
      }
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="shot-button trace-button" aria-label={`Download trace for ${name}`} aria-busy={busy}
        onClick={() => { if (!busy) void download(); }}>
        <Download size={14} aria-hidden="true" />
        <span>{busy ? "Downloading…" : "Trace"}</span>
      </button>
      {showNote && <span className="muted trace-note">{TRACE_NOTE}</span>}
      {failed && <span role="alert" className="trace-error">The trace could not be downloaded. Try again.</span>}
    </>
  );
}
