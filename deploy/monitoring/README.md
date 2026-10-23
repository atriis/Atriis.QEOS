# The cluster's kube-prometheus-stack

Prometheus for QEOS on Kubernetes (ADR-038, Stage 2): the Prometheus operator and its CRDs, one Prometheus,
kube-state-metrics and node-exporter, as the Helm release `qeos-monitoring` in the namespace `qeos-monitoring`. The QEOS
chart (`deploy/helm/qeos`) brings the rest: its ServiceMonitors and PrometheusRules, Grafana and Alertmanager.

It needs CRDs and cluster roles, which the deploy identity (admin of the QEOS namespace only) cannot create, so it is a
separate release that a cluster admin installs with `install.sh`: once per cluster, and again after every version bump.
CI's `helm-kind` job runs the same script before the QEOS install.

```bash
# AKS staging, as a cluster admin (deploy/azure/README.md, section 4.5)
bash deploy/monitoring/install.sh --env staging --context aks-qeos-staging

# kind (CI, and "Testing locally with kind" in deploy/helm/README.md): the QEOS namespace enforces restricted
bash deploy/monitoring/install.sh --env ci --context kind-qeos-kind --enforce-restricted

# What would be installed, touching no cluster (no --context); and the checks on it (helm 3, yq v4, network; no
# cluster: a kubectl stub stands in for one)
bash deploy/monitoring/install.sh --env staging --template
bash deploy/monitoring/tests/install_test.sh
```

## What install.sh does

`install.sh --env ci|staging|production --context <kubectl context> [--qeos-namespace qeos] [--qeos-release qeos]
[--namespace qeos-monitoring] [--enforce-restricted] [--allow-downgrade] [--template]`; exit 2 for a usage error (an
unknown environment, no `--context`, a namespace that is not a DNS label or is Kubernetes' own (`default`,
`kube-system`, `kube-public`, `kube-node-lease`), the same namespace twice, a release name that is not a DNS label of
at most 53 characters), 1 when a step fails.

0. **The cluster.** `--context` is required and every `kubectl` and `helm` call uses it, never the current context: an
   admin signed in to another cluster would otherwise change that one. An unknown context stops the script. Before
   anything changes it prints the context, its API server and both namespaces.
1. **The chart.** `helm dependency build` downloads the version `Chart.lock` pins into `charts/` (ignored by git), with
   a repository configuration of its own (the admin's helm repositories are neither read nor changed). The archive's
   sha256 must equal the `qeos.atriis.com/kube-prometheus-stack-sha256` annotation in `Chart.yaml`, or nothing is
   installed: CI and every admin install the same bytes.
2. **Namespaces.** Both are created if missing and labelled for Pod Security: the monitoring namespace `privileged`
   (node-exporter needs the host's network, PID namespace and file systems); the QEOS namespace `enforce=baseline`,
   `warn=restricted`, `audit=restricted`, or `enforce=restricted` with `--enforce-restricted` (CI). A QEOS namespace
   that already enforces `restricted` is never lowered silently: without `--enforce-restricted` the script stops (exit
   1, before any change) unless `--allow-downgrade` is given. Likewise the monitoring namespace: the script labels the
   one it creates `qeos.atriis.com/monitoring=true`, and an existing namespace without that label (someone else's, or
   a typo in `--namespace`) is not made privileged unless `--allow-downgrade` is given. This is the only place either
   namespace is created; the CI step that creates the QEOS namespace does so only if it is missing.
3. **CRDs**, from the verified archive, with `kubectl apply --server-side --force-conflicts`: Helm installs CRDs once and
   never upgrades them, so a version bump would otherwise leave the old ones.
4. **The release:** `helm upgrade --install qeos-monitoring deploy/monitoring --skip-crds --atomic --wait`, then waits
   until Prometheus itself is available (the operator starts it after Helm is done).

`--template` skips step 0, stops after step 1 and prints `helm template` instead; the test renders it.

## Values

| File | Used for | Holds |
|---|---|---|
| `values.yaml` | every environment | everything below that names no namespace |
| `values-ci.yaml` | kind | no persistent storage (an emptyDir), small requests |
| `values-staging.yaml` | AKS staging | Prometheus on a 20Gi `managed-csi` volume |

There is no `values-production.yaml` yet, so `--env production` is refused: production arrives in Stage 3, like
`deploy-aks.yml`'s.

Everything that depends on the namespaces comes from `install.sh`, never from a values file, so `--qeos-namespace` and
`--namespace` change all of it: the Alertmanager endpoint, the namespace selectors, the enforcement exclusions and the
NetworkPolicy's sources (with `--qeos-release`). A plain `helm install` without the script fails on `qeosNamespace`.

**The monitoring namespace is named twice.** The QEOS chart cannot look it up (its deploy identity sees its own
namespace only), so it names it in `networkPolicy.prometheus.namespace` (`deploy/helm/README.md`), whose default is
`qeos-monitoring`, this script's default. With another `--namespace`, set that value to the same name in the QEOS
chart's values, or the APIs refuse Prometheus's scrapes on 8000 (they time out); `install.sh` prints a note saying so.

- `fullnameOverride: qeos-monitoring`: the Prometheus Service is `qeos-monitoring-prometheus:9090`, its pods are
  labelled `app.kubernetes.io/name: prometheus` (the QEOS chart's `networkPolicy.prometheus` admits them).
- **No Grafana, no Alertmanager**: both run from the QEOS chart with Compose's provisioning and routing. Prometheus
  sends alerts to the Service `alertmanager`, port `http`, in the QEOS namespace.
- **What Prometheus reads:** every ServiceMonitor, PodMonitor and PrometheusRule in the QEOS namespace and its own,
  whatever its labels (the `*SelectorNilUsesHelmValues: false` settings), and nothing from other namespaces.
- **`enforcedNamespaceLabel: namespace`:** series and alerts from the QEOS namespace's ServiceMonitors and rules carry
  `namespace=<the QEOS namespace>`, whatever a target sends. The monitoring namespace's own ServiceMonitors and rules are
  excluded (they describe the whole cluster: a pod's or a node's series keep their own `namespace`).
- **Retention 15 days**, the same as Compose's Prometheus.
- **The control plane is not scraped** (`kubeControllerManager`, `kubeScheduler`, `kubeEtcd`, `kubeProxy` off): AKS
  manages it and exposes none of it.
- **Alert noise.** Every default rule reaches QEOS's Alertmanager, so these are off: `Watchdog` and `InfoInhibitor`
  (QEOS's rules have their own Watchdog), `KubeCPUOvercommit` and `KubeMemoryOvercommit` (always true on a small node
  pool), and the rule groups `etcd`, `kubeSchedulerAlerting`, `kubeControllerManager`, `kubeProxy` (nothing scrapes
  them). The rest (pods crash looping, nodes out of disk or memory, volumes filling, the API server's error budget)
  stay on: on AKS they replace Compose's `qeos-host` alerts.
- **Restricted settings** on every container where the component allows them: non-root, read-only root file system, no
  privilege escalation, all capabilities dropped, the RuntimeDefault seccomp profile. node-exporter has them too, but
  still needs the host's namespaces, hence the privileged namespace.
- **Prometheus is not open to the cluster.** A NetworkPolicy (in `extraManifests`; the chart's own option always adds
  an Egress policy type, which would stop scraping) admits 9090 only from the QEOS chart's Grafana (pods
  `app.kubernetes.io/name: grafana` and `app.kubernetes.io/instance: <--qeos-release>` in the QEOS namespace, so not
  any pod someone labels grafana) and from the monitoring namespace (the operator, Prometheus itself), and the config reloader's 8080
  from the monitoring namespace (Prometheus scrapes it). It is ingress only: scraping is outbound. Checked by hand on
  kind with kindnet: a Grafana-labelled pod in `qeos` and a pod in `qeos-monitoring` get 200, any other pod in `qeos`
  or a pod in `default` times out.

## The pin

`Chart.yaml` is a wrapper chart whose only dependency is kube-prometheus-stack, so the version lives where Dependabot's
`helm` ecosystem finds it (`.github/dependabot.yml`, `/deploy/monitoring`). The values are nested under
`kube-prometheus-stack:`.

**92.2.0** (Prometheus operator v0.94.1, Prometheus v3.15.0), released 2026-10-08: the newest release at least two
weeks old on 2026-10-23, when this was set up (the project waits two weeks before adopting a third-party release, so
a broken one is usually yanked or fixed by then). Newer releases existed (up to 92.11.0 on 2026-10-20).

**Vendored or downloaded?** Downloaded at install time by `helm dependency build`, not committed: the archive and its
subcharts are a few megabytes of generated files that every bump would rewrite. The same bytes are guaranteed by the
sha256 check instead: `install.sh` refuses any archive whose digest differs from `Chart.yaml`'s annotation.

### Bumping the version

Dependabot's PR changes `Chart.yaml` and `Chart.lock` but not the digest, so CI's render check fails on it until a
person adds it, which is the point: a cluster-wide chart is reviewed before it is installed.

1. Wait until the release is at least two weeks old; read its upgrade notes
   (`https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack#upgrading-chart`),
   above all for CRD and values changes.
2. Its digest, as the repository index publishes it:

   ```bash
   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
   helm repo update prometheus-community
   helm show chart prometheus-community/kube-prometheus-stack --version <version> >/dev/null   # it exists
   yq '.entries."kube-prometheus-stack"[] | select(.version == "<version>") | .digest' \
     "$(helm env HELM_REPOSITORY_CACHE)/prometheus-community-index.yaml"
   ```

3. Put it in the annotation, update the version and the reasons above, and run `tests/install_test.sh`; CI's kind job
   installs it.
4. After the merge, a cluster admin runs `install.sh` against each cluster (deploy/azure/README.md, section 4.5).
