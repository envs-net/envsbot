# rss plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

RSS/Atom feed watcher and poster

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
