"""Split module for plugins/idlerpg.py: items."""

from __future__ import annotations
import random
from typing import Any


def _unique_defs_by_name() -> dict[str, dict[str, Any]]:
    return {str(item.get("name")): dict(item) for item in UNIQUE_ITEMS if item.get("name")}


def _unique_bonuses(player: dict[str, Any]) -> list[dict[str, Any]]:
    unique_items = player.get("unique_items")
    if not isinstance(unique_items, dict):
        return []
    defs = _unique_defs_by_name()
    bonuses: list[dict[str, Any]] = []
    for slot, name in unique_items.items():
        item = defs.get(str(name))
        if not item:
            continue
        bonus = str(item.get("bonus") or "")
        if not bonus:
            continue
        bonuses.append({
            "slot": str(slot),
            "name": str(name),
            "bonus": bonus,
            "bonus_percent": int(item.get("bonus_percent", 0) or 0),
        })
    return bonuses


def _unique_bonus_percent(player: dict[str, Any], bonus: str) -> int:
    total = sum(
        int(item.get("bonus_percent", 0) or 0)
        for item in _unique_bonuses(player)
        if item.get("bonus") == bonus
    )
    return max(0, min(35, total))


def _adjust_percent_amount(amount: int, player: dict[str, Any], bonus: str, *, increase: bool = False) -> int:
    percent = _unique_bonus_percent(player, bonus)
    if percent <= 0:
        return max(1, int(amount))
    factor = (100 + percent) if increase else max(0, 100 - percent)
    return max(1, int(int(amount) * factor / 100))


def _item_sum(player: dict[str, Any]) -> int:
    items = player.get("items", {})
    if not isinstance(items, dict):
        return 0
    total = 0
    for value in items.values():
        try:
            total += max(0, int(value or 0))
        except (TypeError, ValueError):
            continue
    return total


def _battle_power(player: dict[str, Any]) -> int:
    level = max(0, int(player.get("level", 0) or 0))
    base = max(1, level * 10 + _item_sum(player) + 1)
    return max(1, int(base * (100 + _unique_bonus_percent(player, "battle_bonus")) / 100))


def _percent_amount(player: dict[str, Any], percent: int | float) -> int:
    ttl = max(1, int(player.get("next", 0) or 0))
    return max(1, int(ttl * max(0.0, float(percent)) / 100.0))


def _battle_percent(opponent: dict[str, Any], outcome: str) -> float:
    level = max(0, int(opponent.get("level", 0) or 0))
    if outcome == "win":
        return max(float(BATTLE_WIN_MIN_PERCENT), level / 4.0)
    return max(float(BATTLE_LOSS_MIN_PERCENT), level / 7.0)


def _battle_clock_delta(player: dict[str, Any], opponent: dict[str, Any], outcome: str) -> int:
    return max(1, int(_percent_amount(player, _battle_percent(opponent, outcome)) * _alignment_battle_factor(player, outcome)))


def _random_percent_amount(player: dict[str, Any], min_percent: int, max_percent: int) -> int:
    low = min(int(min_percent), int(max_percent))
    high = max(int(min_percent), int(max_percent))
    return _percent_amount(player, random.randint(low, high))


def _roll_unique_item(player: dict[str, Any]) -> dict[str, Any] | None:
    if not UNIQUE_ITEMS_ENABLED:
        return None
    level = int(player.get("level", 0) or 0)
    if level < UNIQUE_ITEM_MIN_LEVEL or random.random() >= UNIQUE_ITEM_CHANCE:
        return None
    eligible = [item for item in UNIQUE_ITEMS if level >= int(item.get("min_level", 0) or 0)]
    if not eligible:
        return None
    item = random.choice(eligible)
    return {
        "name": str(item["name"]),
        "slot": str(item["slot"]),
        "level": random.randint(int(item["min_item_level"]), int(item["max_item_level"])),
        "bonus": str(item.get("bonus") or ""),
        "bonus_percent": int(item.get("bonus_percent", 0) or 0),
    }


def _grant_level_item(player: dict[str, Any]) -> str:
    unique = _roll_unique_item(player)
    items = player.setdefault("items", {})
    unique_items = player.setdefault("unique_items", {})
    if unique:
        slot = str(unique["slot"])
        level = int(unique["level"])
        items[slot] = max(int(items.get(slot, 0) or 0), level)
        unique_items[slot] = str(unique["name"])
        _award(player, "unique_item")
        _inc_stat(player, "unique_items_found", 1)
        _check_level_achievements(player)
        bonus = str(unique.get("bonus", "")).replace("_", " ")
        bonus_part = f" ({int(unique.get('bonus_percent', 0) or 0)}% {bonus})" if bonus else ""
        return f"🌌 {_display_player(player)} found {unique['name']}, a level {level} {slot}, near {_player_region(player)}{bonus_part}!"
    item = random.choice(ITEMS)
    gain = max(1, int(player.get("level", 0) or 0) + random.randint(0, 3))
    if gain >= int(items.get(item, 0) or 0):
        items[item] = gain
        unique_items.pop(item, None)
    _check_level_achievements(player)
    return f"✨ {_display_player(player)} found {item} level {gain} near {_player_region(player)}."


def _maybe_critical_strike(winner: dict[str, Any], loser: dict[str, Any], messages: list[str]) -> None:
    if random.random() >= CRITICAL_STRIKE_CHANCE:
        return
    _award(winner, "critical_striker")
    winner_name = _display_player(winner)
    loser_name = _display_player(loser)
    amount = _random_percent_amount(loser, CRITICAL_MIN_PERCENT, CRITICAL_MAX_PERCENT)
    changed = _add_time(loser, amount)
    loser.setdefault("penalties", {})["critical"] = (
        int(loser.get("penalties", {}).get("critical", 0) or 0) + changed
    )
    messages.append(
        f"💢 {winner_name} has dealt {loser_name} a Critical Strike! "
        f"{_duration_clock(changed)} is added to {_possessive(loser_name)} clock."
    )
    messages.append(_next_level_line(loser))


def _maybe_battle_item_drop(winner: dict[str, Any], loser: dict[str, Any], messages: list[str]) -> None:
    if random.random() >= ITEM_DROP_CHANCE:
        return
    winner_items = winner.setdefault("items", {})
    loser_items = loser.setdefault("items", {})
    candidates: list[tuple[str, int, int]] = []
    for item in ITEMS:
        try:
            winner_level = int(winner_items.get(item, 0) or 0)
            loser_level = int(loser_items.get(item, 0) or 0)
        except (TypeError, ValueError):
            continue
        if loser_level > winner_level:
            candidates.append((item, loser_level, winner_level))
    if not candidates:
        return
    item, loser_level, winner_level = random.choice(candidates)
    winner_items[item] = loser_level
    loser_items[item] = winner_level
    winner_unique = winner.setdefault("unique_items", {})
    loser_unique = loser.setdefault("unique_items", {})
    winner_unique_name = winner_unique.get(item)
    loser_unique_name = loser_unique.get(item)
    if loser_unique_name:
        winner_unique[item] = loser_unique_name
    else:
        winner_unique.pop(item, None)
    if winner_unique_name:
        loser_unique[item] = winner_unique_name
    else:
        loser_unique.pop(item, None)
    winner_name = _display_player(winner)
    loser_name = _display_player(loser)
    messages.append(
        f"🎒 In the fierce battle, {loser_name} dropped their level {loser_level} {item}! "
        f"{winner_name} picks it up, tossing their old level {winner_level} {item} to {loser_name}."
    )


def _run_item_blessing(players: list[tuple[str, dict[str, Any]]], messages: list[str]) -> None:
    _jid, player = random.choice(players)
    item = random.choice(ITEMS)
    items = player.setdefault("items", {})
    try:
        old_level = int(items.get(item, 0) or 0)
    except (TypeError, ValueError):
        old_level = 0
    level = max(0, int(player.get("level", 0) or 0))
    gain = max(1, old_level // 10, level // 10)
    items[item] = old_level + gain
    name = _display_player(player)
    _award(player, "item_blessed")
    _inc_stat(player, "item_blessings", 1)
    _check_level_achievements(player)
    messages.append(
        f"✨ {name}'s {item} has been blessed by a wandering enchanter near {_player_region(player)}! "
        f"{_possessive(name)} {item} gains {gain} level{'s' if gain != 1 else ''}."
    )


def _run_item_damage(players: list[tuple[str, dict[str, Any]]], messages: list[str]) -> None:
    candidates: list[tuple[dict[str, Any], str, int]] = []
    for _jid, player in players:
        items = player.setdefault("items", {})
        for item in ITEMS:
            try:
                level = int(items.get(item, 0) or 0)
            except (TypeError, ValueError):
                level = 0
            if level > 0:
                candidates.append((player, item, level))
    if not candidates:
        return
    player, item, old_level = random.choice(candidates)
    loss = max(1, old_level // 10)
    new_level = max(0, old_level - loss)
    player.setdefault("items", {})[item] = new_level
    if new_level <= 0:
        player.setdefault("unique_items", {}).pop(item, None)
    _award(player, "item_damaged")
    _inc_stat(player, "item_damage_events", 1)
    name = _display_player(player)
    messages.append(
        f"🪨 {name} slipped and damaged their {item} near {_player_region(player)}! "
        f"{_possessive(name)} {item} loses {loss} level{'s' if loss != 1 else ''}."
    )


def _run_item_swap(players: list[tuple[str, dict[str, Any]]], messages: list[str]) -> None:
    pair = _choose_two_players(players)
    if pair is None:
        return
    (_winner_jid, winner), (_loser_jid, loser) = pair
    winner_items = winner.setdefault("items", {})
    loser_items = loser.setdefault("items", {})
    candidates: list[tuple[str, int, int]] = []
    for item in ITEMS:
        try:
            winner_level = int(winner_items.get(item, 0) or 0)
            loser_level = int(loser_items.get(item, 0) or 0)
        except (TypeError, ValueError):
            continue
        # Fairness guard: swap only when the target item is better and the winner gives
        # their old item back. This mirrors classic IdleRPG steal/swap events without
        # deleting progress from either player.
        if loser_level > winner_level:
            candidates.append((item, loser_level, winner_level))
    if not candidates:
        return
    item, loser_level, winner_level = random.choice(candidates)
    winner_items[item] = loser_level
    loser_items[item] = winner_level
    winner_unique = winner.setdefault("unique_items", {})
    loser_unique = loser.setdefault("unique_items", {})
    winner_unique_name = winner_unique.get(item)
    loser_unique_name = loser_unique.get(item)
    if loser_unique_name:
        winner_unique[item] = loser_unique_name
    else:
        winner_unique.pop(item, None)
    if winner_unique_name:
        loser_unique[item] = winner_unique_name
    else:
        loser_unique.pop(item, None)
    _award(winner, "item_swapped")
    _inc_stat(winner, "item_swaps_won", 1)
    winner_name = _display_player(winner)
    loser_name = _display_player(loser)
    messages.append(
        f"🎒 {winner_name} found {loser_name}'s level {loser_level} {item} while they were distracted! "
        f"{winner_name} leaves their old level {winner_level} {item} behind, which {loser_name} then takes."
    )
