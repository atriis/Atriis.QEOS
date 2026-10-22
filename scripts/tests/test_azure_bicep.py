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


def chart_secret_keys() -> set[str]:
    """The Key Vault keys staging's SecretProviderClasses read (secretproviderclass.yaml, migrate-hook.yaml)."""
    keys: set[str] = set()
    for svc in VALUES["services"].values():
        keys.update((svc.get("secretEnv") or {}).values())
        if svc.get("database"):
            keys.add(f"{svc['database']}-db-password")
        if svc.get("artifacts") and staging("artifacts", "backend") == "s3":
            keys.update({"artifacts-s3-access-key", "artifacts-s3-secret-key"})
    hook = text(CHART / "templates" / "migrate-hook.yaml")
    match = re.search(r"\$hookKeys := list ((?:\"[^\"]+\" ?)+)", hook)
    assert match, "the migration hook's key list moved"
    keys.update(re.findall(r'"([^"]+)"', match.group(1)))
    for name in VALUES["migrate"]["order"]:
        keys.add(f"{VALUES['services'][name]['database']}-db-password")
    return keys - set(staging("keyvault", "absent") or [])


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
    ]
