"""
Help system plugin.

Provides the `{prefix}help` command which lists available commands
and displays detailed documentation for a specific command.

The help system reads command docstrings dynamically and replaces
the `{prefix}` placeholder with the currently configured command
prefix before sending the output to the user.

To reduce chatroom spam, help requests are only allowed in private
messages to the bot.
"""

from command import command

PLUGIN_META = {
    "name": "help",
    "version": "1.0",
    "description": "Command help and documentation system"
}


@command("help", "h")
async def help_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Show available commands or detailed help for a specific command.

    Command
    -------
    {prefix}help
    {prefix}help <command>

    Behavior
    --------
    Without arguments
        Lists all available commands and their aliases.

    With a command name
        Displays the full documentation of the specified command.

    Notes
    -----
    The requested command name must NOT include the command prefix.

    Examples
    --------
    {prefix}help
    {prefix}help status
    {prefix}help plugins
    """

    target = msg["from"].bare if is_room else msg["from"]
    mtype = "groupchat" if is_room else "chat"
    #
    # Block help in chatrooms
    if mtype == "groupchat":
        bot.send_message(
            mto=target,
            mbody="❌Help requests to the bot only in private chat,"
            + "to prevent spam.",
            mtype=mtype
        )
        return

    prefix = bot.prefix
    is_admin = bot.is_admin(sender_jid)

    # -------------------------------------------------
    # HELP FOR A SPECIFIC COMMAND
    # -------------------------------------------------

    if args:
        # try longest command match
        for i in range(len(args), 0, -1):
            candidate = " ".join(args[:i])
            if candidate in bot.commands:
                name = candidate
                args = args[i:]
                break

        if name not in bot.commands:
            bot.send_message(
                mto=target,
                mbody=f"Unknown command: {name}",
                mtype=mtype
            )
            return

        func = bot.commands[name]

        if getattr(func, "admins_only", False) and not is_admin:
            bot.send_message(
                mto=target,
                mbody=f"Unknown command: {name}",
                mtype=mtype
            )
            return

        doc = func.__doc__ or "No help available."
        doc = doc.strip().replace("{prefix}", prefix)

        bot.send_message(
            mto=target,
            mbody=doc,
            mtype=mtype
        )

        return

    # -------------------------------------------------
    # GENERAL HELP (LIST COMMANDS)
    # -------------------------------------------------

    grouped = {}

    for name, func in bot.commands.items():

        if getattr(func, "admins_only", False) and not is_admin:
            continue

        grouped.setdefault(func, func._command_names)

    sorted_commands = sorted(
        grouped.items(),
        key=lambda item: item[0]._command_names[0]
    )

    lines = []

    for func, names in sorted_commands:

        aliases = ", ".join(f"{prefix}{n}" for n in names)

        doc = func.__doc__ or ""
        first_line = doc.strip().split("\n")[0] if doc else ""
        first_line = first_line.replace("{prefix}", prefix)

        admin_marker = ""
        if getattr(func, "admins_only", False):
            admin_marker = " (✅ admin)"

        if first_line:
            line = f"{aliases} — {first_line}{admin_marker}"
        else:
            line = f"{aliases} - {admin_marker}"

        lines.append(line)

    response = "Available commands:\n" + "\n".join(lines)

    bot.send_message(
        mto=target,
        mbody=response,
        mtype=mtype
    )
