import { useEffect, useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getCollectionSettings, putCollectionSettings } from "../api/collection";
import { ago } from "../overview/format";
import ErrorBanner from "./ErrorBanner";

interface Props {
  projectId: number;
  /** Undefined while the role is loading: the state shows, the switch waits. */
  canManage: boolean | undefined;
}

export default function CollectionCard({ projectId, canManage }: Props) {
  const qc = useQueryClient();
  const queryKey = ["collection-settings", projectId];
  const hint = useId();
  const shotsHint = useId();
  const tracesHint = useId();
  const daysHint = useId();
  const roleNote = useId();
  const settings = useQuery({ queryKey, queryFn: () => getCollectionSettings(projectId) });
  const save = useMutation({
    mutationFn: (change: Parameters<typeof putCollectionSettings>[1]) => putCollectionSettings(projectId, change),
    onSuccess: (data) => qc.setQueryData(queryKey, data),
  });
  const on = settings.data?.collect_manual ?? true;
  // Off by default (ADR-036): screenshots can show personal data, and an image cannot be masked
  const keepShots = settings.data?.keep_screenshots ?? false;
  // Off by default (ADR-037): a trace holds page snapshots and network traffic
  const keepTraces = settings.data?.keep_traces ?? false;
  const storedDays = settings.data?.trace_days ?? 14;
  const [days, setDays] = useState(String(storedDays));
  const [daysError, setDaysError] = useState(false);
  useEffect(() => { setDays(String(storedDays)); }, [storedDays]);
  const commitDays = () => {
    const n = Number(days);
    if (days.trim() === "" || !Number.isInteger(n) || n < 1 || n > 90) { setDaysError(true); return; }
    setDaysError(false);
    if (n !== storedDays && !save.isPending) save.mutate({ trace_days: n });
  };
  const saving = (field: "collect_manual" | "keep_screenshots" | "keep_traces") => save.isPending && save.variables?.[field] !== undefined;
  const describedBy = (own: string) => (canManage === false ? `${own} ${roleNote}` : own);

  return (
    <div className="card">
      <h2>Collection</h2>
      <div className="switch-row">
        <button
          type="button"
          role="switch"
          className="switch"
          aria-checked={on}
          aria-describedby={describedBy(hint)}
          aria-busy={saving("collect_manual")}
          disabled={canManage !== true || settings.isLoading}
          // Not disabled while saving, so keyboard focus stays on the switch; extra clicks are ignored
          onClick={() => { if (!save.isPending) save.mutate({ collect_manual: !on }); }}
        >
          <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
          <span>Collect runs started manually in CI</span>
          <span className="switch-state muted" aria-hidden="true">{saving("collect_manual") ? "Saving…" : on ? "On" : "Off"}</span>
        </button>
      </div>
      <p id={hint} className="muted">
        Manual means a person started the run: “Run workflow” or a re-run on GitHub, a pipeline run from
        GitLab’s web page or a manual job, a manual Azure build. Runs started from QEOS are always collected.
        Needs qeos-collector 0.5.0 or later; older collectors are always collected.
      </p>
      <div className="switch-row">
        <button
          type="button"
          role="switch"
          className="switch"
          aria-checked={keepShots}
          aria-describedby={describedBy(shotsHint)}
          aria-busy={saving("keep_screenshots")}
          disabled={canManage !== true || settings.isLoading}
          onClick={() => { if (!save.isPending) save.mutate({ keep_screenshots: !keepShots }); }}
        >
          <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
          <span>Keep screenshots from uploads</span>
          <span className="switch-state muted" aria-hidden="true">{saving("keep_screenshots") ? "Saving…" : keepShots ? "On" : "Off"}</span>
        </button>
      </div>
      <p id={shotsHint} className="muted">
        Screenshots can show personal data and are never masked. They are deleted with the run’s results.
      </p>
      <div className="switch-row">
        <button
          type="button"
          role="switch"
          className="switch"
          aria-checked={keepTraces}
          aria-describedby={describedBy(tracesHint)}
          aria-busy={saving("keep_traces")}
          disabled={canManage !== true || settings.isLoading}
          onClick={() => { if (!save.isPending) save.mutate({ keep_traces: !keepTraces }); }}
        >
          <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
          <span>Keep traces from uploads</span>
          <span className="switch-state muted" aria-hidden="true">{saving("keep_traces") ? "Saving…" : keepTraces ? "On" : "Off"}</span>
        </button>
      </div>
      <p id={tracesHint} className="muted">
        Traces contain page snapshots and network traffic, which can include cookies, tokens and personal data of your test accounts. QEOS cannot mask them. Turn this on only if every project reader may see that.
      </p>
      <label className="field-inline">
        <span>Keep them for (days)</span>
        <input
          type="number" inputMode="numeric" min={1} max={90} step={1}
          value={days}
          aria-invalid={daysError}
          aria-describedby={daysError ? daysHint : undefined}
          disabled={canManage !== true || settings.isLoading}
          onChange={(e) => { setDays(e.target.value); setDaysError(false); }}
          onBlur={commitDays}
          onKeyDown={(e) => { if (e.key === "Enter") commitDays(); }}
        />
      </label>
      {daysError && <p id={daysHint} role="alert" className="field-error">Enter a whole number of days between 1 and 90.</p>}
      {canManage === false && <p id={roleNote} className="muted">Only owners and admins can change these settings.</p>}
      {settings.data != null && settings.data.discarded_count > 0 && (
        <p className="muted">
          {settings.data.discarded_count} manual {settings.data.discarded_count === 1 ? "upload" : "uploads"} not collected
          {settings.data.last_discarded_at != null && `, last ${ago(settings.data.last_discarded_at)}`}.
        </p>
      )}
      {settings.error != null && <ErrorBanner error={settings.error} onRetry={() => settings.refetch()} />}
      {save.error != null && <ErrorBanner error={save.error} />}
    </div>
  );
}
