# QEOS Helm chart

`deploy/helm/qeos/` deploys the whole platform on Kubernetes (ADR-038, spec
`docs/superpowers/specs/2026-10-21-aks-deployment-design.md` section 5.3): the five APIs, the dashboard, the gateway,
the four loop jobs and a migration hook. Compose (`docker-compose.yml`, `deploy/` on a VM) is unchanged and does not
use it.

| Values file | Where | What it adds |
|---|---|---|
| `values.yaml` | always | defaults only: no hostname, no secret, no environment |
| `values-ci.yaml` | kind in CI | images loaded as `qeos/<service>:local`, in-cluster PostgreSQL and MinIO, secrets from the `qeos-secrets` Secret |
| `values-staging.yaml` | AKS staging | Key Vault secrets, Azure Blob, the NetworkPolicy; Bicep's outputs come with `--set` |

```bash
# Render and check (needs helm 3 and yq v4; no cluster), and db-init's secret handling (stub psql)
bash deploy/helm/qeos/tests/render_test.sh
bash deploy/helm/qeos/tests/db_init_test.sh

# kind (Task 6 does this in CI): create the Secret, then install
kubectl create namespace qeos
kubectl -n qeos create secret generic qeos-secrets $(yq '.ciSecrets | to_entries | .[] | "--from-literal=" + .key + "=" + .value' deploy/helm/qeos/values-ci.yaml)
helm install qeos deploy/helm/qeos -n qeos -f deploy/helm/qeos/values-ci.yaml --wait --timeout 10m

# AKS: --timeout must exceed migrate.activeDeadlineSeconds (900 s), or Helm, not the Job, cuts a slow migration short
helm upgrade --install qeos deploy/helm/qeos -n qeos -f deploy/helm/qeos/values-staging.yaml --set ... --atomic --wait --timeout 20m
```

## What it creates

- **Deployments**, named like the Compose services: `auth-service`, `organization-service`, `project-service`,
  `ingestion-service`, `test-management-service`, `dashboard` and `gateway` with 2 replicas each, a
  PodDisruptionBudget (`minAvailable: 1`) and pods spread across nodes; `ingestion-retention`, `analytics-rollup`,
  `impact-rollup` and `weekly-summary` with 1 replica each (their PostgreSQL advisory locks make a second copy
  harmless, so a rolling update may overlap).
- **Services** (ClusterIP) with the Compose names: the APIs on 8000, the dashboard and the gateway on 8080. Nothing is
  exposed outside the cluster by the chart; the edge (Gateway API, Task 10) sends traffic to the `gateway` Service.
- One **ConfigMap** per workload, `qeos-<service>-env`, with its non-secret settings; secrets reach the pods only as
  `secretKeyRef`s (below). A change to the settings rolls the pods (`checksum/env` annotation).
- **ServiceAccounts** `qeos-services`, `qeos-ingestion`, `qeos-ingestion-retention` (and the hook's `qeos-migrate`):
  with Key Vault each carries its managed identity's client id (workload identity). Only the pods that call Azure with
  the SDK (`azureSdk: true`: ingestion and retention, for Blob) carry the label `azure.workload.identity/use`. The
  webhook it triggers injects `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` into every container's env, where they would
  override auth-service's settings of the same name (its Entra sign-in app). The Key Vault CSI driver needs no label:
  it gets the ServiceAccount's token itself.
- The **NetworkPolicy** `gateway-ingress` (when `networkPolicy.enabled`): the gateway's pods accept traffic only from
  the edge's namespace, `edge.namespace` (Application Routing: `app-routing-system`). The other policies of spec 5.3
  come in Stage 2. It is off in `values-ci.yaml`: kind's default network plugin does not enforce policies.

Every container runs as its image's non-root user (uid 10001 for the Python images, 101 for nginx) with a read-only
root filesystem, no privilege escalation, all capabilities dropped and the RuntimeDefault seccomp profile. Writable
directories are emptyDirs: `/tmp` everywhere, and `/var/cache/nginx` for the dashboard and the gateway. The gateway
renders its configuration into `/tmp/nginx` (`NGINX_RENDER_DIR`); its pid and temporary files are in `/tmp` already
(`gateway/nginx.conf.template`), and the dashboard writes `config.js` to `/tmp/qeos-config`. Pods get no Kubernetes API
token and no service-link variables (`enableServiceLinks: false`: a Service named `postgres` would otherwise inject
`POSTGRES_*` variables next to the settings of the same prefix).

Probes: readiness and liveness on `/health` (the APIs' own; the gateway answers it itself). The dashboard is ready on
`/config.js`, which exists only once its start-up script ran, and alive on `/health` (its SPA fallback). Loop jobs listen on no port and have none. `terminationGracePeriodSeconds: 30` and a `preStop`
sleep of 5 s let in-flight requests and in-API background tasks finish while the endpoints drop the pod.

## Values

| Value | Default | Meaning |
|---|---|---|
| `image.registry` | `""` | empty: `qeos/<service>:<tag>`; on AKS the ACR login server |
| `image.tag` | required | the git SHA (or `platform-v*` version) of the images; also `QEOS_COMMIT` |
| `image.pullPolicy` | `IfNotPresent` | `Never` on kind |
| `publicUrl` | required | `https://<host>`; `BASE_URL` (auth) and `DASHBOARD_URL` (ingestion and its jobs) |
| `namespaceSuffix` | `""` | appended to every service name; empty: `.<release namespace>.svc.cluster.local` |
| `version` | `""` | `QEOS_VERSION`; empty: the chart's `appVersion` |
| `secrets.source` | `keyvault` | `keyvault` or `kubernetes` (an existing Secret, `secrets.name`) |
| `secrets.optional` | `tm-secrets-key`, `smtp-user`, `smtp-password` | keys a pod may start without |
| `keyvault.name`, `keyvault.tenantId` | required with `keyvault` | the vault (Bicep output `keyVaultName`) |
| `keyvault.clientIds.<identity>` | required with `keyvault` | `services`, `ingestion`, `ingestion-retention`, `migrate` (Bicep output `workloadIdentityClientIds`) |
| `keyvault.absent` | `[]` | optional keys the vault does not hold, left out of the SecretProviderClasses |
| `postgres.host` | required | the server (Flexible Server: `<name>.postgres.database.azure.com`) |
| `postgres.adminUser` | `qeosadmin` | the admin login, used by the migration hook only |
| `postgres.sslmode` | `require` | `PGSSLMODE` for every connection (`disable` for the in-cluster CI server) |
| `postgres.clientImage` | `postgres:15.13` | psql for db-init (needs psql 15 or newer) |
| `artifacts.backend` | `s3` | `s3` or `azure` (`ARTIFACTS_BACKEND`) |
| `artifacts.s3.endpoint`, `.bucket` | `""`, `qeos-artifacts` | `ARTIFACTS_S3_*`; the keys are secrets |
| `artifacts.azure.accountUrl`, `.container` | `""`, `qeos-artifacts` | `ARTIFACTS_AZURE_*` (workload identity, no key) |
| `smtp.host`, `.port`, `.tls`, `.fromEmail`, `.fromName` | empty host: no email | the non-secret SMTP settings |
| `monitoring.enabled` | `false` | `MONITORING_ENABLED` for auth and the gateway; Grafana comes in Stage 2 |
| `gateway.trustedProxies` | required | the edge's address range (`GATEWAY_TRUSTED_PROXIES`); real client IPs and per-IP limits depend on it |
| `gateway.rates.*` | `auth 3r/s`, `api 10r/s`, `collect 5r/s`, `collectBlobs 25r/s`, `collectArtifacts 5r/s` | `RATE_*`, per pod: half of Compose's, as two pods serve |
| `gateway.importMaxBody` | `25m` | `GATEWAY_IMPORT_MAX_BODY` |
| `edge.namespace` | `app-routing-system` | the only namespace the gateway accepts traffic from |
| `networkPolicy.enabled` | `true` | renders `gateway-ingress` |
| `migrate.order` | the five APIs | the hook's migration order, after db-init |
| `migrate.imageTag` | `""` | the migration images' tag; empty: `image.tag` |
| `migrate.activeDeadlineSeconds`, `.backoffLimit` | `900`, `0` | a longer or failed migration fails the release; Helm's `--timeout` must be longer (20m) |
| `migrate.resources` | 50m/128Mi, limit 500m/512Mi | each hook container |
| `ci.backing` | `false` | in-cluster PostgreSQL and MinIO (kind only) |
| `services.<name>.replicas`, `.resources`, `.env` | see `values.yaml` | per workload; `env` holds plain settings and wins over the chart's |

`values.yaml` documents the other per-workload fields (`database`, `identity`, `secretEnv`, `urls`, ...). Internal
URLs are built as `http://<service><suffix>:8000` and carry no password: the services send `INTERNAL_API_PASSWORD`
themselves (ADR-038, Task 4).

Resources are starting estimates (APIs 100m/256Mi requested, 1 CPU/512Mi limit; ingestion 1Gi; loop jobs 512Mi;
nginx 128Mi), not yet measured on a running cluster. Revisit them with `kubectl top` once staging carries real load.

The edge in front of the gateway (Task 10) keeps the public `Host` header, so the services' redirects and links use
the public address. Its routes, certificate and limits come in Task 10.

## Secrets

No secret is in a values file, a ConfigMap or a rendered manifest: `tests/render_test.sh` checks that none of the CI
dummy values in `values-ci.yaml` (`ciSecrets`, which no template reads) appears in the output. Pods read secrets
through `secretKeyRef`s only; the hook reads them as files.

| Key (Key Vault secret name) | Read by |
|---|---|
| `secret-key` | every API and loop job (`SECRET_KEY`); the hook's migrations |
| `internal-api-password` | auth (`INTERNAL_API_PASSWORD`, `ORGANIZATION_INTERNAL_API_PASSWORD`), organization, project, ingestion, test-management, the loop jobs |
| `<db>-db-password` | each service's own role `<db>_app` (`POSTGRES_PASSWORD`); the hook; `<db>` is `auth`, `organization`, `project`, `ingestion`, `testmgmt` |
| `postgres-admin-password` | the hook's db-init only (and the in-cluster CI server) |
| `tm-secrets-key` (optional) | test-management (`TM_SECRETS_KEY`) |
| `smtp-user`, `smtp-password` (optional) | auth, ingestion and its jobs |
| `artifacts-s3-access-key`, `artifacts-s3-secret-key` | ingestion and ingestion-retention with `artifacts.backend: s3` (and MinIO in CI) |

- **`secrets.source: kubernetes`** (kind): one existing Secret, `qeos-secrets`, holds every key. The chart never
  creates it.
- **`secrets.source: keyvault`** (AKS): one SecretProviderClass per workload, `qeos-<workload>`, lists only the keys
  that workload reads (its own database password, never another service's) and syncs them into the Secret
  `qeos-secrets-<workload>`. Workloads sharing an identity share its client id. The CSI driver syncs only while a pod
  mounts the volume, so each such pod mounts it at `/mnt/secrets-store`. A key the vault lacks makes the mount fail:
  list optional keys it does not hold in `keyvault.absent`.

Database settings go in as `POSTGRES_SERVER`, `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` (the settings'
components path, which URL-escapes the password, so a generated password may hold any character) plus libpq's
`PGSSLMODE`. No `DATABASE_URL` is set.

## The migration hook

Before every install and upgrade, Helm runs the Job `qeos-migrate` (`pre-install,pre-upgrade`, weight 0). Hooks run
before the chart's own resources exist, so what the Job needs is a hook too, at weight -10: its ServiceAccount
`qeos-migrate`, its SecretProviderClass `qeos-migrate` (Key Vault: files only, nothing synced), and the ConfigMap
`qeos-migrate-scripts`. The Job reads the secrets as files in `/mnt/secrets` (from the CSI volume, or the
`qeos-secrets` Secret on kind). Each container mounts only the files it needs: the admin password reaches db-init
alone, and each migration sees its own role's password and `secret-key`. One init container each, in order:

1. `db-init` (`files/db-init.sh`, in `postgres.clientImage`, as the admin login): creates each database and its login
   role `<db>_app` if missing, sets the role's password from `<db>-db-password`, makes the role the owner of its own
   database and revokes `CONNECT` from everyone else. Idempotent; it works with Flexible Server's admin, which is not a
   superuser. It checks every password first: a missing or blank one stops it before any role is changed (an empty
   password would clear the role's and lock out its running pods). `tests/db_init_test.sh` covers this.
2. Each service in `migrate.order` (`files/migrate.sh <db>`, in the service's own image): `alembic upgrade head` as
   `<db>_app`.

If any step fails or the Job runs past `migrate.activeDeadlineSeconds` (keep Helm's `--timeout` longer: 20m for
900 s), Helm marks the release failed and applies none
of the new Deployments: the old pods keep serving. A failed Job is kept for `kubectl logs` until the next release
replaces it; a successful one is deleted.

Each API also has an init container, `wait-for-schema` (`files/wait-for-schema.sh`), that waits up to 300 s for its
database to be at the image's alembic head, so a pod never serves an unmigrated schema. A database already ahead of
the image (an older pod restarting after a newer release migrated) is accepted, by the rule below. It recognises
"ahead" by alembic's "Can't locate revision", so it cannot tell a newer release from a divergent one: a database
migrated by a hotfix branch whose revision this image lacks also passes. A hotfix migration must therefore land on
master too, in the same revision chain.

On kind, `ci.backing` adds PostgreSQL and MinIO as `pre-install` hooks at weight -20 (and the bucket Job at -15), so
they exist before the migration hook. They are created once per release, untouched by upgrades, and left behind by
`helm uninstall`; their data lives in emptyDirs.

### Migrations stay compatible with the previous release (expand, then contract)

During a rolling update old and new pods run side by side on the already-migrated schema, and an old pod may restart
after the migration. So every migration must work with the release before it:

- **Expand** first: add tables, nullable columns or columns with defaults, new indexes. Old code ignores them.
- **Contract** in a later release, once no running release uses it: drop or rename a column or table, add a
  `NOT NULL` without a default, change a type.
- A rename is an add (and copy) in one release and a drop in a later one.

Reviewers reject a migration that would break the previous release's code.
