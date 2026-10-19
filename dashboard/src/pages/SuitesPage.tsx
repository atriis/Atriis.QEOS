import { ChevronRight } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suite, createSuite, listSuites, shardText } from "../api/cases";
import ErrorBanner from "../components/ErrorBanner";
import RunControl from "../components/RunControl";
import { useCanEdit } from "../lib/useCanEdit";
import PageHeader from "../components/PageHeader";
import { tableCardClass, useIsWide } from "../lib/useIsWide";

const MANUAL_GROUP = "Made in QEOS";

export interface SuiteGroup { key: string; group: string; workflow: string | null; suites: Suite[] }

/** Repository suites grouped by workflow file (shown by group name, ordered by it), then the hand-made ones.
 *  Two workflows with the same `name:` stay two groups, so Run all dispatches the right file. */
export function groupSuites(suites: Suite[]): SuiteGroup[] {
  const repo = new Map<string, SuiteGroup>();
  const manual: Suite[] = [];
  for (const s of suites) {
    if (s.origin !== "repository") {
      manual.push(s);
      continue;
    }
    const key = `repo:${s.workflow ?? ""}`;
    const entry = repo.get(key) ?? { key, group: s.group_name ?? s.workflow ?? "Repository", workflow: s.workflow ?? null, suites: [] };
    entry.suites.push(s);
    repo.set(key, entry);
  }
  const out = [...repo.values()].sort((a, b) => a.group.localeCompare(b.group) || (a.workflow ?? "").localeCompare(b.workflow ?? ""));
  if (manual.length > 0) out.push({ key: "manual", group: MANUAL_GROUP, workflow: null, suites: manual });
  return out;
}

/** The group's name for labels: with the workflow file when another group shows the same name. */
function groupLabel(g: SuiteGroup, all: SuiteGroup[]): string {
  return g.workflow && all.some((o) => o !== g && o.group === g.group) ? `${g.group} (${g.workflow})` : g.group;
}

/** The project's suites: named, ordered lists of test cases. */
export default function SuitesPage() {
  // The header sticks only while the table fits its card; a wide table keeps its sideways scroll
  const card = useIsWide<HTMLDivElement>();
  const { projectId } = useParams();
  const id = Number(projectId);
  const canEdit = useCanEdit(id);
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const suites = useQuery({ queryKey: ["suites", id], queryFn: () => listSuites(id) });
  const create = useMutation({
    mutationFn: () => createSuite(id, { name: name.trim(), ...(description.trim() ? { description: description.trim() } : {}) }),
    onSuccess: () => {
      setName("");
      setDescription("");
      return qc.invalidateQueries({ queryKey: ["suites", id] });
    },
  });

  const groups = suites.data ? groupSuites(suites.data) : [];
  const first = groups[0];

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <section>
      <PageHeader title="Suites" tabs={[{ label: "Cases", to: "../cases" }, { label: "Suites" }]} />

      {suites.error != null && <ErrorBanner error={suites.error} onRetry={() => suites.refetch()} />}
      {suites.isPending && <p className="muted">Loading suites…</p>}
      {suites.data?.length === 0 && (
        <p className="muted">No suites yet. A suite groups cases to run together, such as a smoke check before each deploy.</p>
      )}
      {groups.map((g) => (
        <details key={g.key} className="suite-group" open>
          <summary>
            <ChevronRight className="chevron" size={16} aria-hidden="true" />
            <h2>{g.group} <span className="muted">({g.suites.length} {g.suites.length === 1 ? "suite" : "suites"})</span></h2>
            {g.workflow && <span className="muted">{g.workflow}</span>}
          </summary>
          {canEdit && g.workflow && (
            <RunControl projectId={id} cases={[]} selection={{ workflow_group: g.workflow }} label="Run all" ariaLabel={`Run all ${groupLabel(g, groups)}`} emphasis={false}
              repo={{ workflow: g.workflow, sourceRepo: g.suites.find((x) => x.source_repo)?.source_repo ?? null, subject: "all its suites", all: true, title: `Run all ${groupLabel(g, groups)}?` }} />
          )}
          <div ref={g.key === first?.key ? card.ref : undefined} className={tableCardClass(card.wide)} tabIndex={0} role="region" aria-label={`${groupLabel(g, groups)} suites`}>
            <table className="data">
              <caption className="sr-only">{groupLabel(g, groups)} suites</caption>
              <thead>
                <tr><th>Suite</th><th className="num">Cases</th><th className="hide-narrow">Changed</th>{canEdit && g.workflow && <th><span className="sr-only">Run</span></th>}</tr>
              </thead>
              <tbody>
                {g.suites.map((s) => (
                  <tr key={s.id}>
                    <td className="wrap-anywhere">
                      <Link to={`${s.id}`}>{s.name}</Link>
                      {s.origin === "repository" && <span className="badge">From repository</span>}
                      {s.shard && <span className="badge">{shardText(s.shard)}</span>}
                      {s.description && <div className="muted">{s.description}</div>}
                    </td>
                    <td className="num">{s.case_count}</td>
                    <td className="hide-narrow">{new Date(s.updated_at ?? s.created_at).toLocaleDateString()}</td>
                    {canEdit && g.workflow && (
                      <td className="run-cell">
                        {s.origin === "repository" && s.workflow && (
                          <RunControl projectId={id} cases={[]} selection={{ suite_id: s.id }} label="Run" ariaLabel={`Run ${s.name}`} emphasis={false}
                            repo={{ workflow: s.workflow, sourceRepo: s.source_repo ?? null, subject: s.external_id ?? s.name, title: `Run ${s.name}?`, noCases: s.case_count === 0 }} />
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}

      {canEdit && (
        <form className="card form-stack" onSubmit={onSubmit}>
          <h2>New suite</h2>
          <label>
            Name
            <input required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Smoke" />
          </label>
          <label>
            <span>Description <span className="muted">(optional)</span></span>
            <input maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          {create.error != null && <ErrorBanner error={create.error} />}
          <div className="button-row">
            <button className="primary" type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create suite"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
