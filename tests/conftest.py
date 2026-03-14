import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.xmpp_fixtures import MockMessage
from bot import Bot
from command import Role


@pytest.fixture
def mock_config(tmp_path):
    config = tmp_path / "config.json"

    config.write_text("""
{
    "jid": "bot@test.local",
    "password": "test",
    "owner": "owner@test.local",
    "prefix": ",",
    "db": ":memory:"
}
""")

    return str(config)


@pytest.fixture
def bot(mock_config):
    bot = Bot(mock_config)

    # prevent real xmpp actions
    bot.send_message = MagicMock()
    bot.make_message = MagicMock()

    bot.get_user_role = AsyncMock(return_value=Role.OWNER)
    bot.connect = AsyncMock()

    # mock DB
    bot.db.connect = AsyncMock()
    bot.db.close = AsyncMock()

    return bot


@pytest.fixture
def fake_msg():
    msg = {
        "body": "",
        "type": "chat",
        "from": MagicMock(),
        "thread": None,
        "id": "123"
    }

    msg["from"].bare = "user@test.local"
    msg["from"].resource = "resource"

    return msg


@pytest.fixture
def xmpp_msg():
    """
    Provide a realistic mock XMPP message.
    """
    return MockMessage()
