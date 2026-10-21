# Running QEOS on Azure Kubernetes Service (AKS)

Date: 2026-10-21 · Status: for approval (builder check done) · Decision record to write: ADR-038

## 1. Intent

QEOS runs today as one Docker Compose project on a single VM behind a Caddy TLS edge (ADR-019). The
blueprint puts Kubernetes behind the trigger "first multi-node deployment" and ADR-003 is a placeholder
that leaves managed Kubernetes "to be addressed separately". The user now wants QEOS published on AKS.

This design says what changes so the same application runs on AKS with Azure-managed state, without
breaking the Compose path that local development, CI and the single-VM package use.

## 2. Decisions taken with the user

- **AKS** is the target, recorded as ADR-038; it supersedes ADR-003's placeholder and leaves ADR-019 valid
  for single-VM installs.
- **PostgreSQL: Azure Database for PostgreSQL Flexible Server** (managed backups, point-in-time restore,
  HA option). Not a pod.
- **Screenshots and other artifacts: Azure Blob Storage**, through a new Azure Blob implementation of
  `ArtifactStore`. No MinIO on AKS. MinIO stays for Compose.
- **Edge: the AKS Application Routing add-on with Gateway API**, plus cert-manager (Let's Encrypt)
  using its Gateway API support. Chosen after the review found that ingress-nginx is retired (upstream
  maintenance ended March 2026; Microsoft patches the add-on's NGINX only through November 2026) and
  Microsoft points to Gateway API as the long-term path. Caddy is not used on AKS.
- **Registry: Azure Container Registry (ACR)**, attached to the AKS cluster (no pull secrets).
- **Fresh start**: AKS starts empty. No data moves from any existing install now. Test cases and repository
  suites come back from the repository sync; results start with the first CI upload; people sign up or are
  invited again; CI jobs get new API keys. Migrating existing data is a separate, later project if wanted.
- The local Docker Compose stack (localhost, the tunnel, CI, the single-VM package) keeps working unchanged.

## 3. Goals, non-goals, anti-goals

Goals:

- Every platform image is built once in CI, pushed to ACR with an immutable tag, and runs unchanged in
  every environment (staging, production).
- One Helm chart deploys the whole platform; environment differences live in values files.
- Secrets come from Azure Key Vault; nothing secret sits in the chart, the images or the repository.
- State lives in managed services (Flexible Server, Blob) with Azure's backups; the cluster holds none.
- The same monitoring, alerts and dashboards work on AKS.
- The Compose path keeps working exactly as today.

Non-goals (this version):

- Multiple gateway replicas with shared rate limits (Redis). The gateway runs one replica; the Ingress
  adds a coarse per-IP limit. Redis stays behind its own trigger.
- Moving in-API background work (notifications, impact evaluation, log scan) to a queue.
- GitOps (Argo CD / Flux), service mesh, Vault, multi-region.
- Migrating data from an existing install (fresh start, see section 2).
- Password-less database sign-in (Microsoft Entra authentication on Flexible Server with workload
  identity). It removes database passwords but needs token refresh in every service; recorded in
  NEXT_STEPS for a later stage.
- Azure Managed Grafana / Azure Monitor managed Prometheus (see 5.7 for why).

Anti-goals:

- Any secret in a Helm values file, a ConfigMap, an image layer or a log line.
- Per-environment images (today the dashboard bakes SSO settings at build time).
- A deploy that can leave the database half migrated with new pods serving traffic.
- The cluster running containers as root or privileged.

## 4. Constraints

- Platform images are built locally today (`qeos/<svc>:local`, `pull_policy: never`); CI never pushes them.
- `postgres:15` is a floating tag; no Dockerfile sets `USER`, so all containers run as root.
- The dashboard bakes `VITE_GOOGLE_CLIENT_ID`, `VITE_MSAL_CLIENT_ID`, `VITE_MSAL_AUTHORITY` at build time.
- nginx uses Docker's embedded DNS (`resolver 127.0.0.11`), trusts a fixed proxy IP
  (`GATEWAY_TRUSTED_PROXIES=172.30.0.10`), and Grafana trusts the gateway by fixed IP
  (`GF_AUTH_PROXY_WHITELIST=172.30.1.10`).
- Rate limits are per gateway instance (nginx `limit_req_zone`).
- `INTERNAL_API_PASSWORD` is embedded in service URLs (`http://ingestion-service:${PW}@project-service:8000`).
- All five databases are reached as superuser `postgres` with one shared password; `db-init` creates them.
- Monitoring uses cAdvisor (Docker socket), node-exporter (`pid: host`), static Prometheus targets by
  Compose name, and the `container_label_com_docker_compose_service` label in one alert and three panels.
- Loop jobs (retention, analytics rollup, impact rollup, weekly summary) and the log scan already take
  PostgreSQL advisory locks, so more than one copy is safe.
- Another session is changing `artifact_store.py` for traces and videos (ADR-037): the Blob adapter must
  build on that interface, not fork it.

## 5. How it works

### 5.1 Azure resources (Bicep, in `deploy/azure/`)

One Bicep template per environment creates: a resource group; AKS (system + user node pool, Azure CNI
Overlay **powered by Cilium** so NetworkPolicies are enforced, workload identity and OIDC issuer on, Key
Vault CSI driver add-on, Application Routing add-on with Gateway API, API server limited to authorised IP
ranges); ACR attached to AKS with a retention policy for untagged images; PostgreSQL Flexible Server
(private access in the cluster's VNet, `pg_stat_statements` on); a Storage account with one private
container `qeos-artifacts` (no public access, soft delete on); Key Vault; a user-assigned managed identity
per workload that needs Azure access (ingestion **and ingestion-retention**: Blob, since retention and
purge delete artifacts; every service and the migration Job: Key Vault read). The deploy identity needs
rights to create role assignments (AcrPull, Key Vault Secrets User, Storage Blob Data Contributor). A runbook in `deploy/azure/README.md` lists the one-time steps Bicep cannot do (DNS record,
Entra app redirect URIs).

### 5.2 Images and CI

- New workflow `build-platform.yml`: on every push to `master` after CI is green, builds every platform
  image and pushes it to ACR as `<acr>/qeos/<svc>:<git-sha>`; a tag `platform-v*` adds `:<version>` to the
  same images. Logs in to Azure by OIDC (federated credential, no stored secret).
- Every Dockerfile gets a non-root `USER` and works with a read-only root filesystem. Writable emptyDirs:
  `/tmp` for all; for the gateway also `/etc/nginx/conf.d` (or a dedicated directory the entrypoint renders
  into: `nginx.conf`, `grafana.conf`, `real_ip.conf`), `/var/cache/nginx` and the pid path; for the
  dashboard the directory that holds the runtime `config.js`. nginx images listen on unprivileged ports
  (8080/8443) inside the container.
- Third-party images are pinned (`postgres:15.x` for Compose only; on AKS PostgreSQL is managed).
- **Dashboard runtime config**: the image serves `/config.js`, written at container start from env
  (`GOOGLE_CLIENT_ID`, `MSAL_CLIENT_ID`, `MSAL_AUTHORITY`); the app reads `window.__QEOS_CONFIG__` first
  and falls back to the `VITE_*` values, so Compose keeps working.

### 5.3 Helm chart (`deploy/helm/qeos/`)

- Deployments: the five APIs, the dashboard, the gateway (1 replica), the four loop jobs (1 replica each;
  advisory locks make more harmless).
- Services (ClusterIP) named like the Compose services. **nginx upstreams become templated fully
  qualified names** (`auth-service.<namespace>.svc.cluster.local:8000`, and Grafana's Service from
  kube-prometheus-stack): nginx's own `resolver` does not use the search domains in `resolv.conf`, so the
  short names that work on Compose do not resolve on Kubernetes. Compose keeps the short names (the
  template default).
- **Migrations**: one Helm `pre-install,pre-upgrade` hook Job runs `db-init` (create databases and
  per-service roles if missing) and then each service's `alembic upgrade head` in order. If it fails, the
  release fails and old pods keep serving. Because hooks run before the chart's normal resources exist,
  the Job's ServiceAccount (workload identity) and SecretProviderClass are hook resources too, with lower
  hook weights, and the Job mounts the Key Vault CSI volume and reads the passwords as files (a synced
  Kubernetes Secret only exists once some pod mounts the volume). APIs also have an init container that
  waits for their database's alembic head to match the image, so a pod never serves an unmigrated schema.
- **Migrations stay compatible with the previous release** (expand, then contract in a later release), so
  rolling updates can run old and new pods side by side with no outage. A review rule and a note in the
  contributing docs enforce it.
- Probes: readiness and liveness on `/health`; `terminationGracePeriodSeconds: 30` and a `preStop` sleep so
  in-API background tasks usually finish.
- Resources: requests and limits per workload. Only the monitoring containers have `mem_limit` today, so the
  builder sets starting values from a measurement of the running Compose stack (`docker stats`) and documents
  them.
- Security context everywhere: `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`,
  drop all capabilities. NetworkPolicies replace Compose's networks: only the gateway reaches the APIs and
  dashboard from the Ingress; only Prometheus scrapes; Grafana only from the gateway.
- Values files: `values.yaml` (defaults), `values-staging.yaml`, `values-production.yaml`.

### 5.4 Edge, gateway and TLS

- A Gateway API `Gateway` (Application Routing add-on) terminates TLS with a cert-manager `Certificate` from
  Let's Encrypt (HTTP-01) for the public domain; one `HTTPRoute` sends everything to the gateway over HTTP
  inside the cluster (the gateway's own self-signed TLS is off on AKS, kept for Compose). The app is public,
  because collectors on GitHub-hosted runners must reach it.
- The gateway trusts the edge's address range in `GATEWAY_TRUSTED_PROXIES` (a value, not a fixed IP), and
  the edge preserves the client IP (`externalTrafficPolicy: Local` on its load balancer, or the add-on's
  equivalent), so real client IPs and the per-IP limits keep working.
- `resolver` in nginx becomes a template value: `127.0.0.11` on Compose, the cluster DNS
  (`kube-dns.kube-system.svc.cluster.local`) on AKS.
- `proxy_redirect` and the HTTP→HTTPS redirect follow `GATEWAY_PUBLIC_PORT` (443 on AKS).
- Body sizes and timeouts from the gateway are mirrored at the edge (largest: artifacts 101m, request
  buffering off), using whatever the add-on's Gateway API implementation offers (policy resources). If the
  edge cannot match a limit, the gateway's own limit stays the enforcing one and the edge is set looser.

### 5.5 Data

- **PostgreSQL**: five databases on one Flexible Server; each service gets its own login role owning only
  its database (created by the migration Job from Key Vault values); the admin login is used only by that
  Job. `qeos_monitor` read role for postgres-exporter. TLS required (`sslmode=require`).
- **Blob**: `AzureBlobArtifactStore` implements `ArtifactStore` (put, get, delete, delete_prefix and
  whatever ADR-037 adds) with `azure-storage-blob` and `DefaultAzureCredential` (workload identity, no
  keys). Selected by `ARTIFACTS_BACKEND=azure` (default `s3`, so Compose is unchanged). Same object keys,
  same `ArtifactNotFound` / `ArtifactDeleteError` semantics; tests mirror the S3 store's.
- **Backups**: Flexible Server automated backups (35 days) and point-in-time restore; Blob soft delete and
  versioning. `deploy/backup.sh` stays for Compose only. A restore drill is part of the runbook.

### 5.6 Secrets and configuration

- Key Vault holds: `SECRET_KEY`, `INTERNAL_API_PASSWORD`, `TM_SECRETS_KEY`, each service's database
  password, the PostgreSQL admin password, SMTP, SSO client secrets, Grafana admin, alert webhooks.
- Mounted through the Secrets Store CSI driver as Kubernetes Secrets, read as env vars.
- Internal service URLs stop embedding the password: services read `*_INTERNAL_URL` (no credentials) and
  `INTERNAL_API_PASSWORD` separately and send Basic auth themselves. Compose sets both, so it keeps working.
- Public URLs (`BASE_URL`, `DASHBOARD_URL`, `GF_SERVER_ROOT_URL`) come from one `publicUrl` value.

### 5.7 Monitoring and logs

- `kube-prometheus-stack` replaces cAdvisor and node-exporter with kubelet/cAdvisor and node metrics;
  QEOS's own Prometheus rules, Alertmanager config and the five Grafana dashboards are shipped in the
  chart (ConfigMaps / PrometheusRules / ServiceMonitors). Chosen over Azure's managed Prometheus/Grafana
  because Grafana must stay behind the gateway's `auth_request` superuser check and the dashboards and
  alerts already live in the repo.
- ServiceMonitors replace static targets, so every replica is scraped. They must keep today's `job` labels
  (`auth`, `organization`, `project`, `ingestion`, `test-management`; `ServiceDown` takes `service` from
  `job`, and `overview.json` / `service-detail.json` filter on `job`) through `jobLabel` or relabeling, and
  the ingestion ServiceMonitor sets `honorLabels: true` so the job-heartbeat `job` labels survive (JobStale,
  JobFailing). QEOS's alerts are scoped to the QEOS namespace, so kube-prometheus-stack's own targets
  (some AKS control-plane ones cannot be scraped) never fire `ServiceDown`.
- The alert and three panels that use `container_label_com_docker_compose_service` switch to a label that
  works on both (`container`), or are templated per platform.
- **Grafana trust**: Grafana's auth proxy can only trust by IP, and gateway pod IPs change. Grafana gets a
  small proxy sidecar that accepts requests only with a shared header secret (from Key Vault, sent by the
  gateway) and forwards them to Grafana on `127.0.0.1`; `GF_AUTH_PROXY_WHITELIST` is `127.0.0.1`. A
  NetworkPolicy also limits Grafana to the gateway. This is what protects Grafana admin access.
- Logs: Container Insights (Log Analytics) on the cluster; all services already log to stdout.

### 5.8 Deploy pipeline

- `deploy-aks.yml`: manual dispatch (environment: staging or production, image tag). Azure OIDC login,
  `az aks get-credentials`, `helm upgrade --install --atomic --wait` with the environment's values file.
- Production requires a GitHub environment approval and deploys a `platform-v*` version. Staging deploys
  the `master` images (by git SHA) automatically after they are built.
- The AKS API server accepts only authorised IP ranges; the GitHub-hosted runner's address is allowed for
  the deploy step (fetched at run time and added temporarily), or a self-hosted runner in the VNet is used
  if the platform team requires it.

### 5.9 Email

AKS has no mail server, and without one verification and invitation links appear only in the auth-service
log (which nobody reads on AKS; this already broke an invite on the local stack). The AKS install sends
mail through **Azure Communication Services Email** (or another SMTP relay) using the existing `SMTP_*`
settings; the credentials are in Key Vault. Bicep creates the Communication Services resource and its
email domain; the runbook covers the sender domain's DNS records. Staging may use the Azure-managed sender
domain.

### 5.10 Testing the chart before Azure

A CI job installs the Helm chart into a throwaway kind cluster with in-cluster PostgreSQL and MinIO (values
file `values-ci.yaml`, `ARTIFACTS_BACKEND=s3`), waits for the migration hook and all pods, and runs
`scripts/smoke_gateway.sh` against it through a port-forward. `helm lint` and `helm template` with each
values file run too. Chart, migration-hook and nginx-upstream mistakes then fail CI on every push, before
anything reaches AKS.

### 5.11 Delivery in stages

Each stage is usable on its own:

1. **Staging that works**: images to ACR (5.2), the Helm chart with migrations (5.3), the edge and TLS
   (5.4), Flexible Server and Azure Blob (5.5), secrets from Key Vault (5.6), email (5.9), the kind CI job
   (5.10), and deploys to staging (5.8). The Azure Blob store is built **after the traces/videos work
   (ADR-037) has landed in `artifact_store.py`**, so it covers screenshots, traces and videos at once.
2. **Hardening and monitoring**: NetworkPolicies, read-only root filesystems everywhere, kube-prometheus-stack
   with QEOS's rules and dashboards, the Grafana proxy sidecar (5.7), Container Insights.
3. **Production**: the production cluster, the approval-gated deploy, the recovery targets checked by a
   restore drill (5.12), and the CI switch-over (5.13).

### 5.12 Recovery targets

Production targets: at most **5 minutes** of data loss (Flexible Server point-in-time restore) and **1 hour**
to restore service. Before production goes live, staging proves both: a point-in-time restore of the
database into a new server and a Blob restore (soft delete / versioning), timed and written up in the
runbook.

### 5.13 Switching CI over (fresh start)

A short checklist in the runbook: create the organization and project on AKS; create new project API keys;
set `QEOS_URL` and `QEOS_API_KEY` in the OBT repository (and any other CI); run the test-case import and
repository-suite sync; invite people. Results then flow to AKS from the next CI run.

### 5.14 Staging cost

Staging uses small sizes (B-series Flexible Server, small node pool) and stops outside working hours
(scheduled `az aks stop` / `az aks start`, Flexible Server stop/start). Production stays on.

## 6. Things to keep in mind

- Rate limits stay per gateway pod; with one gateway replica this matches today. Scaling the gateway is
  gated on Redis (TODO).
- Ingestion's per-process limits (8 storage calls, 60 s pending-deletion cache) become per pod; documented.
- The refresh cookie and Grafana cookie are same-origin; the Ingress must serve the dashboard and API on
  one host.
- The Entra app registration needs the new redirect URI; the Microsoft sign-in setup guide gets an AKS note.
- Cost: AKS nodes, Flexible Server and Storage replace one VM; the runbook gives a small-footprint SKU set.
- The Compose path (dev, CI, single VM) must keep passing CI unchanged.

## 7. Left to the builder

- Exact Bicep module layout, SKUs and node sizes (small defaults, documented).
- Chart helper structure and naming.
- Whether migrations run as one Job with ordered steps or one Job per service.
- Exact NetworkPolicy rules, within the intent in 5.3.

## 8. Calls made without the user (check these)

- **Own subscription**: it goes into a subscription or resource group the team controls, one AKS cluster
  per environment (staging, production). If it must fit a corporate landing zone instead (hub VNet,
  private DNS, Azure Policy / Gatekeeper rules), the Bicep and the pod security settings need a pass with
  the platform team. The Gatekeeper templates at the repo root are not applied by this design.
- **Public app, restricted API server**: the app is on a public domain; the AKS API server is limited to
  authorised IP ranges; no Front Door/WAF in this version.
- **Bicep** for Azure resources (not Terraform).
- **Migrations stay backward compatible for one release** (rolling updates, no outage) rather than
  `Recreate` with a short outage.
- **Images for every master commit** in ACR (staging), with an ACR retention policy for untagged images.
- **Azure Communication Services Email** for mail on AKS.
- **Recovery targets** of 5 minutes data loss and 1 hour to restore (adjust if the business needs differ).
- **Staging stops outside working hours** to save cost.
- **Workload identity** for Blob and Key Vault (no storage keys).
- **kube-prometheus-stack** in the cluster, not Azure managed Prometheus/Grafana.
- **One gateway replica** on AKS until Redis-backed limits exist.
- **Helm** (not Kustomize), deployed by a GitHub Actions workflow (not GitOps).
- **Release tag `platform-v*`** builds and pushes all platform images.
- Staging and production as the two environments.
- Dashboard SSO settings move to runtime `config.js`; Compose keeps build-time values as fallback.
- Internal URLs stop carrying the password (Compose updated in the same change).
