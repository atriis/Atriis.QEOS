import { Suspense, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { SkeletonStat } from "../components/Skeleton";
import type { StoredWidget } from "./catalog";
import WidgetBoundary from "./WidgetBoundary";
import { definitionOf, withDefaults } from "./widgets/registry";

interface Props {
  projectId: number;
  widget: StoredWidget;
  /** Edit mode: the widget's toolbar and, while open, its settings form, above the widget. */
  tools?: ReactNode;
  onOpenSettings?: () => void;
}

/** One widget in its card (spec §4): the h2 is the title link to the full view, and the widget renders inside its own
 *  error boundary and Suspense (its code loads on demand). Nothing for a type this dashboard does not know. */
export default function WidgetCard({ projectId, widget, tools, onOpenSettings }: Props) {
  const def = definitionOf(widget.type);
  if (def === undefined) return null;
  const settings = withDefaults(def, widget.settings);
  const title = def.cardTitle ? def.cardTitle(settings) : def.title;
  const titleId = `ov-${widget.id}-title`;
  const heading = <h2 id={titleId}><Link to={def.link(projectId, settings)}>{title}</Link></h2>;
  const Body = def.Component;
  const loading = (
    <>
      {heading}
      <SkeletonStat label={`Loading ${title}…`} />
    </>
  );
  return (
    <section className={widget.size === "wide" ? "card wide" : "card"} aria-labelledby={titleId} data-widget-id={widget.id} tabIndex={-1}>
      {tools}
      {/* New settings render a failed widget again */}
      <WidgetBoundary heading={heading} title={title} resetKey={JSON.stringify(settings)}>
        <Suspense fallback={loading}>
          <Body projectId={projectId} settings={settings} size={widget.size} heading={heading} titleId={titleId} onOpenSettings={onOpenSettings} />
        </Suspense>
      </WidgetBoundary>
    </section>
  );
}
