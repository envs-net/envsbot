# IdleRPG plugin

The `idlerpg` plugin is an XMPP MUC adaptation of the classic IRC IdleRPG game.
Players register a character in a room, stay online, and level up by idling.
Normal room messages add penalty time to the player's timer.

The game is room-scoped. Each room has its own players, timers, items and quest
state.

## Enable the game

Room owners/admins can enable or disable IdleRPG like other room plugins:

```text
,rooms enable <room_jid> idlerpg
,rooms disable <room_jid> idlerpg
```

From a MUC private message to the bot, room admins can also use:

```text
,idlerpg on
,idlerpg off
,idlerpg enabled
```

By default, new rooms have IdleRPG disabled:

```python
ROOM_PLUGIN_DEFAULTS = {
    "idlerpg": False,
}
```

## Player commands

Use these in the game room or from a MUC private message to the bot:

```text
,idlerpg register <character> <class>
,idlerpg status [character]
,idlerpg whoami
,idlerpg top [page|last|all]
,idlerpg players [page|last|all]
,idlerpg items [character]
,idlerpg align <good|neutral|evil>
,idlerpg quest
,idlerpg login
,idlerpg logout
,idlerpg remove-me
```


`status` always shows character progress. Use `,idlerpg enabled` to inspect whether the game is enabled in the current room.

Aliases:

```text
,irpg ...
,idle ...
```

Examples:

```text
,idlerpg register Sven sysadmin
,idlerpg status
,idlerpg top
,idlerpg items Sven
,idlerpg align good
```

## How leveling works

A player levels up when their time-to-level reaches zero.

The default level timer follows the classic IdleRPG formula:

```text
TTL = rp_base * (rp_step ** current_level)
```

Defaults:

```python
IDLERPG = {
    "rp_base": 600,
    "rp_step": 1.16,
}
```

While the player is online in the room and not explicitly logged out, the bot
subtracts elapsed idle time from the timer on every game tick.

## Penalties

Normal room messages penalize registered players. By default, bot commands are
not counted as penalty messages.

```python
IDLERPG = {
    "message_penalty": 1,
    "penalty_step": 1.14,
    "logout_penalty": 20,
    "max_penalty": 604800,
    "count_command_messages": False,
}
```

The penalty formula is:

```text
penalty = base_penalty * (penalty_step ** current_level)
```

`max_penalty` caps a single penalty event. Set it to `0` to disable the cap.

## Random events, battles and items

On level-up, the player may find an item.

The game loop can also trigger rare classic IdleRPG-style events:

- PvP battles between online players
- critical strikes that add time to the defeated player's clock
- item drops and swaps after battles
- item blessings that improve a random item
- calamities that add time to a player's timer
- godsends that remove time from a player's timer
- alignment bonuses that remove time for aligned players

Whenever an event changes a player's timer, the bot also prints the player's new
time to next level. Example output:

```text
Alice [42/111] has challenged Bob [13/96] in combat and won! 0 days, 00:12:10 is removed from Alice's clock.
Alice reaches next level in 0 days, 05:41:33.
Alice has dealt Bob a Critical Strike! 0 days, 00:03:20 is added to Bob's clock.
Bob reaches next level in 0 days, 09:12:44.
```

Relevant settings:

```python
IDLERPG = {
    "event_chance": 0.01,
    "item_chance": 0.20,
    "battle_event_weight": 0.55,
    "item_event_weight": 0.15,
    "alignment_event_weight": 0.10,
    "critical_strike_chance": 0.10,
    "item_drop_chance": 0.12,
}
```

## Quests

When enough online players have reached the configured minimum level, the bot can
start a room quest. Quest completion removes 25% of the participating players'
remaining timer burden.

Relevant settings:

```python
IDLERPG = {
    "quest_min_level": 40,
    "quest_interval": 21600,
    "quest_min_duration": 43200,
    "quest_max_duration": 86400,
}
```

## Admin commands

Room moderators/admins can adjust characters:

```text
,idlerpg push <character> <duration>
,idlerpg setlevel <character> <level>
,idlerpg reset <character>
,idlerpg delete <character>
```

Examples:

```text
,idlerpg push Sven 10m
,idlerpg setlevel Sven 12
,idlerpg reset Sven
,idlerpg delete Sven
```

## Diagnostics

IdleRPG exposes runtime state for plugin diagnostics:

```text
,plugins state idlerpg
,plugins state idlerpg <room_jid>
```

The state includes room count, player count, online player count, active quests
and running game-loop tasks.

The supervised game-loop tasks are also visible through:

```text
,tasks
,tasks all
```
