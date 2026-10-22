# QEOS on Azure: the AKS environment (runbook)

The Azure resources of one QEOS environment on AKS (ADR-038, spec
`docs/superpowers/specs/2026-10-21-aks-deployment-design.md` section 5.1), as Bicep, and the steps around them that
Bicep cannot do. The Helm chart that runs on it is `deploy/helm/qeos` (`deploy/helm/README.md`); the single-VM Compose
install is `deploy/README.md` and does not change.

| File | What |
|---|---|
| `main.bicep` | Subscription scope: the resource group and every module below; the outputs the chart and workflows use |
| `staging.bicepparam` | Staging's sizes; secret, personal and per-operator values come from environment variables |
| `modules/network.bicep` | VNet: subnet `aks-nodes` (service endpoints Key Vault, Storage) and subnet `postgres` (delegated) |
| `modules/aks.bicep` | The cluster, its control-plane identity, the edge's static public IP, Log Analytics for Defender, the maintenance windows |
| `modules/acr.bicep` | Container registry; AcrPull for the kubelet, AcrPush for the GitHub identity |
| `modules/identities.bicep` | One managed identity per workload identity, federated with its ServiceAccount |
| `modules/keyvault.bicep` | Key Vault (RBAC), `postgres-admin-password`, `smtp-user`, Key Vault Secrets User per secret for the identities that read it |
| `modules/postgres.bicep` | PostgreSQL Flexible Server, private access, its private DNS zone |
| `modules/storage.bicep` | Storage account and container `qeos-artifacts`; Storage Blob Data Contributor for ingestion and retention |
| `modules/email.bicep` | Communication Services, Email Service, the Azure-managed sender domain, the SMTP username and send role |
| `modules/budget.bicep` | Monthly budget with alert emails at 80% and 100% |
| `init-secrets.sh` | Generates, once, the Key Vault secrets Bicep does not write |
| `bicepconfig.json` | Linter rules; CI fails on any warning |

CI (`ci.yml`, job `bicep`) builds and lints the templates and the parameter file on every push, and
`scripts/tests/test_azure_bicep.py` fails when the Key Vault secret names, which identity reads which secret, the
workload identities, ServiceAccount names, container name, admin login or pod range here differ from the chart's. Nothing in CI signs in to Azure.

## 1. What gets created

| Resource | Settings that matter |
|---|---|
| AKS `aks-qeos-<env>` | Azure CNI Overlay powered by Cilium (`networkDataplane`/`networkPolicy: cilium`, pod range `10.244.0.0/16`); workload identity and OIDC issuer; Key Vault Secrets Store CSI add-on (rotation every 2 min); Application Routing's Gateway API implementation (GatewayClass `approuting-istio`) on the managed Gateway API CRDs, NGINX off; Entra ID sign-in with Azure RBAC, local accounts disabled; API server open only to `apiServerAuthorizedIpRanges`; auto-upgrade `patch`, node OS `NodeImage`, both in a Sunday 01:00-05:00 UTC window; Defender for Containers sensor; a tainted system pool (1 node) and an autoscaling user pool (2-4 nodes, Azure Linux) |
| Public IP `pip-aks-qeos-<env>-edge` | Static, Standard, DNS label `qeos-<env>-<hash>` (scope `ResourceGroupReuse`, so Azure adds a hash: the name cannot be taken over); outside the cluster, so it survives stops and rebuilds; the control-plane identity has Network Contributor on it to attach it |
| ACR `acrqeos<env><hash>` | No admin user, no anonymous pull; the kubelet pulls with AcrPull (no pull secret) |
| PostgreSQL `psql-qeos-<env>-<hash>` | Version 16, `Standard_B1ms` Burstable in staging; private access in subnet `postgres` with zone `<server>.private.postgres.database.azure.com`; no public access; `require_secure_transport` on and `ssl_min_protocol_version` TLSv1.2, pinned; backups 35 days; `pg_stat_statements` allowed in `azure.extensions` (the platform already preloads it, so `shared_preload_libraries` keeps its default and no restart is needed); admin login `qeosadmin` (the chart's `postgres.adminUser`) |
| Storage `stqeos<env><hash>` | Shared keys off (Entra ID only), no public blob access, TLS 1.2, HTTPS only; reachable from the node subnet and `operatorIpRanges` only; soft delete 14 days (blobs and containers), versioning on, previous versions removed after 14 days; private container `qeos-artifacts` |
| Key Vault `kv-qeos-<env>-<hash>` | RBAC mode (no access policies), soft delete 90 days; purge protection on in every environment (section 9); each secret readable only by the identities whose SecretProviderClasses list it (`secretReaders` in `main.bicep`), e.g. `postgres-admin-password` by `migrate` alone; reachable from the node subnet and `operatorIpRanges` only |
| Managed identities `id-qeos-<env>-{services,ingestion,ingestion-retention,migrate}` | Federated with `system:serviceaccount:<namespace>:qeos-<identity>`, issuer the cluster's OIDC URL, audience `api://AzureADTokenExchange`; each reads its own Key Vault secrets; `ingestion` and `ingestion-retention` also read, write, copy and delete blobs in `qeos-artifacts` |
| Communication Services `acs-qeos-<env>-<hash>` + Email Service | Data in `emailDataLocation` (Europe); the Azure-managed domain `<guid>.azurecomm.net`, sender `DoNotReply@` it; access keys off (SMTP signs in with Entra ID) |
| Budget `budget-qeos-<env>` | `monthlyBudget` per month on the resource group; email to `budgetEmails` at 80% and 100% of actual cost |

Outputs (`az deployment sub show --name qeos-<env> --query properties.outputs`):

| Output | Used as |
|---|---|
| `acrName` | repository variable `ACR_NAME`; chart `image.registry` = `<acrName>.azurecr.io` |
| `aksName`, `resourceGroup` | `az aks get-credentials` in the deploy workflow |
| `keyVaultName` | chart `keyvault.name`; `init-secrets.sh` |
| `postgresHost` | chart `postgres.host` |
| `storageAccountUrl`, `artifactsContainer` | chart `artifacts.azure.accountUrl`, `artifacts.azure.container` |
| `workloadIdentityClientIds` | chart `keyvault.clientIds.{services,ingestion,ingestion-retention,migrate}` |
| `communicationEmailSender` | chart `smtp.fromEmail` |
| `stagingHostname` | the edge's DNS name, `qeos-<env>-<hash>.<hash>.<region>.cloudapp.azure.com` (section 4.3): chart `publicUrl` = `https://<stagingHostname>` |

The chart's `keyvault.tenantId` is the tenant, the same as the repository variable `AZURE_TENANT_ID`.

## 2. Before the first deploy

1. **A subscription** the team controls (spec section 8) and an account with **Owner** on it, or Contributor plus
   Role Based Access Control Administrator: the templates create role assignments and one custom role.
2. **Tools**: Azure CLI 2.86 or newer (the Application Routing Gateway API needs it), `az bicep install`, `kubectl`,
   `helm`, `jq` and `kubelogin` (`az aks install-cli`), `openssl`, `gh`.
3. **Resource providers**, once per subscription:

   ```bash
   for ns in Microsoft.ContainerService Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL Microsoft.Storage \
     Microsoft.KeyVault Microsoft.ManagedIdentity Microsoft.Network Microsoft.OperationalInsights \
     Microsoft.Communication Microsoft.Consumption Microsoft.Security; do
     az provider register --namespace "$ns"
   done
   ```

4. **Defender for Containers plan**: the cluster's security profile turns the sensor on, but the plan is billed and
   switched on per subscription, so Bicep leaves it alone. If the subscription does not have it yet:
   `az security pricing create --name Containers --tier standard`.
5. **The GitHub identity** (the `AZURE_CLIENT_ID` the workflows sign in with): an Entra application with federated
   credentials for this repository: `repo:<org>/Atriis.QEOS:ref:refs/heads/master` (`build-platform.yml`) and
   `repo:<org>/Atriis.QEOS:environment:staging` (`deploy-aks.yml`, whose deploy job runs in the GitHub environment
   `staging`). Its service
   principal's object id is `QEOS_DEPLOY_PRINCIPAL_ID` below: Bicep gives it AcrPush on the registry; on the cluster,
   Azure Kubernetes Service Cluster User Role (kubeconfig) and Azure Kubernetes Service Contributor Role (adding its
   runner to the authorised IP ranges for a run); and Azure Kubernetes Service RBAC Admin on the chart's namespace
   only (`<cluster>/namespaces/qeos`: helm). Nothing cluster-wide: the namespace and cert-manager are a cluster
   admin's one-time step (section 4.5). It needs no role on Key Vault or Storage.
6. **An Entra group of cluster admins** (`QEOS_AKS_ADMIN_GROUP_ID`): with local accounts off, `kubectl` signs in with
   Entra ID, and only this group gets cluster-admin. The deploy identity is admin of the namespace `qeos` only (item 5).

## 3. Deploy

From the repository root, in bash. The parameter file reads these from the environment:

| Variable | Required | Value |
|---|---|---|
| `QEOS_ADMIN_IP_RANGES` | yes | Operators' public addresses, comma-separated CIDRs (`203.0.113.7/32,198.51.100.0/24`): the API server, Key Vault and Storage admit them |
| `QEOS_POSTGRES_ADMIN_PASSWORD` | yes | First deploy: a new random value. Later: the one in Key Vault (below) |
| `QEOS_BUDGET_EMAILS` | yes | Comma-separated addresses for the budget alerts |
| `QEOS_OPERATOR_PRINCIPAL_ID` | no | Your object id (`az ad signed-in-user show --query id -o tsv`) or a group's: Key Vault Secrets Officer, for `init-secrets.sh` |
| `QEOS_AKS_ADMIN_GROUP_ID` | no | The cluster admins group |
| `QEOS_DEPLOY_PRINCIPAL_ID` | no | The GitHub identity's service principal object id |
| `QEOS_SECRETS_INITIALIZED` | no | `true` once `init-secrets.sh` has run (section 3.1): the identities then get read access to its secrets |
| `QEOS_SMTP_APP_CLIENT_ID`, `QEOS_SMTP_APP_PRINCIPAL_ID` | no | The ACS SMTP application (section 4.1); empty on the first deploy |

```bash
az login
az account set --subscription <subscription id>

export QEOS_ADMIN_IP_RANGES="$(curl -s https://api.ipify.org)/32"
export QEOS_BUDGET_EMAILS="ops@example.com"
export QEOS_OPERATOR_PRINCIPAL_ID="$(az ad signed-in-user show --query id -o tsv)"
export QEOS_AKS_ADMIN_GROUP_ID="<group object id>"
export QEOS_DEPLOY_PRINCIPAL_ID="$(az ad sp show --id <AZURE_CLIENT_ID> --query id -o tsv)"
# First deploy only. Flexible Server wants three of: upper case, lower case, digits, symbols. The fixed "Qa1-" gives
# all four; the rest is random hex. No character needs escaping in a shell, a URL or SQL
export QEOS_POSTGRES_ADMIN_PASSWORD="Qa1-$(openssl rand -hex 24)"

# What would change, then the deploy (20-30 minutes the first time)
az deployment sub what-if --name qeos-staging --location westeurope --parameters deploy/azure/staging.bicepparam
az deployment sub create  --name qeos-staging --location westeurope --parameters deploy/azure/staging.bicepparam
az deployment sub show --name qeos-staging --query properties.outputs
```

**Every later deploy** must pass the admin password the vault holds, or it changes the server's password to a new
value (Bicep writes the new one to the vault too, so the next migration hook still signs in, but nothing else would
know it):

```bash
export QEOS_POSTGRES_ADMIN_PASSWORD="$(az keyvault secret show --vault-name <keyVaultName> \
  --name postgres-admin-password --query value -o tsv)"
```

Redeploying also resets the API server's authorised ranges to `QEOS_ADMIN_IP_RANGES`.

### 3.1 The secrets

The chart's SecretProviderClasses read these Key Vault secrets (`deploy/helm/README.md`, "Secrets"); a missing one,
or one the workload's identity may not read, fails the pod's volume mount, so all must exist and be granted before the
first `helm install`. Each identity reads only the secrets its workloads' SecretProviderClasses list (`secretReaders`
in `main.bicep`, kept equal to the chart by `scripts/tests/test_azure_bicep.py`); a role on a secret needs the secret,
so the secrets `init-secrets.sh` generates are granted by the deploy after it:

| Secret | Written by |
|---|---|
| `postgres-admin-password` | Bicep (`QEOS_POSTGRES_ADMIN_PASSWORD`) |
| `secret-key`, `internal-api-password`, `auth-db-password`, `organization-db-password`, `project-db-password`, `ingestion-db-password`, `testmgmt-db-password` | `init-secrets.sh`, once, random |
| `smtp-user` | Bicep, once the SMTP application exists (section 4.1) |
| `smtp-password` | `init-secrets.sh` with `SMTP_PASSWORD` set (section 4.1) |
| `tm-secrets-key` | not in staging yet: `values-staging.yaml` lists it in `keyvault.absent` |

```bash
KEYVAULT_NAME=<keyVaultName> bash deploy/azure/init-secrets.sh
# Grant them: from now on every deploy runs with this set (forgetting it later removes nothing)
export QEOS_SECRETS_INITIALIZED=true
az deployment sub create --name qeos-staging --location westeurope --parameters deploy/azure/staging.bicepparam
```

`init-secrets.sh` keeps every secret that exists, so it is safe to rerun. The migration hook sets each database role's password from
the vault on every release: to rotate one, set a new value in the vault and deploy.

- **A pod stuck in `ContainerCreating` with a CSI mount error `403 Forbidden`** right after `init-secrets.sh`: the deploy
  with `QEOS_SECRETS_INITIALIZED=true` was skipped, so no identity may read the new secrets yet. Run it (above); the
  pods mount on their next retry.
- **Deploys are incremental**: Bicep adds and updates, never deletes. Taking an identity out of a secret's
  `secretReaders` in `main.bicep` leaves its existing role assignment in place; remove it by hand
  (`az role assignment list --scope <secret id>`, then `az role assignment delete --ids <id>`).

## 4. One-time steps Bicep cannot do

### 4.1 Email: the ACS SMTP application

ACS SMTP signs in with a Microsoft Entra application; Bicep cannot create one (it would need Microsoft Graph rights).
The username is `qeos-<env>`, the password is the application's client secret.

```bash
app_id="$(az ad app create --display-name qeos-staging-smtp --query appId -o tsv)"
sp_id="$(az ad sp create --id "$app_id" --query id -o tsv)"
# Shown once: keep it only in the variable. Note the expiry date: renew the secret and rerun init-secrets.sh before it
SMTP_PASSWORD="$(az ad app credential reset --id "$app_id" --display-name acs-smtp --years 1 --query password -o tsv)"

# smtp-password first: the deploy below grants read access to it, which needs the secret
SMTP_PASSWORD="$SMTP_PASSWORD" KEYVAULT_NAME=<keyVaultName> bash deploy/azure/init-secrets.sh
unset SMTP_PASSWORD

# Bicep adds the SMTP username qeos-staging (linked to the app), its send role, the secret smtp-user, and read access
# to both SMTP secrets for the identities that send mail
export QEOS_SMTP_APP_CLIENT_ID="$app_id" QEOS_SMTP_APP_PRINCIPAL_ID="$sp_id"
az deployment sub create --name qeos-staging --location westeurope --parameters deploy/azure/staging.bicepparam
```

The chart's SMTP settings (`values-staging.yaml`): `smtp.host` `smtp.azurecomm.net`, `smtp.port` 587, `smtp.tls` true;
`smtp.fromEmail` is the output `communicationEmailSender` (the deploy workflow's `EMAIL_SENDER`). The send role is a custom role with only the three permissions ACS documents for
SMTP. The portal (Communication Services, **SMTP Usernames**) shows the username as *Ready to use* once everything is
linked. Until this is done, `values-staging.yaml` lists `smtp-user` and `smtp-password` in `keyvault.absent`, and the
chart then leaves `SMTP_HOST` empty: the platform runs and email links appear only in the auth-service log. Once both
secrets are in the vault and granted, remove the two entries from `keyvault.absent` and deploy.

The Azure-managed domain is meant for testing and has low sending limits. A custom sender domain (production) needs
its own domain resource in `email.bicep` and DNS records (domain verification, SPF, DKIM) at the DNS host.

### 4.2 Microsoft sign-in: redirect URIs

Add the environment's address (the chart's `publicUrl`, `https://<host>` with no path) to the Entra app registration
QEOS signs in with, as a **Single-page application** redirect URI (`docs/MICROSOFT_SIGN_IN.md`). Staging uses
`https://<stagingHostname>` until a domain is chosen; when the address changes, add the new one.

### 4.3 The edge's address and DNS

Bicep creates the edge's public IP itself (`pip-aks-qeos-<env>-edge`, static, in the environment's resource group)
with the DNS label that gives the output `stagingHostname` (`qeos-<env>-<hash>.<hash>.<region>.cloudapp.azure.com`: the label carries one hash, and
the label's reuse scope makes Azure add another before the region; always copy the output, never build the name).
Because the cluster does not own it, the address and its name survive `az aks stop`, a node pool rebuild and even a
new cluster. The add-on creates the Gateway's LoadBalancer Service; the chart's `Gateway` `qeos-edge` passes it these
annotations through `spec.infrastructure.annotations` (from the deploy workflow's `AKS_NAME` and `AKS_RESOURCE_GROUP`),
so the Service takes this IP instead of a new one:

```yaml
service.beta.kubernetes.io/azure-pip-name: pip-aks-qeos-staging-edge
service.beta.kubernetes.io/azure-load-balancer-resource-group: rg-qeos-staging
```

If the add-on ever stops passing them through, the per-Gateway ConfigMap customization (the add-on's allow list) sets
the same annotations. Check after the first deploy that the Gateway's address is this IP:
`kubectl -n qeos get gateway qeos-edge -o jsonpath='{.status.addresses[0].value}'` against
`az network public-ip show -g rg-qeos-staging -n pip-aks-qeos-staging-edge --query ipAddress -o tsv`.

Check too that the Service keeps client addresses (`kubectl -n qeos get svc qeos-edge-approuting-istio -o
jsonpath='{.spec.externalTrafficPolicy}'` is `Local`, set through the chart's ConfigMap `qeos-edge-options`) and that
the gateway logs real client addresses (`kubectl -n qeos logs deploy/gateway`), not `10.244.x.x`.

The public domain is still open (spec 6a). When it is chosen: a CNAME from the host to `stagingHostname` (or an A
record to the IP), then `publicUrl`, the certificate and the redirect URIs (4.2) follow it.

### 4.4 Old images in the registry

ACR's untagged-manifest retention policy needs the Premium tier; on Basic, a scheduled ACR task removes images older
than 30 days, keeping the newest 20 tags of each repository:

```bash
az acr task create --registry <acrName> --name purge-old-images --schedule "0 3 * * Sun" --context /dev/null \
  --cmd "acr purge --filter 'qeos/.*:.*' --ago 30d --keep 20 --untagged"
```

### 4.5 Cluster-wide pieces (a cluster admin, once)

The deploy identity is admin of the chart's namespace only, so a member of the cluster admins group does these once
per cluster (and again after a cluster rebuild):

```bash
az aks get-credentials --resource-group rg-qeos-staging --name aks-qeos-staging
kubelogin convert-kubeconfig -l azurecli

# The chart's namespace: the deploy identity's RBAC Admin role is scoped to it
kubectl create namespace qeos

# cert-manager with its CRDs and Gateway API support (the chart's Certificate and Issuer use it). Pin a current
# release from https://cert-manager.io/docs/releases/
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --version <v1.x.y> \
  --set crds.enabled=true --set config.enableGatewayAPI=true
```

The chart brings its own namespaced `Issuer` (Let's Encrypt, HTTP-01 through the Gateway) and `Certificate`, so
nothing else cluster-wide is needed. Upgrading cert-manager is the same `helm upgrade` by a cluster admin.

## 5. GitHub configuration

Repository variables (Settings, Secrets and variables, Actions, **Variables**). None is secret: the workflows sign in
with OIDC and read secrets from nothing.

| Variable | Value | Used by |
|---|---|---|
| `AZURE_CLIENT_ID` | The GitHub identity's application (client) id | `build-platform.yml`, the deploy workflow |
| `AZURE_TENANT_ID` | The tenant id (also the chart's `keyvault.tenantId`) | both |
| `AZURE_SUBSCRIPTION_ID` | The subscription | both |
| `ACR_NAME` | Output `acrName` | both |

### 5.1 The deploy workflow

`deploy-aks.yml` deploys the chart to staging after every successful image build on master, and by hand (Actions,
**Deploy to AKS**, Run workflow: environment, tag). `deploy/helm/README.md` ("The deploy workflow") describes its
steps. Its deploy job runs in the GitHub environment `staging` (Settings, Environments; created on the first run if
missing) and reads the remaining outputs as that environment's variables. To copy them after a Bicep deploy:

```bash
az deployment sub show --name qeos-staging --query properties.outputs -o json > outputs.json
out() { jq -r ".$1.value" outputs.json; }
gh variable set ACR_NAME --body "$(out acrName)"
gh variable set AKS_NAME --env staging --body "$(out aksName)"
gh variable set AKS_RESOURCE_GROUP --env staging --body "$(out resourceGroup)"
gh variable set KEY_VAULT_NAME --env staging --body "$(out keyVaultName)"
gh variable set POSTGRES_HOST --env staging --body "$(out postgresHost)"
gh variable set STORAGE_ACCOUNT_URL --env staging --body "$(out storageAccountUrl)"
gh variable set ARTIFACTS_CONTAINER --env staging --body "$(out artifactsContainer)"
gh variable set WORKLOAD_IDENTITY_CLIENT_IDS --env staging --body "$(jq -c .workloadIdentityClientIds.value outputs.json)"
gh variable set EMAIL_SENDER --env staging --body "$(out communicationEmailSender)"
gh variable set PUBLIC_HOSTNAME --env staging --body "$(out stagingHostname)"
gh variable set ACME_EMAIL --env staging --body "ops@example.com"     # Let's Encrypt's expiry notices
```

Until every variable is set, the automatic run only prints a notice. Before the first deploy: section 3.1 (secrets),
4.5 (namespace and cert-manager) and the cluster running. The workflow signs in to the cluster with Entra ID
(`kubelogin convert-kubeconfig -l azurecli` after `az aks get-credentials`: the cluster has no local accounts), and
adds its runner's address to the API server's authorised ranges for the run only, removing it in a final step that
runs even when the deploy fails. If a run is cancelled hard and the address stays, the next Bicep deploy resets the
list to `QEOS_ADMIN_IP_RANGES` (section 3), or remove it with `az aks update --api-server-authorized-ip-ranges`.

## 6. Staging stop and start (spec 5.14)

Staging runs only in working hours. Stopping keeps every resource, the cluster's configuration and the data; a stopped
cluster and server cost only their storage.

```bash
rg=rg-qeos-staging
# Evening
az aks stop --resource-group "$rg" --name aks-qeos-staging
az postgres flexible-server stop --resource-group "$rg" --name <server name>
# Morning: the database first, so the services find it
az postgres flexible-server start --resource-group "$rg" --name <server name>
az aks start --resource-group "$rg" --name aks-qeos-staging
```

Suggested schedule: start 06:00 UTC and stop 19:00 UTC on working days, stopped over the weekend. Run it from a
scheduled GitHub workflow or an Azure Automation runbook with an identity that has Azure Kubernetes Service
Contributor Role on the cluster and Contributor on the server. Keep in mind:

- Flexible Server **starts by itself after 7 days** stopped; the next stop catches it.
- **Upgrades run only on a running cluster**: the Sunday 01:00-05:00 UTC window passes unused while staging is
  stopped. Start it before the window once in a while (or move staging's window into working hours) so patches land.
- A stopped cluster ignores deploys: the deploy workflow fails until it is started.
- The edge's public IP and `stagingHostname` stay while the cluster is stopped: Bicep owns the IP (4.3).

## 7. Switching CI over (fresh start, spec 5.13)

AKS starts empty: nothing moves from an existing install.

1. Sign up on the AKS address, then create the organization and the project.
2. Create new project API keys for each CI pipeline that uploads.
3. In the OBT repository (and any other CI that reports): set `QEOS_URL` to the AKS address and `QEOS_API_KEY` to the
   new key.
4. Run the test-case import and the repository-suite sync, so test cases and suites come back.
5. Invite the people who used the old install.

Results then flow to AKS from the next CI run. The old install keeps its data until it is switched off.

## 8. Restores (spec 5.12)

- **Database**: point-in-time restore into a new server (`az postgres flexible-server restore --source-server <server>
  --restore-time <UTC time> --name <new server>`), at most 35 days back; then point the chart's `postgres.host` at it.
- **Artifacts**: a deleted blob or container is restorable for 14 days (soft delete); an overwritten blob through its
  previous version (versioning).

Before production, staging proves both, timed against the targets (5 minutes of data loss, 1 hour to restore), and the
results are written up here.

## 9. Tearing staging down, and Key Vault recovery

```bash
az group delete --name rg-qeos-staging
```

The budget goes with the resource group. Key Vault has **purge protection in every environment**: a deleted vault, or a
deleted secret, stays recoverable for 90 days and nobody can purge it sooner. Losing the secrets by mistake costs more
than a vault name kept busy after a teardown.

- **Rebuilding in the same resource group name**: the vault's name comes from the subscription and the resource group
  name, so a redeploy asks for the same name while the deleted vault still holds it, and fails. Recover the vault
  first; the redeploy then updates it, with every secret as it was (`init-secrets.sh` keeps them):

  ```bash
  az keyvault list-deleted --query "[].name" -o tsv
  az keyvault recover --name <keyVaultName>
  ```

- **A fresh vault instead**: deploy with another `resourceGroupName` (a new name and hash); the old vault expires on its
  own after 90 days. Every secret is then new (run `init-secrets.sh` again, a new admin password).
- **One deleted secret**: `az keyvault secret list-deleted --vault-name <keyVaultName>`, then
  `az keyvault secret recover --vault-name <keyVaultName> --name <secret>`. Setting the same name again before
  recovering it fails while the deleted one exists.

Communication Services and Email Service names are free again once the resource group is gone.
