"""`.qeos.yml`: project defaults for the collector. Flags beat environment
variables beat the file. Parsed with a small built-in reader (flat keys and
string lists), so the collector stays dependency-free."""
import pytest

from qeos_collector.config_file import load_config
from qeos_collector.upload import ConfigError

YAML = """
# QEOS collector defaults
url: https://qeos.example.com
environment: staging
ca-file: certs/internal-ca.pem
spool: .qeos-spool
fail-on-error: true
no-changes: false
no-screenshots: true
patterns:
  - "reports/**/*.xml"
  - "cucumber.json"
components:
  - product-api@a1b2c3d4e5f6
"""


def test_load_and_types(tmp_path):
    path = tmp_path / ".qeos.yml"
    path.write_text(YAML, encoding="utf-8")
    config = load_config(str(tmp_path))
    assert config["url"] == "https://qeos.example.com"
    assert config["environment"] == "staging"
    assert config["ca-file"] == "certs/internal-ca.pem"
    assert config["spool"] == ".qeos-spool"
    assert config["fail-on-error"] is True
    assert config["no-changes"] is False
    assert config["no-screenshots"] is True
    assert config["patterns"] == ["reports/**/*.xml", "cucumber.json"]
    assert config["components"] == ["product-api@a1b2c3d4e5f6"]


def test_missing_file_is_empty(tmp_path):
    assert load_config(str(tmp_path)) == {}


def test_unknown_keys_are_rejected(tmp_path):
    (tmp_path / ".qeos.yml").write_text("api-key: qeos_nope\n", encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        load_config(str(tmp_path))
    assert "api-key" in str(err.value)


def test_broken_yaml_is_a_config_error(tmp_path):
    (tmp_path / ".qeos.yml").write_text("url: a\n  dangling:\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(tmp_path))


def test_a_file_that_is_not_utf8_is_a_config_error(tmp_path):
    (tmp_path / ".qeos.yml").write_bytes(b"url: https://q\xff\n")
    with pytest.raises(ConfigError, match="not UTF-8 text"):
        load_config(str(tmp_path))
