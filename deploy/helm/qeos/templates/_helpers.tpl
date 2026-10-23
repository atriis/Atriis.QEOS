{{/* Shared pieces of the QEOS chart (ADR-038). Each workload is one entry of .Values.services. */}}

{{/* The suffix appended to service names: ".<namespace>.svc.cluster.local" unless namespaceSuffix says otherwise */}}
{{- define "qeos.suffix" -}}
{{- default (printf ".%s.svc.cluster.local" .Release.Namespace) .Values.namespaceSuffix -}}
{{- end -}}

{{/* qeos.image (dict "ctx" $ "image" "<name>" "tag" "<tag or empty>") -- [<registry>/]qeos/<name>:<tag> */}}
{{- define "qeos.image" -}}
{{- $ctx := .ctx -}}
{{- $tag := default (required "image.tag is required: the git SHA or version the images were built from" $ctx.Values.image.tag) .tag -}}
{{- if $ctx.Values.image.registry -}}
{{- printf "%s/qeos/%s:%s" $ctx.Values.image.registry .image $tag -}}
{{- else -}}
{{- printf "qeos/%s:%s" .image $tag -}}
{{- end -}}
{{- end -}}

{{- define "qeos.publicUrl" -}}
{{- $url := required "publicUrl is required: https://<host> users and collectors reach" .Values.publicUrl -}}
{{- if not (hasPrefix "https://" $url) -}}
{{- fail (printf "publicUrl must start with https://, got %q" $url) -}}
{{- end -}}
{{- trimSuffix "/" $url -}}
{{- end -}}

{{/* The host of publicUrl, without a port: the edge's listeners, routes and certificate */}}
{{- define "qeos.publicHost" -}}
{{- $host := (urlParse (include "qeos.publicUrl" .)).host -}}
{{- regexReplaceAll ":[0-9]+$" $host "" -}}
{{- end -}}

{{/* The edge's namespace: where the add-on runs the Gateway's proxy pods (the Gateway's own namespace) */}}
{{- define "qeos.edgeNamespace" -}}
{{- default .Release.Namespace .Values.edge.namespace -}}
{{- end -}}

{{/* qeos.callers (dict "ctx" $ "name" "<service>") -- JSON list, sorted: the workloads whose services.<x>.urls name
the service. The gateway, which proxies to every API and the dashboard, has no urls: networkpolicies.yaml adds it */}}
{{- define "qeos.callers" -}}
{{- $callers := list -}}
{{- range $name, $svc := .ctx.Values.services -}}
{{- if has $.name (values ($svc.urls | default dict)) -}}
{{- $callers = append $callers $name -}}
{{- end -}}
{{- end -}}
{{- toJson (sortAlpha $callers) -}}
{{- end -}}

{{/* Every NetworkPolicy's podSelector ends with this: never the edge's proxy pods. The add-on runs them in the Gateway's
namespace (the release's) and Istio may copy the Gateway's labels onto them, app.kubernetes.io/instance included;
gateway.networking.k8s.io/gateway-name, which it always sets, tells them apart. Their traffic is the add-on's to rule */}}
{{- define "qeos.notEdge" -}}
matchExpressions:
  - key: gateway.networking.k8s.io/gateway-name
    operator: DoesNotExist
{{- end -}}

{{/* qeos.labels (dict "ctx" $ "name" "<service>" "component" "<kind>") */}}
{{- define "qeos.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/part-of: qeos
app.kubernetes.io/component: {{ .component }}
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .ctx.Chart.Name .ctx.Chart.Version }}
{{- end -}}

{{- define "qeos.selector" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
{{- end -}}

{{- define "qeos.keyvault" -}}
{{- eq .Values.secrets.source "keyvault" -}}
{{- end -}}

{{/* The Secret a workload's secretKeyRefs read: the CI Secret, or the one its own SecretProviderClass syncs */}}
{{- define "qeos.secretName" -}}
{{- if eq .ctx.Values.secrets.source "kubernetes" -}}
{{- .ctx.Values.secrets.name -}}
{{- else -}}
{{- printf "qeos-secrets-%s" .name -}}
{{- end -}}
{{- end -}}

{{/* qeos.secretRefs (dict "ctx" $ "svc" $svc) -- JSON: env var -> secret key, for every secret the workload reads */}}
{{- define "qeos.secretRefs" -}}
{{- $refs := dict -}}
{{- range $env, $key := (.svc.secretEnv | default dict) -}}
{{- $_ := set $refs $env $key -}}
{{- end -}}
{{- /* The shared key the Grafana sidecar checks (X-QEOS-Grafana-Key): the gateway sends it, so only with monitoring on */ -}}
{{- if and (eq .svc.kind "gateway") .ctx.Values.monitoring.enabled -}}
{{- $_ := set $refs "GRAFANA_PROXY_KEY" "grafana-proxy-key" -}}
{{- end -}}
{{- if .svc.database -}}
{{- $_ := set $refs "POSTGRES_PASSWORD" (printf "%s-db-password" .svc.database) -}}
{{- end -}}
{{- if and .svc.artifacts (eq .ctx.Values.artifacts.backend "s3") -}}
{{- $_ := set $refs "ARTIFACTS_S3_ACCESS_KEY" "artifacts-s3-access-key" -}}
{{- $_ := set $refs "ARTIFACTS_S3_SECRET_KEY" "artifacts-s3-secret-key" -}}
{{- end -}}
{{- toJson $refs -}}
{{- end -}}

{{/* qeos.secretEnv (dict "ctx" $ "svc" $svc) -- the env entries, each a secretKeyRef (never a value) */}}
{{- define "qeos.secretEnv" -}}
{{- $ctx := .ctx -}}
{{- $secret := include "qeos.secretName" (dict "ctx" $ctx "name" .name) -}}
{{- $refs := include "qeos.secretRefs" . | fromJson -}}
{{- range $env := keys $refs | sortAlpha }}
- name: {{ $env }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ get $refs $env }}
      {{- if has (get $refs $env) $ctx.Values.secrets.optional }}
      optional: true
      {{- end }}
{{- end }}
{{- end -}}

{{/* qeos.env (dict "ctx" $ "name" "<service>" "svc" $svc) -- JSON of the workload's non-secret settings */}}
{{- define "qeos.env" -}}
{{- $ctx := .ctx -}}
{{- $svc := .svc -}}
{{- $suffix := include "qeos.suffix" $ctx -}}
{{- $env := dict -}}
{{- if has $svc.kind (list "api" "loop") -}}
{{- $_ := set $env "QEOS_VERSION" (default $ctx.Chart.AppVersion $ctx.Values.version) -}}
{{- $_ := set $env "QEOS_COMMIT" (toString $ctx.Values.image.tag) -}}
{{- /* The settings' components path (qeos_shared.config): the password is URL-escaped there, so any character works */ -}}
{{- $_ := set $env "POSTGRES_SERVER" (required "postgres.host is required" $ctx.Values.postgres.host) -}}
{{- $_ := set $env "POSTGRES_DB" (printf "%s_db" $svc.database) -}}
{{- $_ := set $env "POSTGRES_USER" (printf "%s_app" $svc.database) -}}
{{- $_ := set $env "PGSSLMODE" $ctx.Values.postgres.sslmode -}}
{{- end -}}
{{- range $var, $target := ($svc.urls | default dict) -}}
{{- $_ := set $env $var (printf "http://%s%s:8000" $target $suffix) -}}
{{- end -}}
{{- range $var := ($svc.publicUrlEnv | default list) -}}
{{- $_ := set $env $var (include "qeos.publicUrl" $ctx) -}}
{{- end -}}
{{- if $svc.monitoring -}}
{{- $_ := set $env "MONITORING_ENABLED" (toString $ctx.Values.monitoring.enabled) -}}
{{- end -}}
{{- if $svc.smtp -}}
{{- /* A server that wants a sign-in, with no credentials, refuses every message, and the links are then neither sent nor
logged. So while Key Vault lacks smtp-user or smtp-password (keyvault.absent), SMTP_HOST stays empty: links are logged */ -}}
{{- $smtpHost := $ctx.Values.smtp.host -}}
{{- if and (eq (include "qeos.keyvault" $ctx) "true") (or (has "smtp-user" $ctx.Values.keyvault.absent) (has "smtp-password" $ctx.Values.keyvault.absent)) -}}
{{- $smtpHost = "" -}}
{{- end -}}
{{- $_ := set $env "SMTP_HOST" $smtpHost -}}
{{- $_ := set $env "SMTP_PORT" (toString $ctx.Values.smtp.port) -}}
{{- $_ := set $env "SMTP_TLS" (toString $ctx.Values.smtp.tls) -}}
{{- $_ := set $env "SMTP_REQUIRE_LOGIN" (toString $ctx.Values.smtp.requireLogin) -}}
{{- $_ := set $env "EMAILS_FROM_EMAIL" $ctx.Values.smtp.fromEmail -}}
{{- $_ := set $env "EMAILS_FROM_NAME" $ctx.Values.smtp.fromName -}}
{{- end -}}
{{- if $svc.artifacts -}}
{{- $backend := $ctx.Values.artifacts.backend -}}
{{- $_ := set $env "ARTIFACTS_BACKEND" $backend -}}
{{- if eq $backend "s3" -}}
{{- $_ := set $env "ARTIFACTS_S3_ENDPOINT" (required "artifacts.s3.endpoint is required with artifacts.backend s3" $ctx.Values.artifacts.s3.endpoint) -}}
{{- $_ := set $env "ARTIFACTS_S3_BUCKET" $ctx.Values.artifacts.s3.bucket -}}
{{- else if eq $backend "azure" -}}
{{- $_ := set $env "ARTIFACTS_AZURE_ACCOUNT_URL" (required "artifacts.azure.accountUrl is required with artifacts.backend azure" $ctx.Values.artifacts.azure.accountUrl) -}}
{{- $_ := set $env "ARTIFACTS_AZURE_CONTAINER" $ctx.Values.artifacts.azure.container -}}
{{- else -}}
{{- fail (printf "artifacts.backend must be s3 or azure, got %q" $backend) -}}
{{- end -}}
{{- end -}}
{{- if eq $svc.kind "gateway" -}}
{{- /* TLS ends at the edge; the gateway listens on 8080 and builds redirects for 443 (gateway/README.md) */ -}}
{{- $_ := set $env "GATEWAY_TLS" "off" -}}
{{- $_ := set $env "GATEWAY_PUBLIC_PORT" "443" -}}
{{- $_ := set $env "GATEWAY_RESOLVER" "kube-dns.kube-system.svc.cluster.local" -}}
{{- $_ := set $env "UPSTREAM_SUFFIX" $suffix -}}
{{- $_ := set $env "GATEWAY_TRUSTED_PROXIES" (required "gateway.trustedProxies is required: the edge's address range" $ctx.Values.gateway.trustedProxies) -}}
{{- $_ := set $env "GATEWAY_IMPORT_MAX_BODY" $ctx.Values.gateway.importMaxBody -}}
{{- $_ := set $env "RATE_AUTH" $ctx.Values.gateway.rates.auth -}}
{{- $_ := set $env "RATE_API" $ctx.Values.gateway.rates.api -}}
{{- $_ := set $env "RATE_COLLECT" $ctx.Values.gateway.rates.collect -}}
{{- $_ := set $env "RATE_COLLECT_BLOBS" $ctx.Values.gateway.rates.collectBlobs -}}
{{- $_ := set $env "RATE_COLLECT_ARTIFACTS" $ctx.Values.gateway.rates.collectArtifacts -}}
{{- /* The rendered configuration goes to /tmp: the root filesystem is read-only */ -}}
{{- $_ := set $env "NGINX_RENDER_DIR" "/tmp/nginx" -}}
{{- $_ := set $env "NGINX_CERT_DIR" "/tmp/certs" -}}
{{- end -}}
{{- range $var, $value := ($svc.env | default dict) -}}
{{- $_ := set $env $var (toString $value) -}}
{{- end -}}
{{- toJson $env -}}
{{- end -}}

{{/* The pod-level security context: the image's own non-root user */}}
{{- define "qeos.podSecurity" -}}
runAsNonRoot: true
runAsUser: {{ .uid }}
runAsGroup: {{ .uid }}
fsGroup: {{ .uid }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Every container (Global Constraints) */}}
{{- define "qeos.containerSecurity" -}}
runAsNonRoot: true
readOnlyRootFilesystem: true
allowPrivilegeEscalation: false
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* qeos.podCommon (dict "ctx" $ "name" "<service>" "uid" <uid>) -- shared pod settings of every long-running workload */}}
{{- define "qeos.podCommon" -}}
securityContext:
  {{- include "qeos.podSecurity" . | nindent 2 }}
# No Kubernetes API access and no service-link variables (they would collide with settings such as POSTGRES_*)
automountServiceAccountToken: false
enableServiceLinks: false
terminationGracePeriodSeconds: 30
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "qeos.selector" . | nindent 8 }}
{{- end -}}

{{/* In-API background tasks usually finish while the endpoints drop the pod */}}
{{- define "qeos.lifecycle" -}}
lifecycle:
  preStop:
    exec:
      command: ["sleep", "5"]
{{- end -}}

{{/* qeos.identityLabels (dict "svc" $svc) -- the workload identity webhook's label, only on pods that call Azure with
the SDK (azureSdk: ingestion and retention, for Blob). The webhook injects AZURE_CLIENT_ID and AZURE_TENANT_ID into
every container's env, where they would override settings of the same name (auth-service's Entra app). The Key Vault
CSI driver needs no label: it gets the ServiceAccount's token through the CSIDriver's tokenRequests */}}
{{- define "qeos.identityLabels" -}}
{{- if .svc.azureSdk }}
azure.workload.identity/use: "true"
{{- end }}
{{- end -}}

{{/* The CSI volume that makes the driver sync the workload's Secret, holding only its own keys: only when it mounts
one (qeos.vaultMounted: Key Vault, and the vault holds one of its keys), so a workload whose every key is in
keyvault.absent never waits for a SecretProviderClass that does not exist. Context: (dict "ctx" $ "name" "svc") */}}
{{- define "qeos.secretsVolume" -}}
{{- if include "qeos.vaultMounted" . }}
- name: secrets-store
  csi:
    driver: secrets-store.csi.k8s.io
    readOnly: true
    volumeAttributes:
      secretProviderClass: {{ printf "qeos-%s" .name }}
{{- end }}
{{- end -}}

{{- define "qeos.secretsMount" -}}
{{- if include "qeos.vaultMounted" . }}
- name: secrets-store
  mountPath: /mnt/secrets-store
  readOnly: true
{{- end }}
{{- end -}}

{{/* A SecretProviderClass's Azure parameters: the identity's client id (several classes may share one) and the Key
Vault keys this class reads */}}
{{- define "qeos.keyvaultParameters" -}}
usePodIdentity: "false"
clientID: {{ required (printf "keyvault.clientIds.%s is required with secrets.source keyvault" .identity) (get .ctx.Values.keyvault.clientIds .identity) | quote }}
keyvaultName: {{ required "keyvault.name is required with secrets.source keyvault" .ctx.Values.keyvault.name | quote }}
tenantId: {{ required "keyvault.tenantId is required with secrets.source keyvault" .ctx.Values.keyvault.tenantId | quote }}
objects: |
  array:
  {{- range $key := .keys }}
    - |
      objectName: {{ $key }}
      objectType: secret
  {{- end }}
{{- end -}}

{{/* The migration hook's database list (DATABASES for db-init) and the volumes every hook container mounts */}}
{{- define "qeos.migrateDatabases" -}}
{{- $dbs := list -}}
{{- range $name := .Values.migrate.order -}}
{{- $dbs = append $dbs (get $.Values.services $name).database -}}
{{- end -}}
{{- join " " $dbs -}}
{{- end -}}

{{/* qeos.migrateMounts (dict "keys" (list ...)) -- each listed secret as one file in /mnt/secrets, nothing else of the volume */}}
{{- define "qeos.migrateMounts" -}}
- name: tmp
  mountPath: /tmp
- name: scripts
  mountPath: /opt/qeos/scripts
  readOnly: true
{{- range $key := .keys }}
- name: secrets
  mountPath: {{ printf "/mnt/secrets/%s" $key }}
  subPath: {{ $key }}
  readOnly: true
{{- end }}
{{- end -}}

{{/* The CI backing services (ci-backing.yaml): their own part-of, so the platform's checks leave them out */}}
{{- define "qeos.ciLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/part-of: qeos-ci
app.kubernetes.io/component: ci-backing
{{- end -}}
{{- define "qeos.ciHook" -}}
helm.sh/hook: pre-install
helm.sh/hook-weight: {{ .weight | quote }}
{{- end -}}

{{/* ---- Monitoring (monitoring.enabled, ADR-038 Stage 2) ---- */}}

{{/* The monitoring namespace: networkPolicy.prometheus.namespace, its single source */}}
{{- define "qeos.prometheusNamespace" -}}
{{- $prometheus := .Values.networkPolicy.prometheus | default dict -}}
{{- required "networkPolicy.prometheus.namespace is required with monitoring.enabled: the Prometheus pods' namespace" $prometheus.namespace -}}
{{- end -}}

{{/* Grafana's data source: monitoring.prometheusUrl, or kube-prometheus-stack's Service in the monitoring namespace */}}
{{- define "qeos.prometheusUrl" -}}
{{- if .Values.monitoring.prometheusUrl -}}
{{- .Values.monitoring.prometheusUrl -}}
{{- else -}}
{{- printf "http://qeos-monitoring-prometheus.%s.svc.cluster.local:9090" (include "qeos.prometheusNamespace" .) -}}
{{- end -}}
{{- end -}}

{{/* Grafana's data source: monitoring/grafana/provisioning/datasources/prometheus.yml (uid prometheus, which the
dashboards name), on the cluster's Prometheus (grafana.yaml) */}}
{{- define "qeos.grafanaDatasources" -}}
apiVersion: 1
datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: {{ include "qeos.prometheusUrl" . }}
    isDefault: true
    editable: false
    jsonData:
      timeInterval: 15s
{{- end -}}

{{/* A NetworkPolicy source: the Prometheus pods (networkPolicy.prometheus), by namespace name and pod labels */}}
{{- define "qeos.prometheusPeer" -}}
{{- $prometheus := .Values.networkPolicy.prometheus | default dict -}}
- namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: {{ include "qeos.prometheusNamespace" . }}
  podSelector:
    matchLabels:
      {{- /* Empty labels would admit every pod of that namespace */}}
      {{- if not $prometheus.podLabels }}
      {{- fail "networkPolicy.prometheus.podLabels is required: the Prometheus pods' labels" }}
      {{- end }}
      {{- toYaml $prometheus.podLabels | nindent 6 }}
{{- end -}}

{{/* JSON: the monitoring workloads (empty with monitoring off), shaped like .Values.services entries so the secret
helpers (qeos.secretRefs, qeos.vaultKeys, qeos.secretEnv) and secretproviderclass.yaml treat them alike. port: their
Service's; podPort: the pod's port behind it (default port). The Prometheus pods reach them there, or, with callers,
those workloads of the release only (networkpolicies.yaml) */}}
{{- define "qeos.monitoringWorkloads" -}}
{{- $workloads := dict -}}
{{- if .Values.monitoring.enabled -}}
{{- $identity := required "monitoring.identity is required with monitoring.enabled" .Values.monitoring.identity -}}
{{- $_ := set $workloads "postgres-exporter" (dict "kind" "postgres-exporter" "identity" $identity "port" 9187
  "secretEnv" (dict "DATA_SOURCE_PASS" "monitoring-db-password")) -}}
{{- $_ := set $workloads "alertmanager" (dict "kind" "alertmanager" "identity" $identity "port" 9093 "smtp" true
  "secretEnv" (dict "ALERT_SLACK_WEBHOOK_URL" "alert-slack-webhook-url" "ALERT_TEAMS_WEBHOOK_URL" "alert-teams-webhook-url"
    "SMTP_USER" "smtp-user" "SMTP_PASSWORD" "smtp-password")) -}}
{{- /* Grafana's Service is its grafana-proxy sidecar (8080), which only the gateway reaches; Grafana reads the admin
password, the sidecar the key (grafana.yaml) */ -}}
{{- $_ := set $workloads "grafana" (dict "kind" "grafana" "identity" $identity "port" 3000 "podPort" 8080 "callers" (list "gateway")
  "secretEnv" (dict "GF_SECURITY_ADMIN_PASSWORD" "grafana-admin-password" "GRAFANA_PROXY_KEY" "grafana-proxy-key")) -}}
{{- end -}}
{{- toJson $workloads -}}
{{- end -}}

{{/* qeos.vaultKeys (dict "ctx" $ "svc" $svc) -- JSON list, sorted: the Key Vault keys the workload's SecretProviderClass
holds, those of its secrets that keyvault.absent does not list. Empty: no SecretProviderClass and no CSI volume */}}
{{- define "qeos.vaultKeys" -}}
{{- $keys := list -}}
{{- range $env, $key := include "qeos.secretRefs" . | fromJson -}}
{{- if not (has $key $.ctx.Values.keyvault.absent) -}}
{{- $keys = append $keys $key -}}
{{- end -}}
{{- end -}}
{{- toJson ($keys | uniq | sortAlpha) -}}
{{- end -}}

{{/* qeos.vaultMounted (dict "ctx" $ "name" "<workload>" "svc" $svc) -- "true" when the workload mounts its
SecretProviderClass's CSI volume: Key Vault, and the vault holds one of its keys (qeos.vaultKeys); empty otherwise, so
an absent key never mounts a class that does not exist (the pod would stay in ContainerCreating) */}}
{{- define "qeos.vaultMounted" -}}
{{- if and (eq .ctx.Values.secrets.source "keyvault") (include "qeos.vaultKeys" . | fromJsonArray) -}}
true
{{- end -}}
{{- end -}}

{{/* qeos.metricsLabels (dict "ctx" $ "job" "<job>") -- a scraped Service's label: Prometheus's job (ServiceMonitor jobLabel) */}}
{{- define "qeos.metricsLabels" -}}
qeos.io/metrics-job: {{ .job }}
{{- end -}}
