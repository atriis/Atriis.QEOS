import { useId, useState, type ReactNode } from "react";
import { XCircle } from "lucide-react";
import { tokenizeLine } from "../lib/gherkinTokens";

interface Props {
  text: string;
  /** Accessible name of the block. */
  label?: string;
  /** Number the lines (a whole .feature file); long lines then wrap instead of scrolling. */
  numbered?: boolean;
  /** Extra content at the end of a 1-based line, such as a scenario's case chip. Numbered blocks only. */
  annotations?: Map<number, ReactNode>;
  /** Marks one 1-based line as the failed step; `tip` shows on hover and keyboard focus (Escape closes it). */
  failed?: { line: number; tip: ReactNode };
}

/** The failed line: focusable, marked in words and an icon as well as red, with a tooltip that is hoverable and never traps focus. */
function FailedLine({ numbered, n, tip, children, note }: { numbered: boolean; n: number; tip: ReactNode; children: ReactNode; note?: ReactNode }) {
  const id = useId();
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const open = (hover || focus) && !dismissed;
  return (
    <span
      className="gk-line gk-failed"
      data-line={numbered ? n : undefined}
      tabIndex={0}
      aria-describedby={open ? id : undefined}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setDismissed(false); }}
      onFocus={() => setFocus(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) { setFocus(false); setDismissed(false); } }}
      onKeyDown={(e) => { if (e.key === "Escape" && open) { e.stopPropagation(); setDismissed(true); } }}
    >
      <span className="gk-code">{children}</span>
      <span className="gk-failed-mark"><XCircle size={14} aria-hidden="true" /> failed</span>
      {note}
      {open && <span id={id} role="tooltip" className="failed-tip">{tip}</span>}
    </span>
  );
}

/** Gherkin: highlighted, never editable. */
export default function GherkinBlock({ text, label = "Gherkin", numbered = false, annotations, failed }: Props) {
  const lines = text.split("\n");
  if (numbered) {
    return (
      <pre className="gherkin numbered" aria-label={label} tabIndex={0}>
        {lines.map((line, i) => failed?.line === i + 1 ? (
          <FailedLine key={i} numbered n={i + 1} tip={failed.tip}
            note={annotations?.has(i + 1) ? <span className="gk-note">{annotations.get(i + 1)}</span> : undefined}>
            {tokenizeLine(line).map((t, j) => <span key={j} className={`gk-${t.kind}`}>{t.text}</span>)}
          </FailedLine>
        ) : (
          // Each line is a block (copying keeps the breaks); its number is drawn from data-line, so it is neither read out nor copied
          <span key={i} className="gk-line" data-line={i + 1}>
            <span className="gk-code">
              {tokenizeLine(line).map((t, j) => <span key={j} className={`gk-${t.kind}`}>{t.text}</span>)}
            </span>
            {annotations?.has(i + 1) && <span className="gk-note">{annotations.get(i + 1)}</span>}
          </span>
        ))}
      </pre>
    );
  }
  return (
    <pre className="gherkin" aria-label={label} tabIndex={0}>
      {lines.map((line, i) => failed?.line === i + 1 ? (
        <span key={i}>
          <FailedLine numbered={false} n={i + 1} tip={failed.tip}>
            {tokenizeLine(line).map((t, j) => <span key={j} className={`gk-${t.kind}`}>{t.text}</span>)}
          </FailedLine>
          {i < lines.length - 1 && "\n"}
        </span>
      ) : (
        <span key={i}>
          {tokenizeLine(line).map((t, j) => <span key={j} className={`gk-${t.kind}`}>{t.text}</span>)}
          {i < lines.length - 1 && "\n"}
        </span>
      ))}
    </pre>
  );
}
