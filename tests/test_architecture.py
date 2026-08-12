"""Regression checks for package ownership and explicit module boundaries."""

from __future__ import annotations

import ast
import re
from importlib import import_module
from pathlib import Path

from utils.plugin_manager_dependencies import topological_sort


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


def _discover_plugin_modules() -> dict[str, str]:
    modules: dict[str, str] = {}
    for package in ("core_plugins", "plugins"):
        package_root = ROOT / package
        for path in package_root.iterdir():
            if path.name.startswith("__"):
                continue
            if path.is_file() and path.suffix == ".py":
                modules.setdefault(path.stem, f"{package}.{path.stem}")
            elif path.is_dir() and (path / "__init__.py").exists():
                modules.setdefault(path.name, f"{package}.{path.name}")
    return modules


def test_complete_plugin_dependency_graph_is_valid_and_acyclic():
    modules = _discover_plugin_modules()
    metadata = {
        name: import_module(module_name).PLUGIN_META
        for name, module_name in modules.items()
    }

    errors: list[str] = []
    for name, meta in metadata.items():
        requires = list(meta.get("requires", []) or [])
        if len(requires) != len(set(requires)):
            errors.append(f"{name}: duplicate dependencies")
        if name in requires:
            errors.append(f"{name}: depends on itself")
        for dependency in requires:
            if dependency not in modules:
                errors.append(f"{name}: unknown dependency {dependency}")

    assert errors == []

    order = topological_sort(metadata, modules)
    positions = {name: index for index, name in enumerate(order)}
    for name, meta in metadata.items():
        for dependency in meta.get("requires", []) or []:
            assert positions[dependency] < positions[name], (
                f"{dependency} must load before {name}"
            )


def test_all_absolute_cross_plugin_imports_are_declared():
    modules = _discover_plugin_modules()
    metadata = {
        name: import_module(module_name).PLUGIN_META
        for name, module_name in modules.items()
    }
    offenders: list[str] = []

    for package in ("core_plugins", "plugins"):
        package_root = ROOT / package
        for path in package_root.rglob("*.py"):
            relative = path.relative_to(package_root)
            owner = relative.parts[0]
            if owner.endswith(".py"):
                owner = owner[:-3]
            if owner == "__init__":
                continue

            declared = set(metadata.get(owner, {}).get("requires", []) or [])
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported_plugins: set[str] = set()
            for node in ast.walk(tree):
                module_names: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_names.append(node.module)
                elif isinstance(node, ast.Import):
                    module_names.extend(alias.name for alias in node.names)
                for module_name in module_names:
                    parts = module_name.split(".")
                    if len(parts) >= 2 and parts[0] in {"core_plugins", "plugins"}:
                        dependency = parts[1]
                        if dependency != owner:
                            imported_plugins.add(dependency)

            for dependency in sorted(imported_plugins - declared):
                offenders.append(
                    f"{path.relative_to(ROOT)}: imports {dependency} "
                    "without declaring it"
                )

    assert offenders == []


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


def _decorated_command_aliases(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    commands: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            func_name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if func_name != "command" or not decorator.args:
                continue
            primary = decorator.args[0]
            if not isinstance(primary, ast.Constant) or not isinstance(
                primary.value, str
            ):
                continue
            aliases: set[str] = set()
            for keyword in decorator.keywords:
                if keyword.arg != "aliases" or not isinstance(
                    keyword.value, (ast.List, ast.Tuple)
                ):
                    continue
                aliases.update(
                    item.value
                    for item in keyword.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
            commands[primary.value] = aliases
    return commands


def _string_membership_sets(path: Path, variable_name: str) -> list[set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.left, ast.Name) or node.left.id != variable_name:
            continue
        if not isinstance(node.ops[0], ast.In) or len(node.comparators) != 1:
            continue
        comparator = node.comparators[0]
        if not isinstance(comparator, (ast.Set, ast.List, ast.Tuple)):
            continue
        literals = {
            item.value
            for item in comparator.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        values.append(literals)
    return values


def _dict_string_keys_for_named_value(path: Path, value_name: str) -> set[str]:
    """Return literal dict keys that map directly to one named handler."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Name)
                and value.id == value_name
            ):
                continue
            keys.add(key.value)
    return keys

def test_add_capable_resource_commands_keep_standard_removal_aliases():
    removal_words = {"delete", "del", "remove", "rm"}

    decorated_add_commands: set[str] = set()
    for package in ("core_plugins", "plugins"):
        for path in (ROOT / package).rglob("*.py"):
            decorated_add_commands.update(
                name
                for name in _decorated_command_aliases(path)
                if name.split()[-1:] == ["add"]
            )
    assert decorated_add_commands == {"rooms add", "acronyms add"}

    add_subcommand_comparisons: set[tuple[str, str]] = set()
    for package in ("core_plugins", "plugins"):
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(
                path.read_text(encoding="utf-8"), filename=str(path)
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                values = [node.left, *node.comparators]
                if not any(
                    isinstance(value, ast.Constant) and value.value == "add"
                    for value in values
                ):
                    continue
                if isinstance(node.left, ast.Name):
                    add_subcommand_comparisons.add(
                        (str(path.relative_to(ROOT)), node.left.id)
                    )
    assert add_subcommand_comparisons == {
        ("plugins/pin.py", "subcmd"),
    }

    rss_commands = ROOT / "plugins" / "rss" / "commands.py"
    assert _dict_string_keys_for_named_value(
        rss_commands, "_rss_handle_add"
    ) == {"add"}
    assert _dict_string_keys_for_named_value(
        rss_commands, "_rss_handle_delete"
    ) == removal_words

    room_commands = _decorated_command_aliases(
        ROOT / "core_plugins" / "rooms" / "commands.py"
    )
    assert {
        "rooms delete",
        "rooms del",
        "rooms remove",
        "rooms rm",
    } <= ({"rooms delete"} | room_commands["rooms delete"])

    assert removal_words in _string_membership_sets(
        ROOT / "plugins" / "pin.py", "subcmd"
    )

    # Acronym additions use a moderated two-stage workflow: `remove` queues a
    # removal request while admin-only `delete` removes pending queue entries.
    # They are intentionally separate commands rather than aliases.
    info_commands = _decorated_command_aliases(ROOT / "plugins" / "info.py")
    assert "acronyms add" in info_commands
    assert {"acronyms rm"} <= info_commands["acronyms remove"]
    assert {"acronyms del"} <= info_commands["acronyms delete"]


def test_profile_acronym_and_restart_file_io_stays_off_event_loop():
    """Keep small local-file workflows out of asynchronous XMPP handlers."""
    targets = {
        "core_plugins/_reg_profile.py": {
            "update_vcard": {"_load_vcard_xml", "read_hash", "write_hash", "open", "exists"},
            "update_avatar": {"_read_binary_file", "read_hash", "write_hash", "open", "exists"},
        },
        "plugins/info.py": {
            "acronyms_cmd": {"_lookup_acronym_descriptions", "open", "exists"},
            "acronyms_add_cmd": {"_queue_acronym_addition", "open", "exists", "makedirs"},
            "acronyms_remove_cmd": {"_queue_acronym_removal", "open", "exists", "makedirs"},
            "acronyms_list_cmd": {"_pending_acronym_lines", "open", "exists"},
            "acronyms_merge_cmd": {"_merge_pending_acronyms", "open", "exists", "remove"},
            "acronyms_delete_cmd": {"_delete_pending_acronyms", "open", "exists"},
            "get_runtime_state": {"_acronym_runtime_counts", "open", "exists"},
        },
        "core_plugins/_admin.py": {
            "bot_restart": {"_write_private_json", "open", "exists", "replace"},
        },
        "bot/lifecycle.py": {
            "_send_restart_notification": {
                "_consume_restart_notification",
                "open",
                "exists",
                "remove",
            },
        },
    }

    offenders: list[str] = []
    for relative_path, functions in targets.items():
        path = ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        async_functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
        }
        for function_name, disallowed_calls in functions.items():
            node = async_functions[function_name]
            for call in (
                item for item in ast.walk(node) if isinstance(item, ast.Call)
            ):
                name = (
                    call.func.id
                    if isinstance(call.func, ast.Name)
                    else call.func.attr
                    if isinstance(call.func, ast.Attribute)
                    else ""
                )
                if name in disallowed_calls:
                    offenders.append(
                        f"{relative_path}:{call.lineno}:{function_name}:{name}"
                    )

    assert offenders == []


def test_persistence_code_uses_database_manager_api_not_shared_connection():
    """Keep the shared SQLite connection private to DatabaseManager itself."""
    offenders: list[str] = []
    manager_path = ROOT / "database" / "manager.py"
    for path in _production_python_files():
        if path == manager_path:
            continue
        source = path.read_text(encoding="utf-8")
        forbidden = (
            r"\b(?:self\.|bot\.)?db\.conn\b",
            r"\b(?:self\.|bot\.)db\.execute\(",
            r"\bself\.conn\.(?:execute|executemany|commit|rollback)\(",
        )
        if any(re.search(pattern, source) for pattern in forbidden):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def _function_line_span(relative_path: str, function_name: str) -> int:
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return int(node.end_lineno or node.lineno) - int(node.lineno) + 1
    raise AssertionError(f"missing function {relative_path}:{function_name}")


def test_refactored_hot_paths_stay_split_into_small_orchestrators():
    """Prevent the main persistence/command/export routers from growing back."""
    assert _function_line_span("plugins/rss/commands.py", "rss_command") <= 90
    assert _function_line_span("database/idlerpg.py", "save_state") <= 100
    assert _function_line_span("plugins/idlerpg/state.py", "_refresh_public_export") <= 100
    assert _function_line_span("bot/lifecycle.py", "on_start") <= 50
    assert _function_line_span("bot/lifecycle.py", "_shutdown_runtime_once") <= 50


def test_large_command_modules_keep_refactored_boundaries():
    """Keep v1.8 command/deployment splits from collapsing back into monoliths."""
    assert len((ROOT / "plugins/rss/commands.py").read_text(encoding="utf-8").splitlines()) <= 1000
    assert len((ROOT / "scripts/deploy.py").read_text(encoding="utf-8").splitlines()) <= 1400
    assert (ROOT / "plugins/rss/command_support.py").exists()
    assert (ROOT / "plugins/rss/subscriptions.py").exists()
    assert (ROOT / "plugins/rss/templates.py").exists()
    assert (ROOT / "utils/deploy_systemd_values.py").exists()


def test_rss_split_helpers_do_not_register_commands():
    for relative_path in (
        "plugins/rss/command_support.py",
        "plugins/rss/subscriptions.py",
        "plugins/rss/templates.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "@command" not in source
