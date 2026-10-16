import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { formatPurgeDate, restoreProject } from "../api/orgs";
import ErrorBanner from "./ErrorBanner";

/** The 410 body project-service sends for a project pending deletion (spec 2026-10-16). */
export interface PendingInfo {
  code: string;
  message: string;
  organization_id: number;
  deleted_at: string;
  deleted_by: number | null;
  purge_at: string;
}

export function isPendingInfo(value: unknown): value is PendingInfo {
  const v = value as Partial<PendingInfo> | null;
  return v != null && v.code === "pending_deletion" && typeof v.purge_at === "string"
    && typeof v.organization_id === "number";
}

/** What a pending project's URLs show instead of the view: when it goes, and Restore for owners and admins. */
export default function PendingDeletion({ projectId, info, canRestore }: {
  projectId: number;
  info: PendingInfo;
  canRestore: boolean;
}) {
  const qc = useQueryClient();
  const restore = useMutation({
    mutationFn: () => restoreProject(projectId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
  return (
    <section className="card pending-deletion" aria-labelledby="pending-title">
      <h1 id="pending-title">
        <Trash2 size={20} aria-hidden="true" /> This project is scheduled for deletion
      </h1>
      <p>
        It will be deleted permanently on <strong>{formatPurgeDate(info.purge_at)}</strong>, with its runs, results,
        logs, test cases, suites and settings.
      </p>
      {canRestore ? (
        <button type="button" className="primary" onClick={() => restore.mutate()} disabled={restore.isPending}>
          {restore.isPending ? "Restoring…" : "Restore project"}
        </button>
      ) : (
        <p className="muted">Ask an owner or admin if this is a mistake.</p>
      )}
      {restore.error != null && <ErrorBanner error={restore.error} />}
    </section>
  );
}
