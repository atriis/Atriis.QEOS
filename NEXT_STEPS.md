# Next Steps

Updated 2026-10-02. This file now just points at the maintained sources —
its previous content contradicted the repo (it claimed `shared/` did not
exist while `shared/qeos_shared` is installed by every service and tested in
CI, and listed shipped features as unbuilt).

- **What to do next**: IMPLEMENTATION_PLAN.md §2 (Now/Next) and §4 (triggered slices).
- **Item-level record**: TODO.md.
- **Current vs target architecture**: ARCHITECTURE_BLUEPRINT_V1_0.md Implementation Status banner.
- **Current-state spec**: TECHNICAL_SPECIFICATION.md.

## AKS follow-ups (ADR-038, Stage 1 built 2026-10-22)

- **Run the first staging deploy** (needs the Azure subscription): deploy the Bicep, set the repository variables, apply
  the GitHub environment branch policies, run `deploy-aks.yml`, then `scripts/smoke_k8s.sh` against the staging address
  and work through "Verify on the first real deploy" in ADR-038.
- **Stage 2** (NetworkPolicies, kube-prometheus-stack with QEOS's rules and dashboards, the Grafana proxy sidecar,
  Container Insights) and **Stage 3** (production, the restore drill, the CI switch-over); see TODO.md.
- Redis shared rate limits and a queue for in-API background work stay behind their triggers.

- Password-less database sign-in on AKS: Microsoft Entra authentication on PostgreSQL Flexible Server with
  workload identity, so no service holds a database password. Needs token refresh in every service's
  SQLAlchemy engine. Out of the first AKS stages by design (docs/superpowers/specs/2026-10-21-aks-deployment-design.md).

## Step screenshots follow-ups (ADR-036, shipped 2026-10-20)

- **Separate image retention.** Images follow their results' retention days. If storage grows, add a shorter retention for images only.
- **Traces.** Stage 1 done 2026-10-21 (ADR-037): upload, `keep_traces` switch (off by default), Trace download button.
  The collector 0.14.0 release and the OBT hook (PR "QEOS: send failure traces to QEOS") are pending. Stage 2, the
  trace viewer in the browser, is done 2026-10-22: one-time links and Playwright's viewer (`playwright-core` pinned)
  served by the dashboard at `/trace-viewer/`. When bumping `playwright-core`, open a real trace before shipping.
  Follow-ups: open more than the first trace.
  Design: `docs/superpowers/specs/2026-10-21-traces-and-videos-design.md`.
- **Videos.** Later, on top of traces: section 8 of the same design.
