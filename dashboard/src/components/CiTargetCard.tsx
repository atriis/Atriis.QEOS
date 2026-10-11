import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { CiTarget, deleteCiTarget, formatDay, getCiTarget, saveCiTarget, tokenState } from "../api/runRequests";
import { ApiError } from "../api/http";
import { addRepository, listRepositories } from "../api/repositories";
import { branchError, normalizeRepo, repoError, workflowError } from "../lib/ciTargetFields";
import { useUserNames } from "../lib/useUserNames";
import ConfirmButton from "./ConfirmButton";
import ErrorBanner from "./ErrorBanner";
import workflowYaml from "../templates/qeos-run.yml.txt?raw";
import runnerScript from "../templates/qeos-run.mjs.txt?raw";

const DEFAULT_WORKFLOW = "qeos-run.yml";
const DEFAULT_BRANCH = "main";

/** The template, guarded to the branch configured here (a replacer function, so a "$&" in a branch stays literal;
 *  a single quote is doubled for the YAML single-quoted string). */
function workflowFor(ref: string | null): string {
  if (!ref) return workflowYaml;
  const branch = ref.replace(/'/g, "''");
  return workflowYaml.replace("refs/heads/main", () => `refs/heads/${branch}`);
}

/** The help block's copy state: only the block copied last says Copied, for 2 s, and the result is announced. */
function useCopyState() {
  const [state, setState] = useState<{ name: string; ok: boolean } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  async function copy(name: string, code: string) {
    clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(code);
      setState({ name, ok: true });
      timer.current = setTimeout(() => setState(null), 2000);
    } catch {
      setState({ name, ok: false }); // clipboard blocked: the text stays selectable
    }
  }
  const message = state == null ? "" : state.ok ? `${state.name} copied` : `Could not copy ${state.name}. Select the text and copy it by hand.`;
  return { copied: state?.ok ? state.name : null, copy, message };
}

function CopyBlock({ name, code, copied, onCopy }: { name: string; code: string; copied: boolean; onCopy: () => void }) {
  return (
    <>
      <pre className="code-block" tabIndex={0} aria-label={name}><code>{code}</code></pre>
      <button type="button" aria-label={`Copy ${name}`} onClick={onCopy}>
        {copied ? "Copied" : "Copy"}
      </button>
    </>
  );
}

/** Owners and admins see this from 14 days before the token expires (Settings and the run panel). */
export function ExpiryWarning({ target }: { target: CiTarget }) {
  const state = tokenState(target);
  const day = state !== "ok" && target.token_expires_at ? formatDay(target.token_expires_at) : null;
  // The live region is always there, so the warning appearing or changing (expiring, then expired) is announced
  return (
    <div role="status">
      {day && (
        <p className="note warn-note" role="note">
          <CircleAlert size={16} aria-hidden="true" />
          <span>
            {state === "expired"
              ? `The GitHub token expired on ${day}. Replace it in Settings`
              : `The GitHub token expires on ${day}. Replace it in Settings`}
          </span>
        </p>
      )}
    </div>
  );
}

/** Settings › Run from QEOS: the repository, workflow, branch and token Play dispatches with. */
export default function CiTargetCard({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const queryKey = ["ci-target", projectId];
  const target = useQuery({ queryKey, queryFn: () => getCiTarget(projectId) });
  const nameOf = useUserNames(projectId);
  const [repo, setRepo] = useState("");
  const [workflow, setWorkflow] = useState(DEFAULT_WORKFLOW);
  const [ref, setRef] = useState(DEFAULT_BRANCH);
  const [token, setToken] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [repoNote, setRepoNote] = useState<string | null>(null);
  const replaceRef = useRef<HTMLButtonElement>(null);
  const returnToReplace = useRef(false);
  const edited = useRef(false); // unsaved edits: a refetch must not overwrite them
  const ids = useId();
  const clip = useCopyState();

  const data = target.data;
  useEffect(() => {
    if (!data || edited.current) return;
    setRepo(data.repo ? `https://github.com/${data.repo}` : "");
    setWorkflow(data.workflow ?? DEFAULT_WORKFLOW);
    setRef(data.ref ?? DEFAULT_BRANCH);
    setToken("");
    setReplacing(false);
    setSubmitted(false);
  }, [data]);
  const edit = (set: (v: string) => void) => (v: string) => { edited.current = true; set(v); };
  /** Back out of a replacement: the stored token stays, and focus returns to Replace. */
  function keepToken() {
    setToken("");
    setReplacing(false);
    returnToReplace.current = true;
  }
  useEffect(() => {
    if (!replacing && returnToReplace.current) {
      returnToReplace.current = false;
      replaceRef.current?.focus();
    }
  }, [replacing]);

  const save = useMutation({
    mutationFn: () => saveCiTarget(projectId, {
      repo: normalizeRepo(repo), workflow: workflow.trim(), ref: ref.trim(), ...(token.trim() ? { token: token.trim() } : {}),
    }),
    onSuccess: (saved) => {
      edited.current = false;
      qc.setQueryData(queryKey, saved);
      if (saved.repo) void addToRepositories(saved.repo);
    },
  });
  const disconnect = useMutation({
    mutationFn: () => deleteCiTarget(projectId),
    onSuccess: () => {
      edited.current = false; // the form starts over from the (now empty) target
      save.reset();
      return qc.invalidateQueries({ queryKey });
    },
  });

  /** The repository Play runs in also belongs in Settings › Repositories, where its status shows. Adding it is a
   *  courtesy after the save: a failure here never undoes the connection, it only says so. */
  async function addToRepositories(saved: string) {
    setRepoNote(null);
    const reposKey = ["repositories", projectId];
    try {
      const list = await qc.fetchQuery({ queryKey: reposKey, queryFn: () => listRepositories(projectId), staleTime: 0 });
      const key = saved.toLowerCase();
      if (list.some((r) => r.provider === "github" && `${r.owner}/${r.name}`.toLowerCase() === key)) return;
      await addRepository(projectId, `https://github.com/${saved}`);
      setRepoNote(`Added ${saved} to Repositories.`);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 409)) {  // 409: someone added it meanwhile, which is fine
        setRepoNote(`Saved. ${saved} could not be added to Repositories; add it there to see its status.`);
      }
    }
    await qc.invalidateQueries({ queryKey: reposKey });
  }

  const parsedRepo = normalizeRepo(repo);
  const errors = {
    repo: repoError(parsedRepo),
    workflow: workflowError(workflow.trim()),
    ref: branchError(ref.trim()),
    token: !data?.configured && !token.trim() ? "Paste the GitHub token" : null,
  };
  const shown = (name: keyof typeof errors) => (submitted ? errors[name] : null);
  const field = (name: keyof typeof errors) => ({
    "aria-invalid": shown(name) ? true : undefined,
    "aria-describedby": shown(name) ? `${ids}-${name}` : undefined,
  });
  const fieldError = (name: keyof typeof errors) =>
    shown(name) && <span id={`${ids}-${name}`} className="field-error">{shown(name)}</span>;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (Object.values(errors).some(Boolean)) return;
    save.mutate();
  }

  const workflowFile = data?.workflow ?? DEFAULT_WORKFLOW;
  return (
    <div className="card">
      <h2>Run from QEOS</h2>
      <p className="muted">
        Play runs the selected scenarios in this repository's GitHub Actions, through a dedicated workflow.
        QEOS never runs test code itself.
      </p>
      {target.error != null && <ErrorBanner error={target.error} onRetry={() => target.refetch()} />}
      {target.isPending && <p className="muted">Loading…</p>}
      {data && !data.available && (
        <p className="note" role="note">
          Running tests from QEOS is not configured on this server. An administrator sets{" "}
          <code>TM_SECRETS_KEY</code> on test-management-service.
        </p>
      )}
      {data?.available && (
        <>
          {data.configured && (
            <>
              {/* The connection and the action that ends it, together, away from Save */}
              <div className="connection-line">
              {tokenState(data) === "expired" && data.token_expires_at ? (
                <p className="muted" role="status">
                  <CircleAlert size={16} aria-hidden="true" />{" "}
                  <span>{`${data.repo} · token …${data.token_last4} · Expired on ${formatDay(data.token_expires_at)}`}</span>
                </p>
              ) : (
                <p className="success-note" role="status">
                  <CheckCircle2 size={16} aria-hidden="true" />
                  <span>
                    {`Connected: ${data.repo} · token …${data.token_last4} · `}
                    {data.token_expires_at ? `expires ${formatDay(data.token_expires_at)}` : "no expiry"}
                  </span>
                </p>
              )}
                <ConfirmButton
                  label="Disconnect"
                  question={`Disconnect ${data.repo}? Nobody can run tests from QEOS until a token is saved again.`}
                  confirmLabel="Disconnect"
                  onConfirm={() => { save.reset(); disconnect.mutate(); }}
                  disabled={disconnect.isPending}
                />
              </div>
              {disconnect.error != null && <ErrorBanner error={disconnect.error} />}
              <ExpiryWarning target={data} />
            </>
          )}
          {data.last_change && (
            <p className="muted">{`Last changed by ${nameOf(data.last_change.user_id)} on ${formatDay(data.last_change.at)}`}</p>
          )}
          <form className="form-stack" onSubmit={onSubmit} noValidate>
            <label>
              <span id={`${ids}-repo-label`}>Repository link</span>
              <input required value={repo} aria-labelledby={`${ids}-repo-label`} onChange={(e) => edit(setRepo)(e.target.value)}
                placeholder="https://github.com/owner/name" inputMode="url"
                {...field("repo")} aria-describedby={[`${ids}-repo-hint`, !errors.repo ? `${ids}-repo-parsed` : null,
                  field("repo")["aria-describedby"]].filter(Boolean).join(" ")}
                autoComplete="off" spellCheck={false} />
              <span id={`${ids}-repo-hint`} className="muted field-hint">
                Paste the repository&apos;s GitHub address. owner/name also works.
              </span>
              {!errors.repo && <span id={`${ids}-repo-parsed`} className="muted field-hint">Runs in <strong>{parsedRepo}</strong></span>}
              {fieldError("repo")}
            </label>
            <label>
              Workflow file
              <input required value={workflow} onChange={(e) => edit(setWorkflow)(e.target.value)} {...field("workflow")}
                autoComplete="off" spellCheck={false} />
              {fieldError("workflow")}
            </label>
            <label>
              Branch
              <input required value={ref} onChange={(e) => edit(setRef)(e.target.value)} {...field("ref")}
                autoComplete="off" spellCheck={false} />
              {fieldError("ref")}
            </label>
            {data.configured && !replacing ? (
              <div className="field-static">
                <span className="field-label">Token</span>
                <span className="token-saved">
                  <span>{`Saved (…${data.token_last4})`}</span>
                  <button type="button" ref={replaceRef} aria-label="Replace token"
                    onClick={() => { save.reset(); setReplacing(true); }}>Replace</button>
                </span>
              </div>
            ) : (
              <label>
                Token
                <span className="token-saved">
                  <input type="password" required={!data.configured} value={token} autoFocus={replacing}
                    onChange={(e) => edit(setToken)(e.target.value)} {...field("token")} autoComplete="off" spellCheck={false} />
                  {replacing && (
                    <button type="button" onClick={keepToken}>Keep current token</button>
                  )}
                </span>
                {fieldError("token")}
              </label>
            )}
            <div className="button-row">
              <button className="primary" type="submit" disabled={save.isPending}>
                {save.isPending ? "Checking with GitHub…" : "Save"}
              </button>
            </div>
          </form>
          {save.error != null && <ErrorBanner error={save.error} />}
          {repoNote && <p className="muted" role="status">{repoNote}</p>}
          <details className="run-help">
            <summary>How to set it up</summary>
            <p>
              The workflow and the script must exist on the repository's default branch and also on the branch set above ({data.ref ?? DEFAULT_BRANCH}):
              GitHub dispatches the workflow file it finds on that branch, and that run reads the script from the same branch.
            </p>
            <ol>
              <li>
                On GitHub, create a <strong>fine-grained personal access token</strong> (Settings › Developer settings ›
                Fine-grained tokens): repository access <strong>only {data.repo ?? "this repository"}</strong>, permission{" "}
                <strong>Actions: Read and write</strong>. Paste it in Token above.
              </li>
              <li>
                Add this workflow as <code>{`.github/workflows/${workflowFile}`}</code> on the repository's{" "}
                <strong>default branch</strong> (GitHub only dispatches workflows found there):
                <CopyBlock name={workflowFile} code={workflowFor(data.ref)} copied={clip.copied === workflowFile}
                  onCopy={() => void clip.copy(workflowFile, workflowFor(data.ref))} />
              </li>
              <li>
                Add the script it runs as <code>.github/scripts/qeos-run.mjs</code>:
                <CopyBlock name="qeos-run.mjs" code={runnerScript} copied={clip.copied === "qeos-run.mjs"}
                  onCopy={() => void clip.copy("qeos-run.mjs", runnerScript)} />
              </li>
              <li>
                In the repository's Settings › Secrets and variables › Actions, add the secret <code>QEOS_API_KEY</code>{" "}
                (a project API key from this page) and the variable <code>QEOS_URL</code> ={" "}
                <code>{window.location.origin}</code>.
              </li>
            </ol>
            <span role="status" aria-live="polite" className="sr-only">{clip.message}</span>
          </details>
        </>
      )}
    </div>
  );
}
