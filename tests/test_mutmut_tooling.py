import importlib.util
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path


def _checkout_root(path: Path) -> Path:
    """Return the real checkout when tests run from mutmut's copy."""
    resolved = path.resolve()
    search_from = resolved if resolved.is_dir() else resolved.parent
    for candidate in (search_from, *search_from.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "scripts" / "mutmut.sh").is_file()
        ):
            return candidate
    return search_from


ROOT = _checkout_root(Path(__file__))


def test_checkout_root_uses_repository_outside_mutmut_copy(tmp_path):
    repo = tmp_path / "repo"
    mutants_test = repo / "mutants" / "tests" / "test_example.py"
    (repo / "scripts").mkdir(parents=True)
    mutants_test.parent.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (repo / "scripts" / "mutmut.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    assert _checkout_root(mutants_test) == repo
    assert _checkout_root(repo) == repo


def _load_test_conftest():
    path = ROOT / "tests/conftest.py"
    spec = importlib.util.spec_from_file_location("envsbot_test_conftest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_wrapper(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / "mutmut.sh"
    shutil.copy2(ROOT / "scripts/mutmut.sh", wrapper)
    wrapper.chmod(0o755)
    return wrapper


def test_mutmut_pythonpath_guard_detects_original_checkout(tmp_path):
    helper = _load_test_conftest()._mutmut_pythonpath_conflicts
    root = tmp_path / "repo"
    mutants = root / "mutants"
    mutants.mkdir(parents=True)

    value = os.pathsep.join((str(root), "/some/other/path"))

    assert helper(mutants, value) == [str(root)]


def test_mutmut_pythonpath_guard_allows_normal_test_run(tmp_path):
    helper = _load_test_conftest()._mutmut_pythonpath_conflicts
    root = tmp_path / "repo"
    root.mkdir()

    assert helper(root, str(root)) == []
    assert helper(root / "mutants", None) == []


def test_mutmut_wrapper_unsets_pythonpath_before_exec(tmp_path):
    wrapper = _copy_wrapper(tmp_path)
    repo = wrapper.parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    output = tmp_path / "output.txt"
    fake_mutmut = fake_bin / "mutmut"
    fake_mutmut.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"${{PYTHONPATH-unset}}|$*\" > {output}\n",
        encoding="utf-8",
    )
    fake_mutmut.chmod(0o755)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    subprocess.run(
        [str(wrapper), "run", "plugins.pin*"],
        check=True,
        cwd=repo,
        env=env,
    )

    assert output.read_text(encoding="utf-8").strip() == "unset|run plugins.pin*"


def test_mutmut_wrapper_fresh_removes_cached_tree(tmp_path):
    wrapper = _copy_wrapper(tmp_path)
    repo = wrapper.parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    output = tmp_path / "output.txt"
    fake_mutmut = fake_bin / "mutmut"
    fake_mutmut.write_text(
        "#!/bin/sh\n"
        f"printf '%s' \"$*\" > {output}\n",
        encoding="utf-8",
    )
    fake_mutmut.chmod(0o755)

    mutants = repo / "mutants"
    marker = mutants / ".wrapper-test-marker"
    mutants.mkdir()
    marker.write_text("stale", encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    subprocess.run(
        [str(wrapper), "fresh"],
        check=True,
        cwd=repo,
        env=env,
    )

    assert not mutants.exists()
    assert output.read_text(encoding="utf-8") == "run"


def test_docs_do_not_recommend_repository_pythonpath_for_mutmut():
    docs = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in ("README.md", "tests/README.md", "docs/release-checklist.md")
    )

    assert 'PYTHONPATH="$PWD" mutmut' not in docs
    assert "./scripts/mutmut.sh" in docs


def test_mutmut_targets_only_covered_lines_and_skips_logging_noise():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    config = pyproject["tool"]["mutmut"]

    assert config["mutate_only_covered_lines"] is True

    patterns = [re.compile(pattern) for pattern in config["do_not_mutate_patterns"]]
    for logging_call in (
        'log.info("connected")',
        '_dep_config.log.exception("failed")',
        'logger.warning("slow")',
    ):
        assert any(pattern.search(logging_call) for pattern in patterns)

    # User-visible and semantic strings must remain in the mutation surface.
    for semantic_line in (
        'return "warning"',
        'await bot.reply(msg, "failed")',
        'state["status"] = "healthy"',
    ):
        assert not any(pattern.search(semantic_line) for pattern in patterns)
