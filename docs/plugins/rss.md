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

Trusted users and higher can set a persistent template for their own 1:1 RSS subscriptions. In a normal direct chat, omit the room JID:

```text
,rss template
,rss template set 📰 $feed_title: $title\n$link\n\n
,rss template test
,rss template unset
```

This personal template is independent of room templates and applies only to feeds delivered directly to that user's bare JID.

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
,rss template set https://example.org/feed.xml DIRECT $title\n$link\n\n
,rss template show https://example.org/feed.xml
,rss template unset https://example.org/feed.xml
```

## Direct subscriptions

Trusted users and higher may subscribe to feeds in a direct chat. Trusted users are limited by `RSS_TRUSTED_MAX_FEEDS` (default: 10); moderators and higher are unlimited.

Use `,rss template set ...` in the same direct chat to customize all personal deliveries, or include a subscribed feed URL for a feed-specific personal template.

Trusted users may remove only their own subscriptions. Owner, superadmin, and admin users may remove a trusted user's subscription explicitly:

```text
,rss remove <feed-url> <user-jid>
```

In direct chat, `,rss list` uses compact sections for room, moderator, and trusted-user feeds while retaining title, status, interval, destination, and URL.
Global moderators may select a single section with `,rss list rooms`, `,rss list mods`, or `,rss list trusted`. Trusted users still see only their own direct subscriptions.

## Commands

### `,rss`

Manage RSS feed subscriptions for rooms and direct users.

Role: `user`<br>
Context: `any`<br>
Category: `rooms`<br>
Usage: `,rss <add|delete|remove|del|rm|retry|reset|pause|resume|health|broken|list|template> ...`

Examples:

- `,rss add https://example.org/feed.rss room@conference.example.org`
- `,rss add https://example.org/feed.rss`
- `,rss list room@conference.example.org`
- `,rss list rooms`
- `,rss list mods`
- `,rss list trusted`
- `,rss list 2`
- `,rss list all`
- `,rss retry all`
- `,rss health`
- `,rss broken`
- `,rss pause https://example.org/feed.rss`
- `,rss resume https://example.org/feed.rss`
- `,rss reset all`
- `,rss retry https://example.org/feed.rss room@conference.example.org`
- `,rss template`
- `,rss template set default 📰 $feed_title: $title\n$link`
- `,rss template set 📰 $feed_title: $title\n$link`
- `,rss template test [$feed_title] $title`
- `,rss template unset`
- `,rss delete https://example.org/feed.rss`
- `,rss remove https://example.org/feed.rss old@conference.example.org`
