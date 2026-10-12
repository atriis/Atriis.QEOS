import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { X } from "lucide-react";
import { formatCount } from "../api/analytics";
import type { Case } from "../api/cases";
import type { SuggestedTest } from "../api/impact";
import { MAX_RUN_CASES } from "../api/runRequests";
import { type LikelyAffected, type NoReadableChange, findLikelyAffected } from "../lib/likelyAffected";
import { useCiTarget } from "../lib/useRunGate";
import { plural, testHistoryPath } from "../lib/words";
import ErrorBanner from "./ErrorBanner";
import { SkeletonStatus } from "./Skeleton";

interface Props {
  /** The section's id, for the header button's `aria-controls`. */
  id: string;
  projectId: number;
  /** Replaces the Cases selection with these cases: the selection bar's Run, its dialog and the estimate follow. */
  onSelect: (cases: Case[]) => void;
  onClose: () => void;
  /** Find tests is the view's primary unless something else holds it (the selection bar's Run). */
  primary?: boolean;
}

const tests = (n: number) => plural(n, "likely affected test", "likely affected tests");

/** The status sentence for an answer: what was selected, or why nothing was. */
function summary(found: LikelyAffected | NoReadableChange | null, branch: string): string {
  if (found === null) return `No run on ${branch} has change data yet`;
  if (found.suggestion === null) return `Run #${found.run.id} has no readable change data`;
  const { suggestion } = found;
  const total = suggestion.tests.length;
  if (total === 0) {
    return suggestion.state === "not_enough_history"
      ? `Not enough history on ${branch} yet to suggest tests: ${formatCount(suggestion.history_runs)} of ${formatCount(suggestion.needed_runs)} runs with changed files`
      : `No tests are likely affected by the latest change on ${branch}`;
  }
  const linked = found.cases.length;
  if (linked === 0) return `${tests(total)}, none linked to ${found.manualOnly.length > 0 ? "an imported case" : "a case"}`;
  const selected = Math.min(linked, MAX_RUN_CASES);
  const capped = linked > MAX_RUN_CASES ? ` (the first ${MAX_RUN_CASES}: at most ${MAX_RUN_CASES} cases per run)` : "";
  return `Selected ${plural(selected, "linked case", "linked cases")}${capped} for ${tests(total)}`;
}

/** Suggested tests Play cannot run, under why, each linked to its history. */
function NotRunnable({ id, title, tests: list, projectId }: { id: string; title: string; tests: SuggestedTest[]; projectId: number }) {
  if (list.length === 0) return null;
  return (
    <>
      <h3 id={id} className="likely-affected-heading">{title}</h3>
      <ul className="impact-list" aria-labelledby={id}>
        {list.map((t) => (
          <li key={t.test_key}><Link to={testHistoryPath(projectId, t.test_key)}>{t.name}</Link></li>
        ))}
      </ul>
    </>
  );
}

/** Run likely affected (spec 2026-10-12 §2.2, plan Ruling 22): scores a branch's latest change and selects the linked
 *  cases; the person reviews the selection and runs it from the selection bar. Inline, never modal. */
export default function LikelyAffectedPanel({ id, projectId, onSelect, onClose, primary = true }: Props) {
  const ids = useId();
  const target = useCiTarget(projectId);
  const [branch, setBranch] = useState("");
  const edited = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const ref = target.data?.ref;
  // The CI target's branch until the person types their own
  useEffect(() => {
    if (!edited.current && ref) setBranch(ref);
  }, [ref]);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  const find = useMutation({
    mutationFn: (name: string) => findLikelyAffected(projectId, name),
    onSuccess: (found) => {
      // Never preselect anything else: no runnable linked case, no selection change
      if (found !== null && found.suggestion !== null && found.cases.length > 0) onSelect(found.cases.slice(0, MAX_RUN_CASES));
    },
  });
  const asked = find.variables ?? "";
  const found = find.data;
  return (
    <section id={id} className="card likely-affected" aria-labelledby={`${ids}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}>
      <div className="card-head">
        <h2 id={`${ids}-title`}>Run likely affected</h2>
        <button type="button" className="ghost widget-tool" aria-label="Close Run likely affected" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <p className="muted">
        Selects the cases linked to the tests a branch's latest change is likely to affect. Review the selection, then run it.
      </p>
      <form className="likely-affected-form" onSubmit={(e) => {
        e.preventDefault();
        const name = branch.trim();
        if (name) find.mutate(name);
      }}>
        <label>
          Branch
          <input ref={inputRef} value={branch} maxLength={255} required autoComplete="off" spellCheck={false}
            onChange={(e) => { edited.current = true; setBranch(e.target.value); }} />
        </label>
        <button type="submit" className={primary ? "primary" : undefined} disabled={find.isPending || branch.trim() === ""}>
          {find.isPending ? "Finding…" : "Find tests"}
        </button>
      </form>
      {find.isPending && (
        <SkeletonStatus label="Finding likely affected tests">
          <span className="skeleton skeleton-line" aria-hidden="true" />
        </SkeletonStatus>
      )}
      <p role="status" className="likely-affected-status">{find.isSuccess ? summary(found ?? null, asked) : ""}</p>
      {find.error != null && <ErrorBanner error={find.error} onRetry={() => find.mutate(asked || branch.trim())} />}
      {found != null && (
        <>
          <p className="muted">
            From the latest change on {asked}: <Link to={`/projects/${projectId}/runs/${found.run.id}`}>{`run #${found.run.id}`}</Link>
            {`, ${plural(found.run.changed_files ?? 0, "changed file", "changed files")}.`}
            {found.suggestion !== null && found.suggestion.state === "not_enough_history" && found.suggestion.tests.length > 0
              && ` Not enough history yet for statistics: ${formatCount(found.suggestion.history_runs)} of ${formatCount(found.suggestion.needed_runs)} runs with changed files, so only tests that changed, fail on the branch or have no history are suggested.`}
          </p>
          {found.suggestion !== null && (
            <>
              <NotRunnable id={`${ids}-unlinked`} title="Not runnable from QEOS (no linked case)" tests={found.unlinked}
                projectId={projectId} />
              <NotRunnable id={`${ids}-manual`} title="Not runnable from QEOS (linked only to a manual case)"
                tests={found.manualOnly} projectId={projectId} />
            </>
          )}
        </>
      )}
    </section>
  );
}
