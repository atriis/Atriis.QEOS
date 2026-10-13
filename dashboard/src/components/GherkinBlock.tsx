import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { XCircle } from "lucide-react";
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

const CLOSE_DELAY_MS = 150;
const TIP_GAP = 4;

/** The failed line: focusable, marked in words and an icon as well as red. Its tip is a portal (never clipped by the block's scroll area, never copied with the Gherkin), open while the pointer is over the line or the tip, or focus is in either. */
function FailedLine({ numbered, n, tip, children, note, trailing }: { numbered: boolean; n: number; tip: ReactNode; children: ReactNode; note?: ReactNode; trailing?: string }) {
  const id = useId();
  const lineRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const open = (hover || focus) && !dismissed;

  const enter = () => { clearTimeout(timer.current); setHover(true); };
  const leave = () => { clearTimeout(timer.current); timer.current = setTimeout(() => { setHover(false); setDismissed(false); }, CLOSE_DELAY_MS); };
  useEffect(() => () => clearTimeout(timer.current), []);

  useLayoutEffect(() => {
    if (!open) { setPos(null); return; }
    const place = () => {
      const line = lineRef.current, el = tipRef.current;
      if (!line || !el) return;
      const r = line.getBoundingClientRect();
      const w = el.offsetWidth, h = el.offsetHeight;
      const below = r.bottom + TIP_GAP;
      const top = below + h > window.innerHeight && r.top - TIP_GAP - h >= 0 ? r.top - TIP_GAP - h : below;
      const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
      setPos((p) => (p && p.top === top && p.left === left ? p : { top, left }));
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => { window.removeEventListener("scroll", place, true); window.removeEventListener("resize", place); };
  }, [open]);

  const inside = (node: Node | null) => !!node && (!!lineRef.current?.contains(node) || !!tipRef.current?.contains(node));
  return (
    <span
      ref={lineRef}
      className="gk-line gk-failed"
      data-line={numbered ? n : undefined}
      tabIndex={0}
      aria-describedby={open ? id : undefined}
      onMouseEnter={enter}
      onMouseLeave={leave}
      onFocus={() => setFocus(true)}
      onBlur={(e) => { if (!inside(e.relatedTarget as Node | null)) { setFocus(false); setDismissed(false); } }}
      onKeyDown={(e) => {
        if (e.key !== "Escape" || !open) return;
        e.stopPropagation();
        // Focus inside the tip (its link) would drop to the page: bring it back to the line first
        if (tipRef.current?.contains(document.activeElement)) lineRef.current?.focus();
        setDismissed(true);
      }}
    >
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
      {open && createPortal(
        <span
          ref={tipRef}
          id={id}
          role="tooltip"
          className="failed-tip"
          style={{ position: "fixed", top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden" }}
          onMouseEnter={enter}
          onMouseLeave={leave}
        >
          {tip}
        </span>,
        document.body,
      )}
    </span>
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
