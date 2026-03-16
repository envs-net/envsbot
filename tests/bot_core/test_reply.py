from unittest.mock import MagicMock


def test_reply_private(bot, xmpp_msg):

    xmpp_msg["type"] = "chat"

    bot.make_message.return_value = MagicMock()

    bot.reply(xmpp_msg, "hello")

    assert bot.make_message.called


def test_reply_groupchat_mention(bot, xmpp_msg):

    xmpp_msg["type"] = "groupchat"
    xmpp_msg["mucnick"] = "Alice"

    message = MagicMock()
    bot.make_message.return_value = message

    bot.reply(xmpp_msg, "hello")

    args = bot.make_message.call_args[1]

    assert "Alice:" in args["mbody"]
