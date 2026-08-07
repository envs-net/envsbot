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


def test_constraint_snapshots_are_exact_and_transitive():
    """Snapshots should be full exact locks, not a copy of direct requirements."""
    for path in (Path("constraints/python312.txt"), Path("constraints/python313.txt")):
        pins = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            assert line.count("==") == 1, f"non-exact constraint in {path}: {line}"
            name, version = line.split("==", 1)
            assert name.strip()
            assert version.strip()
            pins.append(name.lower())

        assert len(pins) >= 70
        assert len(pins) == len(set(pins))

    assert "pyyaml==6.0.3" in Path("constraints/python312.txt").read_text(encoding="utf-8").lower()
    assert "pyyaml-ft==8.0.0" in Path("constraints/python313.txt").read_text(encoding="utf-8").lower()


def test_ci_verifies_constraint_dependency_closure():
    github = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    drone = Path(".drone.yml").read_text(encoding="utf-8")

    assert "python scripts/check_constraints.py ${{ matrix.constraints }}" in github
    assert "python scripts/check_constraints.py constraints/python312.txt" in drone
    assert "python scripts/check_constraints.py constraints/python313.txt" in drone


def test_github_actions_use_node24_generations():
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow


def test_aiohttp_security_floor_and_locks():
    """Known-vulnerable aiohttp releases must not re-enter supported installs."""
    requirement = "aiohttp>=3.14.3,<4"
    assert requirement in Path("requirements.txt").read_text(encoding="utf-8")

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert requirement in pyproject["project"]["dependencies"]

    for path in (Path("constraints/python312.txt"), Path("constraints/python313.txt")):
        assert "aiohttp==3.14.3" in path.read_text(encoding="utf-8").lower()
