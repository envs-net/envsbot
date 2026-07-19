# translate plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

Translate text or replied-to messages with optional source-language auto-detection.

## Translation forms and message contexts

Translate text with an explicit source language, automatic source-language detection, or the short target-only form:

```text
,tr en uk Hello, world!
,tr auto pl Guten Morgen
,tr de Hello, world!
```

Language arguments use supported ISO or BCP-47 codes such as `de`, `en`, `pl`, `uk`, `pt-BR` or `zh-CN`. `auto` is valid only as the source language.

The command works in public rooms, MUC private messages and normal direct chats. Reply to an existing message and omit the text to translate the replied-to message:

```text
,tr de
,tr en uk
```

Reply targets are resolved through the shared persistent message cache. Native XEP-0461 replies and client-provided visible fallback quotes are supported in all three message contexts.

## Room setting

Public-room and MUC-PM use is controlled per room. Inside the room or a MUC PM, use:

```text
,translate status
,translate on
,translate off
,rooms enable translate
,rooms disable translate
```

From a normal direct chat, pass the target room JID to the `rooms` command:

```text
,rooms enable room@conference.example.org translate
,rooms disable room@conference.example.org translate
```

Direct translation in a normal private chat does not depend on a room toggle.

## Commands

### `,translate`

Translate text or a replied-to message.

Role: `user`<br>
Context: `any`<br>
Category: `utility`<br>
Usage: `,tr [from] <to> [text or reply]`

Aliases: `,tr`

Examples:

- `,tr en uk Hello, world!`
- `,tr uk Hallo Welt!`
- `,tr auto pl Guten Morgen`
- `Reply in a room, MUC PM or private chat with ,tr en uk`
- `Reply in a room, MUC PM or private chat with ,tr uk`
- `,translate status`
- `,rooms enable translate`
