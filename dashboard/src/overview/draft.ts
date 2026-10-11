import { MAX_WIDGETS, type StoredLayout, type StoredWidget, type WidgetSettings, type WidgetSize } from "./catalog";

/** The editor's working copy (spec §2.2: changes apply to a draft; the live page changes only on Save). */
export interface Draft {
  layout: StoredLayout;
  /** Reset was pressed and nothing changed since: Save deletes the stored layout instead of saving a copy (Ruling 20). */
  reset: boolean;
}

export type DraftAction =
  | { kind: "move"; id: string; by: -1 | 1 }
  | { kind: "size"; id: string }
  | { kind: "remove"; id: string }
  | { kind: "add"; id: string; type: string; size: WidgetSize; settings: WidgetSettings }
  | { kind: "settings"; id: string; settings: WidgetSettings }
  | { kind: "replace"; layout: StoredLayout }
  | { kind: "reset"; layout: StoredLayout };

/** "w<n>", the first n from the widget count up that no widget uses. */
export function nextWidgetId(widgets: StoredWidget[]): string {
  const taken = new Set(widgets.map((w) => w.id));
  let n = widgets.length + 1;
  while (taken.has(`w${n}`)) n += 1;
  return `w${n}`;
}

const copy = (layout: StoredLayout): StoredLayout => ({
  schema: layout.schema,
  widgets: layout.widgets.map((w) => ({ ...w, settings: { ...w.settings } })),
});

function edited(draft: Draft, widgets: StoredWidget[]): Draft {
  return { layout: { ...draft.layout, widgets }, reset: false };
}

export function draftReducer(draft: Draft, action: DraftAction): Draft {
  const widgets = draft.layout.widgets;
  // An edit of a widget that is not in the draft changes nothing (the reset mark included)
  const absent = (id: string) => !widgets.some((w) => w.id === id);
  switch (action.kind) {
    case "move": {
      const from = widgets.findIndex((w) => w.id === action.id);
      const to = from + action.by;
      if (from < 0 || to < 0 || to >= widgets.length) return draft;
      const next = [...widgets];
      [next[from], next[to]] = [next[to], next[from]];
      return edited(draft, next);
    }
    case "size":
      if (absent(action.id)) return draft;
      return edited(draft, widgets.map((w): StoredWidget => (w.id === action.id ? { ...w, size: w.size === "wide" ? "normal" : "wide" } : w)));
    case "remove":
      if (absent(action.id)) return draft;
      return edited(draft, widgets.filter((w) => w.id !== action.id));
    case "add":
      if (widgets.length >= MAX_WIDGETS || widgets.some((w) => w.id === action.id)) return draft;
      return edited(draft, [...widgets, { id: action.id, type: action.type, size: action.size, settings: { ...action.settings } }]);
    case "settings":
      if (absent(action.id)) return draft;
      return edited(draft, widgets.map((w): StoredWidget => (w.id === action.id ? { ...w, settings: { ...action.settings } } : w)));
    case "replace":
      return { layout: copy(action.layout), reset: false };
    case "reset":
      return { layout: copy(action.layout), reset: true };
  }
}

export function isDirty(draft: Draft, start: StoredLayout): boolean {
  return draft.reset || JSON.stringify(draft.layout) !== JSON.stringify(start);
}
