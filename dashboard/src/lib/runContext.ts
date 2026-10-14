import { useEffect, useRef } from "react";

/** `?run=` from a Last runs bar: a positive run id, else null (the page shows the latest results). */
export function runParam(params: URLSearchParams): number | null {
  const raw = params.get("run");
  if (raw == null || !/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  return n > 0 && Number.isSafeInteger(n) ? n : null;
}

/** "failed" → "Failed": a status as the run context note says it. */
export const statusWord = (status: string) => status.charAt(0).toUpperCase() + status.slice(1);

/** Once per run opened from a bar, bring the first marked failed step into view. */
export function useScrollToFailure(runId: number | null, marked: boolean) {
  const done = useRef<number | null>(null);
  useEffect(() => {
    if (runId == null || !marked || done.current === runId) return;
    done.current = runId;
    document.querySelector(".gk-failed")?.scrollIntoView?.({ block: "center" });
  }, [runId, marked]);
}
