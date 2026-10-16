import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { MAX_AGE_DAYS, type RangeProblem, addDays, checkRange } from "../lib/period";

interface Props {
  /** The applied custom range, or "" while none is */
  from: string;
  to: string;
  today: string;
  onApply: (from: string, to: string) => void;
  /** Shown while no custom range is applied yet: closes the row without applying */
  onCancel?: () => void;
  /** Move focus to From when the row appears (the reader just pressed "Custom…") */
  autoFocus?: boolean;
}

/** One compact row for a custom period (spec: Filters): From, To, Apply and the range error inline. It sits right
 *  under the period chips when "Custom…" is pressed or a custom range is applied, so the dates never hide inside the
 *  full filter form. The same checks as the URL reader: both dates, in order, at most 90 days, not after today. */
export default function PeriodRange({ from, to, today, onApply, onCancel, autoFocus }: Props) {
  const uid = useId();
  const errorId = `${uid}-error`;
  const fromRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState({ from, to });
  const [problem, setProblem] = useState<RangeProblem | null>(null);

  // The draft follows the URL (Back, a chip removed, a pasted link)
  useEffect(() => {
    setDraft({ from, to });
    setProblem(null);
  }, [from, to]);
  useEffect(() => {
    if (autoFocus) fromRef.current?.focus();
  }, [autoFocus]);

  function apply(e: FormEvent) {
    e.preventDefault();
    const found = checkRange(draft.from, draft.to, today);
    setProblem(found);
    if (!found) onApply(draft.from, draft.to);
  }
  const invalid = (field: "from" | "to") => problem?.fields.includes(field) || undefined;
  const describedBy = (field: "from" | "to") => (problem?.fields.includes(field) ? errorId : undefined);

  return (
    <form className="period-range" onSubmit={apply} noValidate aria-label="Custom period">
      <label>From
        <input ref={fromRef} type="date" value={draft.from} min={addDays(today, -MAX_AGE_DAYS)} max={today}
          aria-invalid={invalid("from")} aria-describedby={describedBy("from")}
          onChange={(e) => { setProblem(null); setDraft((d) => ({ ...d, from: e.target.value })); }} />
      </label>
      <label>To
        <input type="date" value={draft.to} min={addDays(today, -MAX_AGE_DAYS)} max={today}
          aria-invalid={invalid("to")} aria-describedby={describedBy("to")}
          onChange={(e) => { setProblem(null); setDraft((d) => ({ ...d, to: e.target.value })); }} />
      </label>
      <button type="submit" className="primary">Apply</button>
      {onCancel && <button type="button" className="ghost" onClick={onCancel}>Cancel</button>}
      {problem && <p id={errorId} className="field-error" role="alert">{problem.message}</p>}
    </form>
  );
}
