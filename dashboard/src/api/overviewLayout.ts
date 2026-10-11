import { ApiError, apiFetch } from "./http";
import type { StoredLayout } from "../overview/catalog";

// Types mirror platforms/project-service/src/project/schemas/overview_layout.py

export type LayoutSource = "personal" | "project" | "builtin";
export type LayoutMode = "personal" | "project";

export interface PersonalMeta { version: number; updated_at: string }
/** `layout` is the project default itself, present even when a personal layout wins (plan Ruling 4). */
export interface ProjectMeta { version: number; updated_by: number; updated_at: string; layout: StoredLayout }

export interface OverviewLayoutState {
  /** null: nothing is saved, the dashboard shows its built-in default. */
  effective: StoredLayout | null;
  source: LayoutSource;
  personal: PersonalMeta | null;
  project: ProjectMeta | null;
}

export interface LayoutRow { layout: StoredLayout; version: number; updated_by: number; updated_at: string }

/** The stored row a 409 names. */
export interface StoredVersion { version: number; updated_by: number; updated_at: string }

const base = (projectId: number) => `/api/v1/projects/${projectId}/overview-layout`;

export function getOverviewLayout(projectId: number): Promise<OverviewLayoutState> {
  return apiFetch(base(projectId));
}

/** `version` is the one editing started from; 0 creates. A stale version is a 409 (see conflictOf). The server
 *  refuses a body over 64 KB with a 422. */
export function saveLayout(projectId: number, mode: LayoutMode, layout: StoredLayout, version: number): Promise<LayoutRow> {
  return apiFetch(`${base(projectId)}/${mode}`, { method: "PUT", body: JSON.stringify({ layout, version }) });
}

export function deleteLayout(projectId: number, mode: LayoutMode): Promise<void> {
  return apiFetch(`${base(projectId)}/${mode}`, { method: "DELETE" });
}

/** The stored version a stale save names: undefined when the error is something else, null when the row is gone.
 *  The 409 body is `{detail: {code: "stale_version", message, current: {version, updated_by, updated_at} | null}}`. */
export function conflictOf(error: unknown): StoredVersion | null | undefined {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "stale_version") return undefined;
  const detail = (error.body as { detail?: { current?: StoredVersion | null } } | undefined)?.detail;
  return detail?.current ?? null;
}
