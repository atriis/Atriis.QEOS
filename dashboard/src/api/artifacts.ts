import { apiBlob, apiFetch } from "./http";

/** One stored artifact of a result (ADR-037); only traces for now. */
export type ResultArtifact = { id: number; kind: "trace"; name: string; bytes: number };

/** A result's artifacts, without their bytes. */
export function listResultArtifacts(projectId: number, runId: number, resultId: number): Promise<{ artifacts: ResultArtifact[] }> {
  return apiFetch(`/api/v1/projects/${projectId}/runs/${runId}/results/${resultId}/artifacts`);
}

/** The zip's path; needs the Bearer header, so fetch it with `downloadArtifact`, not as a link. */
export function artifactDownloadUrl(projectId: number, id: number): string {
  return `/api/v1/projects/${projectId}/artifacts/${id}`;
}

/** The zip's bytes, with the Bearer header and refresh. */
export function downloadArtifact(projectId: number, id: number): Promise<Blob> {
  return apiBlob(artifactDownloadUrl(projectId, id));
}

/** A one-time link to an artifact (ADR-037): no Bearer header needed, 60 s, this user and client address only. */
export type ArtifactLink = { url: string; expires_at: string };

/** Asks for a one-time link; `url` is relative to this origin. */
export function createArtifactLink(projectId: number, id: number): Promise<ArtifactLink> {
  return apiFetch(`/api/v1/projects/${projectId}/artifacts/${id}/link`, { method: "POST" });
}

/** The self-hosted Playwright trace viewer (dist/trace-viewer/, same origin), reading the trace from `linkUrl`. */
export function traceViewerUrl(linkUrl: string): string {
  return "/trace-viewer/index.html?trace=" + encodeURIComponent(new URL(linkUrl, window.location.origin).href);
}
