import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { FailedStepTest } from "../api/runs";
import ErrorBanner from "./ErrorBanner";
import { TEXT_GROUPED_NOTE, casesByTestKey, failedStepsQuery, sinceText, stepAnchor } from "../lib/failedSteps";
import { plural, testHistoryPath } from "../lib/words";

const ANCHOR = "#step-";

/** The run's failed steps across test cases (spec 2026-10-14 §4.1): one row per step, biggest first; a row opens to
 *  its error groups and the test cases with the text they ran. `#step-<key>` opens and scrolls to a row. */
export default function FailedSteps({ projectId, runId }: { projectId: number; runId: number }) {
  const query = useQuery(failedStepsQuery(projectId, runId));
  const steps = query.data?.steps;
  const keys = useMemo(
    () => [...new Set((steps ?? []).flatMap((s) => s.errors.flatMap((e) => e.tests.map((t) => t.test_key.toLowerCase()))))].sort(),
    [steps],
  );
  const linked = useQuery({
    queryKey: ["failed-steps-cases", projectId, keys],
    enabled: keys.length > 0,
    queryFn: () => casesByTestKey(projectId, keys),
    staleTime: 60_000,
  });
  const { hash, key: locationKey } = useLocation();
  const target = hash.startsWith(ANCHOR) ? decodeURIComponent(hash.slice(ANCHOR.length)) : null;
  const [toggled, setToggled] = useState<ReadonlyMap<string, boolean>>(new Map());
  const scrolled = useRef<string | null>(null);
  // Following the same link again reopens its row and scrolls back to it, even after the user collapsed it
  useEffect(() => {
    if (target == null) return;
    scrolled.current = null;
    setToggled((t) => {
      if (!t.has(target)) return t;
      const next = new Map(t);
      next.delete(target);
      return next;
    });
  }, [target, locationKey]);
  useEffect(() => {
    if (target == null || scrolled.current === target || !steps?.some((s) => s.key === target)) return;
    scrolled.current = target;
    document.getElementById(stepAnchor(target))?.scrollIntoView?.({ block: "start" });
  }, [target, steps, locationKey]);

  const hrefOf = (t: FailedStepTest) => {
    const number = linked.data?.get(t.test_key.toLowerCase());
    return number != null ? `/projects/${projectId}/cases/${number}?run=${runId}` : testHistoryPath(projectId, t.test_key);
  };

  if (query.error == null && (!steps || steps.length === 0)) return null;
  return (
    <section className="card" aria-labelledby="failed-steps">
      <h2 id="failed-steps">Failed steps</h2>
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {steps && (
        <ol className="step-list">
          {steps.map((s) => {
            const open = toggled.get(s.key) ?? s.key === target;
            const panel = `${stepAnchor(s.key)}-errors`;
            return (
              <li key={s.key} id={stepAnchor(s.key)}>
                <button type="button" className="step-head" aria-expanded={open} aria-controls={panel}
                  onClick={() => setToggled((t) => new Map(t).set(s.key, !open))}>
                  <ChevronRight size={16} aria-hidden="true" className="step-chevron" />
                  <code className="step-pattern">{s.pattern}</code>
                </button>
                <p className="step-meta">
                  failed in {plural(s.cases, "test case", "test cases")} · {sinceText(s)}
                </p>
                {s.by === "text" && <p className="muted step-note">{TEXT_GROUPED_NOTE}</p>}
                <div id={panel} className="step-errors" hidden={!open}>
                  {s.errors.map((e) => (
                    <div key={e.shape} className="step-error">
                      <h3 className="step-error-shape">
                        {e.shape ? <code>{e.shape}</code> : <span className="muted">No error message</span>}{" "}
                        <span className="muted">{plural(e.cases, "test case", "test cases")}</span>
                      </h3>
                      {e.example && e.example !== e.shape && <p className="muted step-error-example">{e.example}</p>}
                      <ul className="step-tests">
                        {e.tests.map((t) => (
                          <li key={t.test_key}>
                            <Link to={hrefOf(t)}>{t.name}</Link> <code className="muted">{t.text}</code>
                          </li>
                        ))}
                        {e.more != null && e.more > 0 && <li className="muted">and {e.more} more</li>}
                      </ul>
                    </div>
                  ))}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
