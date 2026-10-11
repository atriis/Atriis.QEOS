"""The architecture documentation against what is deployed, the same locally and in CI.

    python scripts/check_architecture_docs.py

Implementation, read from the repository:
  - the long-running services of docker-compose.yml and deploy/docker-compose.prod.yml (a service another
    one waits on with `service_completed_successfully` is a one-shot job, db-init or a migration, and skipped);
  - the hosts the gateway proxies to (gateway/*.conf*).
Documentation:
  - the Mermaid diagram and the component table in README.md's Architecture section;
  - the Services row of the implementation status banner in ARCHITECTURE_BLUEPRINT_V1_0.md.

Both directions are checked: every running service is drawn and listed, and every service the documents
name exists. Exits 1 with one line per finding. Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A name is found when it starts a word: "postgres" is found in "PostgreSQL 15", "grafana" in "Grafana"
def mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(name)}", text, re.IGNORECASE) is not None


def compose_services(text: str) -> dict[str, set[str]]:
    """{service: profiles} for the long-running services of a compose file."""
    block = re.search(r"^services:\n(.*?)(?=^\S|\Z)", text, re.MULTILINE | re.DOTALL)
    if not block:
        return {}
    services: dict[str, set[str]] = {}
    current = None
    for line in block.group(1).splitlines():
        m = re.match(r"^  ([a-z0-9][a-z0-9_-]*):\s*$", line)
        if m:
            current = m.group(1)
            services[current] = set()
            continue
        p = re.match(r"^    profiles:\s*\[(.*)\]", line)
        if p and current:
            services[current] = {x.strip().strip("'\"") for x in p.group(1).split(",") if x.strip()}
    one_shot = set(re.findall(r"^      ([a-z0-9][a-z0-9_-]*):\n        condition: service_completed_successfully",
                              text, re.MULTILINE))
    return {name: profiles for name, profiles in services.items() if name not in one_shot}


def gateway_upstreams(texts: list[str]) -> set[str]:
    return {host for text in texts for host in re.findall(r"set \$\w*upstream http://([a-z0-9-]+):\d+", text)}


def architecture_section(readme: str) -> str:
    m = re.search(r"^## Architecture\n(.*?)(?=^## )", readme, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def diagram_of(section: str) -> str:
    m = re.search(r"```mermaid\n(.*?)```", section, re.DOTALL)
    return m.group(1) if m else ""


def table_of(section: str) -> list[list[str]]:
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in section.splitlines() if line.startswith("|")]
    return rows[2:]  # past the header and the |---| line


def banner_services(blueprint: str) -> str:
    m = re.search(r"^> \| Services \| (.*)$", blueprint, re.MULTILINE)
    return m.group(1) if m else ""


def check(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    read = lambda rel: (root / rel).read_text(encoding="utf-8")

    stack = compose_services(read("docker-compose.yml"))
    prod = compose_services(read("deploy/docker-compose.prod.yml"))
    upstreams = gateway_upstreams([read(f"gateway/{p.name}") for p in sorted((root / "gateway").glob("*.conf*"))])
    section = architecture_section(read("README.md"))
    diagram, table = diagram_of(section), table_of(section)
    table_text = "\n".join(" | ".join(r) for r in table)
    banner = banner_services(read("ARCHITECTURE_BLUEPRINT_V1_0.md"))

    for what, found in (("README.md: no Architecture section", section), ("README.md: no Mermaid diagram", diagram),
                        ("README.md: no component table", table),
                        ("ARCHITECTURE_BLUEPRINT_V1_0.md: no Services row in the status banner", banner)):
        if not found:
            problems.append(what)
    if problems:
        return problems

    # Implementation -> documentation
    for name in sorted(stack):
        if not mentions(diagram, name):
            problems.append(f"README.md diagram: compose service {name!r} is not drawn")
        if not mentions(table_text, name) and not mentions(table_text, name.removesuffix("-service")):
            problems.append(f"README.md component table: compose service {name!r} is not listed")
        if not stack[name] and name != "postgres" and not mentions(banner, name.removesuffix("-service")):
            problems.append(f"ARCHITECTURE_BLUEPRINT_V1_0.md status banner: service {name!r} is missing from the Services row")
    for name in sorted(set(prod) - set(stack)):
        if not mentions(table_text, name):
            problems.append(f"README.md component table: production service {name!r} "
                            "(deploy/docker-compose.prod.yml) is not listed")
    for host in sorted(upstreams - set(stack)):
        problems.append(f"gateway proxies to {host!r}, which docker-compose.yml does not run")

    # Documentation -> implementation
    documented = set(re.findall(r"(?<![\w-])([a-z0-9]+(?:-[a-z0-9]+)*-(?:service|exporter))\b",
                                f"{diagram}\n{table_text}\n{banner}"))
    for name in sorted(documented - set(stack)):
        problems.append(f"documentation names {name!r}, which docker-compose.yml does not run")
    for row in table:
        for path in re.findall(r"\]\(([^)#]+)", row[1] if len(row) > 1 else ""):
            if not (root / path).exists():
                problems.append(f"README.md component table: path {path!r} does not exist")
    return problems


def main() -> int:
    problems = check()
    for p in problems:
        print(f"architecture docs: {p}")
    if problems:
        print("Update README.md's Architecture section and the blueprint's status banner to match.", file=sys.stderr)
        return 1
    print("architecture docs: README diagram, component table and blueprint banner match the stack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
