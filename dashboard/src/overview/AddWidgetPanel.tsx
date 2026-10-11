import { X } from "lucide-react";
import { MAX_WIDGETS } from "./catalog";
import { addableDefinitions } from "./widgets/registry";
import type { WidgetDefinition } from "./widgets/types";

interface Props {
  id: string;
  /** The layout holds MAX_WIDGETS already. */
  full: boolean;
  onAdd: (def: WidgetDefinition) => void;
  onClose: () => void;
}

/** Every widget type with a one-line description (spec §2.2 Add widget). Escape closes it. */
export default function AddWidgetPanel({ id, full, onAdd, onClose }: Props) {
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
