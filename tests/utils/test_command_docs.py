from __future__ import annotations

from pathlib import Path

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
