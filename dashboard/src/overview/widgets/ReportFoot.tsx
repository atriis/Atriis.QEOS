import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

/** A report widget's card foot: the Report at the widget's section, as its title links. */
export default function ReportFoot({ to }: { to: string }) {
  return (
    <div className="card-foot">
      <Link className="link-arrow" to={to}>Report <ArrowRight size={14} aria-hidden="true" /></Link>
    </div>
  );
}
