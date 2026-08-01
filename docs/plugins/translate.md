# translate plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

## Overview

Translate text or replied-to messages with optional source-language auto-detection.

## Translation forms and message contexts

Translate text with an explicit source language, automatic source-language detection, or the short target-only form:

```text
,tr en uk Hello, world!
,tr auto pl Guten Morgen
,tr de Hello, world!
```

Language arguments use supported ISO or BCP-47 codes such as `de`, `en`, `pl`, `uk`, `pt-BR` or `zh-CN`. `auto` is valid only as the source language.

## Configured language defaults

The global Python configuration supports:

```python
TRANSLATE_FROM = "auto"
TRANSLATE_TO = None
```

These values preserve the original behavior: the source is detected automatically and every command still requires a target language. Set `TRANSLATE_TO` to a supported language code to enable shorter commands:

```python
TRANSLATE_FROM = "auto"
TRANSLATE_TO = "de"
```

With that example configuration, direct text and replies can be translated without language arguments:

```text
,tr Hello, world!
Reply to a message with ,tr
```

A target argument such as `,tr pl Text` overrides `TRANSLATE_TO`; an explicit pair such as `,tr en uk Text` overrides both defaults. The settings are applied by `,config reload` without restarting the bot.

Automatic detection can be ambiguous for very short text, especially single words written in the Latin alphabet. If the provider detects the target language and returns the input unchanged, the bot now explains the ambiguity and suggests an explicit source/target pair such as `,tr de en Blume`. Longer phrases usually give the provider enough context for reliable detection.

If a shorthand target equals the configured source, the bot automatically uses `auto` as the source instead of sending a no-op translation such as `en` to `en`. An explicitly supplied pair such as `,tr en en text` is still respected unchanged.

With `TRANSLATE_TO` configured, `,tr auto` translates the literal word `auto`. To explicitly select automatic source detection for a reply, include the target too, for example `,tr auto de`.

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
Context: `room, MUC PM or private chat`<br>
Category: `utility`<br>
Usage: `,tr [from] [to] [text or reply]`

Aliases: `,tr`

#### Subcommands

- `,tr [from] [to] <text>`
  - Description: Translate provided text with explicit or configured language defaults.
  - Examples:
    - `,tr en uk Hello, world!` — Translate English text into Ukrainian.
    - `,tr auto pl Guten Morgen` — Detect the source language automatically and translate into Polish.

- `Reply to a message with ,tr [from] [to]`
  - Description: Translate the replied-to message without copying its text into the command.
  - Examples:
    - `Reply with ,tr en uk` — Translate the replied-to message from English into Ukrainian.

- `,translate on`
  - Description: Enable translation commands in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,translate on` — Enable translation commands for the current room or MUC PM.

- `,translate off`
  - Description: Disable translation commands in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,translate off` — Disable translation commands for the current room or MUC PM.

- `,translate status`
  - Description: Show whether translation commands is enabled in the current room.
  - Context: `room or MUC PM`
  - Examples:
    - `,translate status` — Inspect the current room setting for translation commands.
