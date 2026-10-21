# Next Steps

Updated 2026-10-02. This file now just points at the maintained sources —
its previous content contradicted the repo (it claimed `shared/` did not
exist while `shared/qeos_shared` is installed by every service and tested in
CI, and listed shipped features as unbuilt).

- **What to do next**: IMPLEMENTATION_PLAN.md §2 (Now/Next) and §4 (triggered slices).
- **Item-level record**: TODO.md.
- **Current vs target architecture**: ARCHITECTURE_BLUEPRINT_V1_0.md Implementation Status banner.
- **Current-state spec**: TECHNICAL_SPECIFICATION.md.

## AKS follow-ups (design 2026-10-21, ADR-038 to write)

- Password-less database sign-in on AKS: Microsoft Entra authentication on PostgreSQL Flexible Server with
  workload identity, so no service holds a database password. Needs token refresh in every service's
  SQLAlchemy engine. Out of the first AKS stages by design (docs/superpowers/specs/2026-10-21-aks-deployment-design.md).

## Step screenshots follow-ups (ADR-036, shipped 2026-10-20)

- **Separate image retention.** Images follow their results' retention days. If storage grows, add a shorter retention for images only.
- **Traces.** Design ready: `docs/superpowers/specs/2026-10-21-traces-and-videos-design.md` (stage 1 download, stage 2
  trace viewer in the browser).
- **Videos.** Later, on top of traces: section 8 of the same design.
