import { useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import type { LogValueGroup } from "../api/analytics";
import { linkFor } from "../lib/logValues";

type Group = LogValueGroup & { link_template?: string | null };

/** How long "Copied" stays. */
const NOTE_MS = 2000;

/** The "Log values" line under a last-result pill (ADR-032): per pattern its values, comma-separated, patterns
 *  separated by "·". Each value is plain text that copies itself when clicked; beside it, small links: the
 *  pattern's https template (new tab) when it has one and, with `projectId`, the runs that hold the value.
 *  Nothing when the result has no values. */
export default function LogValuesLine({ values, label = "Log values", projectId }: {
  values: Group[] | undefined; label?: string; projectId?: number;
}) {
  const [note, setNote] = useState("");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const groups = (values ?? []).filter((g) => g.values.length > 0);
  if (groups.length === 0) return null;

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNote("Copied");
    } catch {
      setNote("Could not copy. Select the value and copy it by hand.");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNote(""), NOTE_MS);
  }

  return (
    <div className="log-values" role="group" aria-label={label}>
      <span className="log-values-label">Log values</span>
      {groups.map((g, gi) => (
        <span key={g.name} className="log-values-group">
          {gi > 0 && <span className="log-values-sep" aria-hidden="true">·</span>}
          <span className="log-values-name">{g.name}:</span>
          {g.values.map((v, vi) => {
            const href = linkFor(g.link_template, v);
            return (
              <span key={v} className="log-values-item">
                <span className="log-value">
                  <button type="button" className="log-value-text" aria-label={`Copy ${g.name} ${v}`} title="Click to copy"
                    onClick={() => copy(v)}>
                    {v}
                  </button>
                  {href && (
                    <a className="log-value-open" href={href} target="_blank" rel="noopener noreferrer"
                      aria-label={`Open ${g.name} ${v} (opens in a new tab)`} title="Open">
                      <ExternalLink size={12} aria-hidden="true" />
                    </a>
                  )}
                  {projectId != null && (
                    <Link className="log-value-runs" aria-label={`Runs with ${g.name} ${v}`}
                      to={`/projects/${projectId}/runs?value=${encodeURIComponent(v)}&pattern=${g.name}`}>
                      runs
                    </Link>
                  )}
                </span>
                {vi < g.values.length - 1 && <span aria-hidden="true">,</span>}
              </span>
            );
          })}
        </span>
      ))}
      <span className="log-values-note" role="status" aria-live="polite">{note}</span>
    </div>
  );
}
