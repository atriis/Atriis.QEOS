import { useEffect, useReducer, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { type StoredVersion, conflictOf } from "../api/overviewLayout";
import ConfirmButton from "../components/ConfirmButton";
import ErrorBanner from "../components/ErrorBanner";
import UnsavedGuard from "../components/UnsavedGuard";
import { useUserNames } from "../lib/useUserNames";
import AddWidgetPanel from "./AddWidgetPanel";
import { MAX_WIDGETS, type StoredWidget, type WidgetSettings } from "./catalog";
import { type Draft, draftReducer, isDirty, nextWidgetId } from "./draft";
import { formatDay } from "./format";
import type { EditSession } from "./session";
import { useOverviewLayout } from "./useOverviewLayout";
import WidgetCard from "./WidgetCard";
import WidgetSettingsForm from "./WidgetSettingsForm";
import WidgetToolbar from "./WidgetToolbar";
import { definitionOf, widgetTitle } from "./widgets/registry";
import type { WidgetDefinition } from "./widgets/types";

interface Props {
  projectId: number;
  session: EditSession;
  /** Leave edit mode: after Save, or a Cancel that discards. */
  onClose: () => void;
  /** After a 409: start again from the stored layout. Rejects when the stored layout cannot be read, and the editor
   *  then stays as it is (never restarted from stale cached data). */
  onReload: () => Promise<void>;
}

type FocusTarget = { id: string; tool: "up" | "down" | "settings" | "card" } | { id: null; tool: "add" };

/** Edit mode (spec §2.2, §2.3, §2.8): the page shows the draft; Save stores it (or deletes the stored layout after a
 *  Reset), Cancel discards it after asking. Moves keep focus and are announced in one polite live region. */
export default function OverviewEditor({ projectId, session, onClose, onReload }: Props) {
  const { save, reset } = useOverviewLayout(projectId);
  const nameOf = useUserNames(projectId);
  const [draft, dispatch] = useReducer(draftReducer, session.start, (layout): Draft => ({ layout, reset: false }));
  const [settingsFor, setSettingsFor] = useState<string | null>(session.openSettingsFor);
  const [adding, setAdding] = useState(false);
  // `n` alternates a trailing no-break space, so the same words said twice still change the live region and re-announce
  const [announcement, setAnnouncement] = useState({ text: "", n: 0 });
  const announce = (text: string) => setAnnouncement((a) => ({ text, n: a.n + 1 }));
  const [conflict, setConflict] = useState<StoredVersion | null | undefined>(undefined);
  const [failure, setFailure] = useState<unknown>(null);
  const [reloading, setReloading] = useState(false);
  const titleRef = useRef<HTMLParagraphElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const focusAfter = useRef<FocusTarget | null>(null);
  const widgets = draft.layout.widgets;
  const dirty = isDirty(draft, session.start);
  const busy = save.isPending || reset.isPending || reloading;
  const project = session.mode === "project";

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    if (conflict !== undefined) reloadRef.current?.focus();
  }, [conflict]);

  // Focus follows the widget that moved, the neighbour of one removed, or the one added
  useEffect(() => {
    const target = focusAfter.current;
    if (target === null) return;
    focusAfter.current = null;
    if (target.id === null) {
      addRef.current?.focus();
      return;
    }
    const card = gridRef.current?.querySelector<HTMLElement>(`[data-widget-id="${target.id}"]`);
    const tool = target.tool === "card" ? null : card?.querySelector<HTMLButtonElement>(`[data-tool="${target.tool}"]`);
    if (tool && !tool.disabled) tool.focus();
    else card?.focus();
  }, [draft, settingsFor]);

  function move(widget: StoredWidget, index: number, by: -1 | 1) {
    dispatch({ kind: "move", id: widget.id, by });
    focusAfter.current = { id: widget.id, tool: by < 0 ? "up" : "down" };
    announce(`${widgetTitle(widget)} moved to position ${index + by + 1} of ${widgets.length}`);
  }

  function toggleSize(widget: StoredWidget) {
    dispatch({ kind: "size", id: widget.id });
    announce(`${widgetTitle(widget)} is now ${widget.size === "wide" ? "normal width" : "wide"}`);
  }

  function remove(widget: StoredWidget, index: number) {
    const neighbour = widgets[index + 1] ?? widgets[index - 1];
    dispatch({ kind: "remove", id: widget.id });
    if (settingsFor === widget.id) setSettingsFor(null);
    focusAfter.current = neighbour ? { id: neighbour.id, tool: "card" } : { id: null, tool: "add" };
    announce(`${widgetTitle(widget)} removed`);
  }

  function add(def: WidgetDefinition) {
    const id = nextWidgetId(widgets);
    dispatch({ kind: "add", id, type: def.type, size: def.defaultSize, settings: { ...def.defaults } });
    setAdding(false);
    focusAfter.current = { id, tool: "card" };
    announce(`${def.title} added at position ${widgets.length + 1} of ${widgets.length + 1}`);
  }

  function applySettings(widget: StoredWidget, settings: WidgetSettings) {
    dispatch({ kind: "settings", id: widget.id, settings });
    setSettingsFor(null);
    focusAfter.current = { id: widget.id, tool: "settings" };
    announce(`${widgetTitle({ ...widget, settings })} settings applied`);
  }

  function resetDraft() {
    dispatch({ kind: "reset", layout: session.fallback });
    setSettingsFor(null);
    announce(project ? "The built-in default is in the draft" : "The project default is in the draft");
  }

  // A conflict stays on screen (its buttons disabled) while an Overwrite is in flight
  async function commit(version: number = session.version) {
    setFailure(null);
    try {
      if (draft.reset) {
        // Delete rather than save a copy, so later changes to the default still arrive (plan Ruling 20). Always sent,
        // even from version 0: a layout saved elsewhere meanwhile is removed too, and a DELETE of nothing is harmless
        await reset.mutateAsync(session.mode);
      } else {
        await save.mutateAsync({ mode: session.mode, layout: draft.layout, version });
      }
      onClose();
    } catch (error) {
      const stored = conflictOf(error);
      if (stored !== undefined) setConflict(stored);
      else {
        setConflict(undefined);
        setFailure(error);
      }
    }
  }

  async function reloadStored() {
    setFailure(null);
    setReloading(true);
    try {
      await onReload();
    } catch (error) {
      // The conflict stays, so Reload or Overwrite can be tried again
      setFailure(error);
    } finally {
      setReloading(false);
    }
  }

  function dismissConflict() {
    setConflict(undefined);
    barRef.current?.querySelector<HTMLButtonElement>("button.primary")?.focus();
  }

  return (
    <>
      <UnsavedGuard dirty={dirty} />
      <div className="overview-edit-bar" role="region" aria-label="Overview editor" ref={barRef}>
        <div>
          <p className="overview-edit-title" ref={titleRef} tabIndex={-1}>
            {project ? "Editing the project default · everyone without a personal layout sees this" : "Editing your Overview"}
          </p>
          {project && session.lastChange && (
            <p className="overview-note">Last changed by {nameOf(session.lastChange.by)} on {formatDay(session.lastChange.at)}</p>
          )}
        </div>
        <div className="button-row">
          <button type="button" ref={addRef} aria-expanded={adding} aria-controls="overview-add" onClick={() => setAdding((a) => !a)}>
            <Plus size={15} aria-hidden="true" /> Add widget
          </button>
          <button type="button" onClick={resetDraft}>{project ? "Reset to built-in default" : "Reset to project default"}</button>
          {session.defaultChangedAt && (
            <span className="overview-note">The project default changed on {formatDay(session.defaultChangedAt)}</span>
          )}
          {dirty ? (
            <ConfirmButton label="Cancel" question="Discard your changes?" confirmLabel="Discard" cancelLabel="Keep editing" onConfirm={onClose} />
          ) : (
            <button type="button" onClick={onClose}>Cancel</button>
          )}
          {project ? (
            <ConfirmButton
              label="Save"
              triggerClassName="primary"
              question="Everyone without a personal layout will see this layout."
              confirmLabel="Save for everyone"
              confirmClassName="primary"
              cancelLabel="Back"
              disabled={busy || !dirty}
              onConfirm={() => void commit()}
            />
          ) : (
            <button type="button" className="primary" disabled={busy || !dirty} onClick={() => void commit()}>Save</button>
          )}
        </div>
        {failure != null && <ErrorBanner error={failure} />}
        {conflict !== undefined && (
          <div
            className="error-banner"
            role="alertdialog"
            aria-label="The layout changed while you were editing"
            aria-describedby="overview-conflict-message"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                dismissConflict();
              }
            }}
          >
            <span id="overview-conflict-message">
              {conflict
                ? `Changed by ${nameOf(conflict.updated_by)} on ${formatDay(conflict.updated_at)} since you started`
                : "This layout was removed since you started"}
            </span>
            <button type="button" ref={reloadRef} disabled={busy} onClick={() => void reloadStored()}>Reload</button>
            <button type="button" disabled={busy} onClick={() => void commit(conflict?.version ?? 0)}>Overwrite</button>
          </div>
        )}
      </div>
      {adding && (
        <AddWidgetPanel
          id="overview-add"
          full={widgets.length >= MAX_WIDGETS}
          onAdd={add}
          onClose={() => {
            setAdding(false);
            addRef.current?.focus();
          }}
        />
      )}
      <p className="sr-only" role="status" aria-live="polite">{announcement.text}{announcement.n % 2 === 1 ? " " : ""}</p>
      <div className="overview-grid" ref={gridRef}>
        {widgets.map((widget, index) => {
          const title = widgetTitle(widget);
          const hasSettings = (definitionOf(widget.type)?.settings.length ?? 0) > 0;
          return (
            <WidgetCard
              key={widget.id}
              projectId={projectId}
              widget={widget}
              onOpenSettings={hasSettings ? () => setSettingsFor(widget.id) : undefined}
              tools={
                <>
                  <WidgetToolbar
                    title={title}
                    first={index === 0}
                    last={index === widgets.length - 1}
                    wide={widget.size === "wide"}
                    hasSettings={hasSettings}
                    settingsOpen={settingsFor === widget.id}
                    onMove={(by) => move(widget, index, by)}
                    onSize={() => toggleSize(widget)}
                    onSettings={() => setSettingsFor((open) => (open === widget.id ? null : widget.id))}
                    onRemove={() => remove(widget, index)}
                  />
                  {settingsFor === widget.id && (
                    <WidgetSettingsForm
                      projectId={projectId}
                      widget={widget}
                      onApply={(settings) => applySettings(widget, settings)}
                      onClose={() => {
                        setSettingsFor(null);
                        focusAfter.current = { id: widget.id, tool: "settings" };
                      }}
                    />
                  )}
                </>
              }
            />
          );
        })}
      </div>
      {widgets.length === 0 && <p className="muted">No widgets in this layout. Add one, or reset to the default.</p>}
    </>
  );
}
