from __future__ import annotations

from utils.command_docs import generate_plugin_docs, validate_command_docs


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
