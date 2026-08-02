from __future__ import annotations

from types import SimpleNamespace

from utils import command_docs
from utils.command import Role
from utils.command_docs import (
    _checkout_root,
    generate_plugin_doc,
    generate_plugin_docs,
    validate_command_docs,
)


def test_checkout_root_uses_repository_outside_mutmut_copy(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    mutants = tmp_path / "mutants"
    mutants.mkdir()

    orphan_mutants = tmp_path / "orphan" / "mutants"

    assert _checkout_root(mutants) == tmp_path
    assert _checkout_root(tmp_path) == tmp_path
    assert _checkout_root(orphan_mutants) == orphan_mutants


def test_checked_in_command_docs_match_generator():
    errors, command_count = validate_command_docs()

    assert errors == []
    assert command_count > 0


def test_generated_rss_docs_include_direct_and_filtered_list_guidance():
    rss_doc = generate_plugin_docs()["rss.md"]

    assert "## Direct subscriptions" in rss_doc
    assert "`,rss list rooms`" in rss_doc
    assert "`,rss list mods`" in rss_doc
    assert "`,rss list trusted`" in rss_doc
    assert "`,rss list own [page|all|last]`" in rss_doc
    assert "The bot recognizes the 1:1 destination automatically" in rss_doc
    assert "never stored as part of the template" in rss_doc
    assert "placeholder text such as `MEINE_JID` is ignored" in rss_doc
    assert ",rss remove all <user-jid>" in rss_doc
    assert "## Fetch retries and startup behavior" in rss_doc
    assert "RSS_STARTUP_STAGGER_SECONDS" in rss_doc
    assert "RSS_FETCH_TIMEOUT_SECONDS" in rss_doc
    assert "DIRECT $title" not in rss_doc
    assert "- `,rss add https://example.org/feed.rss`" in rss_doc
    assert "`,rss delete all user@example.org`" in rss_doc




def test_generated_idlerpg_docs_group_player_and_admin_commands():
    idlerpg_doc = generate_plugin_docs()["idlerpg.md"]

    assert "##### Player commands" in idlerpg_doc
    assert "##### Room owner/admin commands" in idlerpg_doc
    assert idlerpg_doc.index("##### Player commands") < idlerpg_doc.index(
        "##### Room owner/admin commands"
    )
    assert "`,idlerpg register <character> <class>`" in idlerpg_doc
    assert "`,idlerpg season reset`" in idlerpg_doc
    assert "`,idlerpg season discard confirm`" in idlerpg_doc


def test_write_generated_docs_writes_exact_utf8_files(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    (root / "docs").mkdir(parents=True)
    plugin_docs = tmp_path / "existing" / "plugins"
    plugin_docs.mkdir(parents=True)
    overview = "Übersicht\n"
    generated = {
        "alpha.md": "Älpha\n",
        "beta.md": "Béta\n",
    }
    monkeypatch.setattr(command_docs, "ROOT", root)
    monkeypatch.setattr(command_docs, "PLUGIN_DOCS_DIR", plugin_docs)
    monkeypatch.setattr(command_docs, "generate", lambda: overview)
    monkeypatch.setattr(command_docs, "generate_plugin_docs", lambda: generated)

    written = command_docs.write_generated_docs()

    expected = [
        root / "docs" / "commands.md",
        plugin_docs / "alpha.md",
        plugin_docs / "beta.md",
    ]
    assert written == expected
    assert expected[0].read_bytes() == overview.encode("utf-8")
    assert expected[1].read_bytes() == generated["alpha.md"].encode("utf-8")
    assert expected[2].read_bytes() == generated["beta.md"].encode("utf-8")
    assert sorted(path.name for path in plugin_docs.iterdir()) == [
        "alpha.md",
        "beta.md",
    ]


def test_write_generated_docs_creates_nested_plugin_directory(monkeypatch, tmp_path):
    root = tmp_path / "checkout"
    (root / "docs").mkdir(parents=True)
    plugin_docs = tmp_path / "missing" / "nested" / "plugins"
    monkeypatch.setattr(command_docs, "ROOT", root)
    monkeypatch.setattr(command_docs, "PLUGIN_DOCS_DIR", plugin_docs)
    monkeypatch.setattr(command_docs, "generate", lambda: "commands\n")
    monkeypatch.setattr(
        command_docs,
        "generate_plugin_docs",
        lambda: {"only.md": "plugin\n"},
    )

    written = command_docs.write_generated_docs()

    assert plugin_docs.is_dir()
    assert written == [
        root / "docs" / "commands.md",
        plugin_docs / "only.md",
    ]
    assert (plugin_docs / "only.md").read_text(encoding="utf-8") == "plugin\n"


def test_generate_plugin_doc_renders_structured_help_and_described_examples():
    cmd = SimpleNamespace(
        name="rooms invite",
        role=Role.ADMIN,
        aliases=[],
        short="Manage pending room invitations.",
        usage="{prefix}rooms invite <list|delete>",
        examples=["{prefix}rooms invite list"],
        subcommands=[
            {
                "name": "delete",
                "usage": "{prefix}rooms invite delete <id>",
                "short": "Delete a pending invitation.",
                "aliases": ["del", "remove", "rm"],
                "examples": [
                    {
                        "command": "{prefix}rooms invite delete 7",
                        "description": "Delete pending invitation 7.",
                    }
                ],
                "role": Role.ADMIN,
                "context": "private chat / MUC PM",
            }
        ],
        category="admin",
        context="private chat / MUC PM",
    )
    meta = {
        "name": "rooms",
        "source": "core",
        "category": "core",
        "description": "Manage rooms.",
    }

    generated = generate_plugin_doc("rooms", meta, [cmd])

    assert "#### Subcommands" in generated
    assert "- `,rooms invite delete <id>`" in generated
    assert "Description: Delete a pending invitation." in generated
    assert "Aliases: `,rooms invite del`, `,rooms invite remove`, `,rooms invite rm`" in generated
    assert "`,rooms invite delete 7` — Delete pending invitation 7." in generated


def test_generated_plugin_docs_start_with_overview_sections():
    plugin_docs = generate_plugin_docs()

    assert plugin_docs
    detailed_docs = {name: text for name, text in plugin_docs.items() if name != "README.md"}
    assert detailed_docs
    assert all("\n## Overview\n" in text for text in detailed_docs.values())


def test_generated_ducks_docs_include_room_profiles_and_overrides():
    ducks_doc = generate_plugin_docs()["ducks.md"]

    assert "## Duck pacing and configuration" in ducks_doc
    assert "### Example for a small or quiet room" in ducks_doc
    assert "### Example for a large or very active room" in ducks_doc
    assert '"min_messages": 150' in ducks_doc
    assert '"min_messages": 40' in ducks_doc
    assert '"min_messages": 500' in ducks_doc
    assert "`,duck config set min_messages 40`" in ducks_doc
    assert "`,duck config reset`" in ducks_doc
    assert "state_save_every" in ducks_doc
    assert "cannot be overridden per room" in ducks_doc
