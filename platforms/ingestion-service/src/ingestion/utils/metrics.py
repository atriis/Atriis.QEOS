"""Prometheus metrics, on their own registry: install_metrics (qeos_shared.metrics) serves it at /metrics
together with the request metrics. Served inside the Docker network; the gateway does not route /metrics."""
from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry()

# The qav_ prefix predates the QEOS rename and is kept for compatibility: renaming a metric breaks
# every dashboard and alert built on it.

RUNS = Counter("qav_ingest_runs", "Test runs stored", registry=REGISTRY)
RESULTS = Counter("qav_ingest_results", "Test results stored", registry=REGISTRY)
REJECTED = Counter("qav_ingest_rejected", "Uploads rejected", ["reason"], registry=REGISTRY)
DISCARDED = Counter("qeos_runs_discarded", "Uploads accepted and not stored, by reason", ["reason"], registry=REGISTRY)
DISCARDED.labels(reason="manual")
DURATION = Histogram("qav_ingest_duration_seconds", "Time to handle POST /collect/runs", registry=REGISTRY)
SCREENSHOTS_DROPPED = Counter(
    "qav_ingest_screenshots_dropped", "Screenshot references of an upload that were not stored", ["reason"],
    registry=REGISTRY,
)
REDACTIONS = Counter(
    "qav_ingest_redactions", "Results in which masking replaced a kind of secret or personal data", ["kind"],
    registry=REGISTRY,
)

# Blueprint §11.2: one execution is one stored test_results row
EXECUTIONS = Counter("test_executions", "Test results stored, by status", ["status"], registry=REGISTRY)
# Job heartbeats are read from the database on each scrape (utils/job_metrics.py); a failed read
# leaves the job series out and counts here, so a database blip never makes ingestion look down
HEARTBEAT_READ_ERRORS = Counter(
    "job_heartbeat_read_errors", "Scrapes that could not read job_heartbeats", registry=REGISTRY,
)

# Pre-create each label's series so it is visible (at 0) before the first event
for _reason in ("auth", "validation", "conflict", "pending_deletion"):
    REJECTED.labels(reason=_reason)
for _reason in ("disabled", "unknown", "invalid", "gone"):
    SCREENSHOTS_DROPPED.labels(reason=_reason)
for _status in ("passed", "failed", "errored", "skipped"):
    EXECUTIONS.labels(status=_status)
