# translate plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `utility`

## Overview

Translate text or replied-to messages with multi-provider fallback and optional source-language auto-detection.

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

Reply targets are resolved through the shared recent-message cache. Native XEP-0461 replies and client-provided visible fallback quotes are supported in all three message contexts.

## Providers and fallback

Translate supports LibreTranslate, Google and DeepL. Without API keys, the default provider is the envs.net LibreTranslate instance. Google is supported only through the official Cloud Translation API and therefore requires `TRANSLATE_GOOGLE_API_KEY`:

```python
TRANSLATE_LIBRETRANSLATE_URL = "https://translate.envs.net/"
TRANSLATE_LIBRETRANSLATE_API_KEY = None
TRANSLATE_GOOGLE_API_KEY = None
TRANSLATE_DEEPL_API_KEY = None
```

When API keys are configured, authenticated providers are tried before the unauthenticated LibreTranslate fallback in the deliberate order LibreTranslate → Google → DeepL. Google uses only the official Cloud Translation Basic v2 API; the previous unauthenticated Google endpoint is not used. A configured DeepL key uses the official `/v2/translate` API. DeepL Free keys ending in `:fx` use `api-free.deepl.com`, while other keys use `api.deepl.com`. API keys are marked sensitive in the envsbot configuration schema and are redacted from operator-facing config output.

A failed, busy or rate-limited provider does not block the entire command while another provider is available. The command moves to the next configured attempt. HTTP 429 state is tracked separately for each provider/API mode, so a cooldown on one provider does not suppress LibreTranslate, Google Cloud or DeepL.

Configured providers refresh their supported-language capabilities in the background every 12 hours. LibreTranslate contributes exact advertised source/target pairs, Google Cloud contributes its Basic v2 language list, and DeepL contributes separate source and target language lists. While a snapshot is fresh, envsbot skips a provider only when the requested pair is definitely unsupported; ambiguous regional/script variants still fall through to the provider. A failed capability refresh never disables translation through that provider.

Translation requests are serialized per provider. A command waits only a bounded time for a provider slot before trying the next provider. HTTP 429 responses honor a longer `Retry-After` value when present and use bounded exponential backoff for that provider.

The defaults are:

```python
TRANSLATE_PROVIDER_QUEUE_TIMEOUT_SECONDS = 5
TRANSLATE_RATE_LIMIT_INITIAL_SECONDS = 60
TRANSLATE_RATE_LIMIT_BACKOFF_MULTIPLIER = 2.0
TRANSLATE_RATE_LIMIT_MAX_SECONDS = 900
```

The fallback cooldown sequence per provider is 60s, 120s, 240s, 480s, then 900s. `,doctor` reports the effective provider chain, per-provider cooldowns, process-local HTTP 429 history and capability-cache freshness/language counts without exposing API keys. Capability discovery is non-blocking, runs as a supervised background task and refreshes twice per day. The listed settings and provider credentials support live config reload.

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
