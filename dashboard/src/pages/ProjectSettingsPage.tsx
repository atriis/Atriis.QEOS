import { useId, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiKey, ApiKeyCreated, createKey, listKeys, revokeKey, updateKey } from "../api/keys";
import { getProject } from "../api/orgs";
import CollectionCard from "../components/CollectionCard";
import CiTargetCard from "../components/CiTargetCard";
import ConfirmButton from "../components/ConfirmButton";
import ErrorBanner from "../components/ErrorBanner";
import SecretBlock from "../components/SecretBlock";
import DataCard from "../components/DataCard";
import LogValuesCard from "../components/LogValuesCard";
import MaskingCard from "../components/MaskingCard";
import NotificationsCard from "../components/NotificationsCard";
import RepositoriesCard from "../components/RepositoriesCard";
import PageHeader from "../components/PageHeader";

// The floating tag: the latest 0.x release, moved by release-collector.yml, so a pasted snippet never goes stale
const COLLECTOR_REF = "collector-v0";

// Mirrors EDIT_ROLES in platforms/project-service/src/project/api/deps.py
const EDIT_ROLES = ["owner", "admin", "member"];
const MANAGE_ROLES = ["owner", "admin"];

const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

/** True when this page is served from the user's own machine: hosted CI runners cannot reach it. */
export function isLocalOrigin(origin: string): boolean {
  try {
    return LOCAL_HOSTS.includes(new URL(origin).hostname);
  } catch {
    return false;
  }
}

// Platforms whose default runners live on the vendor's servers, never on this machine
const HOSTED_RUNNERS = ["github", "gitlab", "azure"];

// What the card can hand out: the upload step for an existing suite workflow, or the test-case sync
export type SnippetKind = "upload" | "sync";

type PlatformSnippets = { label: string; code: Record<SnippetKind, string> };

const PIP_INSTALL = (ref: string) =>
  `pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@${ref}#subdirectory=collector"`;

// Ready-to-paste CI wiring; the key itself always travels as a CI secret.
// "upload" goes after the test step of the suite's own workflow; "sync" keeps the test cases equal to the
// .feature files (docs/SETUP.md 4.2.3): on GitHub a workflow of its own, elsewhere a step or job.
function ciSnippets(origin: string): Record<string, PlatformSnippets> {
  const local = isLocalOrigin(origin);
  const caFile = local ? " --ca-file qeos-ca.crt" : "";
  return {
    github: {
      label: "GitHub Actions",
      code: {
        upload: `# QEOS: uploads the results, so the run appears under Runs and on its test cases.
# Goes after the test step, in the job that runs cucumber-js.
# Needs the repository variable QEOS_URL (this QEOS address) and the repository secret QEOS_API_KEY.
- name: Upload results to QEOS
  if: always() && vars.QEOS_URL != ''   # failing builds report too; repositories without QEOS skip cleanly
  uses: atriis/Atriis.QEOS/collector-action@${COLLECTOR_REF}
  with:
    url: \${{ vars.QEOS_URL }}
    patterns: test-results/cucumber-report.json   # the Cucumber JSON the test step writes (json: formatter); JUnit XML works too
  env:
    QEOS_API_KEY: \${{ secrets.QEOS_API_KEY }}

# Shards gathered with download-artifact: the same step in the job that gathers every shard's report,
# after the last download step, with the pattern under download-artifact's path (one QEOS run):
#     patterns: shard-reports/**/cucumber-report.json`,
        sync: `# QEOS: keeps the test cases equal to the .feature files, so Test cases follows the repository.
# Commit as .github/workflows/qeos-sync-cases.yml on the default branch; it runs on every push that changes a .feature file
# or a suite workflow. Change ".github/workflows/suite-*.yml" (here and in on.push.paths) to the pattern that names
# your repository's suite workflows; they become read-only suites in QEOS. Drop both if you have none.
# Needs the repository variable QEOS_URL (this QEOS address) and the repository secret QEOS_API_KEY.
name: QEOS sync test cases

on:
  push:
    paths: ["tests/features/**", ".github/workflows/suite-*.yml"]
  workflow_dispatch:
    inputs:
      first_sync:
        description: "First sync only: allow archiving the old dashboard-imported cases"
        type: boolean
        default: false

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: atriis/Atriis.QEOS/collector-action@${COLLECTOR_REF}
        with:
          url: \${{ vars.QEOS_URL }}
          command: import-features
          patterns: "tests/features/**/*.feature"
          extra-args: \${{ inputs.first_sync && '--allow-mass-archive' || '' }} --suites ".github/workflows/suite-*.yml"
        env:
          QEOS_API_KEY: \${{ secrets.QEOS_API_KEY }}`,
      },
    },
    gitlab: {
      label: "GitLab CI",
      code: {
        upload: `# .gitlab-ci.yml — set QEOS_API_KEY as a masked CI/CD variable
include:
  - remote: https://raw.githubusercontent.com/atriis/Atriis.QEOS/${COLLECTOR_REF}/templates/qeos-collector.gitlab-ci.yml

qeos-collector-upload:
  variables:
    QEOS_URL: ${origin}
    QEOS_PATTERNS: "test-results/cucumber-report.json"   # Cucumber JSON links results to the cases; JUnit XML works too`,
        sync: `# .gitlab-ci.yml — set QEOS_API_KEY as a masked CI/CD variable
# syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
# first sync after a dashboard import: run it once with --allow-mass-archive
qeos-import-features:
  image: python:3.12
  rules:
    - changes: ["tests/features/**/*"]
  script:
    - ${PIP_INSTALL(COLLECTOR_REF)}
    - qeos-collector import-features "tests/features/**/*.feature"
  variables:
    QEOS_URL: ${origin}   # QEOS_API_KEY comes from the masked CI/CD variable`,
      },
    },
    azure: {
      label: "Azure Pipelines",
      code: {
        upload: `# azure-pipelines.yml — after the test step; add QEOS_API_KEY as a secret pipeline variable
- script: |
    ${PIP_INSTALL(COLLECTOR_REF)}
    qeos-collector upload "test-results/cucumber-report.json"   # Cucumber JSON links results to the cases; JUnit XML works too
  displayName: Upload test results to QEOS
  condition: always()      # report results even when tests failed
  continueOnError: true    # a failed upload does not fail the pipeline
  env:
    QEOS_URL: ${origin}
    QEOS_API_KEY: $(QEOS_API_KEY)   # secret variables reach scripts only when mapped here
    # a secret still named QAV_API_KEY (before the QEOS rename)? map it instead: QEOS_API_KEY: $(QAV_API_KEY)`,
        sync: `# azure-pipelines.yml — add QEOS_API_KEY as a secret pipeline variable
# syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
# first sync after a dashboard import: run it once with --allow-mass-archive
- script: |
    ${PIP_INSTALL(COLLECTOR_REF)}
    qeos-collector import-features "tests/features/**/*.feature"
  displayName: Sync test cases from .feature files
  env:
    QEOS_URL: ${origin}
    QEOS_API_KEY: $(QEOS_API_KEY)   # secret variables reach scripts only when mapped here`,
      },
    },
    jenkins: {
      label: "Jenkins",
      code: {
        upload: `// Jenkinsfile — needs the qeos shared library (collector-jenkins/)
withCredentials([string(credentialsId: 'qeos-api-key', variable: 'QEOS_API_KEY')]) {
  withEnv(['QEOS_URL=${origin}']) {
    // Cucumber JSON links results to the cases; JUnit XML works too
    qeosCollectorUpload(patterns: 'test-results/cucumber-report.json', ref: '${COLLECTOR_REF}')
  }
}`,
        sync: `// Jenkinsfile — right after qeosCollectorUpload(ref: '${COLLECTOR_REF}'), which creates the .qeos-venv this reuses
// syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
// first sync after a dashboard import: run it once with --allow-mass-archive
withCredentials([string(credentialsId: 'qeos-api-key', variable: 'QEOS_API_KEY')]) {
  withEnv(['QEOS_URL=${origin}']) {
    sh '''
      .qeos-venv/bin/python -m qeos_collector import-features "tests/features/**/*.feature"
    '''
  }
}`,
      },
    },
    cli: {
      label: "Any machine (CLI)",
      code: {
        upload: `${PIP_INSTALL(COLLECTOR_REF)}
${local ? `# The local stack uses a self-signed certificate; from the Atriis.QEOS folder:
docker compose cp gateway:/etc/nginx/certs/tls.crt qeos-ca.crt
` : ""}# Cucumber JSON links results to the cases; JUnit XML works too
QEOS_URL=${origin} QEOS_API_KEY=<your key> qeos-collector upload "test-results/cucumber-report.json"${caFile}`,
        sync: `${PIP_INSTALL(COLLECTOR_REF)}
${local ? `# The local stack uses a self-signed certificate; from the Atriis.QEOS folder:
docker compose cp gateway:/etc/nginx/certs/tls.crt qeos-ca.crt
` : ""}# from the repository root, so the paths match the Cucumber report; add --allow-mass-archive once for a first sync after a dashboard import
QEOS_URL=${origin} QEOS_API_KEY=<your key> qeos-collector import-features "tests/features/**/*.feature"${caFile}`,
      },
    },
  };
}

/** A key's "may read test suggestions" switch, as the Collection card's: the state is the On/Off word and the thumb's
 *  position, not colour alone. Not disabled while saving, so keyboard focus stays on it. */
function ImpactSwitch({ apiKey, hint, saving, onToggle }: {
  apiKey: ApiKey; hint: string; saving: boolean; onToggle: (on: boolean) => void;
}) {
  const on = apiKey.can_read_impact === true;
  return (
    <button type="button" role="switch" className="switch switch-compact" aria-checked={on} aria-busy={saving}
      aria-label={`Test suggestions for key ${apiKey.name}`} aria-describedby={hint} onClick={() => onToggle(!on)}>
      <span className="switch-track" aria-hidden="true"><span className="switch-thumb" /></span>
      <span className="switch-state" aria-hidden="true">{saving ? "Saving…" : on ? "On" : "Off"}</span>
    </button>
  );
}

export default function ProjectSettingsPage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [canReadImpact, setCanReadImpact] = useState(false);
  const impactHint = useId();
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const local = isLocalOrigin(window.location.origin);
  const [platform, setPlatform] = useState(local ? "cli" : "github");
  const [snippetKind, setSnippetKind] = useState<SnippetKind>("upload");
  const [snippetCopied, setSnippetCopied] = useState(false);
  const snippets = useMemo(() => ciSnippets(window.location.origin), []);
  const snippetCode = snippets[platform].code[snippetKind];

  const keys = useQuery({ queryKey: ["keys", id], queryFn: () => listKeys(id) });
  // Same key as ProjectLayout, so this is served from its cache
  const project = useQuery({ queryKey: ["project", id], queryFn: () => getProject(id) });
  const canEdit = EDIT_ROLES.includes(project.data?.my_role ?? "");
  // Same rule as the ingestion API (EDIT_ROLES on create and revoke): anyone with read access may list
  const roleKnown = project.data != null;
  // Reading test suggestions is for owners and admins to allow (ingestion MANAGE_ROLES, spec 2026-10-13 §9)
  const canManage = MANAGE_ROLES.includes(project.data?.my_role ?? "");

  const create = useMutation({
    mutationFn: () => createKey(id, name.trim(), canManage && canReadImpact),
    onSuccess: (key) => {
      setCreated(key);
      setName("");
      setCanReadImpact(false);
      qc.invalidateQueries({ queryKey: ["keys", id] });
    },
  });
  const update = useMutation({
    mutationFn: ({ keyId, on }: { keyId: number; on: boolean }) => updateKey(id, keyId, on),
    onSuccess: (key) =>
      qc.setQueryData<ApiKey[]>(["keys", id], (list) => list?.map((k) => (k.id === key.id ? key : k))),
    // A 409 means the key was revoked meanwhile: read the list again so the row says so
    onError: () => qc.invalidateQueries({ queryKey: ["keys", id] }),
  });
  const revoke = useMutation({
    mutationFn: (keyId: number) => revokeKey(id, keyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["keys", id] }),
  });

  return (
    <section>
      <PageHeader title="Settings" />
      <RepositoriesCard projectId={id} canEdit={project.data == null ? undefined : canEdit} />
      <div className="card">
        <h2>API keys</h2>
        <p className="muted">
          The collector authenticates uploads with a project API key, sent as the{" "}
          <code>QEOS_API_KEY</code> environment variable in CI.
        </p>
        {roleKnown && !canEdit && <p className="muted">Only owners, admins and members manage API keys.</p>}
        {canEdit && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
            className="inline-form"
          >
            <label>
              Name
              <input required placeholder="e.g. github-actions" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            {canManage && (
              <label className="check">
                <input type="checkbox" checked={canReadImpact} aria-describedby={impactHint}
                  onChange={(e) => setCanReadImpact(e.target.checked)} />
                Can read test suggestions
              </label>
            )}
            <button type="submit" disabled={create.isPending}>Create key</button>
          </form>
        )}
        {roleKnown && (
          <p id={impactHint} className="muted">
            Lets <code>qeos-collector impact</code> and <code>run-impact</code> read this project's test suggestions.
            {!canManage && " Only owners and admins allow test suggestions."}
          </p>
        )}
        <span role="status" className="sr-only">{snippetCopied ? "Copied" : ""}</span>
        {create.error != null && <ErrorBanner error={create.error} />}
        {revoke.error != null && <ErrorBanner error={revoke.error} />}
        {update.error != null && <ErrorBanner error={update.error} />}
        {created && (
          <SecretBlock label={`API key ${created.name}`} value={created.key}
            copyLabel={`Copy key ${created.name}`} copyText="Copy key" />
        )}

        {keys.error != null && <ErrorBanner error={keys.error} onRetry={() => keys.refetch()} />}
        {keys.isPending && <p className="muted">Loading keys…</p>}
        {keys.data?.length === 0 && <p className="muted">No API keys yet — create one to start uploading.</p>}
        {keys.data != null && keys.data.length > 0 && (
          <table className="data">
            <thead>
              <tr>
                <th>Name</th><th>Key</th><th>Test suggestions</th><th>Created</th><th>Last used</th>
                <th><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {keys.data.map((key) => (
                <tr key={key.id}>
                  <td>{key.name}</td>
                  <td><code>{key.key_prefix}…</code></td>
                  <td>
                    {canManage && !key.revoked_at ? (
                      <ImpactSwitch apiKey={key} hint={impactHint}
                        saving={update.isPending && update.variables?.keyId === key.id}
                        onToggle={(on) => { if (!update.isPending) update.mutate({ keyId: key.id, on }); }} />
                    ) : (key.can_read_impact ? "On" : "Off")}
                  </td>
                  <td>{new Date(key.created_at).toLocaleDateString()}</td>
                  <td>{key.last_used_at ? new Date(key.last_used_at).toLocaleString() : "—"}</td>
                  <td>
                    {key.revoked_at ? (
                      <span className="muted">revoked</span>
                    ) : !canEdit ? null : (
                      <ConfirmButton
                        label="Revoke"
                        ariaLabel={`Revoke key ${key.name}`}
                        question={`Revoke key ${key.name}? Uploads using it stop working immediately.`}
                        confirmLabel="Revoke"
                        onConfirm={() => revoke.mutate(key.id)}
                        disabled={revoke.isPending}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Wire up your CI</h2>
        <p className="muted">
          {snippetKind === "sync" ? (
            platform === "github" ? (
              <>
                Commit this as <code>.github/workflows/qeos-sync-cases.yml</code> on the default branch and run it
                once by hand (Actions → Run workflow; tick <code>first_sync</code> if the cases were first imported
                from the dashboard). After that, every push that changes a <code>.feature</code> file syncs the
                cases; other branches skip.
              </>
            ) : platform === "cli" ? (
              <>Run this from the repository root on any machine with Python 3.9+: the paths must match the test report.</>
            ) : (
              <>
                Add this to the pipeline: it syncs the test cases on the default branch and skips on any other.
                Store the API key as a CI secret named <code>QEOS_API_KEY</code>.
              </>
            )
          ) : platform === "cli" ? (
            <>Run this on any machine with Python 3.9+, from the folder holding your test reports.</>
          ) : platform === "github" ? (
            <>
              In the repository, Settings → Secrets and variables → Actions: variable <code>QEOS_URL</code> (this
              QEOS address), secret <code>QEOS_API_KEY</code>. Then paste this into the workflow that runs the
              tests; the comment at the end covers a suite that gathers shard reports first.
            </>
          ) : (
            <>
              Paste this after your test step; store the API key as a CI secret named{" "}
              <code>QEOS_API_KEY</code>.
            </>
          )}
        </p>
        <label>
          CI platform
          <select value={platform} onChange={(e) => { setPlatform(e.target.value); setSnippetCopied(false); }}>
            {Object.entries(snippets).map(([value, s]) => (
              <option key={value} value={value}>{s.label}</option>
            ))}
          </select>
        </label>
        <label>
          What to add
          <select
            value={snippetKind}
            onChange={(e) => { setSnippetKind(e.target.value as SnippetKind); setSnippetCopied(false); }}
          >
            <option value="upload">Upload results after the tests</option>
            <option value="sync">Sync test cases from .feature files</option>
          </select>
        </label>
        {local && HOSTED_RUNNERS.includes(platform) && (
          <p role="note" className="note">
            Hosted {snippets[platform].label} runners cannot reach localhost, where this page is
            served from. Use the CLI on this machine, a self-hosted runner here (add{" "}
            <code>--ca-file</code> for the self-signed certificate), or a deployment with a public address.
          </p>
        )}
        <pre data-testid="ci-snippet" className="code-block" tabIndex={0} aria-label="CI configuration">
          <code>{snippetCode}</code>
        </pre>
        <button
          type="button"
          aria-label="Copy snippet for CI"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(snippetCode);
              setSnippetCopied(true);
            } catch {
              setSnippetCopied(false); // clipboard blocked: the snippet stays selectable
            }
          }}
        >
          {snippetCopied ? "Copied" : "Copy snippet"}
        </button>
        {platform === "github" && MANAGE_ROLES.includes(project.data?.my_role ?? "") && (
          <p className="muted">
            Running selected tests from QEOS (Play) needs a third file, <code>qeos-run.yml</code>: see{" "}
            <a href="#run-from-qeos">Run from QEOS</a> below.
          </p>
        )}
      </div>

      <CollectionCard
        projectId={id}
        canManage={project.data == null ? undefined : MANAGE_ROLES.includes(project.data.my_role ?? "")}
      />
      {project.data != null && MANAGE_ROLES.includes(project.data.my_role ?? "") && <CiTargetCard projectId={id} />}

      <MaskingCard projectId={id} canEdit={project.data == null ? undefined : canEdit} />
      <LogValuesCard projectId={id} canEdit={project.data == null ? undefined : canEdit} />
      {project.data != null && (
        <NotificationsCard projectId={id} projectName={project.data.name} canEdit={canEdit} />
      )}
      {project.data != null && (
        <DataCard
          project={project.data}
          canManage={MANAGE_ROLES.includes(project.data.my_role ?? "")}
          onDeleted={() => {
            // Pending now: the project list shows it greyed (owners and admins) or not at all
            void qc.invalidateQueries({ queryKey: ["projects"] });
            // Its cached copy is live and fresh for a minute: Back would show the project as if nothing happened
            qc.removeQueries({ queryKey: ["project", id] });
            navigate("/");
          }}
        />
      )}
    </section>
  );
}
