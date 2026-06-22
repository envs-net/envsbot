import pytest
import os
import asyncio


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
