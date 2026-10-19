import { useQuery } from "@tanstack/react-query";
import { getProject } from "../api/orgs";
import { CiTarget, RunRequest, getCiTarget, isActive, listRunRequests, tokenState } from "../api/runRequests";

export const RUN_POLL_MS = 5_000;
// Mirror EDIT_ROLES / the run endpoints in test-management's api/deps.py: who may run and stop, and who manages the target
export const RUN_ROLES = ["owner", "admin", "member"];
export const MANAGE_ROLES = ["owner", "admin"];

export type RunGate = { ok: true; target: CiTarget } | { ok: false; reason: string; toSettings: boolean };

/** The project's newest run request; polled every 5 s while the server still checks it with GitHub. */
export function useLatestRunRequest(projectId: number) {
  return useQuery({
    queryKey: ["run-requests", projectId, "latest"],
    queryFn: async (): Promise<RunRequest | null> => (await listRunRequests(projectId, { limit: 1, offset: 0 })).items[0] ?? null,
    refetchInterval: (query) => (query.state.data?.refreshing ? RUN_POLL_MS : false),
  });
}

/** The newest active request of each workflow (a repository suite's workflow, or the CI target's for manual runs). */
export function useActiveRunRequests(projectId: number) {
  return useQuery({
    queryKey: ["run-requests", projectId, "active"],
    queryFn: async (): Promise<RunRequest[]> => (await listRunRequests(projectId, { limit: 50, offset: 0 })).items.filter(isActive),
    refetchInterval: (query) => (query.state.data?.some((r) => r.refreshing) ? RUN_POLL_MS : false),
  });
}

export function useCiTarget(projectId: number) {
  return useQuery({ queryKey: ["ci-target", projectId], queryFn: () => getCiTarget(projectId) });
}

/** What a Play dispatches: a repository suite's or group's workflow, and the repository its file lives in (null: the server decides). */
export interface RunScope { workflow: string; sourceRepo: string | null }

export const mismatchReason = (sourceRepo: string) => `Set up Run from QEOS in Project Settings for ${sourceRepo}`;

/** Whether Play may start a run, and if not the reason to show; first matching reason wins. `active` is the active request of the workflow Play would start. */
export function gate(role: string | undefined, target: CiTarget, active: RunRequest | null, now: number = Date.now(), scope?: RunScope): RunGate {
  if (!RUN_ROLES.includes(role ?? "")) return { ok: false, reason: "Viewers can't run tests", toSettings: false };
  if (!target.available) return { ok: false, reason: "Running tests from QEOS is not configured on this server", toSettings: false };
  if (!target.configured) return { ok: false, reason: "Configure in Settings", toSettings: true };
  if (tokenState(target, now) === "expired") return { ok: false, reason: "GitHub token expired", toSettings: true };
  if (scope?.sourceRepo && target.repo && scope.sourceRepo.toLowerCase() !== target.repo.toLowerCase()) {
    return { ok: false, reason: mismatchReason(scope.sourceRepo), toSettings: true };
  }
  if (active && isActive(active)) return { ok: false, reason: "A run is in progress", toSettings: false };
  return { ok: true, target };
}

/** Undefined while the role, the target or the active requests are still loading. One active run per workflow: others do not block. */
export function useRunGate(projectId: number, scope?: RunScope): RunGate | undefined {
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId) });
  const target = useCiTarget(projectId);
  const active = useActiveRunRequests(projectId);
  if (!project.data || !target.data || active.isPending) return undefined;
  const workflow = scope?.workflow ?? target.data.workflow;
  // A request without a workflow (an older server) counts against the CI target's
  const mine = (active.data ?? []).find((r) => (r.workflow ?? target.data.workflow) === workflow) ?? null;
  return gate(project.data.my_role, target.data, mine, Date.now(), scope);
}
