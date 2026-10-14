import { useMemo, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Info, XCircle } from "lucide-react";
import { type LatestResult, getLatestResults } from "../api/analytics";
import { type Case, type FeatureCase, type FeatureDetail, listCases } from "../api/cases";
import { MAX_RUN_CASES } from "../api/runRequests";
import { caseAsOfRun, useRunStrips } from "../components/CaseTable";
import ErrorBanner from "../components/ErrorBanner";
import { featureLabel } from "../components/FeatureList";
import FailedTipAnchor from "../components/FailedTipAnchor";
import FailedStepTip from "../components/FailedStepTip";
import { type StepSpread, useStepSpread } from "../lib/failedSteps";
import GherkinBlock from "../components/GherkinBlock";
import LastResultPill from "../components/LastResultPill";
import RunContextNote from "../components/RunContextNote";
import PageHeader from "../components/PageHeader";
import RunControl from "../components/RunControl";
import { type Block, splitFeature } from "../lib/featureBlocks";
import { locateFailedStep, scenarioSteps, stepLines } from "../lib/failedStep";
import { GROUP_CASES_MAX, featureDetailQuery, fileLabel } from "../lib/featureQueries";
import { runParam, useScrollToFailure } from "../lib/runContext";
import { useCanEdit } from "../lib/useCanEdit";

const LATEST_BATCH = 500;
const HEADING = /^\s*[^\s:#@|][^:#@|]*:/;

/** The file as the cases hold it, for a file imported before raw files were stored: the Feature line, then
 *  each scenario's own Gherkin (or its title), with the line its heading lands on. */
export function rebuildFeature(detail: FeatureDetail, cases: Case[]): { text: string; lines: Map<number, number> } {
  const byNumber = new Map(cases.map((c) => [c.number, c]));
  const out = [`Feature: ${detail.feature_name ?? featureLabel(detail)}`];
  const lines = new Map<number, number>();
  for (const fc of detail.cases) {
    out.push("");
    const block = (byNumber.get(fc.number)?.gherkin ?? `Scenario: ${fc.title}`).replace(/\s+$/, "").split("\n");
    const heading = block.findIndex((l) => HEADING.test(l));
    lines.set(fc.number, out.length + 1 + Math.max(heading, 0));
    out.push(...block);
  }
  return { text: out.join("\n"), lines };
}

/** "3 passed · 1 failed · 2 no runs": cases by the status of their latest result (or of one run: "not in run"). */
function statusCounts(statuses: (string | undefined)[], none = "no runs"): string {
  const n = new Map<string, number>();
  for (const st of statuses) n.set(st ?? none, (n.get(st ?? none) ?? 0) + 1);
  const order = (k: string) => (k === none ? 2 : k === "passed" ? 0 : k === "failed" ? 1 : 1.5);
  return [...n].sort((x, y) => order(x[0]) - order(y[0])).map(([k, v]) => `${v} ${k}`).join(" · ");
}

/** A step the scenario inherits (its Background, feature- or rule-level) failed: named on the card, with the same tip as a failed line. */
function BackgroundFailure({ projectId, step, result, spread }: { projectId: number; step: string; result: LatestResult; spread?: StepSpread }) {
  return (
    <p className="scenario-bg-failure">
      <FailedTipAnchor className="scenario-bg-failure-line" tip={<FailedStepTip projectId={projectId} result={result} spread={spread} />}>
        <XCircle size={14} aria-hidden="true" />
        Failed in Background: {step}
      </FailedTipAnchor>
    </p>
  );
}

/** One .feature file: its raw text with each scenario linked to its case, and Run feature. */
export default function FeaturePage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const canEdit = useCanEdit(id);
  const [params] = useSearchParams();
  const path = params.get("path") ?? "";
  // Opened from a Last runs bar: every scenario as of that run
  const runId = runParam(params);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const detail = useQuery({ ...featureDetailQuery(id, path), enabled: path !== "" });
  const data = detail.data;
  // Not stored yet: the scenarios are rebuilt from the cases' own Gherkin
  const rebuilt = useQuery({
    queryKey: ["feature-rebuild", id, path],
    enabled: data != null && data.content == null,
    queryFn: async () => {
      const page = await listCases(id, {
        feature: data!.feature_name ?? undefined, folder: data!.folder || undefined, origin: "imported", limit: GROUP_CASES_MAX, offset: 0,
      });
      return page.items.filter((c) => c.source_path === path);
    },
  });
  const source = useMemo(() => {
    if (!data) return null;
    if (data.content != null) {
      return { text: data.content, lines: new Map(data.cases.flatMap((c) => (c.line != null ? [[c.number, c.line] as const] : []))) };
    }
    return rebuilt.data ? rebuildFeature(data, rebuilt.data) : null;
  }, [data, rebuilt.data]);
  const cases = useMemo(() => data?.cases ?? [], [data]);
  const keys = useMemo(() => [...new Set(cases.flatMap((c) => (c.automated_test_key ? [c.automated_test_key] : [])))], [cases]);
  const { lastRuns } = useRunStrips(id, keys);
  const latest = useQuery({
    queryKey: ["latest-results", "feature", id, keys, runId],
    enabled: keys.length > 0,
    queryFn: async () => {
      const merged: Record<string, LatestResult> = {};
      const batches: string[][] = [];
      for (let i = 0; i < keys.length; i += LATEST_BATCH) batches.push(keys.slice(i, i + LATEST_BATCH));
      for (const r of await Promise.all(batches.map((b) => getLatestResults(id, b, runId ?? undefined)))) Object.assign(merged, r.results);
      return merged;
    },
  });

  const results = latest.data ?? {};
  const resultOf = (c: FeatureCase) => (c.automated_test_key ? results[c.automated_test_key.toLowerCase()] : undefined);
  const spreadOf = useStepSpread(id, cases.map(resultOf));
  const split = useMemo(() => {
    if (!source) return null;
    return splitFeature(source.text, [...source.lines.values()]);
  }, [source]);
  const stored = data?.content != null;

  /** Where a case's failed step is: a line inside its own block, or the Background in the preamble. */
  const failureOf = (c: FeatureCase, block: Block): { line?: number; background?: string; result: LatestResult } | null => {
    const result = resultOf(c);
    const step = result?.failed_step;
    const heading = source?.lines.get(c.number);
    if (!result || !step || !source || heading == null) return null;
    // A rebuilt file holds each case's own Gherkin, Background included: read the block itself
    const steps = stored ? scenarioSteps(source.text, heading) : stepLines(source.text, block.start, block.end);
    // A file rebuilt from the cases has its own line numbers: only the text can be trusted
    const at = locateFailedStep(steps, stored ? step : { text: step.text });
    if (at == null) return null;
    const line = steps[at].line;
    if (line >= block.start && line <= block.end) return { line: line - block.start + 1, result };
    // Outside the scenario's own block: inherited from a Background (feature- or rule-level)
    return { background: steps[at].text, result };
  };

  const cards: { c: FeatureCase; block: Block }[] = [];
  const unplaced: FeatureCase[] = [];
  if (source && split) {
    const used = new Set<number>();
    for (const c of cases) {
      const line = source.lines.get(c.number);
      const block = line != null && !used.has(line) ? split.scenarios.get(line) : undefined;
      if (block && line != null) { used.add(line); cards.push({ c, block }); } else unplaced.push(c);
    }
  }
  const counts = latest.isSuccess ? statusCounts(cases.map((c) => resultOf(c)?.status), runId != null ? "not in run" : undefined) : "";
  const anyFailure = cards.some(({ c, block }) => failureOf(c, block)?.line != null);
  const title = data ? featureLabel(data) : fileLabel(path) || "Feature";
  useScrollToFailure(runId, anyFailure);

  return (
    <section>
      <PageHeader
        title={title}
        subtitle={<code>{path}</code>}
        headingRef={headingRef}
        actions={canEdit && data ? (
          <RunControl projectId={id} label="Run feature"
            cases={cases.slice(0, MAX_RUN_CASES).map((c) => ({ number: c.number, title: c.title, testKey: c.automated_test_key }))}
            selection={{ case_numbers: cases.slice(0, MAX_RUN_CASES).map((c) => c.number) }}
            emptyReason="This feature has no scenarios" />
        ) : undefined}
      />
      {path === "" && <p className="muted">No feature file was named.</p>}
      {detail.error != null && <ErrorBanner error={detail.error} onRetry={() => detail.refetch()} />}
      {rebuilt.error != null && <ErrorBanner error={rebuilt.error} onRetry={() => rebuilt.refetch()} />}
      {(detail.isLoading || rebuilt.isLoading) && <p className="muted">Loading the feature…</p>}
      {data && data.content == null && (
        <p className="note" role="note">
          <Info size={16} aria-hidden="true" />
          <span>Re-import this file to see it exactly as written.</span>
        </p>
      )}
      {runId != null && data && (
        <RunContextNote projectId={id} runId={runId} error={latest.error ?? undefined}
          startedAt={Object.values(results)[0]?.started_at}
          missing={latest.isSuccess && Object.keys(results).length === 0 ? `No scenario of this feature was in run #${runId}.` : undefined}
          latestHref={`/projects/${id}/cases/feature?path=${encodeURIComponent(path)}`} />
      )}
      {counts !== "" && <p className="muted feature-counts">{counts}</p>}
      {latest.error != null && runId == null && <p className="muted">The latest results could not be loaded.</p>}
      {split?.preamble && (
        <div className="card feature-source">
          <GherkinBlock text={split.preamble.text} label="Feature" numbered startLine={split.preamble.start} />
        </div>
      )}
      {cards.map(({ c, block }) => {
        const failure = failureOf(c, block);
        const result = resultOf(c);
        return (
          <article key={c.number} className="card scenario-card" aria-label={`${c.key} ${c.title}`}>
            <div className="scenario-card-head">
              <h2>
                <Link className="case-chip" to={`/projects/${id}/cases/${c.number}`}>{c.key}</Link>
                <span className="scenario-card-title">{c.title}</span>
              </h2>
              <div className="scenario-card-status">
                {c.automated_test_key != null && latest.isSuccess && (runId != null && !result
                  ? <span className="badge badge-muted">Not in run #{runId}</span>
                  : <LastResultPill result={result} />)}
                {lastRuns(c.automated_test_key, { hideEmpty: latest.isSuccess, href: caseAsOfRun(id, c.number) })}
              </div>
            </div>
            {failure?.background != null && <BackgroundFailure projectId={id} step={failure.background} result={failure.result} spread={spreadOf(failure.result)} />}
            <div className="feature-source">
              <GherkinBlock text={block.text} label={`${c.key} Gherkin`} numbered startLine={block.start}
                failed={failure?.line != null
                  ? { line: failure.line, tip: <FailedStepTip projectId={id} result={failure.result} spread={spreadOf(failure.result)} /> }
                  : undefined} />
            </div>
          </article>
        );
      })}
      {unplaced.length > 0 && (
        <div className="card">
          <h2>Scenarios not found in the file</h2>
          <ul className="ordered-cases">
            {unplaced.map((c) => (
              <li key={c.number}>
                <span className="muted">{c.key}</span>
                <Link className="case-title" to={`/projects/${id}/cases/${c.number}`}>{c.title}</Link>
                {lastRuns(c.automated_test_key, { href: caseAsOfRun(id, c.number) })}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
