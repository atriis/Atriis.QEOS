import { FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Lock, LockOpen } from "lucide-react";
import { apiBlob } from "../api/http";
import { Project, placeLegalHold, releaseLegalHold } from "../api/orgs";
import { downloadBlob } from "../lib/csv";
import ConfirmButton from "./ConfirmButton";
import DeleteProjectDialog from "./DeleteProjectDialog";
import ErrorBanner from "./ErrorBanner";

interface Props {
  project: Project;
  /** Owners and admins: legal hold, export and deleting the project. */
  canManage: boolean;
  /** After the project was deleted (it is pending for 7 days): leave its pages. */
  onDeleted?: () => void;
}

export default function DataCard({ project: initial, canManage, onDeleted }: Props) {
  const qc = useQueryClient();
  const [project, setProject] = useState(initial);
  const [reason, setReason] = useState("");
  const days = project.settings?.result_retention_days ?? 90;
  const hold = project.legal_hold ?? null;

  function updated(next: Project) {
    setProject(next);
    // Keeps the layout's copy (and my_role) in step without a refetch
    qc.setQueryData(["project", project.id], next);
  }

  const place = useMutation({
    mutationFn: () => placeLegalHold(project.id, reason.trim()),
    onSuccess: (next) => {
      setReason("");
      updated(next);
    },
  });
  const release = useMutation({ mutationFn: () => releaseLegalHold(project.id), onSuccess: updated });
  const exporting = useMutation({
    mutationFn: async () => {
      const blob = await apiBlob(`/api/v1/projects/${project.id}/export`);
      const date = new Date().toISOString().slice(0, 10).replaceAll("-", "");
      downloadBlob(`qeos-project-${project.id}-${date}.ndjson`, blob);
    },
  });

  function onPlace(e: FormEvent) {
    e.preventDefault();
    place.mutate();
  }

  return (
    <div className="card">
      <h2>Data</h2>
      <p>
        Results are kept for <strong>{days} days</strong>, then deleted by the daily retention job.
      </p>

      <div className="hold-status">
        {hold ? (
          <>
            <p className="hold-line">
              <Lock size={16} aria-hidden="true" />
              <span>
                <strong>On legal hold since {new Date(hold.since).toLocaleDateString()}.</strong>{" "}
                Nothing of this project is deleted, whatever its age, until the hold is released.
              </span>
            </p>
            {hold.reason && <p className="muted hold-reason">Reason: {hold.reason}</p>}
          </>
        ) : (
          <p className="hold-line">
            <LockOpen size={16} aria-hidden="true" />
            <span>Not on legal hold.</span>
          </p>
        )}
      </div>

      {canManage ? (
        <>
          {hold ? (
            <ConfirmButton
              label="Release legal hold"
              question={`Release the hold? On its next pass, retention deletes results older than ${days} days.`}
              confirmLabel="Release"
              onConfirm={() => release.mutate()}
              disabled={release.isPending}
            />
          ) : (
            <form className="inline-form" onSubmit={onPlace}>
              <label className="grow">
                Reason
                <input
                  required
                  maxLength={500}
                  placeholder="e.g. audit 2026-Q4, litigation request"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              <button type="submit" disabled={place.isPending || !reason.trim()}>
                {place.isPending ? "Placing…" : "Place legal hold"}
              </button>
            </form>
          )}
          {place.error != null && <ErrorBanner error={place.error} />}
          {release.error != null && <ErrorBanner error={release.error} />}

          <div className="export-row">
            <button onClick={() => exporting.mutate()} disabled={exporting.isPending}>
              <Download size={15} aria-hidden="true" />
              {exporting.isPending ? "Preparing download…" : "Download all results"}
            </button>
            <span className="muted">
              Every run and result as NDJSON (one JSON object per line), masked as stored. Export
              before deleting the project.
            </span>
          </div>
          {exporting.error != null && <ErrorBanner error={exporting.error} />}

          <DeleteProjectDialog project={project} onDeleted={onDeleted ?? (() => {})} />
        </>
      ) : (
        <p className="muted">Only owners and admins can place a legal hold, export the data or delete the project.</p>
      )}
    </div>
  );
}
