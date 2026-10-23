#!/usr/bin/env bash
# The release's NetworkPolicies and the namespace's Pod Security level, checked from inside the cluster (ADR-038, spec
# 5.3). A port-forward bypasses NetworkPolicies, so smoke_k8s.sh cannot see them: this script runs throwaway pods in the
# namespace (curl, the restricted security context) and calls the Services from there. kind only.
#   bash scripts/check_k8s_policies.sh qeos [release]
# Each check is one line of CHECKS below: FROM URL EXPECT.
#   FROM    stranger: a pod with no workload's labels, which no policy admits; or a workload WITHOUT a Service (a loop
#           job) whose selector labels the pod borrows, so the policies treat it as that workload. Never a workload
#           with a Service: the Service would send real traffic to the throwaway pod
#   EXPECT  an HTTP status; or blocked: the connection times out (curl exit 28), as a NetworkPolicy drops it
set -uo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <namespace> [release]" >&2
  exit 2
fi
NAMESPACE="$1"
RELEASE="${2:-qeos}"

CHECKS=(
  # Nothing of the release answers a pod that is none of its callers. postgres and MinIO (kind only) close a
  # connection that is not theirs, so anything but a timeout means the port was reachable
  "stranger http://auth-service:8000/health blocked"
  "stranger http://organization-service:8000/health blocked"
  "stranger http://project-service:8000/health blocked"
  "stranger http://ingestion-service:8000/health blocked"
  "stranger http://test-management-service:8000/health blocked"
  "stranger http://dashboard:8080/health blocked"
  "stranger http://gateway:8080/health blocked"
  "stranger http://postgres:5432/ blocked"
  "stranger http://minio:9000/minio/health/live blocked"
  # A caller reaches what its URLs name, and nothing else: the policies admit by workload, not by namespace
  "ingestion-retention http://project-service:8000/health 200"
  "ingestion-retention http://test-management-service:8000/health 200"
  "ingestion-retention http://minio:9000/minio/health/live 200"
  "ingestion-retention http://auth-service:8000/health blocked"
  "ingestion-retention http://dashboard:8080/health blocked"
)
# curlimages/curl 8.16.0 (the multi-arch index); its user curl_user is uid 101, and a named user cannot be checked
# against runAsNonRoot, so the pod gives the number
IMAGE="curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6"
CURL_UID=101

# It borrows a workload's labels: never on a real cluster
context="$(kubectl config current-context 2>/dev/null)"
case "$context" in
  kind-*) ;;
  *) echo "FAIL  kubectl context '${context:-none}' is not a kind cluster: kind only"; exit 1 ;;
esac
KUBECTL=(kubectl -n "$NAMESPACE")

failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

pods=()
cleanup() {
  [ "${#pods[@]}" -eq 0 ] || "${KUBECTL[@]}" delete pod --ignore-not-found --wait=false "${pods[@]}" >/dev/null 2>&1
}
trap cleanup EXIT

# pod_labels FROM -- the labels of the throwaway pod for FROM, as YAML lines
pod_labels() {
  if [ "$1" = stranger ]; then
    printf '    app.kubernetes.io/name: qeos-policy-check\n'
  else
    printf '    app.kubernetes.io/name: %s\n    app.kubernetes.io/instance: %s\n' "$1" "$RELEASE"
  fi
}

# start_pod FROM -- a sleeping curl pod with the restricted settings; its name on stdout
start_pod() {
  local name="qeos-policy-check-$1"
  # A previous run's pod may still be terminating (the cleanup does not wait): gone first, or apply would patch it
  "${KUBECTL[@]}" delete pod --ignore-not-found --wait=true --timeout=60s "$name" >/dev/null || return 1
  "${KUBECTL[@]}" apply -f - >/dev/null <<YAML || return 1
apiVersion: v1
kind: Pod
metadata:
  name: $name
  labels:
$(pod_labels "$1")
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  enableServiceLinks: false
  terminationGracePeriodSeconds: 0
  securityContext:
    runAsNonRoot: true
    runAsUser: $CURL_UID
    runAsGroup: $CURL_UID
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: curl
      image: $IMAGE
      imagePullPolicy: IfNotPresent
      command: ["sleep", "600"]
      securityContext:
        runAsNonRoot: true
        readOnlyRootFilesystem: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: 10m
          memory: 16Mi
        limits:
          cpu: 200m
          memory: 64Mi
YAML
  echo "$name"
}

# ---- Pod Security: the namespace enforces restricted, so a pod without the settings is refused ----
level="$("${KUBECTL[@]}" get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}' 2>/dev/null)"
[ "$level" = restricted ] && pass "namespace $NAMESPACE enforces Pod Security restricted" \
  || fail "namespace $NAMESPACE enforces '${level:-nothing}', want restricted"
if out="$("${KUBECTL[@]}" run qeos-psa-check --image="$IMAGE" --restart=Never --dry-run=server -- true 2>&1)"; then
  fail "a pod without the restricted settings is admitted"
else
  case "$out" in
    *'violates PodSecurity "restricted'*) pass "a pod without the restricted settings is refused" ;;
    *) fail "the plain pod failed for another reason: $(printf '%s' "$out" | head -c 300)" ;;
  esac
fi

# ---- NetworkPolicies ----
froms="$(printf '%s\n' "${CHECKS[@]}" | cut -d' ' -f1 | sort -u)"
for from in $froms; do
  if name="$(start_pod "$from")"; then
    pods+=("$name")
  else
    fail "could not create the throwaway pod for $from"
  fi
done
if [ "${#pods[@]}" -gt 0 ] && ! "${KUBECTL[@]}" wait --for=condition=Ready --timeout=120s "${pods[@]/#/pod/}" >/dev/null; then
  fail "the throwaway pods did not become ready"
  "${KUBECTL[@]}" get pods "${pods[@]}" -o wide
fi

for check in "${CHECKS[@]}"; do
  read -r from url expect <<< "$check"
  # Through the pod's sh: Git Bash would turn a /dev/null argument into a Windows path on its way to kubectl.exe
  code="$("${KUBECTL[@]}" exec "qeos-policy-check-$from" -- sh -c 'curl -s -o /dev/null -w "%{http_code}" -m 5 "$1"' curl "$url" 2>/dev/null)"
  rc=$?
  if [ "$expect" = blocked ]; then
    [ "$rc" = 28 ] && pass "$from -> $url is blocked (timed out)" \
      || fail "$from -> $url is reachable: curl exit $rc, HTTP ${code:-none}"
  else
    [ "$rc" = 0 ] && [ "$code" = "$expect" ] && pass "$from -> $url answers $code" \
      || fail "$from -> $url: curl exit $rc, HTTP ${code:-none}, want $expect"
  fi
done

if [ "$failures" -eq 0 ]; then
  echo "all policy checks passed"
  exit 0
fi
echo "$failures policy check(s) failed"
exit 1
