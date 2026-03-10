from command import command


@command("status set", owner_only=True)
async def status_set(bot, sender_jid, nick, args, msg, is_room):
    """
    Set the bot presence status.

    Usage
    -----
    {prefix}status set <show> [message]

    Parameters
    ----------
    show
        Presence type. Supported values:
        online, chat, away, xa, dnd - (xa: extended away; dnd: Do not disturb)

    message (optional)
        Status text displayed by the bot.

    Examples
    --------
    {prefix}status set away
    {prefix}status set away Out for lunch
    """

    target = msg["from"].bare if is_room else msg["from"]
    mtype = "groupchat" if is_room else "chat"

    if len(args) < 1:

        bot.send_message(
            mto=target,
            mbody=f"Usage: {bot.prefix}setstatus <show> [message]",
            mtype=mtype
        )
        return

    show = args[0].lower()
    message = " ".join(args[1:]) if len(args) > 1 else ""

    valid_states = {"online", "chat", "away", "xa", "dnd"}

    if show not in valid_states:

        bot.send_message(
            mto=target,
            mbody="Invalid status. Valid values: online, chat, away, xa, dnd",
            mtype=mtype
        )
        return

    bot.presence.update(show, message)

    emoji = bot.presence.emoji(show)

    if message:
        response = f"Status updated {emoji} ({show}) {message}"
    else:
        response = f"Status updated {emoji} ({show})"

    bot.send_message(
        mto=target,
        mbody=response,
        mtype=mtype
    )


@command("status", "s")
async def show_status(bot, sender_jid, nick, args, msg, is_room):
    """
    Show the current bot status.

    Usage
    -----
    {prefix}status

    Displays the presence state and status message
    currently broadcast by the bot.
    """

    target = msg["from"].bare if is_room else msg["from"]
    mtype = "groupchat" if is_room else "chat"

    show = bot.presence.status["show"]
    message = bot.presence.status["status"]

    emoji = bot.presence.emoji(show)

    bot.send_message(
        mto=target,
        mbody=f"Current status {emoji} ({show}) {message}",
        mtype=mtype
    )
