# rss plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

RSS/Atom feed watcher and poster

## RSS templates

RSS posts can use a room-wide template or a feed-specific template. Feed-specific templates take precedence over the room template, and the room template takes precedence over the built-in default.

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

### Feed-specific templates

Inside a subscribed room, place the feed URL before the template:

```text
,rss template set https://example.org/feed.xml 📰 $title\n$link\n\n
,rss template show https://example.org/feed.xml
,rss template test https://example.org/feed.xml
,rss template unset https://example.org/feed.xml
```

From a normal private chat, pass both the room JID and feed URL:

```text
,rss template set room@conference.example.org https://example.org/feed.xml 📰 $title\n$link\n\n
```

## Commands

### `,rss`

Manage RSS feed subscriptions for rooms.

Role: `user`<br>
Context: `any`<br>
Category: `rooms`<br>
Usage: `,rss <add|delete|remove|del|rm|retry|reset|pause|resume|health|broken|list|template> ...`

Examples:

- `,rss add https://example.org/feed.rss room@conference.example.org`
- `,rss list room@conference.example.org`
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
- `,rss template set 📰 $feed_title: $title\n$link`
- `,rss template test [$feed_title] $title`
- `,rss template unset`
- `,rss delete https://example.org/feed.rss`
- `,rss remove https://example.org/feed.rss old@conference.example.org`
