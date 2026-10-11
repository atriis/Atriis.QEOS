import type { StoredLayout } from "./catalog";
import WidgetCard from "./WidgetCard";
import { knownWidgets } from "./widgets/registry";

interface Props {
  projectId: number;
  layout: StoredLayout;
  /** Opens edit mode on this widget's settings (the empty-branch and no-name buttons). */
  onOpenSettings?: (widgetId: string) => void;
}

/** The live Overview: the layout's widgets in order on the `auto-fit, minmax(260px, 1fr)` grid. */
export default function WidgetGrid({ projectId, layout, onOpenSettings }: Props) {
  const widgets = knownWidgets(layout);
  if (widgets.length === 0) return <p className="muted">This Overview has no widgets. Use Customise to add some.</p>;
  return (
    <div className="overview-grid">
      {widgets.map((widget) => (
        <WidgetCard
          key={widget.id}
          projectId={projectId}
          widget={widget}
          onOpenSettings={onOpenSettings ? () => onOpenSettings(widget.id) : undefined}
        />
      ))}
    </div>
  );
}
