from __future__ import annotations

from pathlib import Path

from utils import command_docs
from utils.command_docs import (
    _checkout_root,
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
    assert "- `,rss add https://example.org/feed.rss`" in rss_doc


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
