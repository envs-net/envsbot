import asyncio
import os
from pathlib import Path

import pytest


def _mutmut_pythonpath_conflicts(
    cwd: Path,
    pythonpath: str | None,
) -> list[str]:
    """Return PYTHONPATH entries that shadow mutmut's generated checkout."""
    if cwd.name != "mutants" or not pythonpath:
        return []

    source_root = cwd.parent.resolve()
    conflicts: list[str] = []
    for raw_entry in pythonpath.split(os.pathsep):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            resolved = Path(entry).expanduser().resolve()
        except OSError:
            continue
        if resolved == source_root:
            conflicts.append(entry)
    return conflicts


def pytest_sessionstart(session):
    """Reject mutmut runs that would import the original source checkout."""
    conflicts = _mutmut_pythonpath_conflicts(
        Path.cwd().resolve(),
        os.environ.get("PYTHONPATH"),
    )
    if not conflicts:
        return

    pytest.exit(
        "Invalid mutmut environment: PYTHONPATH points at the original "
        "repository while pytest is running from ./mutants. This can make "
        "mutations appear to survive without testing them. Run "
        "'./scripts/mutmut.sh fresh' (or unset PYTHONPATH and run mutmut).",
        returncode=2,
    )


@pytest.fixture(scope='session')
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def tmp_db_path(tmp_path):
    db_path = tmp_path / "test_db.sqlite"
    yield str(db_path)
    try:
        os.remove(db_path)
    except OSError:
        # The temporary file may already be removed by the test or fixture cleanup.
        return


@pytest.fixture
def clean_config(monkeypatch, tmp_path):
    # Set up env vars or config as needed before tests run.
    cfg_path = tmp_path / "config.py"
    cfg_path.write_text(
        "\n".join([
            'JID = "testbot@example.tld"',
            'PASSWORD = "Passw0rd"',
            'NICK = "testbot"',
            'TIMEZONE = "US/Alaska"',
            'OWNER = "owner@example.tld"',
            'YOUTUBE_API_KEY = "ToP53cRetPassw0rd"',
            'COMMAND_PREFIX = "+"',
            'DB_FILE = "bot_test.db"',
            'LOG_LEVEL = "INFO"',
            'USERS = {"max_room_nicks": 5}',
            'AVATAR_PATH = "avatar.jpg"',
            'AVATAR_TYPE = "image/jpeg"',
            'REMINDER_MAX_AGE_DAYS = 365',
        ])
    )
    monkeypatch.setenv("ENVSBOT_CONFIG", str(cfg_path))
    yield cfg_path
