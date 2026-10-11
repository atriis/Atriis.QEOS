import { X } from "lucide-react";
import { MAX_WIDGETS } from "./catalog";
import { type LayoutTemplate, TEMPLATES } from "./templates";
import { addableDefinitions, widgetTitle } from "./widgets/registry";
import type { WidgetDefinition } from "./widgets/types";

interface Props {
  id: string;
  /** The layout holds MAX_WIDGETS already. */
  full: boolean;
  onAdd: (def: WidgetDefinition) => void;
  /** Replaces the draft with a template (spec §2.5). */
  onTemplate: (template: LayoutTemplate) => void;
  onClose: () => void;
}

/** Templates first, then every widget type with a one-line description (spec §2.2, §2.5). Escape closes it. */
export default function AddWidgetPanel({ id, full, onAdd, onTemplate, onClose }: Props) {
  return (
    <section
      id={id}
      className="card"
      aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <div className="card-head">
        <h2 id={`${id}-title`}>Add a widget</h2>
        <button type="button" className="ghost widget-tool" aria-label="Close the widget list" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <h3 className="add-widget-heading">Start from a template</h3>
      <p className="muted">A template replaces the draft; Cancel still undoes it.</p>
      <ul className="add-widget-list">
        {TEMPLATES.map((template) => (
          <li key={template.name}>
            <div>
              <strong>{template.label}</strong>
              <p className="muted">{template.layout.widgets.map((w) => widgetTitle(w)).join(", ")}</p>
            </div>
            <button type="button" aria-label={`Use the ${template.label} layout`} onClick={() => onTemplate(template)}>Use</button>
          </li>
        ))}
      </ul>
      <h3 className="add-widget-heading">Widgets</h3>
      {full && <p className="muted">A layout holds at most {MAX_WIDGETS} widgets. Remove one to add another.</p>}
      <ul className="add-widget-list">
        {addableDefinitions().map((def) => (
          <li key={def.type}>
            <div>
              <strong>{def.title}</strong>
              <p className="muted">{def.description}</p>
            </div>
            <button type="button" aria-label={`Add ${def.title}`} disabled={full} onClick={() => onAdd(def)}>Add</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
