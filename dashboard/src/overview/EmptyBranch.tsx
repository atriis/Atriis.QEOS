import { SlidersHorizontal } from "lucide-react";

interface Props {
  branch: string;
  /** The widget's period, in days. */
  days: number;
  onOpenSettings?: () => void;
}

/** A widget set to a branch with no runs in its period (spec §2.8): said plainly, never an error and never a zero, with
 *  the way out. Every widget with a branch setting uses this one state. */
export default function EmptyBranch({ branch, days, onOpenSettings }: Props) {
  return (
    <div className="overview-empty">
      <p className="muted">No runs on {branch} in the last {days} days</p>
      {onOpenSettings && (
        <button type="button" onClick={onOpenSettings}><SlidersHorizontal size={15} aria-hidden="true" /> Change settings</button>
      )}
    </div>
  );
}
