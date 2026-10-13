import { useId, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiKey, ApiKeyCreated, createKey, listKeys, revokeKey, updateKey } from "../api/keys";
import { getProject } from "../api/orgs";
import CollectionCard from "../components/CollectionCard";
import CiTargetCard from "../components/CiTargetCard";
import ConfirmButton from "../components/ConfirmButton";
import ErrorBanner from "../components/ErrorBanner";
import SecretBlock from "../components/SecretBlock";
import DataCard from "../components/DataCard";
import MaskingCard from "../components/MaskingCard";
import NotificationsCard from "../components/NotificationsCard";
import RepositoriesCard from "../components/RepositoriesCard";
import PageHeader from "../components/PageHeader";

const COLLECTOR_REF = "collector-v0.7.0";

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

// Ready-to-paste CI wiring; the key itself always travels as a CI secret
function ciSnippets(origin: string): Record<string, { label: string; code: string }> {
  return {
    github: {
      label: "GitHub Actions",
      code: `# .github/workflows/tests.yml — after the test step
- uses: carneiru/QA-Vision-Platform/collector-action@${COLLECTOR_REF}
  if: always()   # report results even when tests failed
  with:
    url: ${origin}
    patterns: "reports/**/*.xml"
  env:
    QEOS_API_KEY: \${{ secrets.QEOS_API_KEY }}

- name: Sync test cases from .feature files   # runs on the default branch only (QEOS_IMPORT_BRANCH to change)
  run: |
    pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@${COLLECTOR_REF}#subdirectory=collector"
    qeos-collector import-features "tests/features/**/*.feature"
  env:
    QEOS_URL: ${origin}
    QEOS_API_KEY: \${{ secrets.QEOS_API_KEY }}`,
    },
    gitlab: {
      label: "GitLab CI",
      code: `# .gitlab-ci.yml — set QEOS_API_KEY as a masked CI/CD variable
include:
  - remote: https://raw.githubusercontent.com/carneiru/QA-Vision-Platform/${COLLECTOR_REF}/templates/qeos-collector.gitlab-ci.yml

qeos-collector-upload:
  variables:
    QEOS_URL: ${origin}
    QEOS_PATTERNS: "reports/**/*.xml"

# syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
qeos-import-features:
  image: python:3.12
  script:
    - pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@${COLLECTOR_REF}#subdirectory=collector"
    - qeos-collector import-features "tests/features/**/*.feature"
  variables:
    QEOS_URL: ${origin}   # QEOS_API_KEY comes from the masked CI/CD variable`,
    },
    azure: {
      label: "Azure Pipelines",
      code: `# azure-pipelines.yml — after the test step; add QEOS_API_KEY as a secret pipeline variable
- script: |
    pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@${COLLECTOR_REF}#subdirectory=collector"
    qeos-collector upload "reports/**/*.xml"
  displayName: Upload test results to QEOS
  condition: always()      # report results even when tests failed
  continueOnError: true    # a failed upload does not fail the pipeline
  env:
    QEOS_URL: ${origin}
    QEOS_API_KEY: $(QEOS_API_KEY)   # secret variables reach scripts only when mapped here
    # a secret still named QAV_API_KEY (before the QEOS rename)? map it instead: QEOS_API_KEY: $(QAV_API_KEY)

# syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
- script: |
    pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@${COLLECTOR_REF}#subdirectory=collector"
    qeos-collector import-features "tests/features/**/*.feature"
  displayName: Sync test cases from .feature files
  env:
    QEOS_URL: ${origin}
    QEOS_API_KEY: $(QEOS_API_KEY)`,
    },
    jenkins: {
      label: "Jenkins",
      code: `// Jenkinsfile — needs the qeos shared library (collector-jenkins/)
withCredentials([string(credentialsId: 'qeos-api-key', variable: 'QEOS_API_KEY')]) {
  withEnv(['QEOS_URL=${origin}']) {
    qeosCollectorUpload(patterns: 'reports/**/*.xml', ref: '${COLLECTOR_REF}')
    // syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
    // reuses the .qeos-venv that qeosCollectorUpload creates, so keep it after the upload step
    sh '''
      .qeos-venv/bin/python -m qeos_collector import-features "tests/features/**/*.feature"
    '''
  }
}`,
    },
    cli: {
      label: "Any machine (CLI)",
      code: isLocalOrigin(origin)
        ? `pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@${COLLECTOR_REF}#subdirectory=collector"
# The local stack uses a self-signed certificate; from the QA-Vision-Platform folder:
docker compose cp gateway:/etc/nginx/certs/tls.crt qeos-ca.crt
QEOS_URL=${origin} QEOS_API_KEY=<your key> qeos-collector upload "reports/**/*.xml" --ca-file qeos-ca.crt
# syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
QEOS_URL=${origin} QEOS_API_KEY=<your key> qeos-collector import-features "tests/features/**/*.feature" --ca-file qeos-ca.crt`
        : `pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@${COLLECTOR_REF}#subdirectory=collector"
QEOS_URL=${origin} QEOS_API_KEY=<your key> qeos-collector upload "reports/**/*.xml"
# syncs test cases from .feature files; runs on the default branch only (set QEOS_IMPORT_BRANCH to change)
QEOS_URL=${origin} QEOS_API_KEY=<your key> qeos-collector import-features "tests/features/**/*.feature"`,
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
  const [name, setName] = useState("");
  const [canReadImpact, setCanReadImpact] = useState(false);
  const impactHint = useId();
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const local = isLocalOrigin(window.location.origin);
  const [platform, setPlatform] = useState(local ? "cli" : "github");
  const [snippetCopied, setSnippetCopied] = useState(false);
  const snippets = useMemo(() => ciSnippets(window.location.origin), []);

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
          {platform === "cli" ? (
            <>Run this on any machine with Python 3.9+, from the folder holding your test reports.</>
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
        {local && HOSTED_RUNNERS.includes(platform) && (
          <p role="note" className="note">
            Hosted {snippets[platform].label} runners cannot reach localhost, where this page is
            served from. Use the CLI on this machine, a self-hosted runner here (add{" "}
            <code>--ca-file</code> for the self-signed certificate), or a deployment with a public address.
          </p>
        )}
        <pre data-testid="ci-snippet" className="code-block" tabIndex={0} aria-label="CI configuration">
          <code>{snippets[platform].code}</code>
        </pre>
        <button
          type="button"
          aria-label="Copy snippet for CI"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(snippets[platform].code);
              setSnippetCopied(true);
            } catch {
              setSnippetCopied(false); // clipboard blocked: the snippet stays selectable
            }
          }}
        >
          {snippetCopied ? "Copied" : "Copy snippet"}
        </button>
      </div>

      <CollectionCard
        projectId={id}
        canManage={project.data == null ? undefined : MANAGE_ROLES.includes(project.data.my_role ?? "")}
      />
      {project.data != null && MANAGE_ROLES.includes(project.data.my_role ?? "") && <CiTargetCard projectId={id} />}

      <MaskingCard projectId={id} canEdit={project.data == null ? undefined : canEdit} />
      {project.data != null && (
        <NotificationsCard projectId={id} projectName={project.data.name} canEdit={canEdit} />
      )}
      {project.data != null && (
        <DataCard project={project.data} canManage={MANAGE_ROLES.includes(project.data.my_role ?? "")} />
      )}
    </section>
  );
}
