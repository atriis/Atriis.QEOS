import { apiBlob, apiFetch } from "./http";

/** One stored step image (ADR-036); `hook` marks a before/after-scenario image, which has no step of its own. */
export type Screenshot = {
  id: number;
  step_text: string;
  step_line: number | null;
  hook: "before" | "after" | null;
  media_type: string;
  bytes: number;
};

/** A result's screenshots in position order, without the images. */
export function getResultScreenshots(projectId: number, runId: number, resultId: number): Promise<{ screenshots: Screenshot[] }> {
  return apiFetch(`/api/v1/projects/${projectId}/runs/${runId}/results/${resultId}/screenshots`);
}

/** One image's bytes, with the Bearer header and refresh (an <img src> could not send the token). */
export function getScreenshotBlob(projectId: number, id: number): Promise<Blob> {
  return apiBlob(`/api/v1/projects/${projectId}/screenshots/${id}`);
}
