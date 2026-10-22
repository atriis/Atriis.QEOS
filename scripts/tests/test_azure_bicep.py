"""deploy/azure (Bicep) creates what the Helm chart reads (ADR-038), so the two cannot drift apart.

A Key Vault secret the chart names but nobody creates fails the pod's secret mount; a workload identity, ServiceAccount
name or namespace that differs from the chart's leaves its federated credential unused, and the pod gets no token. The
tests read the Bicep and init-secrets.sh as text: CI's scripts/tests job has no Bicep CLI (the bicep job builds it).
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AZURE = ROOT / "deploy" / "azure"
CHART = ROOT / "deploy" / "helm" / "qeos"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load(path: Path) -> dict:
    return yaml.safe_load(text(path))


def bicep_list(source: str, name: str) -> list[str]:
    match = re.search(rf"^var {name} = \[(.*?)^\]", source, re.S | re.M)
    assert match, f"var {name} not found"
    return re.findall(r"'([^']+)'", match.group(1))


def bicep_string(source: str, pattern: str) -> str:
    match = re.search(pattern + r" = '([^']*)'", source, re.M)
    assert match, f"{pattern} not found"
    return match.group(1)


MAIN = text(AZURE / "main.bicep")
VALUES = load(CHART / "values.yaml")
STAGING = load(CHART / "values-staging.yaml")
SMTP_KEYS = {"smtp-user", "smtp-password"}


def staging(*keys):
    """A value of values-staging.yaml, or of values.yaml when staging does not set it."""
    for source in (STAGING, VALUES):
        node = source
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                break
            node = node[key]
        else:
            return node
    raise KeyError(keys)


def chart_identities() -> set[str]:
    """Every identity a workload names, plus the migration hook's own (migrate-hook.yaml)."""
    identities = {svc["identity"] for svc in VALUES["services"].values() if svc.get("identity")}
    hook = text(CHART / "templates" / "migrate-hook.yaml")
    assert ".Values.keyvault.clientIds.migrate" in hook
    return identities | {"migrate"}


def chart_keys_by_identity() -> dict[str, set[str]]:
    """identity -> the Key Vault keys staging's SecretProviderClasses of its workloads read (secretproviderclass.yaml,
    one per workload, and the migration hook's qeos-migrate, migrate-hook.yaml)."""
    # The SMTP credentials are absent from staging only until the ACS SMTP application exists; Bicep then writes and
    # grants smtp-user and init-secrets.sh sets smtp-password (README, section 4.1), so they count as read here
    absent = set(staging("keyvault", "absent") or []) - SMTP_KEYS
    by_identity: dict[str, set[str]] = {}
    for svc in VALUES["services"].values():
        if not svc.get("identity"):
            continue
        keys = set((svc.get("secretEnv") or {}).values())
        if svc.get("database"):
            keys.add(f"{svc['database']}-db-password")
        if svc.get("artifacts") and staging("artifacts", "backend") == "s3":
            keys.update({"artifacts-s3-access-key", "artifacts-s3-secret-key"})
        by_identity.setdefault(svc["identity"], set()).update(keys - absent)
    hook = text(CHART / "templates" / "migrate-hook.yaml")
    match = re.search(r"\$hookKeys := list ((?:\"[^\"]+\" ?)+)", hook)
    assert match, "the migration hook's key list moved"
    migrate = set(re.findall(r'"([^"]+)"', match.group(1)))
    for name in VALUES["migrate"]["order"]:
        migrate.add(f"{VALUES['services'][name]['database']}-db-password")
    by_identity["migrate"] = migrate - absent
    return by_identity


def chart_secret_keys() -> set[str]:
    return set().union(*chart_keys_by_identity().values())


def bicep_secret_readers() -> dict[str, set[str]]:
    """main.bicep's secretReaders: secret -> the identities granted Key Vault Secrets User on it."""
    match = re.search(r"^var secretReaders = \{(.*?)^\}", MAIN, re.S | re.M)
    assert match, "var secretReaders not found"
    readers = {}
    for secret, identities in re.findall(r"^\s*'([^']+)': \[([^\]]*)\]", match.group(1), re.M):
        assert secret not in readers, secret
        readers[secret] = set(re.findall(r"'([^']+)'", identities))
    return readers


def provided_secret_keys() -> set[str]:
    """Secrets Bicep writes (modules/keyvault.bicep) plus the ones init-secrets.sh creates or sets."""
    vault = text(AZURE / "modules" / "keyvault.bicep")
    from_bicep = re.findall(
        r"^resource \w+ 'Microsoft\.KeyVault/vaults/secrets@[^']+' = (?:if \(.*?\) )?\{\s*parent: vault\s*name: '([^']+)'",
        vault,
        re.M,
    )
    script = text(AZURE / "init-secrets.sh")
    match = re.search(r"^GENERATED=\((.*?)^\)", script, re.S | re.M)
    assert match, "GENERATED=( ... ) not found in init-secrets.sh"
    generated = match.group(1).split()
    from_env = re.findall(r"^\s*set_secret ([a-z0-9-]+)$", script, re.M)
    return set(from_bicep) | set(generated) | set(from_env)


def test_bicep_creates_every_secret_the_chart_reads_and_no_other():
    assert provided_secret_keys() == chart_secret_keys()


def test_each_identity_reads_exactly_its_workloads_secrets():
    granted: dict[str, set[str]] = {}
    for secret, identities in bicep_secret_readers().items():
        for identity in identities:
            granted.setdefault(identity, set()).add(secret)
    assert granted == chart_keys_by_identity()


def test_only_the_migration_hook_reads_the_admin_password():
    assert bicep_secret_readers()["postgres-admin-password"] == {"migrate"}


def test_roles_are_per_secret_and_purge_protection_always_on():
    vault = text(AZURE / "modules" / "keyvault.bicep")
    # Key Vault Secrets User only through the per-secret loop; the vault-wide role is the operator's Secrets Officer
    assert len(re.findall(r"roleDefinitions', secretsUser\)", vault)) == 1
    assert "scope: grantedSecrets[i]" in vault
    assert re.search(r"^\s*enablePurgeProtection: true$", vault, re.M)
    assert "PurgeProtection" not in text(AZURE / "staging.bicepparam")


def test_postgres_pins_tls():
    postgres = text(AZURE / "modules" / "postgres.bicep")
    for name, value in (("require_secure_transport", "ON"), ("ssl_min_protocol_version", "TLSv1.2")):
        assert re.search(rf"name: '{name}'\s+properties: \{{\s+value: '{value}'", postgres), name


def test_documented_admin_password_meets_flexible_servers_rule():
    """Three of four classes (upper, lower, digit, symbol); hex alone has two, and the first deploy would fail."""
    readme = text(AZURE / "README.md")
    match = re.search(r'^export QEOS_POSTGRES_ADMIN_PASSWORD="(.*)"$', readme, re.M)
    assert match
    sample = match.group(1).replace("$(openssl rand -hex 24)", "0123456789abcdef" * 3)
    assert "$" not in sample, "the README command changed: update this test"
    classes = [any(c.isupper() for c in sample), any(c.islower() for c in sample), any(c.isdigit() for c in sample),
               any(not c.isalnum() for c in sample)]
    assert sum(classes) >= 3 and 8 <= len(sample) <= 128


def test_bicep_writes_postgres_admin_and_smtp_user():
    vault = text(AZURE / "modules" / "keyvault.bicep")
    for key in ("postgres-admin-password", "smtp-user"):
        assert f"name: '{key}'" in vault


def test_workload_identities_match_the_chart():
    identities = bicep_list(MAIN, "workloadIdentities")
    assert len(identities) == len(set(identities))
    assert set(identities) == chart_identities()
    assert set(identities) == set(VALUES["keyvault"]["clientIds"])


def test_artifact_writers_are_the_azure_sdk_workloads():
    writers = {svc["identity"] for svc in VALUES["services"].values() if svc.get("azureSdk")}
    assert set(bicep_list(MAIN, "artifactWriters")) == writers == {"ingestion", "ingestion-retention"}


def test_federated_subject_is_the_charts_serviceaccount():
    identities = text(AZURE / "modules" / "identities.bicep")
    assert "subject: 'system:serviceaccount:${namespace}:qeos-${identity}'" in identities
    assert "audiences: ['api://AzureADTokenExchange']" in identities
    # The chart names them qeos-<identity> (serviceaccounts.yaml) and qeos-migrate (the hook)
    assert 'printf "qeos-%s" $identity' in text(CHART / "templates" / "serviceaccounts.yaml")
    assert re.search(r"kind: ServiceAccount\nmetadata:\n  name: qeos-migrate\n", text(CHART / "templates" / "migrate-hook.yaml"))
    # The deploy workflow and the CI job install into qeos
    assert bicep_string(MAIN, r"^param namespace string") == "qeos"


def test_names_and_ranges_shared_with_the_chart():
    assert bicep_string(MAIN, r"^var artifactsContainer") == staging("artifacts", "azure", "container")
    assert bicep_string(MAIN, r"^param postgresAdminLogin string") == staging("postgres", "adminUser")
    assert bicep_string(MAIN, r"^var podCidr") == staging("gateway", "trustedProxies")


def test_deploy_workflow_names_the_edge_ip_as_bicep_does():
    # aks.bicep names the edge's public IP after the cluster; the deploy workflow derives it from the AKS_NAME variable
    assert "name: 'pip-${name}-edge'" in text(AZURE / "modules" / "aks.bicep")
    workflow = text(ROOT / ".github" / "workflows" / "deploy-aks.yml")
    assert 'edge.publicIp.name="pip-${AKS_NAME}-edge"' in workflow
    assert 'edge.publicIp.resourceGroup="$AKS_RESOURCE_GROUP"' in workflow
    # The workflow installs into the namespace the federated credentials and the deploy identity's role name
    assert re.search(r"^\s*NAMESPACE: qeos$", workflow, re.M)


def test_outputs_are_the_interface():
    outputs = re.findall(r"^output (\w+) ", MAIN, re.M)
    assert outputs == [
        "acrName",
        "aksName",
        "resourceGroup",
        "keyVaultName",
        "postgresHost",
        "storageAccountUrl",
        "artifactsContainer",
        "workloadIdentityClientIds",
        "communicationEmailSender",
        "stagingHostname",
    ]
