# ADR-038: QEOS on Azure Kubernetes Service (AKS), with Azure-managed state

Status: Accepted (2026-10-21; Stage 1, staging, built 2026-10-22; first real deploy pending) · Spec: `docs/superpowers/specs/2026-10-21-aks-deployment-design.md` · Supersedes ADR-003 for AKS

## Context

QEOS ran as one Docker Compose project, on a laptop or on a single VM behind a Caddy TLS edge (ADR-019). The
blueprint kept Kubernetes behind the trigger "first multi-node deployment", and ADR-003 is a placeholder that
leaves managed Kubernetes "to be addressed separately". The team now wants QEOS published on AKS, with state in
Azure services and a deploy that is repeatable. The Compose path (local development, CI, the single-VM package)
must keep working unchanged.

## Decision

- **AKS, one cluster per environment** (staging built; production is Stage 3). Azure resources are Bicep in
  `deploy/azure/`; the application is one Helm chart, `deploy/helm/qeos/`, with `values.yaml`, `values-staging.yaml`
  and `values-ci.yaml` (`values-production.yaml` comes with production, Stage 3). Deployed by a GitHub Actions
  workflow, not GitOps.
- **State lives in managed services.** PostgreSQL is Azure Database for PostgreSQL Flexible Server (five databases,
  one login role per service, the admin login used only by the migration Job, TLS required). Screenshots and traces
  are Azure Blob Storage, through `AzureBlobArtifactStore` behind `ARTIFACTS_BACKEND=azure` (default `s3`, so
  Compose keeps MinIO), authenticated by workload identity with no key anywhere. The cluster holds no state.
- **Images are built once.** `build-platform.yml` builds, Trivy-scans (a fixable critical finding fails the build)
  and pushes every image to Azure Container Registry as `<acr>/qeos/<svc>:<git-sha>`, signing in by OIDC. A
  `platform-v*` tag never rebuilds: it checks that master's build pushed `:<git-sha>` for the tagged commit and copies
  each manifest to `:<version>` in the registry, comparing the digests, so production runs the image staging ran.
  Every image runs as a non-root user with a read-only-ready root
  filesystem; nginx images listen on 8080/8443. The dashboard reads its sign-in settings at start from `/config.js`
  (falling back to the build-time `VITE_*` values), so one image serves every environment.
- **Secrets from Key Vault** through the Secrets Store CSI driver: one SecretProviderClass per workload, read through
  one of four managed identities (`services`, shared by seven workloads, `ingestion`, `ingestion-retention` and
  `migrate`), so a workload mounts only the secrets it names. Internal service URLs no longer embed the password:
  `*_INTERNAL_URL` is bare and `INTERNAL_API_PASSWORD` is read separately (Compose sets both).
- **Migrations are a Helm `pre-install,pre-upgrade` hook Job** (`db-init`, then each service's `alembic upgrade
  head`); if it fails the release fails and the old pods keep serving. APIs wait in an init container until their
  database is at the image's head. Migrations stay compatible with the previous release (expand, then contract).
- **Edge: the AKS Application Routing add-on with Gateway API**, plus cert-manager (Let's Encrypt, HTTP-01). The
  add-on's Gateway API implementation is Istio-based (`approuting-istio`). A static public IP outside the cluster
  survives stops and rebuilds; the Gateway names it by annotation. One `HTTPRoute` sends everything to the QEOS
  gateway over HTTP inside the cluster (the gateway's own TLS is off on AKS). One NetworkPolicy lets only the edge's
  proxy pods reach the gateway, which trusts `X-Forwarded-For` from the pod range alone.
- **Two replicas of each API, the dashboard and the gateway**, with PodDisruptionBudgets and spread across nodes.
  The four loop jobs run one replica each (advisory locks make more harmless).
- **Fresh start.** AKS begins empty; no data moves from an existing install.
- **Two GitHub identities.** The build identity (`AZURE_BUILD_CLIENT_ID`) holds AcrPush only and trusts `master`
  and the release tags (one federated credential per tag: wildcard subjects need Entra's flexible federated
  credentials, in preview). The deploy identity (`AZURE_DEPLOY_CLIENT_ID`, a variable of the GitHub environment)
  holds AcrPull and the cluster roles and trusts only `environment:<name>`, so the environment's branch policy and
  reviewers guard every use of the cluster roles.
- **Deploys:** `deploy-aks.yml` (manual or chained after a green build on master) signs in by OIDC, adds the runner's
  address to the API server's authorised ranges for the run only, and runs `helm upgrade --install --atomic --wait`
  of exactly the SHA the build pushed. Production is gated by a GitHub environment approval and deploys a
  `platform-v*` version.
- **Chosen without the user, as built:** Bicep over Terraform; Helm over Kustomize; email through Azure
  Communication Services (Azure-managed sender domain in staging); recovery targets of 5 minutes data loss and 1 hour
  to restore (proved by a restore drill before production); a Sunday-night maintenance window with automatic patch
  and node-image upgrades; Azure budget alerts at 80% and 100%; staging stopped outside working hours;
  kube-prometheus-stack in the cluster, not Azure managed Prometheus or Grafana (Grafana must stay behind the
  gateway's superuser check).

## Alternatives considered

- **ingress-nginx on AKS.** Rejected: upstream maintenance ended in March 2026 and Microsoft patches the add-on's
  NGINX only through November 2026. Gateway API is the path Microsoft recommends.
- **Caddy on AKS.** Rejected: certificates and routing are the cluster edge's job there.
- **PostgreSQL or MinIO as pods.** Rejected: backups, point-in-time restore and durability are Azure's to run.
- **Replace Compose with the chart.** Rejected: development, CI and single-VM installs need it unchanged.

## Consequences

- **Costs.** AKS nodes (one system and two to four user nodes of 2 vCPU in staging; the control plane on the Free
  tier), Flexible Server (B1ms in staging), a Storage account, Key Vault, ACR (Basic) and Communication Services
  replace one VM. Staging stops outside working hours; a budget of 300 per month alerts at 80% and 100%.
  Production stays on and costs more (Stage 3).
- **Compose is kept**, and CI still runs its smoke tests; the chart is tested in a throwaway kind cluster on every
  push (`helm-kind`, with in-cluster PostgreSQL and MinIO), so chart, migration-hook and nginx mistakes fail before
  AKS.
- **Edge limits.** The add-on has no edge rate or body-size limits, so the QEOS gateway's own limits stay the
  enforcing ones. With two gateway replicas nginx's per-pod zones allow a client up to twice the rate, so the limits
  are halved on AKS (a chart value). Exact shared limits wait for Redis.
- **The deploy identity keeps AKS Contributor** (trade-off). Adding the runner to the API server's authorised ranges
  needs `managedClusters/write`, and a custom role would not be narrower. The role could also change those ranges or
  re-enable local accounts. It is otherwise scoped: AcrPull on the registry, Kubernetes RBAC Admin on the `qeos`
  namespace only (cert-manager is a one-time cluster-admin step), and it cannot push images. A self-hosted runner in the VNet removes the need.
- **Key Vault purge protection is on**, in staging too: losing secrets to a mistaken delete costs more than the
  friction of renaming a vault on a rebuild.
- **Bicep deploys are incremental**: a role assignment Bicep no longer makes stays. The split of the GitHub identities
  moved AcrPush from the deploy identity to the build identity, so an environment deployed before it keeps the deploy
  identity's AcrPush until it is removed: `deploy/azure/check-role-assignments.sh` lists the two identities' roles in
  the resource group and flags or deletes any Bicep does not make (`deploy/azure/README.md`, section 3.2).
- **Per-secret access.** Each identity gets Key Vault Secrets User on the secrets it names, not on the vault. Only
  ingestion and its retention job hold a Storage data role, and Storage has shared-key access off.
- **GitHub environment branch policies.** The deploy identity's federated credential trusts the `staging` and
  `production` environments only, so each must allow deployments from `master` only (production also `platform-v*`
  tags). Bicep and
  the workflow cannot set this; an admin must (`deploy/azure/README.md`, section 5.1).
- **NetworkPolicies are ingress only** (Stage 2; `deploy/helm/README.md`). Every pod of the release is denied by
  default and each Service admits its callers alone, but egress stays open (residual): Blob, Entra ID and Key Vault
  have no stable addresses, and restricting them needs Cilium's FQDN policies (CiliumNetworkPolicy `toFQDNs`), which
  the chart does not use yet. A compromised pod can therefore still reach the internet and anything outside the
  namespace that has no policy of its own; inside it, only the Services that admit it.
- **kube-prometheus-stack is a cluster admin's release** (Stage 2; `deploy/monitoring/README.md`). It needs CRDs and
  cluster roles the deploy identity cannot create, so `deploy/monitoring/install.sh` installs it (release and namespace
  `qeos-monitoring`, Prometheus only: Grafana and Alertmanager come from the QEOS chart) once per cluster and after each
  version bump; CI's kind job runs the same script. The version is pinned in a wrapper chart Dependabot bumps, and the
  archive by its sha256. Prometheus admits 9090 from the QEOS chart's Grafana and its own namespace only.
- **QEOS's own monitoring comes from the chart** (Stage 2; `deploy/helm/README.md`, "Monitoring"). With
  `monitoring.enabled` (on in CI and staging) it renders ServiceMonitors with Compose's job names, PrometheusRules from
  byte-for-byte copies of Compose's rule files (without `qeos-host`: under the namespace enforcement a QEOS rule never
  sees `node_*` series), postgres-exporter as `qeos_monitor` (`pg_monitor` only; db-init creates it) and Alertmanager
  rendered by Compose's `render.sh`, with the null receiver when no channel is configured. Without
  kube-prometheus-stack's CRDs the render stops, naming `deploy/monitoring/install.sh`, so nothing is half applied.
- Per-process limits in ingestion (8 storage calls, a 60 s pending-deletion cache) become per pod.
- Staging stopped during the Sunday window misses its upgrade; documented.

## Verify on the first real deploy

Nothing here can be proved without a real subscription:

- Key Vault CSI mounts for pods without the workload-identity label (only ingestion and retention carry it).
  Fallback: keep the label and pin auth-service's `AZURE_*` variables.
- Blob copy and batch delete with Entra authentication; the Storage Blob Data Contributor role for ingestion and
  retention; the 18 s credential-failure latency.
- The namespace-scope Kubernetes RBAC Admin assignment, and that it covers Gateway API and cert-manager resources.
- The IP-level Network Contributor the edge's static address needs.
- The Gateway's static-IP annotations (`azure-pip-name`, `azure-load-balancer-resource-group`).
- Real client IPs reach the gateway (`externalTrafficPolicy: Local`) and the trusted-proxy range matches.
- The add-on's proxy pods and the probe annotations; the namespace the edge pods run in.
- With the NetworkPolicies under Cilium: kubelet probes and the edge's proxy pods still reach the pods (kind's kindnet
  is proved in CI), and Prometheus reaches the APIs from `networkPolicy.prometheus`.
- kube-prometheus-stack on AKS: node-exporter in the privileged `qeos-monitoring` namespace, Prometheus's 20Gi
  `managed-csi` volume, its NetworkPolicy under Cilium (Grafana in the QEOS namespace admitted, other pods refused; on
  kind it is proved by hand), and the default rules quiet on a healthy cluster.
- Monitoring on AKS: Kubernetes RBAC Admin at namespace scope also covers `monitoring.coreos.com` (ServiceMonitor,
  PrometheusRule); Flexible Server's admin may grant `pg_monitor` and create `pg_stat_statements` (db-init with
  monitoring on; CI's server gives its admin the same rights by hand); postgres-exporter reaches the server with
  `sslmode=require`.
- `pg_stat_statements` preloaded on Flexible Server; `db-init` with Flexible Server's admin (CI's kind job already
  runs it on PostgreSQL 16 as a `CREATEROLE CREATEDB` admin that is not a superuser, which needs the role granted
  `WITH INHERIT TRUE, SET TRUE`).
- The Defender for Containers plan is enabled on the subscription (`az security pricing show --name Containers`:
  `pricingTier` `Standard`); Bicep turns on the sensor only.
- A cancelled deploy run still removes the runner's /32 from the authorised ranges.
- Federated credentials (the build identity on master and on a release tag, the deploy identity on
  `environment:staging`), SMTP keys in the vault, and sign-in by Microsoft with the new redirect URI.
- AcrPull is enough for the deploy identity's `az acr repository show`, and AcrPush for the release job's
  `docker buildx imagetools create` and digest check.

## Later

- **Redis** shared rate limits (the trigger, a second gateway instance, is met on AKS; the per-pod limits are the stopgap).
- **A queue** for in-API background work (notifications, impact evaluation, log scan).
- **Entra database authentication** on Flexible Server with workload identity, so no service holds a database
  password (NEXT_STEPS).
- **Stage 2, hardening and monitoring:** NetworkPolicies beyond the one the edge needs, kube-prometheus-stack with
  QEOS's rules and dashboards, the Grafana proxy sidecar (header secret, replacing IP trust), Container Insights.
- **Stage 3, production:** the production cluster, the approval-gated deploy, the restore drill that proves the
  recovery targets, the CI switch-over checklist, a self-hosted runner if required.
- Migrating data from an existing install; Front Door or WAF; a corporate landing zone.
