import { type ReactNode } from "react";
import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import FailedTipAnchor from "./FailedTipAnchor";
import { STEPS, tokenizeLine } from "../lib/gherkinTokens";

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
  /** The file line the first line stands for (a scenario cut out of a file); numbered blocks only. `failed.line`, `passedThrough` and `annotations` stay relative to the block. */
  startLine?: number;
  /** Content on the left of a 1-based line, such as a step's screenshot button, in a column every line keeps (so the
   *  steps stay aligned); not selected when the Gherkin is copied. Passing it, even empty, reserves the column. */
  annotations?: Map<number, ReactNode>;
  /** Marks one 1-based line as the step the scenario stopped at (`tone` failed by default); `tip` shows on hover and keyboard focus (Escape closes it). */
  failed?: { line: number; tip: ReactNode; tone?: StepTone };
  /** The steps on lines up to this one (1-based) ran and passed, and are marked green with their tables and doc
   *  strings; the steps after it did not run and stay unmarked. Omitted: no step is marked passed. */
  passedThrough?: number;
}

const MARK = {
  failed: { className: "gk-line gk-failed", srText: "Failed step: ", word: "failed", Icon: XCircle },
  skipped: { className: "gk-line gk-failed gk-skipped", srText: "Skipped step: ", word: "skipped", Icon: CircleDashed },
} as const;

/** How far a result's steps ran and passed, for `passedThrough`: every step when the result passed, the steps before
 *  the marked one when it stopped at one (`stoppedAt`, 1-based); unknown (nothing marked) otherwise, such as a failure
 *  in a Background or one whose step was not found. */
export function passedThroughOf(status: string | undefined, stoppedAt: number | null | undefined): number | undefined {
  if (stoppedAt != null) return stoppedAt - 1;
  return status === "passed" ? Number.MAX_SAFE_INTEGER : undefined;
}

/** Which 1-based lines belong to a step that passed: the step's own line ("step"), then its table rows and doc string
 *  ("part", marked green but not announced again). */
export function passedLines(lines: string[], through: number | undefined): Map<number, "step" | "part"> {
  const passed = new Map<number, "step" | "part">();
  if (through === undefined) return passed;
  let owner = false;
  let inDoc = false;
  lines.forEach((line, i) => {
    const n = i + 1;
    const rest = line.trim();
    if (inDoc || rest.startsWith('"""') || rest.startsWith("```")) {
      if (rest.startsWith('"""') || rest.startsWith("```")) inDoc = !inDoc;
      if (owner) passed.set(n, "part");
      return;
    }
    if (rest.startsWith("|")) {
      if (owner) passed.set(n, "part");
      return;
    }
    if (rest === "" || rest.startsWith("#")) return;
    owner = STEPS.some((k) => rest.startsWith(k)) && n <= through;
    if (owner) passed.set(n, "step");
  });
  return passed;
}

// An empty line holds a <br>: as a row with no line feed of its own it would otherwise have no height, and copying would drop it
const tokens = (line: string) => (line === "" ? <br /> : tokenizeLine(line).map((t, j) => <span key={j} className={`gk-${t.kind}`}>{t.text}</span>));

/** The marked line: focusable, marked in words and an icon as well as colour (red failed, yellow skipped); its tip is the shared FailedTipAnchor's. */
function FailedLine({ numbered, n, tip, tone = "failed", children, lead, note }: { numbered: boolean; n: number; tip: ReactNode; tone?: StepTone; children: ReactNode; lead?: ReactNode; note?: ReactNode }) {
  const { className, srText, word, Icon } = MARK[tone];
  // The visible word is hidden from screen readers: the prefix above already says it
  const mark = <span className="gk-failed-mark" aria-hidden="true"><Icon size={14} /> {word}</span>;
  return (
    <FailedTipAnchor className={className} dataLine={numbered ? n : undefined} tip={tip}>
      <span className="sr-only">{srText}</span>
      {lead}
      <span className="gk-code">{children}</span>
      <span className="gk-failed-end">
        {mark}
        {note}
      </span>
    </FailedTipAnchor>
  );
}

/** Gherkin: highlighted, never editable. Each line is a block row, so copying puts each on its own line (no line feed
 *  of its own, which would add a blank line); a numbered line's number is drawn from data-line, neither read out nor copied. */
export default function GherkinBlock({ text, label = "Gherkin", numbered = false, startLine = 1, annotations, failed, passedThrough }: Props) {
  const lines = text.split("\n");
  const gutter = annotations !== undefined;
  const passed = passedLines(lines, passedThrough === undefined ? undefined : Math.min(passedThrough, failed ? failed.line - 1 : passedThrough));
  const noteAt = (n: number) => (annotations?.has(n) ? <span className="gk-note">{annotations.get(n)}</span> : undefined);
  const className = ["gherkin", numbered && "numbered", gutter && "has-gutter"].filter(Boolean).join(" ");
  return (
    <pre className={className} aria-label={label} tabIndex={0}>
      {lines.map((line, i) => {
        const n = i + 1;
        // The column on the left (when reserved) holds the line's note; otherwise the note ends the line
        const lead = gutter ? <span className="gk-gutter">{noteAt(n)}</span> : undefined;
        const note = gutter ? undefined : noteAt(n);
        if (failed?.line === n) {
          return (
            <FailedLine key={i} numbered={numbered} n={i + startLine} tip={failed.tip} tone={failed.tone} lead={lead} note={note}>
              {tokens(line)}
            </FailedLine>
          );
        }
        const ok = passed.get(n);
        // A passed step says so in a word and an icon as well as colour, like the failed one; its table rows and doc
        // string share the green but are not announced again
        const mark = ok === "step" && <span className="gk-passed-mark" aria-hidden="true"><CheckCircle2 size={14} /> passed</span>;
        return (
          <span key={i} className={ok ? "gk-line gk-passed" : "gk-line"} data-line={numbered ? i + startLine : undefined}>
            {ok === "step" && <span className="sr-only">Passed step: </span>}
            {lead}
            <span className="gk-code">{tokens(line)}</span>
            {(mark || note) && <span className="gk-line-end">{mark}{note}</span>}
          </span>
        );
      })}
    </pre>
  );
}
