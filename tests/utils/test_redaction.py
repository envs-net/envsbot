from __future__ import annotations

from utils.redaction import REDACTED, redact_text, redact_value


def test_redact_value_preserves_container_shapes():
    data = {
        "password": "secret",
        "items": ["https://user:pass@example.org/path", {"token": "abc"}],
        "coords": ("x", "y"),
        "tags": {"alpha", "beta"},
    }

    redacted = redact_value(data)

    assert redacted["password"] == REDACTED
    assert redacted["items"] == ["https://example.org/path", {"token": REDACTED}]
    assert redacted["coords"] == ("x", "y")
    assert redacted["tags"] == {"alpha", "beta"}
    assert isinstance(redacted["tags"], set)


def test_redact_text_redacts_assignments_but_not_plain_key_names():
    assert redact_text("password=secret token=abc") == "password=<redacted> token=<redacted>"
    assert redact_text("secret") == "secret"
    assert redact_text("token") == "token"


class HashableDict(dict):
    __hash__ = object.__hash__


def test_redact_value_set_falls_back_for_unhashable_redacted_items():
    redacted = redact_value({HashableDict({"token": "abc"})})

    assert isinstance(redacted, set)
    assert redacted == {"{'token': '<redacted>'}"}


def test_redact_value_redacts_secret_assignments_in_strings():
    assert redact_value("token=abc") == "token=<redacted>"
    assert redact_value("https://user:pass@example.org/path") == "https://example.org/path"
    assert redact_value("secret") == "secret"
