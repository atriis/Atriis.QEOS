import WidgetEmpty from "./WidgetEmpty";

interface Props {
  branch: string;
  /** The widget's period, in days; a widget without one (Recent runs) names only the branch. */
  days?: number;
  onOpenSettings?: () => void;
}

/** A widget set to a branch with no runs in its period (spec §2.8). Every widget with a branch setting uses this one
 *  state. */
export default function EmptyBranch({ branch, days, onOpenSettings }: Props) {
  return (
    <WidgetEmpty onOpenSettings={onOpenSettings}>
      {days === undefined ? `No runs on ${branch}` : `No runs on ${branch} in the last ${days} days`}
    </WidgetEmpty>
  );
}
