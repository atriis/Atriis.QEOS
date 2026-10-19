from importlib.metadata import version

import qeos_collector


def test_the_version_has_a_single_source():
    assert qeos_collector.__version__ == "0.10.0"
    assert version("qeos-collector") == qeos_collector.__version__
