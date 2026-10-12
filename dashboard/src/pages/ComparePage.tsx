import { FormEvent, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CompareItem, RunOverview, compareRuns } from "../api/runs";
import { formatDuration } from "../api/analytics";
import ErrorBanner from "../components/ErrorBanner";
import NarrowMeta from "../components/NarrowMeta";
import SortableTh from "../components/SortableTh";
import StatusDot from "../components/StatusDot";
import { nextSort, parseSort, sortRows, SortState } from "../lib/sort";
import { plural } from "../lib/words";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";

const MAX_LISTED = 200;
// One order for every section, kept in the URL; the API returns at most 200 per section, so this sorts what is shown
const SORT_KEYS = ["name", "before", "now", "change"] as const;
type SortKey = (typeof SORT_KEYS)[number];
const DEFAULT_SORT: SortState<SortKey> = { key: "name", dir: "asc" };

const SECTIONS = [
  { key: "new_failures", title: "New failures", hint: "Passed in the base run, fail now." },
  { key: "fixed", title: "Fixed", hint: "Failed in the base run, pass now." },
  { key: "still_failing", title: "Still failing", hint: "Failing in both runs." },
  { key: "slower", title: "Slower", hint: "Passed in both, at least 1 s and 50% slower now." },
  { key: "added", title: "Added", hint: "Only in this run." },
  { key: "removed", title: "Removed", hint: "Only in the base run." },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

function RunLine({ label, run }: { label: string; run: RunOverview }) {
  return (
    <p className="muted compare-run">
      <strong>{label}</strong> <Link to={`../${run.id}`} relative="path">#{run.id}</Link> ·{" "}
      {new Date(run.started_at).toLocaleString()} · {run.branch ?? "no branch"} ·{" "}
      {run.commit_sha ? <code>{run.commit_sha.slice(0, 7)}</code> : "no commit"} · {run.passed} passed,{" "}
      {run.failed + run.errored} failing
    </p>
  );
}

function Status({ value }: { value: string | null }) {
  return value ? <StatusDot status={value} /> : <span className="muted">—</span>;
}

function Section({ projectId, kind, items, total, sort, onSort }: {
  projectId: string | undefined;
  sort: SortState<SortKey>;
  onSort: (key: SortKey) => void;
  kind: (typeof SECTIONS)[number];
  items: CompareItem[];
  total: number;
}) {
  const slower = kind.key === "slower";
  const rows = sortRows(items, sort, (t, key) => {
    if (key === "name") return t.name;
    if (key === "before") return slower ? t.base_duration_ms : t.base_status;
    if (key === "now") return slower ? t.head_duration_ms : t.head_status;
    return slower ? (t.head_duration_ms ?? 0) - (t.base_duration_ms ?? 0) : t.message;
  });
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLElement>();
  return (
    <section ref={card.ref} className={tableCardClass(card.wide)} aria-labelledby={`cmp-${kind.key}`} role="region">
      <h2 id={`cmp-${kind.key}`}>{kind.title} <span className="muted">({total})</span></h2>
      <p className="muted">{kind.hint}{total > items.length && ` Showing the first ${MAX_LISTED}.`}</p>
      <table className="data">
        <thead>
          <tr>
            <SortableTh label="Test" sortKey="name" sort={sort} onSort={onSort} />
            <SortableTh label="Before" sortKey="before" sort={sort} onSort={onSort} className={slower ? "num" : undefined} />
            <SortableTh label="Now" sortKey="now" sort={sort} onSort={onSort} className={slower ? "num" : undefined} />
            <SortableTh label={slower ? "Change" : "Message"} sortKey="change" sort={sort} onSort={onSort} className={slower ? "num" : "hide-narrow"} />
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.test_key}>
              <td className="wrap-anywhere">
                <Link to={`/projects/${projectId}/tests/${encodeURIComponent(t.test_key)}`}>{t.name}</Link>
                <div className="muted">{t.suite} / {t.class_name}</div>
                {!slower && <NarrowMeta items={[{ label: "Message", value: t.message ?? "—" }]} />}
              </td>
              {slower ? (
                <>
                  <td className="num">{formatDuration(t.base_duration_ms ?? 0)}</td>
                  <td className="num">{formatDuration(t.head_duration_ms ?? 0)}</td>
                  <td className="num">+{formatDuration((t.head_duration_ms ?? 0) - (t.base_duration_ms ?? 0))}</td>
                </>
              ) : (
                <>
                  <td><Status value={t.base_status} /></td>
                  <td><Status value={t.head_status} /></td>
                  <td className="hide-narrow wrap-anywhere">{t.message ? <code>{t.message}</code> : <span className="muted">—</span>}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** One run against another, test by test: what broke, what got fixed, what got slower. */
export default function ComparePage() {
  const { projectId, runId, baseId } = useParams();
  const head = Number(runId);
  const base = Number(baseId);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const sort = parseSort(params.get("sort"), params.get("dir"), SORT_KEYS, DEFAULT_SORT);
  const onSort = (key: SortKey) => {
    const next = nextSort(sort, key, "asc");
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next.key === DEFAULT_SORT.key && next.dir === DEFAULT_SORT.dir) {
        p.delete("sort");
        p.delete("dir");
      } else {
        p.set("sort", next.key);
        p.set("dir", next.dir);
      }
      return p;
    }, { replace: true });
  };
  const [other, setOther] = useState(String(base));
  useEffect(() => setOther(String(base)), [base]);

  const query = useQuery({ queryKey: ["compare", head, base], queryFn: () => compareRuns(head, base) });
  const data = query.data;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const next = Number(other);
    if (Number.isInteger(next) && next > 0) navigate(`/projects/${projectId}/runs/${head}/compare/${next}`);
  }

  const c = data?.counts;
  return (
    <section>
      <p>
        <Link className="link-arrow" to={`/projects/${projectId}/runs/${head}`}><ArrowLeft size={14} aria-hidden="true" /> Run #{head}</Link>
      </p>
      <PageHeader title={`Run #${head} compared with #${base}`} />

      <form className="filters" onSubmit={onSubmit}>
        <label>
          Compare with run #
          <input type="number" min={1} inputMode="numeric" required value={other} onChange={(e) => setOther(e.target.value)} />
        </label>
        <button type="submit">Compare</button>
      </form>

      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {query.isPending && <p className="muted">Comparing…</p>}
      {data && c && (
        <>
          <RunLine label="Base" run={data.base} />
          <RunLine label="Now" run={data.head} />
          <p className="compare-summary">
            {plural(c.new_failures, "new failure", "new failures")} · {c.fixed} fixed · {c.still_failing} still failing ·{" "}
            {c.slower} slower · {c.added} added · {c.removed} removed · {c.unchanged} unchanged
          </p>
          {SECTIONS.filter((s) => c[s.key as SectionKey] > 0).map((s) => (
            <Section key={s.key} projectId={projectId} kind={s} items={data[s.key as SectionKey]} total={c[s.key as SectionKey]} sort={sort} onSort={onSort} />
          ))}
          {SECTIONS.every((s) => c[s.key as SectionKey] === 0) && (
            <p className="muted">No test changed outcome or got notably slower.</p>
          )}
        </>
      )}
    </section>
  );
}
