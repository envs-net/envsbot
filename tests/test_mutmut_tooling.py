import importlib.util
import json
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


def _install_fake_python(fake_bin: Path) -> None:
    fake_python = fake_bin / "python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)


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
    _install_fake_python(fake_bin)
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
    _install_fake_python(fake_bin)
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



def test_mutmut_release_gate_uses_curated_deterministic_scope():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    config = pyproject["tool"]["mutmut"]

    assert config["source_paths"] == [
        "bot/routing.py",
        "core_plugins/help/formatting.py",
        "database/message_cache.py",
        "plugins/translate.py",
        "plugins/weather.py",
        "utils/plugin_manager.py",
        "utils/plugin_manager_runtime.py",
        "utils/plugin_manager_inspection.py",
        "utils/plugin_manager_lifecycle.py",
    ]
    assert config["pytest_add_cli_args_test_selection"] == [
        "tests/bot/test_envsbot.py",
        "tests/core_plugins/test_help.py",
        "tests/database/test_message_cache.py",
        "tests/plugins/test_translate.py",
        "tests/plugins/test_weather.py",
        "tests/utils/test_command_help.py",
        "tests/utils/test_plugin_manager.py",
    ]

    # These paths are covered by the normal pytest/coverage gate but are kept
    # out of the release mutation gate because the full-repo audit showed
    # large numbers of timeout mutants in long-running/background workflows.
    assert "utils/message_cache.py" not in config["source_paths"]
    assert "plugins/idlerpg/commands.py" not in config["source_paths"]
    assert "utils/config/runtime.py" not in config["source_paths"]


def test_mutmut_version_pin_matches_regression_baseline():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = tuple(pyproject["project"]["optional-dependencies"]["dev"])
    pin = next(requirement for requirement in dev if requirement.startswith("mutmut=="))
    baseline = json.loads((ROOT / "tests/regression-baseline.json").read_text(encoding="utf-8"))

    assert pin == "mutmut==3.6.0"
    assert baseline["mutation"]["mutmut_version"] == pin.removeprefix("mutmut==")
    assert (ROOT / "scripts/mutmut.sh").read_text(encoding="utf-8").count("mutation-tool-check") == 2


def test_mutmut_wrapper_dispatches_regression_commands(tmp_path):
    wrapper = _copy_wrapper(tmp_path)
    repo = wrapper.parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    output = tmp_path / "python-args.txt"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/bin/sh\n"
        f"printf '%s' \"$*\" > {output}\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    for command, expected in (
        ("check", "-m envs_xmpp_ops.regression mutation-check"),
        ("accept", "-m envs_xmpp_ops.regression mutation-accept"),
    ):
        subprocess.run([str(wrapper), command], check=True, cwd=repo, env=env)
        assert output.read_text(encoding="utf-8") == expected
