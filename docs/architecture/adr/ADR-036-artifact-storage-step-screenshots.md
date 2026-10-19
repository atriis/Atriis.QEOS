# ADR-036: Artifact storage on MinIO for step screenshots

Status: Accepted (2026-10-19) · Spec: `docs/superpowers/specs/2026-10-19-step-screenshots-design.md`

## Context

The tests take a screenshot at the end of every scenario and the collector drops it. People reading a failed result
in QEOS cannot see what the page looked like. Showing it needs somewhere to keep images.

The Blueprint names this exact moment as the adoption trigger for MinIO: "Artifacts feature (screenshots/videos/traces)
starts". Images cannot go in PostgreSQL rows or in the run JSON: the gateway body limit is 10 MB, and a run with
per-step images can reach several GB.

## Decision

- **MinIO, S3-compatible.** A `minio` service and a one-shot `minio-init` (creates the private bucket
  `qeos-artifacts`, no anonymous policy) join `docker-compose.yml` and, through it, the production package. MinIO
  has no published port. The volume is `qeos_minio_data`.
- **Only ingestion talks to it**, through `boto3` and `ARTIFACTS_S3_ENDPOINT`, `ARTIFACTS_S3_BUCKET`,
  `ARTIFACTS_S3_ACCESS_KEY` and `ARTIFACTS_S3_SECRET_KEY`. Any S3 service can replace MinIO by changing those four.
  Images are read back through ingestion with the same sign-in as every other read, never by presigned URL.
- **Content-addressed per project.** The object key is `screenshots/{project_id}/{sha256}`: the same image uploaded
  twice is stored once, and a project's images all sit under one prefix, which is how a project purge deletes them.
  A prefix to delete always ends with `/`, so project 1 never matches project 10.
- **Off by default.** If any of the four settings is unset, `get_artifact_store()` returns `None` and screenshots
  are off. QEOS keeps working. A project must also switch screenshots on in its settings (a later task).
- **One key pair.** The compose files use MinIO's root user as ingestion's key pair, with a dev default for a
  local stack. The production package requires `ARTIFACTS_S3_SECRET_KEY`, and `deploy/init-env.sh` generates it.
- **The MinIO image is pinned by digest.** MinIO no longer publishes images on Docker Hub, so the compose files use
  Chainguard's maintained build (`cgr.dev/chainguard/minio`), which includes the `mc` client.

## Consequences

- The VM backup must include the volume. `deploy/backup.sh` copies it next to the database dump, and the deploy
  README gives the restore commands. Without the volume, results keep working and their images answer "not found".
- Images are not masked. QEOS cannot read text inside an image, so screenshots can show names, emails and booking
  data. This is why they are off by default, and SECURITY and the privacy notes say so.
- Storage grows with images. They follow the retention days of the results they belong to, and are deleted with the
  project. A shorter image retention is a possible later step.
- A new dependency: `boto3` in ingestion's `requirements.txt` (the collector stays standard-library only).
- MinIO is another container on the one VM (ADR-019). Updating it means copying a new digest in two places.
