# QEOS Helm chart

`deploy/helm/qeos/` deploys the whole platform on Kubernetes (ADR-038, spec
`docs/superpowers/specs/2026-10-21-aks-deployment-design.md` section 5.3): the five APIs, the dashboard, the gateway,
the four loop jobs and a migration hook. Compose (`docker-compose.yml`, `deploy/` on a VM) is unchanged and does not
use it.

| Values file | Where | What it adds |
|---|---|---|
| `values.yaml` | always | defaults only: no hostname, no secret, no environment |
| `values-ci.yaml` | kind in CI | images loaded as `qeos/<service>:kind`, in-cluster PostgreSQL and MinIO, secrets from the `qeos-secrets` Secret |
| `values-staging.yaml` | AKS staging | Key Vault secrets, Azure Blob, the edge (Gateway API, TLS), email, the NetworkPolicy; Bicep's outputs come with `--set` from the deploy workflow |

```bash
# Render and check (needs helm 3 and yq v4; no cluster), and db-init's secret handling (stub psql)
bash deploy/helm/qeos/tests/render_test.sh
bash deploy/helm/qeos/tests/db_init_test.sh

# kind (CI job helm-kind; "Testing locally with kind" below): create the Secret, then install
kubectl create namespace qeos
kubectl -n qeos create secret generic qeos-secrets $(yq '.ciSecrets | to_entries | .[] | "--from-literal=" + .key + "=" + .value' deploy/helm/qeos/values-ci.yaml)
helm install qeos deploy/helm/qeos -n qeos -f deploy/helm/qeos/values-ci.yaml --wait --timeout 10m

# AKS: the workflow deploy-aks.yml runs this ("The deploy workflow" below). --timeout must exceed
# migrate.activeDeadlineSeconds (900 s), or Helm, not the Job, cuts a slow migration short
helm upgrade --install qeos deploy/helm/qeos -n qeos -f deploy/helm/qeos/values-staging.yaml --set ... --atomic --wait --timeout 20m
```

## Testing locally with kind

The CI job `helm-kind` (`.github/workflows/ci.yml`) does this on every push: the render checks, the seven images, a
kind cluster, the install, `scripts/smoke_k8s.sh`, and two failed upgrades. The same steps on a workstation with Docker
(Desktop), kind, kubectl, helm 3 and yq v4:

```bash
# 1. The images, tagged as values-ci.yaml expects. :kind, not Compose's :local, so the dev stack's images stay as they are
for pair in auth-service:platforms/auth-service/auth-service/Dockerfile organization-service:platforms/organization-service/Dockerfile \
            project-service:platforms/project-service/Dockerfile ingestion-service:platforms/ingestion-service/Dockerfile \
            test-management-service:platforms/test-management-service/Dockerfile dashboard:dashboard/Dockerfile; do
  docker build -t "qeos/${pair%%:*}:kind" -f "${pair#*:}" .
done
docker build -t qeos/gateway:kind gateway

# 2. A cluster on the Kubernetes minor AKS creates by default (1.36; the node image the CI job pins), the images in it
kind create cluster --name qeos-kind --image kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed
kind load docker-image --name qeos-kind qeos/auth-service:kind qeos/organization-service:kind qeos/project-service:kind \
  qeos/ingestion-service:kind qeos/test-management-service:kind qeos/dashboard:kind qeos/gateway:kind

# 3. The Secret and the install (above): about 4 minutes, most of it pulling PostgreSQL and MinIO

# 4. The smoke through a port-forward; the gateway runs GATEWAY_TLS=off, so it is plain HTTP
pip install ./collector                       # qeos-collector, for the upload
kubectl -n qeos port-forward svc/gateway 28080:8080 &
bash scripts/smoke_k8s.sh http://localhost:28080 qeos     # ends with "all k8s checks passed"

# 5. A failed migration fails the upgrade; the release keeps serving. First one that starts and exits 1: each image
#    with an `alembic` shim (the CI step "Build and load the broken-migration images" builds them), so the Job fails
#    at once (backoffLimit 0, reason BackoffLimitExceeded)
helm upgrade qeos deploy/helm/qeos -n qeos -f deploy/helm/qeos/values-ci.yaml \
  --set migrate.imageTag=broken-migration --wait --timeout 5m                                         # fails
kubectl -n qeos get job qeos-migrate -o jsonpath='{.status.conditions[?(@.type=="Failed")].reason}'   # BackoffLimitExceeded
#    Then one whose image does not exist: it never starts, and the Job fails on its deadline (DeadlineExceeded)
helm upgrade qeos deploy/helm/qeos -n qeos -f deploy/helm/qeos/values-ci.yaml \
  --set migrate.imageTag=does-not-exist --set migrate.activeDeadlineSeconds=60 --wait --timeout 5m   # fails
helm history qeos -n qeos          # 1 deployed, 2 failed, 3 failed
bash scripts/smoke_k8s.sh http://localhost:28080 qeos --health-only

kind delete cluster --name qeos-kind
```

`smoke_k8s.sh` checks the gateway's `/health`, each service's `/health/<service>` route and the dashboard; then
registers a user (its verification token read from the CI PostgreSQL with `kubectl exec`), logs in, creates an
organization, a project and an API key, uploads a JUnit file with `qeos-collector` and reads the run back.
`--health-only` stops after the health checks. It refuses any URL but `http://localhost:<port>` or `127.0.0.1`, and
any kubectl context not named `kind-*`: it writes to the databases. Use a port nothing else publishes: if Compose's
gateway holds it, the checks reach Compose (a TLS-on gateway answers `301`, and the script stops after the health
checks). A failed check prints the status and at most 300 bytes of the body with API keys and tokens blanked, never
the raw body. In CI the `ciSecrets` dummy values are masked (`::add-mask::`) before the Secret is created, so the pod
logs printed on a failure cannot show them either.

`kind create cluster` makes `kind-qeos-kind` the current kubectl context; `kind delete cluster` removes it, so switch
back with `kubectl config use-context <yours>`.

## What it creates

- **Deployments**, named like the Compose services: `auth-service`, `organization-service`, `project-service`,
  `ingestion-service`, `test-management-service`, `dashboard` and `gateway` with 2 replicas each, a
  PodDisruptionBudget (`minAvailable: 1`) and pods spread across nodes; `ingestion-retention`, `analytics-rollup`,
  `impact-rollup` and `weekly-summary` with 1 replica each (their PostgreSQL advisory locks make a second copy
  harmless, so a rolling update may overlap).
- **Services** (ClusterIP) with the Compose names: the APIs on 8000, the dashboard and the gateway on 8080. Nothing is
  exposed outside the cluster by these; the edge (below) sends traffic to the `gateway` Service.
- One **ConfigMap** per workload, `qeos-<service>-env`, with its non-secret settings; secrets reach the pods only as
  `secretKeyRef`s (below). A change to the settings rolls the pods (`checksum/env` annotation).
- **ServiceAccounts** `qeos-services`, `qeos-ingestion`, `qeos-ingestion-retention` (and the hook's `qeos-migrate`):
  with Key Vault each carries its managed identity's client id (workload identity). Only the pods that call Azure with
  the SDK (`azureSdk: true`: ingestion and retention, for Blob) carry the label `azure.workload.identity/use`. The
  webhook it triggers injects `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` into every container's env, where they would
  override auth-service's settings of the same name (its Entra sign-in app). The Key Vault CSI driver needs no label:
  it gets the ServiceAccount's token itself.
- The **edge** (when `edge.enabled`, AKS): the Gateway `qeos-edge`, the HTTPRoutes `qeos` and `qeos-https-redirect`,
  the ConfigMap `qeos-edge-options`, the cert-manager `Issuer` `qeos-letsencrypt` and `Certificate` `qeos-edge` ("The
  edge" below). Off in `values-ci.yaml`: the smoke reaches the gateway through a port-forward.
- The **NetworkPolicy** `gateway-ingress` (when `networkPolicy.enabled`): the gateway's pods accept traffic only from
  the edge's proxy pods: those labelled `gateway.networking.k8s.io/gateway-name: qeos-edge` (Istio's own selector for
  a Gateway's pods) in `edge.namespace` (empty, also in staging: the release namespace, where the add-on runs them). The other policies of spec 5.3 come in Stage 2. It is off in `values-ci.yaml`: kind's
  default network plugin does not enforce policies.

Everything the chart renders is namespaced and lands in the release namespace (no ClusterRole, ClusterIssuer,
GatewayClass or Namespace): the deploy identity administers that namespace only. `tests/render_test.sh` checks it.

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
| `smtp.host`, `.port`, `.tls`, `.fromEmail`, `.fromName` | empty host: no email | the non-secret SMTP settings; with Key Vault, `SMTP_HOST` stays empty while `smtp-user` or `smtp-password` is in `keyvault.absent` (a server that wants a sign-in would refuse every message, and the links would be neither sent nor logged) |
| `monitoring.enabled` | `false` | `MONITORING_ENABLED` for auth and the gateway; Grafana comes in Stage 2 |
| `gateway.trustedProxies` | required | the edge's address range (`GATEWAY_TRUSTED_PROXIES`); real client IPs and per-IP limits depend on it |
| `gateway.rates.*` | `auth 3r/s`, `api 10r/s`, `collect 5r/s`, `collectBlobs 25r/s`, `collectArtifacts 5r/s` | `RATE_*`, per pod: half of Compose's, as two pods serve |
| `gateway.importMaxBody` | `25m` | `GATEWAY_IMPORT_MAX_BODY` |
| `edge.enabled` | `false` | render the Gateway, the HTTPRoutes, the Issuer and the Certificate (AKS) |
| `edge.namespace` | `""` | the edge proxy pods' namespace (`gateway-ingress`); empty: the release namespace |
| `edge.gatewayClassName` | `approuting-istio` | Application Routing's Gateway API implementation |
| `edge.publicIp.name`, `.resourceGroup` | required with `edge.enabled` | Bicep's static public IP, `pip-<aksName>-edge` in the environment's resource group |
| `edge.acme.email` | required with `edge.enabled` | Let's Encrypt's contact (expiry notices) |
| `edge.acme.server` | Let's Encrypt production | the ACME directory; `https://acme-staging-v02.api.letsencrypt.org/directory` for untrusted test certificates |
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

## The edge (AKS)

Spec 5.4. AKS's Application Routing add-on, in its Gateway API mode (GatewayClass `approuting-istio`, an Istio control
plane in `aks-istio-system` that manages Gateways only), runs the edge. The chart creates (`templates/gateway-api.yaml`,
`templates/certificate.yaml`):

- **Gateway `qeos-edge`**: listener `https` (443) ends TLS for `publicUrl`'s host with the Secret `qeos-edge-tls`;
  listener `http` (80) answers Let's Encrypt's challenge and redirects everything else to HTTPS (HTTPRoute
  `qeos-https-redirect`, 301). For each Gateway the add-on creates, in the Gateway's namespace, a Deployment, a
  LoadBalancer Service, an HPA (2-5 replicas) and a PDB, all named `qeos-edge-approuting-istio`.
- **HTTPRoute `qeos`**: everything over HTTPS to the `gateway` Service on 8080, which applies Compose's routes, limits
  and `auth_request`. The public `Host` reaches the gateway, so the services' redirects and links use the public
  address.
- **The static public IP**: `spec.infrastructure.annotations` (`service.beta.kubernetes.io/azure-pip-name`,
  `azure-load-balancer-resource-group`), which the add-on copies onto its Service, make it take Bicep's
  `pip-<aksName>-edge` and so the DNS name `stagingHostname` (`deploy/azure/README.md`, section 4.3).
- **Client addresses**: `spec.infrastructure.parametersRef` points at the ConfigMap `qeos-edge-options`, the add-on's
  per-Gateway customization, overlaid on the generated Service: `externalTrafficPolicy: Local`, and the add-on's
  health-probe annotations for ports 80 and 443 unset, as the add-on's documentation requires with `Local` (Azure's
  load balancer then probes the Service's health-check node port). With `Local` the edge sees each client's address
  and appends it to `X-Forwarded-For`; the gateway believes that header only from `gateway.trustedProxies`, the pod
  range (Azure CNI Overlay, `10.244.0.0/16`, where the edge pods get their addresses), and takes the last untrusted
  address (`real_ip_recursive`). Without `Local` every client would share one SNAT address and one rate-limit bucket.
- **The certificate**: a namespaced cert-manager `Issuer` (`qeos-letsencrypt`, ACME, HTTP-01 through the Gateway's
  `http` listener) and a `Certificate` (`qeos-edge`, ECDSA P-256, renewed by cert-manager) writing `qeos-edge-tls`.
  cert-manager itself, with its CRDs and Gateway API support, is a cluster admin's one-time step
  (`deploy/azure/README.md`, section 4.5). The https listener stays unready until the first certificate is issued (a
  few minutes after the first deploy).

**Limits.** The add-on offers no rate limits, body-size limits or request buffering settings (no `EnvoyFilter`; its
documentation lists these as unsupported). It applies no body-size limit and streams request bodies, so the gateway's
own limits stay the enforcing ones: per-IP rates halved (`gateway.rates`, two gateway pods), bodies up to 101m for
artifacts with buffering off. The route's overall timeout is off (`timeouts.request: 0s`), so a long upload is never
cut by the edge; the gateway's proxy timeouts end slow requests. Per-client limits shared across gateway pods wait for
Redis (spec 5.4).

Sources: [Application routing add-on with the Gateway API](https://learn.microsoft.com/azure/aks/app-routing-gateway-api)
(GatewayClass, generated resources, limitations, `externalTrafficPolicy: Local` and the probe annotations),
[Istio add-on Gateway API, ConfigMap customizations](https://learn.microsoft.com/azure/aks/istio-gateway-api)
(`parametersRef`, the allow list, which has `spec.externalTrafficPolicy` and `metadata.annotations`), and Istio's
gateway template (`manifests/charts/istio-control/istio-discovery/files/kube-gateway.yaml`) for the proxy pods' labels.

## The deploy workflow

`.github/workflows/deploy-aks.yml` (spec 5.8):

- **Triggers**: after a successful "Build platform images" run on master, to staging, and by hand (`environment`
  staging or production, `tag` a full git SHA or a platform version such as `1.2.3`). Production is a later stage:
  choosing it fails at once.
- **What it deploys**: the exact commit the build pushed images for. The build's job `built` uploads it as the
  artifact `built-sha` once all seven images are pushed, and the deploy downloads it from the triggering run; a build
  that pushed nothing leaves none, and nothing is deployed. A manual tag or SHA must be on master (`git merge-base
  --is-ancestor`), as must a platform version's `platform-v*` tag.
- **Steps**: a check of every variable's form (the client ids are GUIDs, the URL and host names well formed) before
  anything else; Azure sign-in with OIDC (no stored secret); kubectl and kubelogin pinned by version and SHA-256; a
  check that all seven images with that tag are in ACR and that the cluster is running; `az aks get-credentials` and
  `kubelogin convert-kubeconfig -l azurecli` (local accounts are off); the runner's address added to the API server's
  authorised ranges (after waiting for any cluster operation in progress, retrying if one starts first, and waiting
  again until the change has landed); `helm upgrade --install --atomic --wait --timeout 20m` with
  `values-<environment>.yaml` and Bicep's outputs as `--set`; then a check that the Gateway is programmed, the
  certificate ready and `https://<host>/health` answers. A last step, which runs whatever happened (a cancel too),
  signs in again, waits until no operation runs on the cluster (the add of a cancelled run goes on in Azure), reads the
  list as it is then and removes only the runner's address, retrying on a conflicting operation and never leaving the
  list empty (which would open the API server to all). The deploy job is serialised per environment (`concurrency` on
  the job, so a run that deploys nothing never takes a waiting deploy's place).
- **Before Azure exists** the automatic run prints a notice and deploys nothing; a manual run fails, naming the
  missing variables.
- It checks out the commit being deployed, so the chart always matches the images.

Variables: the repository's `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` and `ACR_NAME`
(`build-platform.yml` uses them too); the rest are variables of the GitHub environment (`staging`), none secret:

| Variable | Value (Bicep output) | Chart value |
|---|---|---|
| `AKS_NAME` | `aksName` | the cluster; `edge.publicIp.name` = `pip-<AKS_NAME>-edge` |
| `AKS_RESOURCE_GROUP` | `resourceGroup` | `edge.publicIp.resourceGroup` |
| `KEY_VAULT_NAME` | `keyVaultName` | `keyvault.name` (`keyvault.tenantId` is `AZURE_TENANT_ID`) |
| `POSTGRES_HOST` | `postgresHost` | `postgres.host` |
| `STORAGE_ACCOUNT_URL` | `storageAccountUrl` | `artifacts.azure.accountUrl` |
| `ARTIFACTS_CONTAINER` | `artifactsContainer` | `artifacts.azure.container` |
| `WORKLOAD_IDENTITY_CLIENT_IDS` | `workloadIdentityClientIds` (the JSON object) | `keyvault.clientIds.*` |
| `EMAIL_SENDER` | `communicationEmailSender` | `smtp.fromEmail` |
| `PUBLIC_HOSTNAME` | `stagingHostname` (later, the chosen domain) | `publicUrl` = `https://<PUBLIC_HOSTNAME>` |
| `ACME_EMAIL` | an address the team reads | `edge.acme.email` |

`deploy/azure/README.md` (sections 2 and 5) covers the identity, its roles and copying the outputs.

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
