import { useId } from "react";
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
  const settings = useQuery({ queryKey, queryFn: () => getCollectionSettings(projectId) });
  const save = useMutation({
    mutationFn: (collectManual: boolean) => putCollectionSettings(projectId, collectManual),
    onSuccess: (data) => qc.setQueryData(queryKey, data),
  });
  const on = settings.data?.collect_manual ?? true;

  return (
    <div className="card">
      <h2>Collection</h2>
      <div className="switch-row">
        <button
          type="button"
          role="switch"
          className="switch"
          aria-checked={on}
          aria-describedby={hint}
          aria-busy={save.isPending}
          disabled={canManage !== true || settings.isLoading}
          // Not disabled while saving, so keyboard focus stays on the switch; extra clicks are ignored
          onClick={() => { if (!save.isPending) save.mutate(!on); }}
        >
          <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
          <span>Collect runs started manually in CI</span>
          <span className="switch-state muted" aria-hidden="true">{save.isPending ? "Saving…" : on ? "On" : "Off"}</span>
        </button>
      </div>
      <p id={hint} className="muted">
        Manual means a person started the run: “Run workflow” or a re-run on GitHub, a pipeline run from
        GitLab’s web page or a manual job, a manual Azure build. Runs started from QEOS are always collected.
        Needs qeos-collector 0.5.0 or later; older collectors are always collected.
        {canManage === false && " Only owners and admins can change this."}
      </p>
      {settings.data != null && settings.data.discarded_count > 0 && (
        <p className="muted">
          {settings.data.discarded_count} manual uploads not collected
          {settings.data.last_discarded_at != null && `, last ${ago(settings.data.last_discarded_at)}`}.
        </p>
      )}
      {settings.error != null && <ErrorBanner error={settings.error} onRetry={() => settings.refetch()} />}
      {save.error != null && <ErrorBanner error={save.error} />}
    </div>
  );
}
