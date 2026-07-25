# rss plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

RSS/Atom feed watcher and poster

## RSS templates

RSS posts can use a global default, a destination-wide template or a feed-specific template. A destination may be a room or a direct subscriber. The priority is: feed-specific template, destination template, global default, built-in default.

### Template variables

- `$feed_title` - title of the subscribed feed
- `$title` - title of the current entry
- `$summary` - entry summary when it is meaningfully different from the title
- `$summary_line` - the summary prefixed with ` - `, or an empty string
- `$link` - normalized link to the current entry
- `$feed_url` - subscribed RSS/Atom URL
- `$feed_link` - website URL advertised by the feed
- `$id` - entry identifier
- `$date` - published/updated date provided by the feed

Use `$$` when a literal dollar sign is needed.

### Newlines and readable spacing

The command is normally entered on one line. Write `\n` in the command to store a real line break. Two trailing `\n` sequences leave one blank separator line after an RSS post. More than two trailing line breaks are capped at two to avoid excessive gaps.

A compact multiline template:

```text
,rss template set 🌐 $feed_link\n📰 $title\n📝 $summary\n🔗 $id – 📅 $date\n\n
```

The stored and rendered message is equivalent to:

```text
🌐 https://example.org/
📰 Example entry
📝 Short example summary
🔗 https://example.org/article – 📅 2026-07-07 12:00

```

Do not add an accidental space after `\n` unless the following line should be indented. For example, use `📝\n$summary`, not `📝\n $summary`.

### Global default template

Global moderators can set one persistent default for every room or direct subscriber that has no destination- or feed-specific override:

```text
,rss template show default
,rss template set default 🌐 $feed_link\n📰 $title\n📝 $summary\n🔗 $link\n\n
,rss template test default
,rss template unset default
```

`unset default` restores the built-in RSS template. The alias `global` can be used instead of `default`.

### Room-wide templates

Inside a room or MUC PM, the room is inferred:

```text
,rss template
,rss template set 📰 $feed_title: $title\n📝 $summary\n🔗 $link\n\n
,rss template test
,rss template unset
```

From a normal private chat, pass the room JID explicitly:

```text
,rss template set room@conference.example.org 📰 $title\n$link\n\n
```

### Personal direct-chat templates

Trusted users and higher can set a persistent template for their own 1:1 RSS subscriptions. In a normal direct chat, omit the room JID. The bot recognizes the 1:1 destination automatically:

```text
,rss template
,rss template set 📰 $feed_title: $title\n$link\n\n
,rss template test
,rss template unset
```

This personal template is independent of room templates and applies only to feeds delivered directly to that user's bare JID. An optional `direct` marker is accepted for clarity, but is not required.

### Feed-specific templates

Inside a subscribed room, place the feed URL before the template:

```text
,rss template set https://example.org/feed.xml 📰 $title\n$link\n\n
,rss template show https://example.org/feed.xml
,rss template test https://example.org/feed.xml
,rss template unset https://example.org/feed.xml
```

From a normal private chat, pass both the room JID and feed URL to manage a room feed:

```text
,rss template set room@conference.example.org https://example.org/feed.xml 📰 $title\n$link\n\n
```

For a personal direct subscription, omit the room JID and place the subscribed feed URL before the template:

```text
,rss template set https://example.org/feed.xml 📰 $title\n$link\n\n
,rss template show https://example.org/feed.xml
,rss template test https://example.org/feed.xml
,rss template unset https://example.org/feed.xml
```

The equivalent explicit forms `template set direct ...` and `template set <feed-url> direct ...` are also accepted. The `direct` marker selects the personal scope and is never stored as part of the template.

## Direct subscriptions

Trusted users and higher may subscribe to feeds in a direct chat. Trusted users are limited by `RSS_TRUSTED_MAX_FEEDS` (default: 10); moderators and higher are unlimited.

The direct-chat destination is implicit. Use `,rss add <feed-url>` without appending your own JID. A redundant own-JID argument or placeholder text such as `MEINE_JID` is ignored so the subscription still belongs to the current 1:1 chat. An explicit, different room JID continues to select that room.

Use `,rss template set ...` in the same direct chat to customize all personal deliveries, or include a subscribed feed URL for a feed-specific personal template.

Trusted users may remove only their own subscriptions. Owner, superadmin, and admin users may remove a trusted user's subscription explicitly:

```text
,rss remove <feed-url> <user-jid>
```

Owner, superadmin, and admin users may also remove every direct RSS subscription for one user in a normal 1:1 chat:

```text
,rss remove all <user-jid>
```

In direct chat, global moderators see compact sections for room, moderator, and trusted-user feeds while retaining title, status, interval, destination, and URL.
Global moderators may select a single section with `,rss list rooms`, `,rss list mods`, or `,rss list trusted`. Trusted users continue to see only their own direct subscriptions with `,rss list`. Any trusted user or global moderator may use `,rss list own [page|all|last]` in a normal 1:1 chat to show only their own personal subscriptions.

## Fetch retries and startup behavior

Feed workers retain their current cursor when an HTTP request fails, so a temporary timeout does not lose entries. The first retry uses `RSS_RETRY_INITIAL_DELAY`, followed by exponential backoff up to `RSS_MAX_BACKOFF_TIME`.

When several feeds use the same host, their first requests after bot startup are spread apart by `RSS_STARTUP_STAGGER_SECONDS` (default: `2.0`). This reduces request bursts against slower Git or feed servers. Set it to `0` to disable staggering. Operators of consistently slow feed servers may also increase `RSS_FETCH_TIMEOUT_SECONDS` without changing the global HTTP timeout.

## Commands

### `,rss`

Manage RSS feed subscriptions for rooms and direct users.

Role: `user`<br>
Context: `room, MUC PM or private chat`<br>
Category: `rooms`<br>
Usage: `,rss <add|delete|remove|del|rm|retry|reset|pause|resume|health|broken|list|template> ...`

#### Subcommands

- `,rss add <feed_url> [room_jid]`
  - Description: Subscribe a room or your direct chat to an RSS/Atom feed.
  - Examples:
    - `,rss add https://example.org/feed.rss` — Subscribe the current 1:1 chat to a feed.
    - `,rss add https://example.org/feed.rss room@conference.example.org` — Subscribe an explicitly named room to a feed.

- `,rss list [own|rooms|mods|trusted|room_jid] [page|all|last]`
  - Description: List RSS subscriptions visible to you.
  - Examples:
    - `,rss list` — Show your direct subscriptions or the full moderator overview.
    - `,rss list own` — Show only your own personal direct subscriptions.
    - `,rss list trusted` — Show trusted-user direct subscriptions permitted for your role.

- `,rss delete <feed_url> [room_jid|jid|all] | ,rss delete all <user_jid>`
  - Description: Remove one subscription, or all direct subscriptions for a user.
  - Aliases: `,rss del`, `,rss remove`, `,rss rm`
  - Examples:
    - `,rss delete https://example.org/feed.rss` — Remove the feed from the current room or your direct subscriptions.
    - `,rss delete all user@example.org` — As an admin, remove every direct RSS subscription for one user.

- `,rss retry <feed_url|all> [room_jid]`
  - Description: Clear retry/backoff state and schedule another feed attempt.
  - Aliases: `,rss reset`
  - Role: `moderator`
  - Examples:
    - `,rss retry https://example.org/feed.rss room@conference.example.org` — Retry one room feed immediately.

- `,rss pause <feed_url> [room_jid|all]`
  - Description: Pause feed delivery without deleting the subscription.
  - Role: `moderator`
  - Examples:
    - `,rss pause https://example.org/feed.rss` — Pause the feed for the current room.

- `,rss resume <feed_url> [room_jid|all]`
  - Description: Resume a paused RSS subscription.
  - Role: `moderator`
  - Examples:
    - `,rss resume https://example.org/feed.rss` — Resume delivery for the current room.

- `,rss health [room_jid] [page|all|last]`
  - Description: Show feed status, retries, errors and last successful delivery.
  - Role: `moderator`
  - Examples:
    - `,rss health` — Inspect the health of feeds visible in the current context.

- `,rss broken [room_jid] [page|all|last]`
  - Description: List only feeds that currently exceed the error threshold.
  - Role: `moderator`
  - Examples:
    - `,rss broken` — Show only broken feeds visible in the current context.

- `,rss template [show|set|unset|test] [default|direct|room_jid] [feed_url] [template]`
  - Description: Show, test or configure global, room and personal RSS templates.
  - Examples:
    - `,rss template` — Show the effective template for the current destination.
    - `,rss template set 📰 $feed_title: $title\n$link` — Set the default template for the current room or direct user.
