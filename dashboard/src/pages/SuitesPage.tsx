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

/** Repository suites grouped by workflow group (ordered by name), then the hand-made ones. */
export function groupSuites(suites: Suite[]): { group: string; workflow: string | null; suites: Suite[] }[] {
  const repo = new Map<string, { group: string; workflow: string | null; suites: Suite[] }>();
  const manual: Suite[] = [];
  for (const s of suites) {
    if (s.origin !== "repository") {
      manual.push(s);
      continue;
    }
    const group = s.group_name ?? s.workflow ?? "Repository";
    const entry = repo.get(group) ?? { group, workflow: s.workflow ?? null, suites: [] };
    entry.suites.push(s);
    repo.set(group, entry);
  }
  const out = [...repo.values()].sort((a, b) => a.group.localeCompare(b.group));
  if (manual.length > 0) out.push({ group: MANUAL_GROUP, workflow: null, suites: manual });
  return out;
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

  const first = suites.data ? groupSuites(suites.data)[0] : undefined;

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
      {suites.data != null && groupSuites(suites.data).map((g) => (
        <details key={g.group} className="suite-group" open>
          <summary>
            <ChevronRight className="chevron" size={16} aria-hidden="true" />
            <h2>{g.group} <span className="muted">({g.suites.length} {g.suites.length === 1 ? "suite" : "suites"})</span></h2>
            {g.workflow && <span className="muted">{g.workflow}</span>}
          </summary>
          {canEdit && g.workflow && (
            <RunControl projectId={id} cases={[]} selection={{ workflow_group: g.workflow }} label="Run all" ariaLabel={`Run all ${g.group}`} emphasis={false}
              repo={{ workflow: g.workflow, sourceRepo: g.suites.find((x) => x.source_repo)?.source_repo ?? null, subject: "all its suites", all: true, title: `Run all ${g.group}?` }} />
          )}
          <div ref={g === first ? card.ref : undefined} className={tableCardClass(card.wide)} tabIndex={0} role="region" aria-label={`${g.group} suites`}>
            <table className="data">
              <caption className="sr-only">{g.group} suites</caption>
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
