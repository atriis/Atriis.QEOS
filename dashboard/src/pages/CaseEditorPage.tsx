import { FormEvent, useEffect, useId, useMemo, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowUp, Bot, FileCode, Plus, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Case, CaseInput, PRIORITIES, Priority, STATUSES, CaseStatus, Step, createCase, getCase, parseLabels, updateCase } from "../api/cases";
import { getHistory, getLatestResults, getTests } from "../api/analytics";
import FailedStepTip from "../components/FailedStepTip";
import LastResultPill from "../components/LastResultPill";
import LogValuesLine from "../components/LogValuesLine";
import RunContextNote from "../components/RunContextNote";
import { useStepSpread } from "../lib/failedSteps";
import { runParam, statusWord, useScrollToFailure } from "../lib/runContext";
import { featureDetailQuery } from "../lib/featureQueries";
import { locateFailedStep, matchesStep, scenarioSteps, stepLines } from "../lib/failedStep";
import { type Locate, placeScreenshots } from "../lib/screenshotLines";
import ConfirmButton from "../components/ConfirmButton";
import ErrorBanner from "../components/ErrorBanner";
import GherkinBlock, { toneOf } from "../components/GherkinBlock";
import ScreenshotButton, { useScreenshotViewer } from "../components/ScreenshotButton";
import RunControl from "../components/RunControl";
import RunPanel from "../components/RunPanel";
import StatusDot from "../components/StatusDot";
import UnsavedGuard from "../components/UnsavedGuard";
import { useCanEdit } from "../lib/useCanEdit";
import PageHeader from "../components/PageHeader";

interface Draft {
  title: string;
  description: string;
  steps: Step[];
  labels: string;
  priority: Priority;
  status: CaseStatus;
}

const EMPTY: Draft = { title: "", description: "", steps: [{ action: "", expected: "" }], labels: "", priority: "medium", status: "draft" };

function toDraft(c: Case): Draft {
  return {
    title: c.title, description: c.description ?? "", steps: c.steps.length ? c.steps : [{ action: "", expected: "" }],
    labels: c.labels.join(", "), priority: c.priority, status: c.status,
  };
}

function toInput(d: Draft): CaseInput {
  return {
    title: d.title.trim(),
    description: d.description.trim() || null,
    steps: d.steps.filter((s) => s.action.trim()).map((s) => ({ action: s.action.trim(), expected: s.expected.trim() })),
    labels: parseLabels(d.labels),
    priority: d.priority,
    status: d.status,
  };
}

/** An imported case's title, steps and labels belong to its .feature file: save only what QEOS owns. */
function toOwnedInput(d: Draft): CaseInput {
  return { description: d.description.trim() || null, priority: d.priority, status: d.status };
}

/** The automated test a case is linked to: its latest result, or a search to link one. */
function Automation({ projectId, c, canEdit, onLink }: {
  projectId: number;
  c: Case;
  canEdit: boolean;
  onLink: (key: string | null, name?: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [asked, setAsked] = useState("");
  const latest = useQuery({
    queryKey: ["history", projectId, c.automated_test_key, "latest"],
    queryFn: () => getHistory(projectId, c.automated_test_key!, { days: 90, limit: 1 }),
    enabled: c.automated_test_key != null,
  });
  const found = useQuery({
    queryKey: ["tests", projectId, "link", asked],
    queryFn: () => getTests(projectId, { days: 90, sort: "name", search: asked, limit: 10, offset: 0 }),
    enabled: asked !== "",
  });
  const last = latest.data?.executions[0];

  return (
    <section className="card" aria-labelledby="automation">
      <h2 id="automation">Automation</h2>
      {c.automated_test_key ? (
        <>
          <p>
            <span className="linked"><Bot size={16} aria-hidden="true" /> Linked to</span>{" "}
            <Link to={`/projects/${projectId}/tests/${encodeURIComponent(c.automated_test_key)}`}>
              {c.automated_name ?? "the automated test"}
            </Link>
          </p>
          {latest.isPending && <p className="muted">Loading the latest result…</p>}
          {latest.isError && <p className="muted">No result in the last 90 days.</p>}
          {last && (
            <p className="muted">
              Latest result: <StatusDot status={last.status} /> in run #{last.run_id}, {new Date(last.started_at).toLocaleString()}
            </p>
          )}
          {canEdit && (
            <ConfirmButton
              label="Unlink"
              question="Unlink this test? The case goes back to manual."
              confirmLabel="Unlink"
              onConfirm={() => onLink(null)}
            />
          )}
        </>
      ) : (
        <>
          <p className="muted">Manual. Link the automated test that covers this case to see its latest result here.</p>
          {canEdit && (
            <form className="filters" onSubmit={(e) => { e.preventDefault(); setAsked(search.trim()); }}>
              <label>
                Find an automated test
                <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="test name" />
              </label>
              <button type="submit">Search</button>
            </form>
          )}
          {found.data && found.data.length === 0 && <p className="muted">No automated test matches “{asked}” in the last 90 days.</p>}
          {found.data && found.data.length > 0 && (
            <ul className="pick-list">
              {found.data.map((t) => {
                const name = [t.suite, t.class_name, t.name].filter(Boolean).join(" › ");
                return (
                  <li key={t.test_key}>
                    <span className="wrap-anywhere">{name}</span>
                    <button type="button" aria-label={`Link ${name}`} onClick={() => onLink(t.test_key, name)}>Link</button>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

/** Write a new case, or read and edit one. People who may not edit see it read-only. */
export default function CaseEditorPage() {
  const { caseNumber } = useParams();
  // Keyed by case, so edits never carry over from one case to another
  return <CaseEditor key={caseNumber ?? "new"} />;
}

function CaseEditor() {
  const { projectId, caseNumber } = useParams();
  const id = Number(projectId);
  const number = caseNumber ? Number(caseNumber) : null;
  // Opened from a Last runs bar: the case as of that run
  const runId = runParam(useSearchParams()[0]);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canEdit = useCanEdit(id) === true;
  const ids = useId();

  const existing = useQuery({
    queryKey: ["case", id, number],
    queryFn: () => getCase(id, number!),
    enabled: number !== null,
  });
  // Edits live apart from the saved case: null means "nothing changed", so a refetch or a
  // link/unlink (which only touches automation fields) can never overwrite what is being typed.
  const [edits, setEdits] = useState<Draft | null>(null);
  const baseline = existing.data ? toDraft(existing.data) : EMPTY;
  const draft = edits ?? baseline;
  const dirty = edits !== null && JSON.stringify(edits) !== JSON.stringify(baseline);
  const [saved, setSaved] = useState(false);
  const [created, setCreated] = useState<number | null>(null);
  // Navigate after the render that clears the edits, so the leave guard no longer blocks
  useEffect(() => {
    if (created !== null && !dirty) navigate(`../${created}`, { relative: "path", replace: true });
  }, [created, dirty, navigate]);

  const afterWrite = (c: Case) => {
    qc.invalidateQueries({ queryKey: ["cases", id] });
    for (const key of ["case-labels", "case-folders", "case-features", "cases-total"]) {
      qc.invalidateQueries({ queryKey: [key, id] });
    }
    qc.setQueryData(["case", id, c.number], c);
  };
  const save = useMutation({
    mutationFn: (input: CaseInput) => (number === null ? createCase(id, input) : updateCase(id, number, input)),
    onSuccess: (c) => {
      afterWrite(c);
      setEdits(null);
      setSaved(true);
      if (number === null) setCreated(c.number);
    },
  });
  // Link and unlink write the automation fields only and leave the form alone
  const link = useMutation({
    mutationFn: (input: CaseInput) => updateCase(id, number!, input),
    onSuccess: afterWrite,
  });

  function setStep(i: number, field: keyof Step, value: string) {
    setEdits({ ...draft, steps: draft.steps.map((s, j) => (j === i ? { ...s, [field]: value } : s)) });
    setSaved(false);
  }
  function moveStep(i: number, by: number) {
    const steps = [...draft.steps];
    [steps[i], steps[i + by]] = [steps[i + by], steps[i]];
    setEdits({ ...draft, steps });
    setSaved(false);
  }
  function change<K extends keyof Draft>(key: K, value: Draft[K]) {
    setEdits({ ...draft, [key]: value });
    setSaved(false);
  }
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    save.mutate(existing.data?.source_path ? toOwnedInput(draft) : toInput(draft));
  }

  const c = existing.data;
  const key = c?.automated_test_key ?? null;
  const latest = useQuery({
    queryKey: ["latest-results", id, key, runId],
    enabled: key != null,
    queryFn: () => getLatestResults(id, [key!], runId ?? undefined).then((r) => r.results[key!.toLowerCase()] ?? null),
  });
  const wantsFeature = !!c?.source_path && (latest.data?.failed_step != null || (latest.data?.screenshot_steps?.length ?? 0) > 0);
  const feature = useQuery({ ...featureDetailQuery(id, c?.source_path ?? ""), enabled: wantsFeature });
  /** The shown line of a step that ran (the failed one, or one with screenshots); null while the file is loading. */
  const locateShown = useMemo<Locate | null>(() => {
    if (!c) return null;
    // Gherkin is shown only on an imported case (a manual one may still carry it): without shown lines, the
    // screenshots all go under the Screenshots link
    if (!c.source_path || !c.gherkin) return () => null;
    // Wait for the file rather than mark a provisional line that then jumps
    if (wantsFeature && feature.isPending) return null;
    const shown = stepLines(c.gherkin);
    const source = feature.data?.content;
    const scenarioLine = feature.data?.cases.find((fc) => fc.number === c.number)?.line ?? null;
    const fileSteps = source && scenarioLine ? scenarioSteps(source, scenarioLine) : null;
    return (step) => {
      const mapped = fileSteps ? locateFailedStep(fileSteps, step) : null;
      // The file's steps must line up with the displayed ones; if not, trust the text alone
      const index = mapped != null && shown[mapped] && matchesStep(shown[mapped].text, step.text)
        ? mapped
        : locateFailedStep(shown, { text: step.text });
      return index != null && shown[index] ? shown[index].line : null;
    };
  }, [c, feature.data, feature.isPending, wantsFeature]);
  const failedStep = latest.data?.failed_step;
  const failedLine = failedStep && locateShown ? locateShown(failedStep) : null;
  const shots = useMemo(
    () => (locateShown && latest.data?.result_id != null ? placeScreenshots(locateShown, latest.data.screenshot_steps) : null),
    [locateShown, latest.data],
  );
  useScrollToFailure(runId, failedLine != null);
  const spreadOf = useStepSpread(id, [latest.data]);
  const shotViewer = useScreenshotViewer();

  if (number !== null && existing.error != null) {
    return (
      <>
        <PageHeader title={`TC-${number}`} />
        <ErrorBanner error={existing.error} onRetry={() => existing.refetch()} />
      </>
    );
  }
  if (number !== null && existing.isPending) {
    return (
      <>
        <PageHeader title={`TC-${number}`} />
        <p className="muted">Loading the case…</p>
      </>
    );
  }
  const readOnly = !canEdit;
  const imported = c?.source_path != null;
  const result = latest.data;
  const shotOf = result?.result_id != null && c
    ? { projectId: id, runId: result.run_id, resultId: result.result_id, name: c.automated_name ?? c.title }
    : null;
  const annotations = shots && shotOf
    ? new Map([...shots.byLine].map(([line, p]) => [line, <ScreenshotButton kind="step" count={p.count} onOpen={() => shotViewer.open({ ...shotOf, step: p.step })} />]))
    : undefined;
  // The pill, with the images of steps not shown in the Gherkin beside it
  const resultLine = key != null && latest.isSuccess && (runId == null || result != null) && (
    <div className="result-line">
      <LastResultPill result={result} />
      {shotOf && shots && shots.unplaced > 0 && <ScreenshotButton kind="link" count={shots.unplaced} onOpen={() => shotViewer.open(shotOf)} />}
    </div>
  );

  return (
    <section>
      <p>
        <Link className="link-arrow" to=".." relative="path">
          <ArrowLeft size={14} aria-hidden="true" /> All test cases
        </Link>
      </p>
      <PageHeader title={c ? `${c.key} · ${c.title}` : "New test case"} />
      {c && runId != null && (
        <RunContextNote projectId={id} runId={runId} latestHref={`/projects/${id}/cases/${c.number}`}
          error={latest.error ?? undefined}
          startedAt={latest.data?.started_at} status={latest.data ? statusWord(latest.data.status) : undefined}
          missing={key == null ? `This case has no automated test, so it has no result in run #${runId}.`
            : latest.isSuccess && latest.data == null ? `This case was not in run #${runId}.` : undefined} />
      )}
      {c?.source_path && c.status !== "archived" && (
        <RunControl projectId={id} cases={[{ number: c.number, title: c.title, testKey: c.automated_test_key }]} selection={{ case_numbers: [c.number] }} label="Run" emphasis={!dirty} />
      )}
      {c && <RunPanel projectId={id} caseNumber={c.number} />}
      {c && c.suites.length > 0 && (
        <p className="muted">
          In suites:{" "}
          {c.suites.map((s, i) => (
            <span key={s.id}>{i > 0 && ", "}<Link to={`../../suites/${s.id}`} relative="path">{s.name}</Link></span>
          ))}
        </p>
      )}

      {c?.source_path && (
        <div className="card source-badge">
          <FileCode size={16} aria-hidden="true" />
          <p>Imported from <code>{c.source_path}</code></p>
          <p className="muted">Title, steps and labels come from the .feature file.</p>
        </div>
      )}

      <UnsavedGuard dirty={dirty} />
      <form className="card form-stack case-form" onSubmit={onSubmit}>
        <fieldset disabled={readOnly} className="plain-fieldset">
          <label>
            Title
            <input required maxLength={200} readOnly={imported} value={draft.title} onChange={(e) => change("title", e.target.value)} />
          </label>
          <label>
            <span>Preconditions and context <span className="muted">(optional)</span></span>
            <textarea rows={3} maxLength={10000} value={draft.description} onChange={(e) => change("description", e.target.value)} />
          </label>
        </fieldset>

        {/* The result, its values and the Gherkin are read-only by nature: outside the disabled fieldset, so a viewer can still copy a value or open screenshots */}
          {imported ? (
            <>
              <h2>Gherkin</h2>
              {resultLine}
              {key != null && latest.data != null && <LogValuesLine values={latest.data.values} projectId={id} />}
              <GherkinBlock
                text={c?.gherkin ?? ""}
                annotations={annotations}
                failed={failedLine != null && latest.data
                  ? { line: failedLine, tone: toneOf(latest.data), tip: <FailedStepTip projectId={id} result={latest.data} spread={spreadOf(latest.data)} /> }
                  : undefined}
              />
            </>
          ) : (
            <>
          {resultLine}
          {key != null && latest.data != null && <LogValuesLine values={latest.data.values} projectId={id} />}
          <fieldset disabled={readOnly} className="plain-fieldset">
          <h2 id={`${ids}-steps`}>Steps</h2>
          <ol className="steps" aria-labelledby={`${ids}-steps`}>
            {draft.steps.map((s, i) => (
              <li key={i} className="step">
                <span className="step-number" aria-hidden="true">{i + 1}</span>
                <div className="step-fields">
                  <label>
                    Action <span className="sr-only">{i + 1}</span>
                    <textarea maxLength={2000} value={s.action} onChange={(e) => setStep(i, "action", e.target.value)} />
                  </label>
                  <label>
                    Expected result <span className="sr-only">{i + 1}</span>
                    <textarea maxLength={2000} value={s.expected} onChange={(e) => setStep(i, "expected", e.target.value)} />
                  </label>
                </div>
                {!readOnly && (
                  <div className="step-actions">
                    <button type="button" className="ghost" aria-label={`Move step ${i + 1} up`} disabled={i === 0} onClick={() => moveStep(i, -1)}>
                      <ArrowUp size={16} aria-hidden="true" />
                    </button>
                    <button type="button" className="ghost" aria-label={`Move step ${i + 1} down`} disabled={i === draft.steps.length - 1} onClick={() => moveStep(i, 1)}>
                      <ArrowDown size={16} aria-hidden="true" />
                    </button>
                    <button type="button" className="ghost" aria-label={`Remove step ${i + 1}`} disabled={draft.steps.length === 1}
                      onClick={() => change("steps", draft.steps.filter((_, j) => j !== i))}>
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ol>
          {!readOnly && draft.steps.length < 50 && (
            <div className="add-step">
              <button type="button" onClick={() => change("steps", [...draft.steps, { action: "", expected: "" }])}>
                <Plus size={16} aria-hidden="true" /> Add step
              </button>
            </div>
          )}
          </fieldset>

            </>
          )}

        <fieldset disabled={readOnly} className="plain-fieldset">
          <label>
            <span>Labels <span className="muted">(comma separated)</span></span>
            <input readOnly={imported} value={draft.labels} onChange={(e) => change("labels", e.target.value)} placeholder="e.g. checkout, smoke"
              spellCheck={false} autoComplete="off" />
          </label>
          <div className="filters">
            <label>
              Priority
              <select value={draft.priority} onChange={(e) => change("priority", e.target.value as Priority)}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <label>
              Status
              <select value={draft.status} onChange={(e) => change("status", e.target.value as CaseStatus)}>
                {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
          </div>
        </fieldset>
        {save.error != null && <ErrorBanner error={save.error} />}
        {link.error != null && <ErrorBanner error={link.error} />}
        {saved && !save.isPending && <p className="success-note" role="status">Saved.</p>}
        {!readOnly && (
          <div className="button-row">
            <button className={dirty || number === null ? "primary" : undefined} type="submit" disabled={save.isPending || (number !== null && !dirty)}>
              {save.isPending ? "Saving…" : number === null ? "Create case" : "Save changes"}
            </button>
            <span role="status" className="muted">{dirty ? "Unsaved changes" : ""}</span>
          </div>
        )}
        {readOnly && <p className="muted">Only owners, admins and members can change test cases.</p>}
      </form>

      {c && (
        <Automation
          projectId={id}
          c={c}
          canEdit={canEdit}
          onLink={(key, name) => link.mutate({ automated_test_key: key, ...(key ? { automated_name: name } : {}) })}
        />
      )}
      {shotViewer.viewer}
    </section>
  );
}
