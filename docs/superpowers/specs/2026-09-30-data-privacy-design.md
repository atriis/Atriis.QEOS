# Data Privacy: Masking and Retention — Design

**Date:** 2026-09-30
**Status:** Draft — awaiting review
**Scope:** ingestion-service masks secrets and personal data in uploaded test output before storing it, and deletes runs older than each project's retention period with a scheduled job; project-service gains an internal endpoint, protected by a username and password, that tells the job each project's retention period.

## Problem

The roadmap's Phase 2 success criteria include "PII detection and redaction working" and "data retention policies enforced", and its exit criteria a security audit of data handling. Today:

- ingestion-service stores each result's `message` and `details` — captured test output of up to 64 KB each — exactly as uploaded. Failure output routinely contains tokens, passwords, connection strings and email addresses.
- project-service has a per-project setting `result_retention_days` (default 90, 1–365) that nothing enforces. Runs are kept forever, including those of deleted projects, whose API keys also stay valid.

Both must be fixed before real customer CI output flows in.

## Decisions (agreed during brainstorming)

| Question | Decision |
|---|---|
| What is masked | Built-in secret patterns plus email addresses and card numbers; always on, not configurable |
| How the job learns retention periods | An internal project-service endpoint the job calls |
| Credentials for that call | A username and password (HTTP Basic), given to the job as a connection string (`http://user:password@host`) |
| Where the job runs | Its own command in the ingestion-service image, run in a loop by its own compose service |

## Masking

### What is masked

- `message` and `details` of every result.
- A password inside `ci_run_url` (`https://user:pass@host/...`).
- Identity fields (`suite`, `class_name`, `name`, `file`) and `branch` are **not** masked: they identify a test across runs and must stay exact.

### Where it runs

In `ingest()`, per result: **mask first, then truncate** to `MAX_TEXT_BYTES`. Truncating first could cut a secret in half so no pattern matches, and the first half would be stored.

The idempotency `request_hash` is still computed from the upload as received, so replaying the same upload with the same `Idempotency-Key` still answers 200 with the stored run.

### Output

Each masked value becomes a marker naming its kind; the text around it stays readable.

| Input | Stored |
|---|---|
| `password=hunter2` | `password=[REDACTED:password]` |
| `Authorization: Bearer eyJhbGc…` | `Authorization: Bearer [REDACTED:authorization]` |
| `https://bob:s3cret@db.acme.test` | `https://bob:[REDACTED:url_password]@db.acme.test` |
| `ghp_16C7e42F292c6912E7710c838347Ae178B4a` | `[REDACTED:github_token]` |
| `ann@acme.com` | `[REDACTED:email]` |

### Patterns

One pure module, `src/ingestion/utils/redaction.py`, exposing `redact(text: str) -> tuple[str, set[str]]` (the masked text and the kinds found). Patterns are applied in this order, so a value matched by an earlier one is not matched again:

| # | Kind | Matches |
|---|---|---|
| 1 | `private_key` | `-----BEGIN … PRIVATE KEY-----` through the matching `-----END … PRIVATE KEY-----`; to the end of the text if there is no end line |
| 2 | `authorization` | The value of an `Authorization:` or `Proxy-Authorization:` header (also `=`), after an optional `Bearer`/`Basic`/`Token`/`Digest` scheme word, which is kept |
| 3 | `url_password` | The password in `scheme://user:password@`; the user name is kept |
| 4 | `jwt` | `eyJ<base64url>.eyJ<base64url>.<base64url>` |
| 5 | token kinds | `github_token` (`ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_` + 36+, `github_pat_` + 22+), `gitlab_token` (`glpat-` + 20+), `aws_access_key` (`AKIA`/`ASIA` + 16 upper-case alphanumerics), `slack_token` (`xoxa-`/`xoxb-`/`xoxp-`/`xoxr-`/`xoxs-` + 10+), `stripe_key` (`sk_`/`rk_` + `live_`/`test_` + 16+), `google_api_key` (`AIza` + 35), `npm_token` (`npm_` + 36), `qav_key` (`qav_` + 43) |
| 6 | `password`, `secret`, `token`, `api_key`, … | The value of a key/value pair whose key, case-insensitively, is or ends with `password`, `passwd`, `pwd`, `secret`, `token`, `api_key`/`apikey`/`api-key`, `access_key`, `client_secret`, `private_key`, `credentials`; written `key=value`, `key: value`, `"key": "value"` or `'key': 'value'`. The kind is the key's normalised name (`db_password` → `password`). A quoted value runs to the closing quote; an unquoted one to whitespace or `,;&"'=`. When the key is not a secret, the value is searched again, so `opts=--password=x` is still caught Empty values and values already starting with `[REDACTED:` are left alone |
| 7 | `email` | An email address |
| 9 | `cookie` | The value of a `Cookie:` / `Set-Cookie:` header, to the end of the line *(added after the final review)* |
| 10 | `password` (CLI, XML) | `curl -u user:pw` / `--user user:pw`, `--password pw`, `<password>pw</password>` (any tag rule 6 recognises) *(added after the final review)* |
| 8 | `card_number` | 13–19 digits, optionally grouped by single spaces or dashes, starting with a card prefix (Visa `4`, Mastercard `51`–`55`/`2221`–`2720`, Amex `34`/`37`, Discover `6011`/`65`) **and** passing the Luhn check |

- Look-alikes that must **not** be masked: git SHAs, UUIDs, timestamps, long numbers that fail Luhn or have no card prefix, and the word "password" in a sentence without a value (`the password field is required`).
- Revised after the final review: an Authorization value runs to the end of the line or the closing quote (`AWS4-HMAC-SHA256 Credential=…, Signature=…`), and `Negotiate`/`NTLM` are kept like `Bearer`; key/value pairs also accept `=>` and `:=`, JSON escaped inside a log (`\"password\": \"x\"`), a scheme word before the value (`X-Auth-Token: Bearer abc`), keys ending in `secret_key`/`signing_key`/`encryption_key`, and an empty URL user name (`redis://:pw@host`); an unquoted value ends at `;`, `,` or `&` only when another `key=` follows (`Password=ab;cd;Database=x`); PGP private key blocks are masked too.
- Every pattern uses bounded repetition (no nested unbounded quantifiers), so input crafted to trigger catastrophic regex backtracking cannot slow ingestion: 64 KB of hostile input must be processed in under one second.
- Masking never rejects an upload; it only replaces text.

### What is recorded

- `test_results.redacted` (boolean, like `truncated`): true when anything in that result was masked.
- A Prometheus counter `qav_ingest_redactions{kind}` (exported as `qav_ingest_redactions_total`), counting results in which each kind was found.
- The masked values are never logged.

## Retention

### project-service: the internal endpoint

`GET /internal/v1/projects/retention`

```json
{"projects": [
  {"project_id": 7, "result_retention_days": 90, "deleted": false},
  {"project_id": 9, "result_retention_days": 30, "deleted": true, "deleted_at": "2026-09-20T10:00:00+00:00"}
]}
```

- Lists **every** project, deleted ones included (`deleted_at IS NOT NULL` → `deleted: true`). `result_retention_days` comes from `settings_view()`, so a project that never set it gets the default (90).
- Authentication: HTTP Basic, checked against `INTERNAL_API_USERNAME` (default `ingestion-service`) and `INTERNAL_API_PASSWORD`, each compared with `hmac.compare_digest`.
  - A missing or wrong pair → 401 with `WWW-Authenticate: Basic`. A user JWT is not accepted here, and the Basic pair is accepted nowhere else.
  - `INTERNAL_API_PASSWORD` unset or empty → 503 `{"detail":"Internal API is not configured"}`; the endpoint is never open by default.
- The gateway does not route `/internal` (its catch-all answers 404); a smoke check pins that.
- Inside the Docker network the call is plain HTTP; mTLS between services stays a TODO item.

### ingestion-service: the job

`python -m src.ingestion.jobs.retention [--dry-run] [--loop]`

Configuration:
- `PROJECT_SERVICE_INTERNAL_URL` — a connection string with the credentials, e.g. `http://ingestion-service:<password>@project-service:8000`. The job takes the user name and password out of the URL and sends them as a Basic `Authorization` header. Whenever it logs the URL, it logs `http://ingestion-service:***@project-service:8000`; the password never appears in any log line or error.
- `RETENTION_INTERVAL_HOURS` — the pause between passes with `--loop` (default 24).
- `RETENTION_BATCH_SIZE` — runs deleted per transaction (default 500).

One pass:

1. **Lock.** On PostgreSQL, take `pg_try_advisory_lock(<fixed id>)`. If another copy holds it, log `already running` and end the pass successfully. (On SQLite, used only by the unit tests, there is no lock.)
2. **Fetch** the retention list. If project-service is unreachable, answers anything but 200, or the body does not match the contract (`projects` a list of objects with an integer `project_id`, an integer `result_retention_days` from 1 to 365, and a boolean `deleted`), the pass **deletes nothing** and fails.
3. **Live projects:** delete runs of that project whose `created_at` (upload time, by the server's clock) is before `now − result_retention_days`.
4. **Deleted projects:** set `revoked_at` on their API keys that are not revoked yet, at once. Their runs are all deleted only once `deleted_at` is more than `RETENTION_DELETED_GRACE_DAYS` (default 7) ago — a soft delete can still be undone; until then the usual retention applies. A deleted project without a usable `deleted_at` fails the pass. *(Grace period added after the final review.)*
5. **Projects that have runs or keys but are missing from the list are not touched**, so a bug or an empty answer can never wipe data. Their number is logged.
6. Deletes run in batches of `RETENTION_BATCH_SIZE` runs per transaction: a batch deletes the batch's results and then its runs explicitly (not relying on `ON DELETE CASCADE`, which SQLite does not enforce by default).
7. **Summary:** one JSON log line, e.g. `{"event":"retention","projects":12,"runs_deleted":340,"keys_revoked":2,"projects_skipped":0,"dry_run":false}`.

- `--dry-run` computes the same numbers and deletes or revokes nothing.
- Without `--loop`: one pass, exit 0 on success, 1 on failure.
- With `--loop`: a pass at start-up, then one every `RETENTION_INTERVAL_HOURS`. A failed pass is logged and the loop goes on. Stops cleanly on SIGTERM.

## Database change

An Alembic migration in ingestion-service adds `redacted BOOLEAN NOT NULL DEFAULT false` to `test_results`. Rows stored before this change are not re-masked (a one-off re-masking command is a TODO item). project-service needs no change: `settings` and `deleted_at` already exist.

## Stack and CI

- `docker-compose.yml`:
  - `INTERNAL_API_PASSWORD` is required, like `SECRET_KEY` (`${INTERNAL_API_PASSWORD:?...}`), and passed to project-service.
  - A new service `ingestion-retention` on the ingestion-service image, command `python -m src.ingestion.jobs.retention --loop`, with `PROJECT_SERVICE_INTERNAL_URL: http://ingestion-service:${INTERNAL_API_PASSWORD}@project-service:8000`; it starts after the ingestion migration and project-service are ready. No ports. The gateway depends on it (`service_started`), so `docker compose up gateway` still brings up the whole platform.
- CI: every job that starts the stack sets `INTERNAL_API_PASSWORD`.
- `scripts/smoke_gateway.sh` requires `INTERNAL_API_PASSWORD` (like `SECRET_KEY`) and adds:
  - an upload whose failure `details` contain a fake GitHub token, read back through the read API showing `[REDACTED:github_token]` and not the token;
  - `GET /internal/v1/projects/retention` through the gateway → 404;
  - one real pass of the job in the stack: `docker compose run --rm ingestion-retention python -m src.ingestion.jobs.retention --dry-run` → exit 0.

## Testing

- **Masking (unit):** per pattern, inputs that must be masked and look-alikes that must not; the marker format; several secrets in one text; an unterminated private key; kinds reported; the 64 KB / 1 s time limit.
- **Ingest (integration):** a secret in `details` is not stored and `redacted` is true; a clean result has `redacted` false; a secret placed across the 64 KB boundary is not partly stored; a password in `ci_run_url` is masked; a replay with the same `Idempotency-Key` still answers 200; the metric counts by kind.
- **Internal endpoint (project-service):** no credentials → 401; wrong user or password → 401; a user JWT → 401; password not configured → 503; correct pair → 200 with live and deleted projects, the default 90 for a project that never set it, and a set value for one that did.
- **Job:** against a fake project-service (scripted responses): old runs deleted and recent ones kept; a deleted project's runs deleted and keys revoked (already-revoked keys untouched); a project missing from the list untouched; unreachable, 401, 500, or a malformed body → nothing deleted, pass fails; `--dry-run` changes nothing but reports the same numbers; batching across several transactions; the password never appears in captured logs; the connection-string parsing (missing credentials → configuration error). The advisory lock is exercised by the smoke test's pass against the stack's PostgreSQL.

## Documentation

- `platforms/ingestion-service/README.md`: what is masked (the pattern table), the `redacted` flag, the retention job and its settings.
- `platforms/project-service/README.md`: the internal endpoint and its credentials.
- Root `README.md`: `INTERNAL_API_PASSWORD` next to `SECRET_KEY` in the quick start.
- `TODO.md`: "PII detection and redaction; retention policies" and "Revoke a project's API keys when the project is deleted" done; new items below.

## Out of scope (TODO.md)

- Re-mask results stored before this change (one-off command).
- Custom masking patterns per project.
- Masking identity fields.
- Artifacts (screenshots, logs) — step screenshots shipped 2026-10-20 (ADR-036) and are **not masked**: QEOS cannot read text inside an image, so they are off by default per project (owner/admin toggle "Keep screenshots from uploads") and SECURITY.md says so. Only the screenshots' step text is masked. Other artifacts: masking applies when they exist.
- Legal hold and data export before deletion.
- mTLS between services.
