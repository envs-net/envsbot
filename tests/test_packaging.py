from __future__ import annotations

import runpy
import stat
import tomllib
from pathlib import Path


_TEST_ROOT = Path(__file__).resolve().parents[1]


def _checkout_root(path: Path) -> Path:
    """Return the real checkout when tests run from mutmut's copy."""
    if path.name == "mutants":
        checkout = path.parent
        if (checkout / "pyproject.toml").is_file():
            return checkout
    return path


ROOT = _checkout_root(_TEST_ROOT)


def test_checkout_root_uses_repository_outside_mutmut_copy(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    mutants = tmp_path / "mutants"
    mutants.mkdir()

    assert _checkout_root(mutants) == tmp_path
    assert _checkout_root(tmp_path) == tmp_path


def test_setuptools_package_discovery_covers_split_packages():
    """Wheel builds must include split plugin/core/config subpackages."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
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
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_version = runpy.run_path(ROOT / "utils/version.py")["__version__"]

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
    for config_path in (ROOT / ".github/workflows/quality.yml", ROOT / ".drone.yml"):
        text = config_path.read_text(encoding="utf-8")
        references.extend(
            token.strip('"\'')
            for token in text.replace("\n", " ").split()
            if token.startswith("constraints/") and token.endswith(".txt")
        )

    assert references
    missing = sorted(path for path in set(references) if not (ROOT / path).is_file())
    assert missing == []


def test_constraint_snapshots_are_exact_and_transitive():
    """Snapshots should be full exact locks, not a copy of direct requirements."""
    for path in (ROOT / "constraints/python312.txt", ROOT / "constraints/python313.txt"):
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

    assert "pyyaml==6.0.3" in (
        ROOT / "constraints/python312.txt"
    ).read_text(encoding="utf-8").lower()
    assert "pyyaml-ft==8.0.0" in (
        ROOT / "constraints/python313.txt"
    ).read_text(encoding="utf-8").lower()


def test_ci_verifies_constraint_dependency_closure():
    github = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    drone = (ROOT / ".drone.yml").read_text(encoding="utf-8")

    assert "python scripts/check_constraints.py ${{ matrix.constraints }}" in github
    assert "python scripts/check_constraints.py constraints/python312.txt" in drone
    assert "python scripts/check_constraints.py constraints/python313.txt" in drone


def test_ci_invokes_quality_script_via_shell():
    github = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    drone = (ROOT / ".drone.yml").read_text(encoding="utf-8")

    assert "run: sh scripts/quality.sh" in github
    assert drone.count("- sh scripts/quality.sh") == 2
    assert "./scripts/quality.sh" not in github
    assert "./scripts/quality.sh" not in drone


def test_operator_shell_scripts_are_executable():
    for relative_path in (
        "scripts/deploy.sh",
        "scripts/quality.sh",
        "scripts/mutmut.sh",
        "scripts/update-constraints.sh",
    ):
        mode = (ROOT / relative_path).stat().st_mode
        assert mode & stat.S_IXUSR, f"{relative_path} must be executable"


def test_github_actions_use_node24_generations():
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow


def test_aiohttp_security_floor_and_locks():
    """Known-vulnerable aiohttp releases must not re-enter supported installs."""
    requirement = "aiohttp>=3.14.3,<4"
    assert requirement in (ROOT / "requirements.txt").read_text(encoding="utf-8")

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert requirement in pyproject["project"]["dependencies"]

    for path in (ROOT / "constraints/python312.txt", ROOT / "constraints/python313.txt"):
        assert "aiohttp==3.14.3" in path.read_text(encoding="utf-8").lower()


def test_quality_audits_exact_lock_without_no_deps_warning():
    """The full lock can be resolved normally, avoiding pip-audit no-deps warnings."""
    quality = (ROOT / "scripts/quality.sh").read_text(encoding="utf-8")

    assert 'pip-audit -r "$constraint_file"' in quality
    assert "--no-deps" not in quality


def test_wheel_packages_runtime_defaults_inside_utils():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert "data-files" not in pyproject["tool"]["setuptools"]
    assert set(package_data["utils"]) >= {"bundled/*.csv", "bundled/*.jpg"}

    bundled_dir = ROOT / "utils/bundled"
    assert (bundled_dir / "init_chat_slang.csv").is_file()
    assert (bundled_dir / "avatar.jpg").is_file()

    # Defaults have one canonical repository copy.  A second root copy could
    # silently drift from the asset shipped in wheels.
    assert not (ROOT / "init_chat_slang.csv").exists()
    assert not (ROOT / "avatar.jpg").exists()


def test_mutmut_does_not_copy_removed_root_asset():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    also_copy = set(pyproject["tool"]["mutmut"].get("also_copy", []))

    assert "init_chat_slang.csv" not in also_copy
    assert "avatar.jpg" not in also_copy


def test_ci_installs_and_smoke_tests_built_wheel():
    github = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    drone = (ROOT / ".drone.yml").read_text(encoding="utf-8")

    assert "python scripts/check_wheel.py" in github
    assert drone.count("python scripts/check_wheel.py") == 2
