# Runtime help

EnvsBot builds its help output from the live command registry. This keeps the in-chat help and the generated command reference close to the code. For a practical start-to-finish walkthrough, see [`tutorial.md`](tutorial.md).

## Main entry points

Examples use the default prefix `,`.

```text
,help
,help commands
,help categories
,help category <name>
,help plugins
,help roles
,help room settings
,help <plugin>
,help ,<command>
,help all
```

## Focused help

Use focused help when you already know the plugin or command name. Prefer the prefixed form for command help because it is unambiguous; the unprefixed command form remains accepted as a convenience shortcut when it does not collide with a plugin name:

```text
,help rooms
,help room settings
,help rooms enable
,help ducks
,help ,rooms add
,help ,users role
,help rooms add
,help users role
```

Plugin help shows the plugin description, category, requirements and visible commands. Command help shows role, context, aliases, usage and examples.

## Categories

`,help commands` groups visible commands by category. Use `,help categories` to list the available categories and `,help category <name>` to show only one group.

Typical categories are:

```text
admin
core
fun
info
rooms
users
xmpp
```

The exact list depends on loaded plugins and your role.


## Command contexts

Command details include a context line so users know where a command is expected to work.
The most common contexts are:

```text
room
MUC PM
private chat
invite notify room
```

`private chat / MUC PM` means either a normal 1:1 chat with the bot or a private
message through a room occupant JID. Some clients prefer normal private chats in
non-anonymous rooms; for room-scoped settings, pass the target room JID explicitly.

## Room plugin settings

Use focused help when you need to find how to enable or disable a plugin in one
room:

```text
,help room settings
,help rooms enable
,help rooms plugins
,help ducks
```

Room plugin settings can be managed with the generic `rooms` commands. In a room
message or MUC PM, the bot can infer the target room automatically:

```text
,rooms plugins
,rooms plugins all
,rooms enable ducks
,rooms disable ducks
,rooms set_plugin_defaults
```

In a normal private chat, include the target room JID:

```text
,rooms plugins room@conference.example.org all
,rooms enable room@conference.example.org ducks
,rooms disable room@conference.example.org xkcd
,rooms set_plugin_defaults room@conference.example.org
```

Some plugins also provide a MUC-PM shortcut for their own room toggle:

```text
,duck on
,duck off
,duck status
```

The sender must be a room admin/owner in the target room or have a bot
moderator/admin role. This keeps clients without MUC-PM support usable without
opening room settings to normal room users.

Common room feature names include:

```text
birthday_notify, dice, ducks, help, information, karma, pin, poll,
presence, reminder, sed, tell, tools, urlcheck, vcard, weather, xkcd, xmpp
```

`information` can also be addressed as `info`. The displayed defaults come from `ROOM_PLUGIN_DEFAULTS` in `config.py` merged with internal fallbacks. Existing per-room changes stay stored in the database until `,rooms set_plugin_defaults` is used for that room.

## Notification rooms

EnvsBot does not have a separate fixed `ADMIN_ROOM` setting. Global bot access is
defined by `OWNER`, `ADMINS` and stored bot roles. Notification targets are
configured separately:

```text
VERSION_CHECK_NOTIFY_JID
ROOM_INVITE_NOTIFY_JID
```

When one of these values points to a MUC room, the bot joins that room before
sending the notification. The room is not automatically stored as an autojoin
room unless you add it with `,rooms add` or `,rooms join`.

## Roles and visibility

Help output is role-aware. Commands that require a stronger role are hidden or rejected.

Lower role values have more privileges:

```text
owner > superadmin > admin > moderator > trusted > user > new/none > banned
```

Privileged commands are normally intended for private chats or MUC PMs. The configured owner should be the only user able to grant superadmin rights.

## In-room help

By default, room help can be disabled per room to reduce noise. When it is disabled, help remains available via private chat or MUC PM. Admins or users with sufficient permissions can control the room setting with:

```text
,help inroom status
,help inroom on
,help inroom off
```

Private chats and MUC PMs remain the preferred place for full help output.

## Updating command docs

After changing command decorators or `utils/command_help.py`, regenerate the command reference:

```bash
python scripts/generate_commands_md.py
```

Generated output lives in [`commands.md`](commands.md).
