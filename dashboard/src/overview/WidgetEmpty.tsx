import { type ReactNode, useId } from "react";
import { SlidersHorizontal } from "lucide-react";

interface Props {
  /** What is absent and why, as a plain sentence. */
  children: ReactNode;
  /** Opens this widget's settings; without it (the editor's own preview) no button shows. */
  onOpenSettings?: () => void;
  /** The id of the widget's card title: the button's name then says which widget it changes. */
  titleId?: string;
}

/** A widget whose settings leave it nothing to show (spec §2.8): said plainly, never an error and never a zero, with
 *  the way out. EmptyBranch and My recent failures use it. */
export default function WidgetEmpty({ children, onOpenSettings, titleId }: Props) {
  const buttonId = useId();
  return (
    <div className="overview-empty">
      <p className="muted">{children}</p>
      {onOpenSettings && (
        <button
          type="button" id={buttonId} onClick={onOpenSettings}
          aria-labelledby={titleId ? `${buttonId} ${titleId}` : undefined}
        ><SlidersHorizontal size={15} aria-hidden="true" /> <span>Change settings</span></button>
      )}
    </div>
  );
}
