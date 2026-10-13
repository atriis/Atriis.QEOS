import { type ReactNode } from "react";
import { XCircle } from "lucide-react";
import FailedTipAnchor from "./FailedTipAnchor";
import { tokenizeLine } from "../lib/gherkinTokens";

interface Props {
  text: string;
  /** Accessible name of the block. */
  label?: string;
  /** Number the lines (a whole .feature file); long lines then wrap instead of scrolling. */
  numbered?: boolean;
  /** The file line the first line stands for (a scenario cut out of a file); numbered blocks only. `failed.line` and `annotations` stay relative to the block. */
  startLine?: number;
  /** Extra content at the end of a 1-based line, such as a scenario's case chip. Numbered blocks only. */
  annotations?: Map<number, ReactNode>;
  /** Marks one 1-based line as the failed step; `tip` shows on hover and keyboard focus (Escape closes it). */
  failed?: { line: number; tip: ReactNode };
}

/** The failed line: focusable, marked in words and an icon as well as red; its tip is the shared FailedTipAnchor's. */
function FailedLine({ numbered, n, tip, children, note, trailing }: { numbered: boolean; n: number; tip: ReactNode; children: ReactNode; note?: ReactNode; trailing?: string }) {
  return (
    <FailedTipAnchor className="gk-line gk-failed" dataLine={numbered ? n : undefined} tip={tip}>
      <span className="sr-only">Failed step: </span>
      <span className="gk-code">{children}</span>
      {numbered ? (
        <span className="gk-failed-end">
          <span className="gk-failed-mark"><XCircle size={14} aria-hidden="true" /> failed</span>
          {note}
        </span>
      ) : (
        <span className="gk-failed-mark"><XCircle size={14} aria-hidden="true" /> failed</span>
      )}
      {trailing}
    </FailedTipAnchor>
  );
}

/** Gherkin: highlighted, never editable. */
export default function GherkinBlock({ text, label = "Gherkin", numbered = false, startLine = 1, annotations, failed }: Props) {
  const lines = text.split("\n");
  if (numbered) {
    return (
      <pre className="gherkin numbered" aria-label={label} tabIndex={0}>
        {lines.map((line, i) => failed?.line === i + 1 ? (
          <FailedLine key={i} numbered n={i + startLine} tip={failed.tip}
            note={annotations?.has(i + 1) ? <span className="gk-note">{annotations.get(i + 1)}</span> : undefined}>
            {tokenizeLine(line).map((t, j) => <span key={j} className={`gk-${t.kind}`}>{t.text}</span>)}
          </FailedLine>
        ) : (
          // Each line is a block (copying keeps the breaks); its number is drawn from data-line, so it is neither read out nor copied
          <span key={i} className="gk-line" data-line={i + startLine}>
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
          {/* The line feed lives inside the block-level failed line, so it ends that line without adding a blank one */}
          <FailedLine numbered={false} n={i + 1} tip={failed.tip} trailing={i < lines.length - 1 ? "\n" : undefined}>
            {tokenizeLine(line).map((t, j) => <span key={j} className={`gk-${t.kind}`}>{t.text}</span>)}
          </FailedLine>
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
