# EnvsBot tutorial

This tutorial walks through a practical first setup and the most common operator tasks.
It complements the generated command reference in [`commands.md`](commands.md) and the runtime help guide in [`help.md`](help.md).

Examples use the default command prefix `,`.

## 1. Where to talk to the bot

EnvsBot accepts commands in three places:

```text
public room message
MUC private message to the bot's room nickname
normal private chat with the bot account
```

For global operator tasks such as status, config, backups, user roles or plugin
reloads, a normal private chat with the bot account is usually the cleanest place.
The command output is not shown to the whole room, and the room context cannot be
guessed incorrectly.

For room-scoped tasks, the easiest place is the target room itself or a MUC PM
from that room. In those contexts the bot can infer the target room:

```text
,rooms enable ducks
,rss add https://example.org/feed.rss
```

When using a normal private chat for a room-scoped task, pass the room JID
explicitly:

```text
,rooms enable room@conference.example.org ducks
,rss add https://example.org/feed.rss room@conference.example.org
```

This is also the recommended fallback when a client does not handle MUC PMs well.
Use public room commands for things that are safe to be visible to everyone; use
private chat or MUC PM for administrative output.

## 2. First start

Create your runtime configuration from the sample file and edit it for your XMPP
account:

```bash
cp config_sample.py config.py
$EDITOR config.py
```

Start the bot with your preferred service manager, then check that it responds:

```text
,status
,version
,help
```

Useful follow-up commands:

```text
,status full
,config show
,config diff
```

## 3. Add and manage rooms

Add a room to the bot's persistent room list:

```text
,rooms add room@conference.example.org
,rooms join room@conference.example.org
,rooms list
```

Show or change stored rooms later:

```text
,rooms list
,rooms update room@conference.example.org nick EnvsBot
,rooms leave room@conference.example.org
,rooms delete room@conference.example.org
```

Incoming room invites are stored as pending invites when room invites are enabled:

```text
,rooms invite list
,rooms invite accept <id>
,rooms invite decline <id>
```

## 4. Use help effectively

Start broad, then narrow down:

```text
,help
,help commands
,help categories
,help category rooms
,help rooms
,help ,rooms add
```

For room plugin toggles, use the dedicated help entry:

```text
,help room settings
,help rooms enable
,help ducks
```

Plugin help shows related commands and room-setting examples. Command help shows role, context, aliases, usage and examples.

## 5. Enable or disable plugins per room

Many plugins can be enabled or disabled per room. In a public room or MUC PM, the bot can infer the room:

```text
,rooms plugins
,rooms plugins all
,rooms enable ducks
,rooms disable ducks
```

From a normal private chat, pass the target room explicitly:

```text
,rooms plugins room@conference.example.org all
,rooms enable room@conference.example.org ducks
,rooms disable room@conference.example.org xkcd
,rooms set_plugin_defaults room@conference.example.org
```

Some plugins also have shortcut commands in MUC PM:

```text
,duck on
,duck off
,duck status
```

The sender must be owner/admin in the target room or have a global bot moderator/admin role. Defaults for new rooms and for `,rooms set_plugin_defaults` come from `ROOM_PLUGIN_DEFAULTS` in `config.py`; existing room-specific changes remain stored until reset explicitly.

## 6. Example: enable ducks in one room

In the room or a MUC PM to the bot:

```text
,rooms enable ducks
,duck status
```

From a normal private chat:

```text
,rooms enable room@conference.example.org ducks
,rooms plugins room@conference.example.org all
```

Then ask for focused help when needed:

```text
,help ducks
```

## 7. RSS feeds

Add a feed for the current room when running the command in a room or MUC PM:

```text
,rss add https://example.org/feed.rss
,rss list
```

From a normal private chat, pass the target room explicitly:

```text
,rss add https://example.org/feed.rss room@conference.example.org
,rss list room@conference.example.org
```

Common maintenance commands:

```text
,rss list all
,rss retry https://example.org/feed.rss
,rss reset https://example.org/feed.rss
,rss retry all
,rss reset all
,rss delete https://example.org/feed.rss room@conference.example.org
```

`retry all` and `reset all` are global operations and require a global moderator/admin role.

Room owners/admins can customize RSS post formatting per room. The default output stays unchanged unless a template is set. Supported variables include `$feed_title`, `$title`, `$summary`, `$summary_line`, `$link`, `$feed_url`, `$feed_link`, `$id`, and `$date`. Use `\n` for a newline and `$$` for a literal dollar sign.

```text
,rss template
,rss template set 📰 $feed_title: $title\n$link
,rss template test [$feed_title] $title
,rss template unset
```

## 8. Room-scoped plugin grants

Global bot roles are not always needed. You can delegate selected room-scoped plugin permissions to a user:

```text
,users grant alice@example.org rss pin poll
,users grants alice@example.org
,users revoke alice@example.org pin poll
```

A plugin grant alone is not enough. The user must also be owner/admin in the target room. The bot verifies this with a direct MUC affiliation query when possible and falls back to its room cache only when the live query is unavailable.

Supported grantable plugins are currently:

```text
rss, pin, poll
```

## 9. Roles and user management

Show roles and privileged users:

```text
,users roles
,users admins
```

Change or inspect a user:

```text
,users info alice@example.org
,users role alice@example.org moderator
,users delete alice@example.org
```

Role changes are guarded. Lower roles cannot modify equal or higher roles, and the configured owner remains protected.

## 10. Backup and configuration

Create and inspect managed backups:

```text
,backup create
,backup list
,backup show <backup.zip>
```

Inspect runtime configuration safely:

```text
,config show
,config diff
,config validate
,config reload
```

Sensitive values are redacted from config output.

## 11. Tasks and plugin reloads

Show supervised background tasks:

```text
,tasks
,tasks full
,tasks rss
```

Manage plugins:

```text
,plugins list
,plugins info rss
,plugins reload rss
,plugins reload all
```

Core plugins cannot be unloaded at runtime.

## 12. Troubleshooting

### Bot does not answer

Check whether the bot is connected and joined to the expected room:

```text
,status
,status full
,rooms list
```

### A plugin does not work in a room

Check whether the plugin is enabled for that room:

```text
,help room settings
,rooms plugins room@conference.example.org all
,rooms enable room@conference.example.org <plugin>
```

### RSS feed shows failed fetches

Show retry state and reset when needed:

```text
,rss list all
,rss retry https://example.org/feed.rss
,rss reset https://example.org/feed.rss
,rss retry all
```

Then check the service logs for the fetch error.

### A user has a plugin grant but cannot manage a room

Verify both parts of the permission check:

```text
,users grants alice@example.org
,rooms plugins room@conference.example.org all
```

The user must have the plugin grant and be owner/admin in the target room.
