import { useEffect, useRef, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import { Printer, RefreshCw, X } from "lucide-react";
import { ApiError } from "../../api/http";
import { getProject } from "../../api/orgs";
import { ChartPatternDefs } from "../../components/ChartKit";
import PageHeader from "../../components/PageHeader";
import PrintHeader from "./PrintHeader";
import ReportFilterBar from "./ReportFilterBar";
import { describeFilters, formatPeriod } from "./describeFilters";
import AreaSection from "./sections/AreaSection";
import CoverageDurationSection from "./sections/CoverageDurationSection";
import FailureCausesSection from "./sections/FailureCausesSection";
import ImpactSection from "./sections/ImpactSection";
import RegressionsSection from "./sections/RegressionsSection";
import SummarySection from "./sections/SummarySection";
import { accuracyDays } from "../../lib/impactQueries";
import { todayIn, useReportFilters } from "./useReportFilters";
import { useReportRequest, useReportSection } from "./useReportRequest";

/** How long the cleared live region stays empty before "Report updated" is written, so the same words written again
 *  are a change a screen reader reads, and so a section that starts fetching just after the filters change (a
 *  child's query starts in its effect) can still mark the page busy first. */
export const ANNOUNCE_DELAY_MS = 150;

/** "Report updated", once, when every section asked after a filter change has settled (spec: Filter bar). The first
 *  load is not announced, nor is a change where any requested section failed (its error banner says so). */
export function useAnnouncement(signature: string | null, busy: boolean, failed = false): string {
  const [message, setMessage] = useState("");
  const last = useRef<string | null>(null);
  const waiting = useRef(false);
  useEffect(() => {
    if (signature === null) return;
    if (last.current !== null && last.current !== signature) {
      waiting.current = true;
      setMessage("");
    }
    last.current = signature;
  }, [signature]);
  useEffect(() => {
    if (!waiting.current || busy) return;
    const timer = window.setTimeout(() => {
      waiting.current = false;
      if (!failed) setMessage("Report updated");
    }, ANNOUNCE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [busy, signature, failed]);
  return message;
}

/** Keeps every chart's data table open on paper (spec: Print / Save as PDF). */
function usePrintOpensDataTables() {
  useEffect(() => {
    const opened: HTMLDetailsElement[] = [];
    const before = () => {
      document.querySelectorAll<HTMLDetailsElement>(".report details.chart-data:not([open])").forEach((d) => {
        d.open = true;
        opened.push(d);
      });
    };
    const after = () => opened.splice(0).forEach((d) => { d.open = false; });
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);
}

/** Brings the section named by the URL's `#report-…` anchor into view once the page has settled (the Overview's widget
 *  links land here): scrolled to, smoothly unless the reader prefers reduced motion, and its heading focused so keyboard
 *  and screen-reader users start there. Once per anchor; a section that is absent is left alone. */
export function useScrollToSection(hash: string, ready: boolean) {
  const done = useRef<string | null>(null);
  useEffect(() => {
    if (!ready || !hash || done.current === hash) return;
    let name: string;
    try { name = decodeURIComponent(hash.slice(1)); } catch { return; }
    const target = document.getElementById(name);
    if (!target) return;
    done.current = hash;
    const reduced = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "start" });
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
  }, [hash, ready]);
}

/** The server's tz 422s: "Unknown time zone: 'X'" from _zone(), or a field error on tz (e.g. longer than 64). */
export function isZoneError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 422 && /^(unknown time zone|tz:)/i.test(error.detail);
}

export default function ReportPage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  // A zone the server's list lacks answers every section with a 422 that Reset filters cannot fix: the page then
  // moves to UTC (dates and the request use the same zone, so the period stays consistent) and says so
  const [zoneRejected, setZoneRejected] = useState(false);
  const [zoneNoticeDismissed, setZoneNoticeDismissed] = useState(false);
  const tz = zoneRejected ? "UTC" : browserTz;
  const today = todayIn(tz);
  const qc = useQueryClient();
  const { filters, update, clearAll, notice, dismissNotice } = useReportFilters(tz);
  const impactDays = accuracyDays(filters.days, filters.to, today);
  const project = useQuery({ queryKey: ["project", id], queryFn: () => getProject(id) });
  const { gate, caseAreas, runUrls, defaultBranch, effectiveBranch } = useReportRequest(id, filters, tz, { loadCaseAreas: true });
  const summary = useReportSection(id, gate, "summary");
  const causes = useReportSection(id, gate, "failure_causes");
  const regressions = useReportSection(id, gate, "regressions");
  const tests = useReportSection(id, gate, "tests");
  const duration = useReportSection(id, gate, "duration");
  const sections = [summary, causes, tests, regressions, duration];
  usePrintOpensDataTables();
  useEffect(() => {
    if (!zoneRejected && tz !== "UTC" && isZoneError(summary.error)) setZoneRejected(true);
  }, [summary.error, tz, zoneRejected]);

  // Every section's request counts (the summary's own status covers the render before its fetch is registered)
  const fetchingSections = useIsFetching({ queryKey: ["report", id] });
  const busy = sections.some((q) => q.fetchStatus === "fetching") || fetchingSections > 0;
  const announcement = useAnnouncement(gate.state === "ready" ? JSON.stringify(gate.key) : null, busy, sections.some((q) => q.isError));
  useScrollToSection(useLocation().hash, gate.state !== "wait" && !busy);
  const applied = describeFilters(filters, defaultBranch, caseAreas.data);
  const generated = summary.data?.generated_at ?? null;
  const subtitle = `${project.data?.name ?? "Project"}: quality report. ${formatPeriod(filters.from, filters.to)} (${filters.days} days), ${tz}.`
    + (generated ? ` Generated ${new Date(generated).toLocaleString()}.` : "")
    + (applied.length ? ` ${applied.map((f) => `${f.name}: ${f.value}`).join("; ")}.` : "");

  function refresh() {
    for (const key of [["report", id], ["case-areas", id], ["run-urls", id]]) {
      void qc.invalidateQueries({ queryKey: key });
    }
  }

  return (
    <div className="report">
      <ChartPatternDefs />
      <PageHeader
        title="Report"
        subtitle={subtitle}
        actions={
          <div className="report-actions no-print">
            <button type="button" onClick={refresh}><RefreshCw size={15} aria-hidden="true" /> Refresh</button>
            <button type="button" onClick={() => window.print()}><Printer size={15} aria-hidden="true" /> Save as PDF</button>
          </div>
        }
      />
      <PrintHeader filters={filters} tz={tz} applied={applied} generatedAt={generated} />
      {notice && (
        <div className="report-notice no-print" role="status">
          <span>Some filters in the link were not valid and were removed</span>
          <button type="button" className="ghost" aria-label="Dismiss the notice" onClick={dismissNotice}><X size={14} aria-hidden="true" /></button>
        </div>
      )}
      {zoneRejected && !zoneNoticeDismissed && (
        <div className="report-notice no-print" role="status">
          <span>Your time zone isn't supported by the server; dates use UTC.</span>
          <button type="button" className="ghost" aria-label="Dismiss the time zone notice" onClick={() => setZoneNoticeDismissed(true)}><X size={14} aria-hidden="true" /></button>
        </div>
      )}
      <ReportFilterBar
        filters={filters} update={update} clearAll={clearAll} today={today} defaultBranch={defaultBranch}
        caseAreas={{ data: caseAreas.data, error: caseAreas.error, isPending: caseAreas.isFetching, refetch: caseAreas.refetch }}
        runUrls={{ error: runUrls.error, refetch: runUrls.refetch }}
        facets={summary.data?.summary?.facets}
      />
      <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
      <SummarySection projectId={id} gate={gate} query={summary} branch={effectiveBranch} environment={filters.environment}
        onClearFilters={clearAll} onTry={update} />
      <FailureCausesSection projectId={id} gate={gate} query={causes} branch={effectiveBranch} onResetFilters={clearAll} />
      <AreaSection projectId={id} gate={gate} query={tests} caseAreas={caseAreas} onResetFilters={clearAll} />
      <RegressionsSection projectId={id} gate={gate} query={regressions} branch={effectiveBranch} onResetFilters={clearAll} />
      <CoverageDurationSection projectId={id} gate={gate} testsQuery={tests} durationQuery={duration} caseAreas={caseAreas}
        filters={filters} onResetFilters={clearAll} />
      {/* Ruling 21: the Report's period when it is the last 7, 14 or 30 days, else 30 days, said in the note */}
      <ImpactSection projectId={id} days={impactDays} followsReport={impactDays === filters.days && filters.to === today}
        onResetFilters={clearAll} />
    </div>
  );
}
