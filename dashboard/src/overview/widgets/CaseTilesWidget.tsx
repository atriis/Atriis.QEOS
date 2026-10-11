import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import CasesKpis from "../../components/CasesKpis";
import { caseTiles } from "./caseTiles";
import type { WidgetProps } from "./types";

/** The Cases view's four KPI tiles, unchanged and under their own query keys: each tile loads, fails and retries on its
 *  own. */
export default function CaseTilesWidget({ projectId, settings, heading }: WidgetProps) {
  return (
    <>
      {heading}
      <CasesKpis projectId={projectId} />
      <div className="card-foot">
        <Link className="link-arrow" to={caseTiles.link(projectId, settings)}>Cases <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
