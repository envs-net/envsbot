"""
Dice rolling plugin.

To set/show plugin status in rooms, use:
    {prefix}dice on|off|status

Command:
    {prefix}dice <num>d<sides> [modifier] [operator] [target]
    {prefix}roll ...
    {prefix}r ...

Examples:
    {prefix}dice 3d20 -5 >= 30
    {prefix}roll 2d6 +2
    {prefix}r 1d100
    {prefix}dice d6
"""

import random
import re
from collections.abc import Collection

from core_plugins._core import (
    _get_enabled_rooms,
    _is_muc_pm,
    handle_room_toggle_command,
)
from utils.command import Role, command
from utils.command_metadata import help_example, help_subcommand, room_toggle_subcommands
from utils.config import config

DICE_KEY = "DICE"
PLUGIN_META = {
    "name": "dice",
    "version": "0.2.0",
    "description": "Roll dice with optional modifiers and success conditions.",
    "category": "games",
    "requires": ["_core"],
}

DICE_RE = re.compile(
    r"^\s*(?:(\d+)?[dD](\d+))\s*([+-]\d+)?\s*"
    r"(<=|>=|<|>)?\s*(\d+)?\s*$"
)


async def make_roll(bot, msg, expr) -> list | None:
    m = DICE_RE.match(expr)
    if not m:
        bot.reply(
            msg,
            f"🟡️ Invalid syntax. Example: {config.get('prefix', ',')}dice "
            "3d20 -5 >= 30"
        )
        return None

    num, sides, mod, op, target = m.groups()
    num = int(num) if num else 1
    sides = int(sides)
    if num < 1 or num > 10 or sides < 2 or sides > 100:
        bot.reply(
            msg,
            "🟡️ Dice number must be 1-10 and sides 2-100."
        )
        return None

    rolls = [random.randint(1, sides) for _ in range(num)]
    mod_val = int(mod) if mod else 0
    if mod_val >= 1000 or mod_val <= -1000:
        bot.reply(
            msg,
            "🟡️ Modifier must be between -999 and 999."
        )
        return None
    total = sum(rolls) + mod_val

    return [num, sides, rolls, mod_val, total, op, target]


@command(
    "dice",
    role=Role.USER,
    aliases=["roll", "r"],
    short="Roll dice using common dice notation.",
    usage="{prefix}dice <on|off|status|NdM [modifier] [operator] [target]>",
    subcommands=[
        help_subcommand(
            "<dice>",
            "{prefix}dice <NdM> [modifier] [operator] [target]",
            "Roll one or more dice with an optional modifier and success test.",
            examples=[
                help_example(
                    "{prefix}dice 2d6",
                    "Roll two six-sided dice.",
                ),
                help_example(
                    "{prefix}dice 3d20 -5 >= 30",
                    "Roll three d20, subtract five and compare the total with 30.",
                ),
            ],
        ),
        *room_toggle_subcommands("dice", "dice rolling"),
    ],
    examples=[
        "{prefix}dice status",
        "{prefix}dice 2d6",
        "{prefix}rooms enable dice",
    ],
    category="fun",
    context="any",
)
async def dice_command(bot, sender_jid, nick, args, msg, is_room):
    """
    Roll dice with optional modifier and success/failure condition.

    For plugin on|off|status in rooms, use:
        {prefix}dice on|off|status

    Usage:
        {prefix}dice <num>d<sides> [modifier] [operator] [target]
        {prefix}roll ...
        {prefix}r ...

    Examples:
        {prefix}dice 3d20 -5 >= 30
        {prefix}roll 2d6 +2
        {prefix}r 1d100
        {prefix}dice d6
    """
    if not args:
        bot.reply(
            msg,
            f"🟡️ Usage: {config.get('prefix', ',')}dice <num>d<sides> "
            "[modifier] [operator] [target]"
        )
        return

    if is_room or _is_muc_pm(msg):
        handled = await handle_room_toggle_command(
            bot,
            msg,
            is_room,
            args,
            store_getter=get_dice_store,
            key=DICE_KEY,
            label="Roll Dice",
            plugin="dice",
            storage="dict",
            log_prefix="[DICE]",
        )
        if handled:
            return

    enabled_rooms = await _get_enabled_rooms(bot, DICE_KEY, "dice")
    if msg["from"].bare not in enabled_rooms and (is_room or _is_muc_pm(msg)):
        bot.reply(msg, "ℹ️ Dice Rolling is disabled in this room.")
        return

    expr = " ".join(args)
    result = await make_roll(bot, msg, expr)
    if result is None:
        return

    num, sides, rolls, mod, total, op, target = result
    mod_str = f" {mod:+d}" if mod else ""
    result_str = f"[{', '.join(str(r) for r in rolls)}]{mod_str} = {total}"

    if op and target:
        target = int(target)
        min_result = num + mod
        max_result = num * sides + mod
        if ((op in (">=", ">") and max_result < target) or
                (op in ("<=", "<") and min_result > target)):
            bot.reply(
                msg,
                "🟡️ Impossible roll: result cannot reach the target."
            )
            return
        can_succeed = (
            (op == ">=" and max_result >= target) or
            (op == ">" and max_result > target) or
            (op == "<=" and min_result <= target) or
            (op == "<" and min_result < target)
        )
        can_fail = (
            (op == ">=" and min_result < target) or
            (op == ">" and min_result <= target) or
            (op == "<=" and max_result > target) or
            (op == "<" and max_result >= target)
        )
        if not (can_succeed and can_fail):
            bot.reply(
                msg,
                "🟡️ This roll cannot fail or cannot succeed. Please adjust "
                "your modifier or target."
            )
            return
        success = False
        if op == ">=":
            success = total >= target
        elif op == "<=":
            success = total <= target
        elif op == ">":
            success = total > target
        elif op == "<":
            success = total < target
        cond_str = f"{op} {target}"
        if success:
            result_str += f" {cond_str} [✅ SUCCESS]"
        else:
            result_str += f" {cond_str} [🔴  FAILURE]"
    bot.reply(msg, f"🎲 {result_str}", ephemeral=False)


async def get_dice_store(bot):
    return bot.db.users.plugin("dice")


def _room_enabled_count(enabled_rooms: Collection[str], room_jid: str | None) -> int:
    if not room_jid:
        return len(enabled_rooms)
    target = str(room_jid).split('/', 1)[0].strip().lower()
    return sum(1 for room in enabled_rooms if str(room).split('/', 1)[0].strip().lower() == target)


async def get_runtime_state(bot, room_jid: str | None = None) -> dict[str, int]:
    """Return small dice counters for diagnostics."""
    enabled_rooms = await _get_enabled_rooms(
        bot, DICE_KEY, "dice", [room_jid] if room_jid else ()
    )
    return {
        "enabled_rooms": _room_enabled_count(enabled_rooms, room_jid),
        "max_dice": 10,
        "max_sides": 100,
    }


async def doctor(bot, room_jid: str | None = None) -> list[str]:
    """Return dice plugin health lines."""
    state = await get_runtime_state(bot, room_jid=room_jid)
    scope = f" for {room_jid}" if room_jid else ""
    return [
        f"✅ Dice{scope}: enabled_rooms={state['enabled_rooms']}, "
        f"limits={state['max_dice']}d{state['max_sides']}"
    ]
