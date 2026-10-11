import type { LayoutMode, OverviewLayoutState } from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";
import { BUILTIN_DEFAULT } from "./templates";
import { knownWidgets } from "./widgets/registry";

/** Where an edit starts, frozen when Customise is pressed: a background refetch never replaces the draft (Ruling 21). */
export interface EditSession {
  mode: LayoutMode;
  start: StoredLayout;
  /** Sent with Save; 0 creates. */
  version: number;
  /** What Reset puts in the draft: the project default (personal mode) or the built-in default (project mode). */
  fallback: StoredLayout;
  /** Personal mode: the project default's date when it changed after this personal layout (spec §2.8). */
  defaultChangedAt: string | null;
  /** Project mode: who changed the default last. */
  lastChange: { by: number; at: string } | null;
  /** A widget whose settings open at once (the empty-branch and no-name buttons). */
  openSettingsFor: string | null;
}

// Widgets of unknown types are left out of the draft (plan Ruling 28)
const known = (layout: StoredLayout): StoredLayout => ({ ...layout, widgets: knownWidgets(layout) });

export function startSession(state: OverviewLayoutState, mode: LayoutMode, openSettingsFor: string | null = null): EditSession {
  if (mode === "personal") {
    const defaultIsNewer = state.personal !== null && state.project !== null
      && Date.parse(state.project.updated_at) > Date.parse(state.personal.updated_at);
    return {
      mode,
      start: known(state.effective ?? BUILTIN_DEFAULT),
      version: state.personal?.version ?? 0,
      fallback: known(state.project?.layout ?? BUILTIN_DEFAULT),
      defaultChangedAt: defaultIsNewer && state.project ? state.project.updated_at : null,
      lastChange: null,
      openSettingsFor,
    };
  }
  return {
    mode,
    // The project default itself, never the editor's own personal layout (plan Ruling 4)
    start: known(state.project?.layout ?? BUILTIN_DEFAULT),
    version: state.project?.version ?? 0,
    fallback: BUILTIN_DEFAULT,
    defaultChangedAt: null,
    lastChange: state.project ? { by: state.project.updated_by, at: state.project.updated_at } : null,
    openSettingsFor,
  };
}
