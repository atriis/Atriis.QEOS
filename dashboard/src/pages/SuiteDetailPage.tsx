import { FormEvent, useEffect, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowUp, X } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SuiteCase, deleteSuite, getSuite, listCases, setSuiteCases, shardText, updateSuite } from "../api/cases";
import ConfirmButton from "../components/ConfirmButton";
import RunControl from "../components/RunControl";
import ErrorBanner from "../components/ErrorBanner";
import UnsavedGuard from "../components/UnsavedGuard";
import { useCanEdit } from "../lib/useCanEdit";
import { estimateText, useDurationEstimate } from "../lib/durationEstimate";
import PageHeader from "../components/PageHeader";

/** One suite: its ordered cases, which members can add, remove and reorder, then save. */
export default function SuiteDetailPage() {
  const { projectId, suiteId } = useParams();
  const id = Number(projectId);
  const sid = Number(suiteId);
  const canEditProject = useCanEdit(id) === true;
  const qc = useQueryClient();
  const navigate = useNavigate();

  const suite = useQuery({ queryKey: ["suite", id, sid], queryFn: () => getSuite(id, sid) });
  // Edits live apart from the saved suite (null = untouched), so a refetch never overwrites them
  const [casesEdit, setCasesEdit] = useState<SuiteCase[] | null>(null);
  const [detailsEdit, setDetailsEdit] = useState<{ name: string; description: string } | null>(null);
  const cases = casesEdit ?? suite.data?.cases ?? [];
  const name = detailsEdit?.name ?? suite.data?.name ?? "";
  const description = detailsEdit?.description ?? suite.data?.description ?? "";
  const dirty = casesEdit !== null;
  const detailsDirty = detailsEdit !== null && (detailsEdit.name !== suite.data?.name || detailsEdit.description !== (suite.data?.description ?? ""));
  const setCases = (next: SuiteCase[]) => setCasesEdit(next);
  const setDetails = (patch: Partial<{ name: string; description: string }>) => setDetailsEdit({ name, description, ...patch });

  // The saved suite's automated cases are what Run suite runs (manual ones are skipped)
  const estimate = useDurationEstimate(id, (suite.data?.cases ?? []).filter((c) => c.source_path !== null).map((c) => c.automated_test_key));

  // A suite synced from the repository is read-only: its workflow decides what it holds
  const fromRepo = suite.data?.origin === "repository";
  const canEdit = canEditProject && !fromRepo;

  const [search, setSearch] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const found = useQuery({
    queryKey: ["cases", id, "pick", asked],
    queryFn: () => listCases(id, { search: asked || undefined, limit: 20, offset: 0 }),
    enabled: asked !== null,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["suites", id] });
    return qc.invalidateQueries({ queryKey: ["suite", id, sid] });
  };
  const saveCases = useMutation({
    mutationFn: () => setSuiteCases(id, sid, cases.map((c) => c.number)),
    onSuccess: async () => {
      await refresh();
      setCasesEdit(null);
    },
  });
  const saveDetails = useMutation({
    mutationFn: () => updateSuite(id, sid, { name: name.trim(), description: description.trim() || null }),
    onSuccess: async () => {
      await refresh();
      setDetailsEdit(null);
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteSuite(id, sid),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["suites", id] });
      // The suite is gone: drop its edits, then leave after the render that lifts the guard
      setCasesEdit(null);
      setDetailsEdit(null);
      setDeleted(true);
    },
  });
  const [deleted, setDeleted] = useState(false);
  useEffect(() => {
    if (deleted && casesEdit === null && detailsEdit === null) navigate(`/projects/${id}/suites`);
  }, [deleted, casesEdit, detailsEdit, navigate, id]);

  function move(i: number, by: number) {
    const next = [...cases];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setCases(next);
  }

  if (suite.error != null || suite.isPending) {
    return (
      <section>
        <PageHeader title="Suite" />
        {suite.error != null ? (
          <ErrorBanner error={suite.error} onRetry={() => suite.refetch()} />
        ) : (
          <p className="muted">Loading the suite…</p>
        )}
      </section>
    );
  }
  const inSuite = new Set(cases.map((c) => c.number));

  return (
    <section>
      <UnsavedGuard dirty={dirty || detailsDirty} />
      <p>
        <Link className="link-arrow" to=".." relative="path"><ArrowLeft size={14} aria-hidden="true" /> All suites</Link>
      </p>
      <PageHeader title={suite.data.name} subtitle={suite.data.description || undefined}
        meta={estimate.data?.estimate_ms != null ? `Estimated duration ${estimateText(estimate.data)}` : undefined} />
      {fromRepo && suite.data.workflow ? (
        // A repository suite runs through its own workflow, whatever cases QEOS holds for it
        <RunControl projectId={id} cases={[]} selection={{ suite_id: sid }} label="Run" ariaLabel={`Run ${suite.data.name}`}
          repo={{ workflow: suite.data.workflow, sourceRepo: suite.data.source_repo ?? null, subject: suite.data.external_id ?? suite.data.name,
            title: `Run ${suite.data.name}?`, noCases: suite.data.cases.length === 0 }} />
      ) : !fromRepo && (
        <RunControl projectId={id} cases={suite.data.cases.map((c) => ({ number: c.number, title: c.title, manual: c.source_path === null, testKey: c.automated_test_key }))}
          selection={{ suite_id: sid }} label="Run suite" emphasis={!dirty && !detailsDirty}
          emptyReason={suite.data.cases.length === 0 ? "This suite has no cases" : "This suite has no automated cases"} />
      )}

      {fromRepo && (
        <section className="card" aria-labelledby="suite-source">
          <h2 id="suite-source">From the repository</h2>
          <dl className="suite-facts">
            <dt>Workflow</dt><dd>{suite.data.workflow}</dd>
            <dt>Suite id</dt><dd>{suite.data.external_id}</dd>
            {suite.data.source_repo && <><dt>Repository</dt><dd>{suite.data.source_repo}</dd></>}
            {suite.data.shard && <><dt>Shard</dt><dd>{shardText(suite.data.shard)}</dd></>}
            {suite.data.test_paths && suite.data.test_paths.length > 0 && (
              <><dt>Test paths</dt><dd>{suite.data.test_paths.map((t) => <div key={t}>{t}</div>)}</dd></>
            )}
          </dl>
          {suite.data.shard && (
            <p className="muted">
              GitHub splits this folder between Half 1 and Half 2 at run time; both list the whole folder.
            </p>
          )}
          <p className="muted">Managed by the repository: change the workflow to change this suite.</p>
        </section>
      )}

      <section className="card" aria-labelledby="suite-cases">
        <h2 id="suite-cases">Cases, in order <span className="muted">({cases.length})</span></h2>
        {cases.length === 0 && <p className="muted">No cases yet{canEdit && ": find them below and add them"}.</p>}
        <ol className="ordered-cases">
          {cases.map((c, i) => (
            <li key={c.number}>
              <span className="muted">{i + 1}.</span>
              <Link to={`../../cases/${c.number}`} relative="path">{c.key}</Link>
              <span className="case-title">
                {c.title}
                {c.status === "archived" && <span className="muted"> · archived</span>}
              </span>
              {canEdit && (
                <span className="button-row">
                  <button type="button" className="ghost" aria-label={`Move ${c.key} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                    <ArrowUp size={16} aria-hidden="true" />
                  </button>
                  <button type="button" className="ghost" aria-label={`Move ${c.key} down`} disabled={i === cases.length - 1} onClick={() => move(i, 1)}>
                    <ArrowDown size={16} aria-hidden="true" />
                  </button>
                  <button type="button" className="ghost" aria-label={`Remove ${c.key} from the suite`}
                    onClick={() => setCases(cases.filter((x) => x.number !== c.number))}>
                    <X size={16} aria-hidden="true" />
                  </button>
                </span>
              )}
            </li>
          ))}
        </ol>
        {saveCases.error != null && <ErrorBanner error={saveCases.error} />}
        {canEdit && (
          <div className="button-row" style={{ marginTop: "var(--space-3)" }}>
            <button type="button" className={dirty || detailsDirty ? "primary" : undefined} disabled={!dirty || saveCases.isPending} onClick={() => saveCases.mutate()}>
              {saveCases.isPending ? "Saving…" : dirty ? "Save order and cases" : "Saved"}
            </button>
            <span role="status" className="muted">{dirty || detailsDirty ? "Unsaved changes" : ""}</span>
          </div>
        )}

        {canEdit && (
          <>
            <form className="filters" style={{ marginTop: "var(--space-4)" }} onSubmit={(e: FormEvent) => { e.preventDefault(); setAsked(search.trim()); }}>
              <label>
                Find cases to add
                <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="title, or empty for all" />
              </label>
              <button type="submit">Search</button>
            </form>
            {found.data && found.data.items.length === 0 && <p className="muted">No case matches.</p>}
            {found.data && found.data.items.length > 0 && (
              <ul className="pick-list">
                {found.data.items.map((c) => (
                  <li key={c.number}>
                    <span className="wrap-anywhere">{c.key} · {c.title}</span>
                    <button
                      type="button"
                      aria-label={`Add ${c.key} to the suite`}
                      disabled={inSuite.has(c.number)}
                      onClick={() => {
                        setCases([...cases, { number: c.number, key: c.key, title: c.title, status: c.status, priority: c.priority, labels: c.labels, automated_test_key: c.automated_test_key }]);
                      }}
                    >
                      {inSuite.has(c.number) ? "In the suite" : "Add"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      {canEdit && (
        <form className="card form-stack" onSubmit={(e) => { e.preventDefault(); saveDetails.mutate(); }}>
          <h2>Details</h2>
          <label>
            Name
            <input required maxLength={100} value={name} onChange={(e) => setDetails({ name: e.target.value })} />
          </label>
          <label>
            <span>Description <span className="muted">(optional)</span></span>
            <input maxLength={2000} value={description} onChange={(e) => setDetails({ description: e.target.value })} />
          </label>
          {saveDetails.error != null && <ErrorBanner error={saveDetails.error} />}
          <div className="button-row">
            <button type="submit" disabled={saveDetails.isPending || !detailsDirty}>{saveDetails.isPending ? "Saving…" : "Save details"}</button>
            <ConfirmButton
              label="Delete suite"
              ariaLabel={`Delete the suite ${suite.data.name}`}
              question="Delete this suite? Its cases stay."
              confirmLabel="Delete"
              onConfirm={() => remove.mutate()}
              disabled={remove.isPending}
            />
          </div>
          {remove.error != null && <ErrorBanner error={remove.error} />}
        </form>
      )}
    </section>
  );
}
