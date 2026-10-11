import { ArrowDown, ArrowUp, Maximize2, SlidersHorizontal, Trash2 } from "lucide-react";

interface Props {
  title: string;
  first: boolean;
  last: boolean;
  wide: boolean;
  hasSettings: boolean;
  settingsOpen: boolean;
  onMove: (by: -1 | 1) => void;
  onSize: () => void;
  onSettings: () => void;
  onRemove: () => void;
}

/** Edit mode only (spec §2.2): labelled icon buttons, each named for its widget, 28 px (44 px on touch). */
export default function WidgetToolbar({ title, first, last, wide, hasSettings, settingsOpen, onMove, onSize, onSettings, onRemove }: Props) {
  return (
    <div className="widget-toolbar" role="group" aria-label={`${title} widget`}>
      <button type="button" className="ghost widget-tool" data-tool="up" aria-label={`Move ${title} up`} disabled={first} onClick={() => onMove(-1)}>
        <ArrowUp size={16} aria-hidden="true" />
      </button>
      <button type="button" className="ghost widget-tool" data-tool="down" aria-label={`Move ${title} down`} disabled={last} onClick={() => onMove(1)}>
        <ArrowDown size={16} aria-hidden="true" />
      </button>
      <button type="button" className="ghost widget-tool" data-tool="size" aria-label={`Show ${title} wide`} aria-pressed={wide} onClick={onSize}>
        <Maximize2 size={16} aria-hidden="true" />
      </button>
      {hasSettings && (
        <button type="button" className="ghost widget-tool" data-tool="settings" aria-label={`${title} settings`} aria-expanded={settingsOpen} onClick={onSettings}>
          <SlidersHorizontal size={16} aria-hidden="true" />
        </button>
      )}
      <button type="button" className="ghost widget-tool" data-tool="remove" aria-label={`Remove ${title}`} onClick={onRemove}>
        <Trash2 size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
