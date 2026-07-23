# urlcheck plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `info`

URL title and YouTube info fetcher for groupchats

## Commands

### `,urlcheck`

Enable, disable or show automatic URL checks in a room.

Role: `user`<br>
Context: `room or MUC PM`<br>
Category: `utility`<br>
Usage: `,urlcheck <on|off|status>`

#### Subcommands

- `,urlcheck on`
  - Description: Enable automatic URL checks in the current room.
  - Examples:
    - `,urlcheck on` — Enable automatic URL checks for the current room or MUC PM.

- `,urlcheck off`
  - Description: Disable automatic URL checks in the current room.
  - Examples:
    - `,urlcheck off` — Disable automatic URL checks for the current room or MUC PM.

- `,urlcheck status`
  - Description: Show whether automatic URL checks is enabled in the current room.
  - Examples:
    - `,urlcheck status` — Inspect the current room setting for automatic URL checks.
