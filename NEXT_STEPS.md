# Next Steps

Updated 2026-10-02. This file now just points at the maintained sources —
its previous content contradicted the repo (it claimed `shared/` did not
exist while `shared/qeos_shared` is installed by every service and tested in
CI, and listed shipped features as unbuilt).

- **What to do next**: IMPLEMENTATION_PLAN.md §2 (Now/Next) and §4 (triggered slices).
- **Item-level record**: TODO.md.
- **Current vs target architecture**: ARCHITECTURE_BLUEPRINT_V1_0.md Implementation Status banner.
- **Current-state spec**: TECHNICAL_SPECIFICATION.md.

## Step screenshots follow-ups (ADR-036, shipped 2026-10-20)

- **Separate image retention.** Images follow their results' retention days. If storage grows, add a shorter retention for images only.
- **Videos and traces.** The MinIO storage and blob endpoints are built to be reused for them.
