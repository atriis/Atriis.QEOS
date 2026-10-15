import { useEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import { Link } from "react-router-dom";
import type { LogValueGroup } from "../api/analytics";
import { linkFor } from "../lib/logValues";

type Group = LogValueGroup & { link_template?: string | null };

/** How long "Copied" stays. */
const NOTE_MS = 2000;

/** The "Log values" line under a last-result pill (ADR-032): per pattern its values, comma-separated, patterns
 *  separated by "·". Each value copies itself; with an https link template it is also a link (new tab). Nothing when
 *  the result has no values. With `projectId`, each value also links to the runs that hold it. */
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
                  {href ? (
                    <a className="log-value-text" href={href} target="_blank" rel="noopener noreferrer">
                      {`${v} `}<span className="sr-only">(opens in a new tab)</span>
                    </a>
                  ) : (
                    <code className="log-value-text">{v}</code>
                  )}
                  <button type="button" className="log-value-copy" aria-label={`Copy ${g.name} ${v}`} title="Copy"
                    onClick={() => copy(v)}>
                    <Copy size={14} aria-hidden="true" />
                  </button>
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
