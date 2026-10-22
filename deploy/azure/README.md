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
| `modules/aks.bicep` | The cluster, its control-plane identity, Log Analytics for Defender, the maintenance windows |
| `modules/acr.bicep` | Container registry; AcrPull for the kubelet, AcrPush for the GitHub identity |
| `modules/identities.bicep` | One managed identity per workload identity, federated with its ServiceAccount |
| `modules/keyvault.bicep` | Key Vault (RBAC), `postgres-admin-password`, `smtp-user`, Key Vault Secrets User for every identity |
| `modules/postgres.bicep` | PostgreSQL Flexible Server, private access, its private DNS zone |
| `modules/storage.bicep` | Storage account and container `qeos-artifacts`; Storage Blob Data Contributor for ingestion and retention |
| `modules/email.bicep` | Communication Services, Email Service, the Azure-managed sender domain, the SMTP username and send role |
| `modules/budget.bicep` | Monthly budget with alert emails at 80% and 100% |
| `init-secrets.sh` | Generates, once, the Key Vault secrets Bicep does not write |
| `bicepconfig.json` | Linter rules; CI fails on any warning |

CI (`ci.yml`, job `bicep`) builds and lints the templates and the parameter file on every push, and
`scripts/tests/test_azure_bicep.py` fails when the Key Vault secret names, workload identities, ServiceAccount names,
container name, admin login or pod range here differ from the chart's. Nothing in CI signs in to Azure.

## 1. What gets created

| Resource | Settings that matter |
|---|---|
| AKS `aks-qeos-<env>` | Azure CNI Overlay powered by Cilium (`networkDataplane`/`networkPolicy: cilium`, pod range `10.244.0.0/16`); workload identity and OIDC issuer; Key Vault Secrets Store CSI add-on (rotation every 2 min); Application Routing's Gateway API implementation (GatewayClass `approuting-istio`) on the managed Gateway API CRDs, NGINX off; Entra ID sign-in with Azure RBAC, local accounts disabled; API server open only to `apiServerAuthorizedIpRanges`; auto-upgrade `patch`, node OS `NodeImage`, both in a Sunday 01:00-05:00 UTC window; Defender for Containers sensor; a tainted system pool (1 node) and an autoscaling user pool (2-4 nodes, Azure Linux) |
| ACR `acrqeos<env><hash>` | No admin user, no anonymous pull; the kubelet pulls with AcrPull (no pull secret) |
| PostgreSQL `psql-qeos-<env>-<hash>` | Version 16, `Standard_B1ms` Burstable in staging; private access in subnet `postgres` with zone `<server>.private.postgres.database.azure.com`; no public access; TLS required; backups 35 days; `pg_stat_statements` in `azure.extensions` and `shared_preload_libraries`; admin login `qeosadmin` (the chart's `postgres.adminUser`) |
| Storage `stqeos<env><hash>` | Shared keys off (Entra ID only), no public blob access, TLS 1.2, HTTPS only; reachable from the node subnet and `operatorIpRanges` only; soft delete 14 days (blobs and containers), versioning on, previous versions removed after 14 days; private container `qeos-artifacts` |
| Key Vault `kv-qeos-<env>-<hash>` | RBAC mode (no access policies), soft delete 90 days; purge protection on except in staging; reachable from the node subnet and `operatorIpRanges` only |
| Managed identities `id-qeos-<env>-{services,ingestion,ingestion-retention,migrate}` | Federated with `system:serviceaccount:<namespace>:qeos-<identity>`, issuer the cluster's OIDC URL, audience `api://AzureADTokenExchange`; all four read Key Vault secrets; `ingestion` and `ingestion-retention` also read, write, copy and delete blobs in `qeos-artifacts` |
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

The chart's `keyvault.tenantId` is the tenant, the same as the repository variable `AZURE_TENANT_ID`.

## 2. Before the first deploy

1. **A subscription** the team controls (spec section 8) and an account with **Owner** on it, or Contributor plus
   Role Based Access Control Administrator: the templates create role assignments and one custom role.
2. **Tools**: Azure CLI 2.86 or newer (the Application Routing Gateway API needs it), `az bicep install`, `kubectl`
   and `kubelogin` (`az aks install-cli`), `openssl`, `gh`.
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
   credentials for this repository (`repo:<org>/Atriis.QEOS:ref:refs/heads/master`, and
   `repo:<org>/Atriis.QEOS:environment:staging` once the deploy workflow uses the `staging` environment). Its service
   principal's object id is `QEOS_DEPLOY_PRINCIPAL_ID` below: Bicep gives it AcrPush on the registry and, on the
   cluster, Azure Kubernetes Service Cluster User Role (kubeconfig), Azure Kubernetes Service RBAC Cluster Admin (helm,
   cert-manager) and Azure Kubernetes Service Contributor Role (adding its runner to the authorised IP ranges for a
   run). It needs no role on Key Vault or Storage.
6. **An Entra group of cluster admins** (`QEOS_AKS_ADMIN_GROUP_ID`): with local accounts off, `kubectl` signs in with
   Entra ID, and only this group and the deploy identity get cluster-admin.

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
| `QEOS_SMTP_APP_CLIENT_ID`, `QEOS_SMTP_APP_PRINCIPAL_ID` | no | The ACS SMTP application (section 4.1); empty on the first deploy |

```bash
az login
az account set --subscription <subscription id>

export QEOS_ADMIN_IP_RANGES="$(curl -s https://api.ipify.org)/32"
export QEOS_BUDGET_EMAILS="ops@example.com"
export QEOS_OPERATOR_PRINCIPAL_ID="$(az ad signed-in-user show --query id -o tsv)"
export QEOS_AKS_ADMIN_GROUP_ID="<group object id>"
export QEOS_DEPLOY_PRINCIPAL_ID="$(az ad sp show --id <AZURE_CLIENT_ID> --query id -o tsv)"
# First deploy only. Hex: no character that needs escaping anywhere
export QEOS_POSTGRES_ADMIN_PASSWORD="$(openssl rand -hex 24)"

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

The chart's SecretProviderClasses read these Key Vault secrets (`deploy/helm/README.md`, "Secrets"); a missing one
fails the pod's volume mount, so all must exist before the first `helm install`:

| Secret | Written by |
|---|---|
| `postgres-admin-password` | Bicep (`QEOS_POSTGRES_ADMIN_PASSWORD`) |
| `secret-key`, `internal-api-password`, `auth-db-password`, `organization-db-password`, `project-db-password`, `ingestion-db-password`, `testmgmt-db-password` | `init-secrets.sh`, once, random |
| `smtp-user` | Bicep, once the SMTP application exists (section 4.1) |
| `smtp-password` | `init-secrets.sh` with `SMTP_PASSWORD` set (section 4.1) |
| `tm-secrets-key` | not in staging yet: `values-staging.yaml` lists it in `keyvault.absent` |

```bash
KEYVAULT_NAME=<keyVaultName> bash deploy/azure/init-secrets.sh
```

It keeps every secret that exists, so it is safe to rerun. The migration hook sets each database role's password from
the vault on every release: to rotate one, set a new value in the vault and deploy.

## 4. One-time steps Bicep cannot do

### 4.1 Email: the ACS SMTP application

ACS SMTP signs in with a Microsoft Entra application; Bicep cannot create one (it would need Microsoft Graph rights).
The username is `qeos-<env>`, the password is the application's client secret.

```bash
app_id="$(az ad app create --display-name qeos-staging-smtp --query appId -o tsv)"
sp_id="$(az ad sp create --id "$app_id" --query id -o tsv)"
# Shown once: keep it only in the variable. Note the expiry date: renew the secret and rerun init-secrets.sh before it
SMTP_PASSWORD="$(az ad app credential reset --id "$app_id" --display-name acs-smtp --years 1 --query password -o tsv)"

# Bicep adds the SMTP username qeos-staging (linked to the app), its send role and the secret smtp-user
export QEOS_SMTP_APP_CLIENT_ID="$app_id" QEOS_SMTP_APP_PRINCIPAL_ID="$sp_id"
az deployment sub create --name qeos-staging --location westeurope --parameters deploy/azure/staging.bicepparam

SMTP_PASSWORD="$SMTP_PASSWORD" KEYVAULT_NAME=<keyVaultName> bash deploy/azure/init-secrets.sh
unset SMTP_PASSWORD
```

The chart's SMTP settings: `smtp.host` `smtp.azurecomm.net`, `smtp.port` 587, `smtp.tls` true, `smtp.fromEmail` the
output `communicationEmailSender`. The send role is a custom role with only the three permissions ACS documents for
SMTP. The portal (Communication Services, **SMTP Usernames**) shows the username as *Ready to use* once everything is
linked. Until this is done, deploy with `smtp-user` and `smtp-password` added to `keyvault.absent` and an empty
`smtp.host`: the platform runs and email links appear only in the auth-service log.

The Azure-managed domain is meant for testing and has low sending limits. A custom sender domain (production) needs
its own domain resource in `email.bicep` and DNS records (domain verification, SPF, DKIM) at the DNS host.

### 4.2 Microsoft sign-in: redirect URIs

Add the environment's address (the chart's `publicUrl`, `https://<host>` with no path) to the Entra app registration
QEOS signs in with, as a **Single-page application** redirect URI (`docs/MICROSOFT_SIGN_IN.md`). Staging uses the
Azure-provided address until a domain is chosen; when the address changes, add the new one.

### 4.3 DNS (later)

The public domain is still open (spec 6a). When it is chosen: an A record (or CNAME to the Azure-provided name) for
the host pointing at the public IP of the edge's load balancer
(`kubectl -n qeos get gateway -o jsonpath='{.items[0].status.addresses[0].value}'`), then `publicUrl`, the
certificate and the redirect URIs (4.2) follow it.

### 4.4 Old images in the registry

ACR's untagged-manifest retention policy needs the Premium tier; on Basic, a scheduled ACR task removes images older
than 30 days, keeping the newest 20 tags of each repository:

```bash
az acr task create --registry <acrName> --name purge-old-images --schedule "0 3 * * Sun" --context /dev/null \
  --cmd "acr purge --filter 'qeos/.*:.*' --ago 30d --keep 20 --untagged"
```

## 5. GitHub configuration

Repository variables (Settings, Secrets and variables, Actions, **Variables**). None is secret: the workflows sign in
with OIDC and read secrets from nothing.

| Variable | Value | Used by |
|---|---|---|
| `AZURE_CLIENT_ID` | The GitHub identity's application (client) id | `build-platform.yml`, the deploy workflow |
| `AZURE_TENANT_ID` | The tenant id (also the chart's `keyvault.tenantId`) | both |
| `AZURE_SUBSCRIPTION_ID` | The subscription | both |
| `ACR_NAME` | Output `acrName` | both |

The deploy workflow (Task 10, `deploy-aks.yml`) reads the remaining outputs (`aksName`, `resourceGroup`,
`keyVaultName`, `postgresHost`, `storageAccountUrl`, `workloadIdentityClientIds`, `communicationEmailSender`) as
variables of the GitHub environment `staging`, under the names that workflow documents. To copy them after a deploy:

```bash
az deployment sub show --name qeos-staging --query properties.outputs -o json > outputs.json
gh variable set ACR_NAME --body "$(jq -r .acrName.value outputs.json)"
```

The deploy identity signs in to the cluster with Entra ID: the workflow needs `kubelogin`
(`kubelogin convert-kubeconfig -l azurecli` after `az aks get-credentials`), since the cluster has no local accounts.

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
- The edge's public IP stays while the cluster is stopped.

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

## 9. Tearing staging down

```bash
az group delete --name rg-qeos-staging
```

Key Vault and Communication Services names stay reserved while soft-deleted (staging's vault has no purge protection,
so `az keyvault purge` frees it). The budget goes with the resource group.
