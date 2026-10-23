from importlib.metadata import version

import qeos_collector


def test_the_version_has_a_single_source():
    assert qeos_collector.__version__ == "0.14.1"
    assert version("qeos-collector") == qeos_collector.__version__


# Where CI users copy the collector's pin from. A release changes them all; this keeps the next one from missing any
PINNED = ["README.md", "docs/SETUP.md", "collector/README.md", "collector-jenkins/vars/qeosCollectorUpload.groovy",
          "templates/qeos-collector.azure-pipelines.yml", "templates/qeos-collector.gitlab-ci.yml"]


def test_every_collector_pin_names_this_version():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    pins = {}
    for name in PINNED:
        text = (root / name).read_text(encoding="utf-8")
        # The forms a pin takes (pip @tag, a raw URL, Action @tag, the Jenkins and template defaults); a history note
        # such as "from `collector-v0.7.0`" or "`@collector-v0.5.2` or later" is not a pin
        found = re.findall(r"(?:@|/|ref: '|\?: '|default: |:-)collector-v(\d+\.\d+\.\d+)(?!`? or later)", text)
        assert found, f"{name} names no collector-vX.Y.Z pin"
        pins[name] = sorted(set(found))
    assert pins == {name: [qeos_collector.__version__] for name in PINNED}
