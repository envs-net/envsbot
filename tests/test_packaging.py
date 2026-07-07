import tomllib
from pathlib import Path


def test_setuptools_package_discovery_covers_split_packages():
    """Wheel builds must include split plugin/core/config subpackages."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    find_config = pyproject["tool"]["setuptools"]["packages"]["find"]

    assert set(find_config["include"]) >= {
        "core_plugins*",
        "plugins*",
        "database*",
        "utils*",
    }
    assert "data*" not in set(find_config.get("exclude", []))
