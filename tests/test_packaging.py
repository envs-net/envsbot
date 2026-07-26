from email.parser import Parser
import tomllib
import runpy
from pathlib import Path

from setuptools.build_meta import prepare_metadata_for_build_wheel


def test_setuptools_package_discovery_covers_split_packages():
    """Wheel builds must include split plugin/core/config subpackages."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    find_config = pyproject["tool"]["setuptools"]["packages"]["find"]

    assert set(find_config["include"]) >= {
        "bot*",
        "core_plugins*",
        "plugins*",
        "database*",
        "utils*",
    }
    assert "data*" not in set(find_config.get("exclude", []))


def test_package_version_is_sourced_from_runtime_code(tmp_path):
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    runtime_version = runpy.run_path("utils/version.py")["__version__"]

    assert "version" not in pyproject["project"]
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "utils.version.__version__",
    }

    dist_info_name = prepare_metadata_for_build_wheel(str(tmp_path))
    metadata = (tmp_path / dist_info_name / "METADATA").read_text(
        encoding="utf-8"
    )

    assert Parser().parsestr(metadata)["Version"] == runtime_version
