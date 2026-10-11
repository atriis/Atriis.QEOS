import type { ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";

interface Props {
  /** What is absent and why, as a plain sentence. */
  children: ReactNode;
  /** Opens this widget's settings; without it (the editor's own preview) no button shows. */
  onOpenSettings?: () => void;
}

/** A widget whose settings leave it nothing to show (spec §2.8): said plainly, never an error and never a zero, with
 *  the way out. EmptyBranch and My recent failures use it. */
export default function WidgetEmpty({ children, onOpenSettings }: Props) {
  return (
    <div className="overview-empty">
      <p className="muted">{children}</p>
      {onOpenSettings && (
        <button type="button" onClick={onOpenSettings}><SlidersHorizontal size={15} aria-hidden="true" /> Change settings</button>
      )}
    </div>
  );
}
