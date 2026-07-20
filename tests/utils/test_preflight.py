from __future__ import annotations

import utils.command_docs as command_docs
import utils.preflight as preflight


def test_preflight_command_docs_uses_importable_validator(monkeypatch):
    calls = []

    def fake_validate_command_docs():
        calls.append("validated")
        return [], 121

    monkeypatch.setattr(
        command_docs,
        "validate_command_docs",
        fake_validate_command_docs,
    )

    ok, message = preflight._check_command_docs()

    assert ok is True
    assert message == "command docs: ok (121 commands)"
    assert calls == ["validated"]


def test_preflight_command_docs_reports_validation_errors(monkeypatch):
    def fake_validate_command_docs():
        return ["docs missing", "metadata missing", "usage missing", "extra"], 120

    monkeypatch.setattr(
        command_docs,
        "validate_command_docs",
        fake_validate_command_docs,
    )

    ok, message = preflight._check_command_docs()

    assert ok is False
    assert "docs missing" in message
    assert "metadata missing" in message
    assert "usage missing" in message
    assert "4 errors" in message
