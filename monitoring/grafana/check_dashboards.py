"""Lints the provisioned Grafana dashboards (monitoring spec §8): valid JSON, the five expected uids, unique
panel ids, the provisioned Prometheus data source on every panel, a query on every panel, and no retired
metric names. Usage: python check_dashboards.py [DIR]; exits 1 on any problem."""
import json
import sys
from pathlib import Path

EXPECTED = {"qeos-overview", "qeos-service-detail", "qeos-jobs-uploads", "qeos-postgresql", "qeos-host-containers"}
# Names the plan replaced with blueprint §11.2 names; a dashboard using one would show "No data"
RETIRED = ("qeos_http_", "qeos_job_", "qeos_build_info", "http_request_duration_seconds")


def problems(path: Path):
    try:
        board = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path.name}: not valid JSON: {exc}"], None
    found = [f"{path.name}: missing {key}" for key in ("uid", "title", "panels", "schemaVersion") if key not in board]
    panels = board.get("panels", [])
    ids = [panel.get("id") for panel in panels]
    if len(ids) != len(set(ids)):
        found.append(f"{path.name}: duplicate panel ids")
    for panel in panels:
        where = f"{path.name} panel {panel.get('id')} ({panel.get('title')})"
        if (panel.get("datasource") or {}).get("uid") != "prometheus":
            found.append(f"{where}: data source is not the provisioned 'prometheus'")
        if "gridPos" not in panel:
            found.append(f"{where}: no gridPos")
        targets = panel.get("targets") or []
        if not targets or not all(target.get("expr") for target in targets):
            found.append(f"{where}: every panel needs a query")
        for target in targets:
            for name in RETIRED:
                if name in target.get("expr", ""):
                    found.append(f"{where}: uses retired metric name {name}")
    return found, board.get("uid")


def main(argv) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "dashboards"
    found, uids = [], []
    for path in sorted(folder.glob("*.json")):
        more, uid = problems(path)
        found += more
        uids.append(uid)
    if len(uids) != len(set(uids)):
        found.append("duplicate dashboard uids")
    if set(uids) != EXPECTED:
        found.append(f"dashboard uids {sorted(u for u in uids if u)} differ from {sorted(EXPECTED)}")
    for problem in found:
        print(f"FAIL {problem}")
    if not found:
        print(f"dashboards: {len(uids)} checked, all fine")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
