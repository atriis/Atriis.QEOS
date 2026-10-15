import { type ReactNode } from "react";
import { CircleDashed, XCircle } from "lucide-react";
import FailedTipAnchor from "./FailedTipAnchor";
import { tokenizeLine } from "../lib/gherkinTokens";

/** Why the scenario stopped at the marked step: it failed there (red), or it was skipped there, undefined, pending,
 *  ambiguous or skipped by a hook (yellow). */
export type StepTone = "failed" | "skipped";

/** The tone of a result's marked step: yellow for a skipped result, red for a failed or errored one. */
export const toneOf = (result: { status: string }): StepTone => (result.status === "skipped" ? "skipped" : "failed");

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
  /** Marks one 1-based line as the step the scenario stopped at (`tone` failed by default); `tip` shows on hover and keyboard focus (Escape closes it). */
  failed?: { line: number; tip: ReactNode; tone?: StepTone };
}

const MARK = {
  failed: { className: "gk-line gk-failed", srText: "Failed step: ", word: "failed", Icon: XCircle },
  skipped: { className: "gk-line gk-failed gk-skipped", srText: "Skipped step: ", word: "skipped", Icon: CircleDashed },
} as const;

/** The marked line: focusable, marked in words and an icon as well as colour (red failed, yellow skipped); its tip is the shared FailedTipAnchor's. */
function FailedLine({ numbered, n, tip, tone = "failed", children, note, trailing }: { numbered: boolean; n: number; tip: ReactNode; tone?: StepTone; children: ReactNode; note?: ReactNode; trailing?: string }) {
  const { className, srText, word, Icon } = MARK[tone];
  const mark = <span className="gk-failed-mark"><Icon size={14} aria-hidden="true" /> {word}</span>;
  return (
    <FailedTipAnchor className={className} dataLine={numbered ? n : undefined} tip={tip}>
      <span className="sr-only">{srText}</span>
      <span className="gk-code">{children}</span>
      {numbered ? (
        <span className="gk-failed-end">
          {mark}
          {note}
        </span>
      ) : mark}
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
          <FailedLine key={i} numbered n={i + startLine} tip={failed.tip} tone={failed.tone}
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
          <FailedLine numbered={false} n={i + 1} tip={failed.tip} tone={failed.tone} trailing={i < lines.length - 1 ? "\n" : undefined}>
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
