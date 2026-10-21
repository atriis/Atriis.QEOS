"""The architecture documentation against what is deployed, the same locally and in CI.

    python scripts/check_architecture_docs.py

Implementation, read from the repository:
  - the long-running services of docker-compose.yml and deploy/docker-compose.prod.yml (a service another
    one waits on with `service_completed_successfully` is a one-shot job, db-init or a migration, and skipped);
  - the hosts the gateway proxies to (gateway/*.conf*);
  - each service's public API: the router prefixes in platforms/**/api/v1/api.py, mounted at /api/v1.
Documentation:
  - the Mermaid diagrams and the component table in README.md's Architecture section;
  - the Services row of the implementation status banner in ARCHITECTURE_BLUEPRINT_V1_0.md;
  - the Routes table in gateway/README.md.

Both directions are checked: every running service is drawn and listed, and every service the documents
name exists; every API prefix reaches its own service through the gateway, every proxied route has a
service behind it, and the Routes table says where each path goes. Exits 1 with one line per finding.
Standard library only.
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
    """Every Mermaid diagram of the section, as one text: a service may be drawn in any of them."""
    return "\n".join(re.findall(r"```mermaid\n(.*?)```", section, re.DOTALL))


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


# ---- Routes -----------------------------------------------------------------------------------------------

API = "/api/v1"
Location = tuple[str, str, "str | None"]  # (modifier, pattern, upstream host)


def service_prefixes(root: Path, services: set[str]) -> dict[str, list[str]]:
    """{service: ["/projects/{id}/cases", ...]} from each running service's api.py, path parameters as {id}."""
    found: dict[str, list[str]] = {}
    for api in sorted(root.glob("platforms/**/api/v1/api.py")):
        if ".venv" in api.parts:
            continue
        name = api.relative_to(root / "platforms").parts[0]
        if name in services:
            text = api.read_text(encoding="utf-8")
            prefixes = re.findall(r'include_router\(\s*[\w.]+,\s*prefix="([^"]+)"', text)
            found[name] = sorted({re.sub(r"\{\w+\}", "{id}", p) for p in prefixes})
    return found


def https_locations(conf: str) -> "list[Location] | None":
    """Each location of the HTTPS server block, in order (None without one); the HTTP block only redirects."""
    listen = re.search(r"listen \d+ ssl", conf)
    if not listen:
        return None
    start = listen.start()
    locations = []
    for m in re.finditer(r"location\s+(=|~\*?|\^~)?\s*(\S+)\s*\{", conf[start:]):
        body_start = start + m.end()
        depth, i = 1, body_start
        while depth:
            depth += {"{": 1, "}": -1}.get(conf[i], 0)
            i += 1
        host = re.search(r"set \$\w*upstream http://([a-z0-9-]+):\d+", conf[body_start:i])
        locations.append((m.group(1) or "", m.group(2), host.group(1) if host else None))
    return locations


def route(locations: list[Location], uri: str) -> Location | None:
    """The location NGINX picks: an exact match, else the longest prefix when it is ^~, else the first
    matching regex in file order, else the longest prefix."""
    for loc in locations:
        if loc[0] == "=" and loc[1] == uri:
            return loc
    prefixes = [loc for loc in locations if loc[0] in ("", "^~") and uri.startswith(loc[1])]
    longest = max(prefixes, key=lambda loc: len(loc[1]), default=None)
    if longest and longest[0] == "^~":
        return longest
    for loc in locations:
        if loc[0].startswith("~") and re.search(loc[1], uri, re.IGNORECASE if loc[0] == "~*" else 0):
            return loc
    return longest


def concrete(path: str) -> str:
    return path.replace("{id}", "1")


def regex_examples(pattern: str) -> list[str]:
    """The paths a location regex such as ^/api/v1/projects/[0-9]+/(a|b)(/|$) stands for."""
    body = pattern.strip("^$").replace("[0-9]+", "1").replace("(/|$)", "")
    group = re.search(r"\(([^()]+)\)", body)
    if not group:
        return [body]
    return [body[:group.start()] + alt + body[group.end():] for alt in group.group(1).split("|")]


def under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def documented_routes(readme: str) -> list[tuple[str, str]]:
    """(path prefix, service) from gateway/README.md's Routes table; "…/x" continues the cell's first path."""
    section = re.search(r"^## Routes\n(.*?)(?=^## |\Z)", readme, re.MULTILINE | re.DOTALL)
    routes = []
    for line in (section.group(1) if section else "").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not re.fullmatch(r"[a-z0-9-]+-service", cells[1]):
            continue  # the header, /health, /grafana/ and the catch-all rows
        base = None
        for path in re.findall(r"`([^`]+)`", cells[0]):
            continues = path.startswith("…")
            path = path.replace("…", "")
            if not continues:
                base = path.rsplit("/", 1)[0]
            elif base is not None:
                path = base + path
            routes.append((path.rstrip("/"), cells[1]))
    return routes


def check_routes(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    read = lambda rel: (root / rel).read_text(encoding="utf-8")
    prefixes = service_prefixes(root, set(compose_services(read("docker-compose.yml"))))
    locations = https_locations(read("gateway/nginx.conf.template"))
    if locations is None:
        return ["gateway/nginx.conf.template: no HTTPS server block (`listen <port> ssl`)"]
    documented = documented_routes(read("gateway/README.md"))
    if not documented:
        return ["gateway/README.md: no Routes table"]

    # Implementation: every API prefix reaches its own service. Documentation: the Routes table says so
    for service, paths in sorted(prefixes.items()):
        for prefix in paths:
            path = concrete(API + prefix)
            for uri in (path, path + "/1"):
                loc = route(locations, uri)
                if not loc or loc[2] != service:
                    problems.append(f"gateway: {uri} ({service}'s {prefix}) goes to {loc[2] if loc else 'nowhere'}")
                    break
            covering = [d for d in documented if under(path, concrete(d[0]))]
            best = max(covering, key=lambda d: len(d[0]), default=None)
            if not best or best[1] != service:
                problems.append(f"gateway/README.md Routes: {API + prefix} belongs to {service}, "
                                f"the table says {best[1] if best else 'nothing'}")

    # Every proxied API location has that service's API behind it
    for modifier, pattern, host in locations:
        if host not in prefixes or "/api/" not in pattern:
            continue
        for uri in (regex_examples(pattern) if modifier.startswith("~") else [pattern]):
            ours = [concrete(API + p) for p in prefixes[host]]
            if not any(under(uri, p) or under(p, uri) for p in ours):
                problems.append(f"gateway: location {pattern} sends {uri} to {host}, which has no such route")

    # Every documented path goes where the table says
    for path, service in documented:
        loc = route(locations, concrete(path))
        if not loc or loc[2] != service:
            problems.append(f"gateway/README.md Routes: {path} is listed for {service}, "
                            f"the gateway sends it to {loc[2] if loc else 'nowhere'}")
    return problems


def main() -> int:
    problems = check() + check_routes()
    for p in problems:
        print(f"architecture docs: {p}")
    if problems:
        print("Update the documents named above, or the gateway, to match.", file=sys.stderr)
        return 1
    print("architecture docs: README diagram, component table, blueprint banner and gateway routes match the stack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
