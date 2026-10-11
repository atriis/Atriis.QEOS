import { useQuery } from "@tanstack/react-query";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { decodeTests, neverRun, unlinkedTestCount } from "../../lib/reportScope";
import { caseAreasQuery, caseAreasMessage } from "../../pages/report/useReportRequest";
import { useWidgetReport } from "../reportWidget";
import ReportFoot from "./ReportFoot";
import { coverage } from "./coverage";
import type { WidgetProps } from "./types";

const number = new Intl.NumberFormat();

/** The Report's coverage join, unchanged (ADR-026): test management's case areas under the Report's key, and the tests
 *  section over the period, across every branch (plan Ruling 13). */
export default function CoverageWidget({ projectId, settings, heading }: WidgetProps) {
  const period = settings.period ?? 30;
  const areas = useQuery(caseAreasQuery(projectId));
  const tests = useWidgetReport(projectId, "tests", period, undefined);
  const section = tests.data?.tests;
  const rows = section ? decodeTests(section) : [];
  // A test cut off by the 50,000-row cap would look never run, so those two counts are not shown then
  const cut = section?.truncated === true;
  const failed = areas.error != null || tests.error != null;
  return (
    <>
      {heading}
      {(areas.isPending || tests.isPending) && !failed && <SkeletonStat label="Loading coverage…" />}
      {areas.error != null && (
        <ErrorBanner error={areas.error} message={caseAreasMessage(areas.error)} onRetry={() => areas.refetch()} />
      )}
      {tests.error != null && <ErrorBanner error={tests.error} onRetry={() => tests.refetch()} />}
      {areas.data && section && (
        <>
          <dl className="overview-figures">
            <div><dt>Active cases</dt><dd>{number.format(areas.data.counts.cases)}</dd></div>
            <div><dt>Linked (automated)</dt><dd>{number.format(areas.data.counts.linked)}</dd></div>
            <div><dt>Manual</dt><dd>{number.format(areas.data.counts.manual)}</dd></div>
            {!cut && <div><dt>Automated, not run in {period} days</dt><dd>{number.format(neverRun(areas.data, rows, { kind: "all" }).length)}</dd></div>}
            {!cut && <div><dt>Tests without a case</dt><dd>{number.format(unlinkedTestCount(areas.data, rows))}</dd></div>}
          </dl>
          {cut && <p className="muted">The test list was cut at 50,000 tests, so cases not run and tests without a case are not counted.</p>}
        </>
      )}
      <ReportFoot to={coverage.link(projectId, settings)} />
    </>
  );
}
