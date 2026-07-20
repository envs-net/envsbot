# ducks plugin

This file is generated from command metadata. Do not edit command sections by hand.

```bash
python scripts/generate_commands_md.py
```

Source: `plugins`
Category: `games`

Duck game for MUCs with room toggles and leaderboards

## Commands

### `,bef`

Befriend the current duck.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,bef`

Examples:

- `,bef`

### `,duck`

Start or interact with the duck game.

Role: `user`<br>
Context: `room / MUC PM; use rooms enable with <room_jid> from private chat`<br>
Category: `fun`<br>
Usage: `,duck <on|off|status|befriend|trap|friends|top|enemies|stats [jid|nickname]>`

Examples:

- `,duck status`
- `,duck on`
- `,duck befriend`
- `,duck stats`
- `,rooms enable ducks`
- `,rooms enable room@conference.example.org ducks`

### `,duckstats`

Show duck game stats.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,duckstats [nick]`

Examples:

- `,duckstats`

### `,trap`

Set a trap in the duck game.

Role: `user`<br>
Context: `any`<br>
Category: `fun`<br>
Usage: `,trap`

Examples:

- `,trap`
