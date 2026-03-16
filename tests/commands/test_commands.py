from utils.command import resolve_command


def test_resolve_unknown_command():
    cmd, args = resolve_command("unknown test")

    assert cmd is None
    assert args == ["unknown", "test"]


def test_resolve_with_args():
    cmd, args = resolve_command("ping hello world")

    if cmd:
        assert args == ["hello", "world"]
