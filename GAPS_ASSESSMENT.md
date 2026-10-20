# Gaps Assessment

Snapshot of 2026-10-02; current state: README.md, TECHNICAL_SPECIFICATION.md, the blueprint banner.

Updated 2026-10-02 against the running system (the previous version predated
the gateway, CI and benchmarks and listed them as absent).

## Closed since the last assessment
- API gateway: NGINX with rate zones, TLS, JSON errors, request IDs, smoke-tested routing.
- CI/CD: `.github/workflows/ci.yml` — service matrix, collector matrix, dashboard, container smokes, gateway full-stack smoke, CodeQL.
- Performance evidence: `scripts/analytics_benchmark.py` (~2M results), numbers in the ingestion README.
- Frontend: `dashboard/` SPA shipped.
- Auth hardening: MFA, httpOnly refresh cookie, SSO tenant allowlist, signing-key fetch hardening.

## Real gaps today
1. **No metrics backend**: ingestion exposes Prometheus metrics; no Prometheus server/Grafana (trigger: first multi-node deployment).
2. **No event bus / queue**: ingestion is synchronous (trigger: 1000+ events/s).
3. **Service-to-service auth**: organization-service cannot verify users against auth-service without a superuser token (TODO gateway follow-up).
4. **Artifacts**: step screenshots are stored (MinIO, ADR-036, 2026-10-20); videos, traces and Playwright attachments are not yet (NEXT_STEPS).
5. **Unverified integrations**: real-tenant SSO sign-in, collector `--ca-file` against the dev self-signed cert, SAML (blocked on an IdP).
6. **Dead prototype weight**: six unwired directories (flagged with READMEs) awaiting archive-or-revive decisions.
7. **Phase 2 exit unproven**: no real-project deployments of the collector; 10k-execution ingestion target untested outside benchmarks.
8. **Single points**: one Postgres, one gateway instance, compose-only deployment (accepted at current maturity L0).

Forward plan: IMPLEMENTATION_PLAN.md. Live record: TODO.md.
