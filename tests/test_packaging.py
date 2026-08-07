import tomllib
import runpy
from pathlib import Path


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


def test_package_version_is_sourced_from_runtime_code():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    runtime_version = runpy.run_path("utils/version.py")["__version__"]

    assert "version" not in pyproject["project"]
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "utils.version.__version__",
    }
    assert isinstance(runtime_version, str)
    assert runtime_version.strip() == runtime_version
    assert runtime_version


def test_ci_constraint_files_exist():
    """CI must only reference checked-in dependency constraint snapshots."""
    references = []
    for config_path in (Path(".github/workflows/quality.yml"), Path(".drone.yml")):
        text = config_path.read_text(encoding="utf-8")
        references.extend(
            token.strip('"\'')
            for token in text.replace("\n", " ").split()
            if token.startswith("constraints/") and token.endswith(".txt")
        )

    assert references
    missing = sorted(path for path in set(references) if not Path(path).is_file())
    assert missing == []
