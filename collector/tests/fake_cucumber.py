"""A stand-in for Cucumber in run-impact's tests and in CI's collector-action job.

It reads a scenario catalogue from FAKE_CUCUMBER_SPEC and understands the arguments run-impact adds for each flavour
(plan Ruling 7). It writes a Cucumber JSON report and exits 1 when a scenario it ran failed. When FAKE_CUCUMBER_LOG is
set, it appends one JSON line per invocation: {"argv", "dry_run", "ran", "rerun"}.

Two more variables:
- FAKE_CUCUMBER_EXTRA names a feature uri it always adds to a rerun selection, as a profile's `paths` would;
- FAKE_CUCUMBER_WINDOWS=1 reports uris with backslashes, as a Windows runner does."""
import json
import os
import sys


def read_rerun(path):
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    wanted = set()
    for entry in text.split("\n"):
        entry = entry.strip()
        if entry:
            uri, *lines = entry.split(":")
            wanted.update((uri, int(line)) for line in lines)
    return text, wanted


def main(argv):
    with open(os.environ["FAKE_CUCUMBER_SPEC"], encoding="utf-8") as handle:
        spec = json.load(handle)
    dry_run, report, rerun, wanted, tags = False, None, None, None, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--dry-run", "-Dcucumber.execution.dry-run=true"):
            dry_run = True
        elif arg == "--format" and i + 1 < len(argv):
            i += 1
            if argv[i].startswith("json:"):
                report = argv[i][len("json:"):]
        elif arg == "--out" and i + 1 < len(argv):
            i += 1
            report = argv[i]
        elif arg.startswith("-Dcucumber.plugin=json:"):
            report = arg[len("-Dcucumber.plugin=json:"):]
        elif arg.startswith("-Dcucumber.features=@"):
            rerun, wanted = read_rerun(arg[len("-Dcucumber.features=@"):])
        elif arg in ("--tags", "-t") and i + 1 < len(argv):
            i += 1
            tags.append(argv[i])
        elif arg.startswith("@"):  # Ruby: @path
            rerun, wanted = read_rerun(arg[1:])
        elif os.path.basename(arg).startswith("@"):  # cucumber-js 12: a relative path to a file named @...
            rerun, wanted = read_rerun(os.path.join(os.getcwd(), arg))
        i += 1
    extra = os.environ.get("FAKE_CUCUMBER_EXTRA")
    windows = os.environ.get("FAKE_CUCUMBER_WINDOWS") == "1"
    ran, features, failed = [], [], False
    for feature in spec["features"]:
        elements = []
        for scenario in feature["scenarios"]:
            if any(tag not in scenario.get("tags", []) for tag in tags):
                continue
            if wanted is not None and (feature["uri"], scenario["line"]) not in wanted and feature["uri"] != extra:
                continue
            status = "skipped" if dry_run else scenario.get("status", "passed")
            failed = failed or status == "failed"
            elements.append({"type": "scenario", "keyword": "Scenario", "name": scenario["name"],
                             "line": scenario["line"],
                             "steps": [{"keyword": "Given ", "name": "a step",
                                        "result": {"status": status,
                                                   "duration": int(scenario.get("seconds", 1) * 1e9)}}]})
            ran.append(f"{feature['uri']}:{scenario['line']}")
        if elements:
            uri = feature["uri"].replace("/", "\\") if windows else feature["uri"]
            features.append({"uri": uri, "name": feature["name"], "keyword": "Feature", "elements": elements})
    if report:
        with open(report, "w", encoding="utf-8") as handle:
            json.dump(features, handle)
    log = os.environ.get("FAKE_CUCUMBER_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "dry_run": dry_run, "ran": ran, "rerun": rerun}) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
