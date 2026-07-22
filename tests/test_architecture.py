"""Regression checks for package ownership and explicit module boundaries."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path


_TEST_ROOT = Path(__file__).resolve().parents[1]


def _checkout_root(path: Path) -> Path:
    """Return the real checkout when tests run from mutmut's copy.

    mutmut instruments production files below ``<repo>/mutants`` and copies
    the tests there.  Static architecture checks must inspect the original
    source tree rather than mutmut's generated trampoline functions, which
    intentionally contain incomplete call variants for individual mutants.
    """
    if path.name == "mutants":
        checkout = path.parent
        if (checkout / "pyproject.toml").exists():
            return checkout
    return path


ROOT = _checkout_root(_TEST_ROOT)
PRODUCTION_ROOTS = ("bot", "core_plugins", "database", "plugins", "scripts", "utils")


def test_checkout_root_uses_repository_outside_mutmut_copy(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    mutants = tmp_path / "mutants"
    mutants.mkdir()

    assert _checkout_root(mutants) == tmp_path
    assert _checkout_root(tmp_path) == tmp_path


def _production_python_files():
    for package in PRODUCTION_ROOTS:
        yield from (ROOT / package).rglob("*.py")
    yield ROOT / "envsbot.py"


def test_split_packages_do_not_inject_namespaces():
    offenders: list[str] = []
    for path in _production_python_files():
        source = path.read_text(encoding="utf-8")
        if "vars(_part).update" in source or "__setattr__" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_bot_and_utils_do_not_depend_on_rooms_plugin():
    offenders: list[str] = []
    for package in ("bot", "utils"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "core_plugins.rooms":
                    offenders.append(str(path.relative_to(ROOT)))
                elif isinstance(node, ast.Import):
                    if any(alias.name == "core_plugins.rooms" for alias in node.names):
                        offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_preflight_uses_library_validator_not_cli_script():
    source = (ROOT / "utils" / "preflight.py").read_text(encoding="utf-8")
    assert "scripts.check_command_docs" not in source
    assert "utils.command_docs" in source


def test_removed_duplicate_helper_modules_stay_removed():
    assert not (ROOT / "utils" / "room_toggles.py").exists()
    assert not (ROOT / "utils" / "xmpp_identity.py").exists()


def test_tls_certificate_network_logic_is_shared_by_both_plugins():
    utility = ROOT / "utils" / "tls_certificate.py"
    assert utility.exists()
    for relative_path in ("plugins/xmpp.py", "plugins/tools.py"):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "from utils.tls_certificate import" in source
        assert "asyncio.open_connection" not in source
        assert ".start_tls(" not in source


def test_split_store_modules_contain_no_commands_or_event_handlers():
    for relative_path in ("plugins/reminder/store.py", "plugins/vcard/store.py"):
        path = ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        function_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not any(name.startswith(("cmd_", "on_")) for name in function_names)
        assert "@command" not in path.read_text(encoding="utf-8")


def test_cross_plugin_imports_are_declared_as_dependencies():
    expected = {
        "core_plugins.doctor": {"rooms"},
        "core_plugins.help": {"_core", "rooms"},
        "core_plugins.presence": {"_core"},
        "core_plugins.users": {"rooms"},
        "plugins.birthday_notify": {"rooms", "_core", "vcard"},
        "plugins.dice": {"_core"},
        "plugins.karma": {"rooms", "_core", "sed"},
        "plugins.pin": {"rooms", "_core", "users"},
        "plugins.poll": {"rooms", "_core", "users"},
        "plugins.rss": {"rooms", "_core", "users"},
    }

    for module_name, dependencies in expected.items():
        metadata = import_module(module_name).PLUGIN_META
        assert dependencies <= set(metadata.get("requires", [])), module_name


def test_plugin_categories_match_help_grouping():
    expected = {
        "core_plugins._core": "core",
        "plugins.birthday_notify": "info",
        "plugins.ducks": "games",
        "plugins.idlerpg": "games",
    }

    for module_name, category in expected.items():
        metadata = import_module(module_name).PLUGIN_META
        assert metadata["category"] == category, module_name


def test_room_toggle_commands_declare_registered_plugin_name():
    offenders: list[str] = []
    for package in ("core_plugins", "plugins"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else ""
                )
                if name != "handle_room_toggle_command":
                    continue
                keywords = {item.arg for item in node.keywords}
                if "plugin" not in keywords:
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}"
                    )

    assert offenders == []
