"""Split module for plugins/idlerpg.py: items."""

from __future__ import annotations
import random
from typing import Any


def _unique_defs_by_name() -> dict[str, dict[str, Any]]:
    return {str(item.get("name")): dict(item) for item in _dep_constants.UNIQUE_ITEMS if item.get("name")}


def _unique_item_tier(item: dict[str, Any] | None) -> int:
    if not isinstance(item, dict):
        return 0
    try:
        return max(1, int(item.get("tier", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _unique_item_level(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _next_unique_upgrade_level(slot: str, tier: int) -> int | None:
    levels = [
        _unique_item_level(item.get("min_level"))
        for item in _dep_constants.UNIQUE_ITEMS
        if str(item.get("slot") or "") == str(slot)
        and _unique_item_tier(item) > int(tier)
    ]
    return max(_unique_item_level(_dep_config.UNIQUE_ITEM_MIN_LEVEL), min(levels)) if levels else None


def _unique_bonuses(player: dict[str, Any]) -> list[dict[str, Any]]:
    unique_items = player.get("unique_items")
    if not isinstance(unique_items, dict):
        return []
    item_levels = player.get("items") if isinstance(player.get("items"), dict) else {}
    defs = _unique_defs_by_name()
    bonuses: list[dict[str, Any]] = []
    for slot, name in unique_items.items():
        item = defs.get(str(name))
        if not item:
            continue
        bonus = str(item.get("bonus") or "")
        if not bonus:
            continue
        tier = _unique_item_tier(item)
        bonuses.append({
            "slot": str(slot),
            "name": str(name),
            "tier": tier,
            "item_level": _unique_item_level(item_levels.get(slot)),
            "min_level": _unique_item_level(item.get("min_level")),
            "effective_min_level": max(
                _unique_item_level(_dep_config.UNIQUE_ITEM_MIN_LEVEL),
                _unique_item_level(item.get("min_level")),
            ),
            "next_upgrade_level": _next_unique_upgrade_level(str(item.get("slot") or slot), tier),
            "bonus": bonus,
            "bonus_percent": int(item.get("bonus_percent", 0) or 0),
        })
    return bonuses


def _unique_item_slots(player: dict[str, Any]) -> set[str]:
    unique_items = player.get("unique_items")
    if not isinstance(unique_items, dict):
        return set()
    return {str(slot) for slot, name in unique_items.items() if str(name or "").strip()}


def _unique_bonus_percent(player: dict[str, Any], bonus: str) -> int:
    total = sum(
        int(item.get("bonus_percent", 0) or 0)
        for item in _unique_bonuses(player)
        if item.get("bonus") == bonus
    )
    return max(0, min(int(_dep_constants.UNIQUE_BONUS_CAP_PERCENT), total))


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


def _alignment_item_sum_factor(player: dict[str, Any]) -> float:
    alignment = str(player.get("alignment") or "neutral").strip().lower()
    key = {"g": "good", "n": "neutral", "e": "evil"}.get(alignment[:1], "neutral")
    return float(_dep_constants.ALIGNMENT_ITEM_POWER_FACTORS[key])


def _battle_power(player: dict[str, Any]) -> int:
    level = max(0, int(player.get("level", 0) or 0))
    item_sum = int(_item_sum(player) * _alignment_item_sum_factor(player))
    base = max(1, level * 10 + item_sum + 1)
    return max(1, int(base * (100 + _unique_bonus_percent(player, "battle_bonus")) / 100))


def _percent_amount(player: dict[str, Any], percent: int | float) -> int:
    ttl = max(1, int(player.get("next", 0) or 0))
    return max(1, int(ttl * max(0.0, float(percent)) / 100.0))


def _battle_percent(opponent: dict[str, Any], outcome: str) -> float:
    level = max(0, int(opponent.get("level", 0) or 0))
    if outcome == "win":
        return max(float(_dep_config.BATTLE_WIN_MIN_PERCENT), level / 4.0)
    return max(float(_dep_config.BATTLE_LOSS_MIN_PERCENT), level / 7.0)


def _battle_clock_delta(player: dict[str, Any], opponent: dict[str, Any], outcome: str) -> int:
    return max(1, int(_percent_amount(player, _battle_percent(opponent, outcome))))


def _random_percent_amount(player: dict[str, Any], min_percent: int, max_percent: int) -> int:
    low = min(int(min_percent), int(max_percent))
    high = max(int(min_percent), int(max_percent))
    return _percent_amount(player, random.randint(low, high))


def _roll_weighted_item_level(player_level: int) -> int:
    normalized_level = max(1, int(player_level))
    max_level = normalized_level + (normalized_level // 2)
    population = range(1, max_level + 1)
    weights = [1.4 ** -level for level in population]
    return int(random.choices(population, weights=weights, k=1)[0])


def _roll_unique_item(player: dict[str, Any]) -> dict[str, Any] | None:
    if not _dep_config.UNIQUE_ITEMS_ENABLED:
        return None
    level = _unique_item_level(player.get("level"))
    if level < _dep_config.UNIQUE_ITEM_MIN_LEVEL or random.random() >= _dep_config.UNIQUE_ITEM_CHANCE:
        return None

    unique_items = player.get("unique_items") if isinstance(player.get("unique_items"), dict) else {}
    item_levels = player.get("items") if isinstance(player.get("items"), dict) else {}
    defs = _unique_defs_by_name()
    eligible: list[tuple[dict[str, Any], int, int, str]] = []
    for raw_item in _dep_constants.UNIQUE_ITEMS:
        item = dict(raw_item)
        if level < _unique_item_level(item.get("min_level")):
            continue
        slot = str(item.get("slot") or "")
        if not slot:
            continue
        low = _unique_item_level(item.get("min_item_level"))
        high = _unique_item_level(item.get("max_item_level"))
        if high < low:
            continue
        existing_name = str(unique_items.get(slot) or "")
        if existing_name:
            existing = defs.get(existing_name)
            current_level = _unique_item_level(item_levels.get(slot))
            if not existing or _unique_item_tier(item) <= _unique_item_tier(existing):
                continue
            low = max(low, current_level + 1)
            if low > high:
                continue
        eligible.append((item, low, high, existing_name))

    if not eligible:
        return None
    item, low, high, existing_name = random.choice(eligible)
    return {
        "name": str(item["name"]),
        "slot": str(item["slot"]),
        "tier": _unique_item_tier(item),
        "min_level": _unique_item_level(item.get("min_level")),
        "level": random.randint(low, high),
        "bonus": str(item.get("bonus") or ""),
        "bonus_percent": int(item.get("bonus_percent", 0) or 0),
        "upgrade_from": existing_name,
    }


def _grant_level_item(player: dict[str, Any], room: dict[str, Any] | None = None) -> str:
    unique = _roll_unique_item(player)
    items = player.setdefault("items", {})
    unique_items = player.setdefault("unique_items", {})
    if unique:
        slot = str(unique["slot"])
        level = _unique_item_level(unique.get("level"))
        existing_unique = str(unique_items.get(slot) or "")
        defs = _unique_defs_by_name()
        candidate_def = defs.get(str(unique.get("name") or ""))
        candidate_tier = _unique_item_tier(candidate_def or unique)
        existing_level = _unique_item_level(items.get(slot))
        if existing_unique:
            existing_def = defs.get(existing_unique)
            existing_tier = _unique_item_tier(existing_def)
            stronger = (
                existing_def is not None
                and candidate_def is not None
                and candidate_tier > existing_tier
                and level > existing_level
            )
            if not stronger:
                _dep_leveling._check_level_achievements(player, room)
                return (
                    f"🌌 {_dep_formatting._display_player(player)} found {unique['name']}, a tier {candidate_tier} "
                    f"level {level} {slot}, near {_dep_map._player_region(player)}, but keeps {existing_unique}."
                )
            items[slot] = level
            unique_items[slot] = str(unique["name"])
            _dep_leveling._award(player, "unique_item")
            _dep_leveling._inc_stat(player, "unique_items_found", 1, room)
            _dep_leveling._inc_stat(player, "unique_item_upgrades", 1, room)
            bonus = str(unique.get("bonus", "")).replace("_", " ")
            bonus_part = f" ({int(unique.get('bonus_percent', 0) or 0)}% {bonus})" if bonus else ""
            return (
                f"🌠 {_dep_formatting._display_player(player)} upgraded {existing_unique} "
                f"(tier {existing_tier}, level {existing_level}) to {unique['name']} "
                f"(tier {candidate_tier}, level {level}) near {_dep_map._player_region(player)}{bonus_part}!"
            )
        items[slot] = max(existing_level, level)
        unique_items[slot] = str(unique["name"])
        _dep_leveling._award(player, "unique_item")
        _dep_leveling._inc_stat(player, "unique_items_found", 1, room)
        bonus = str(unique.get("bonus", "")).replace("_", " ")
        bonus_part = f" ({int(unique.get('bonus_percent', 0) or 0)}% {bonus})" if bonus else ""
        return (
            f"🌌 {_dep_formatting._display_player(player)} found {unique['name']}, a tier {candidate_tier} "
            f"level {level} {slot}, near {_dep_map._player_region(player)}{bonus_part}!"
        )
    item = random.choice(_dep_constants.ITEMS)
    gain = _roll_weighted_item_level(int(player.get("level", 0) or 0))
    existing_unique = str(unique_items.get(item) or "")
    if existing_unique:
        _dep_leveling._check_level_achievements(player, room)
        return (
            f"✨ {_dep_formatting._display_player(player)} found {item} level {gain} near {_dep_map._player_region(player)}, "
            f"but keeps {existing_unique}."
        )
    if gain >= int(items.get(item, 0) or 0):
        items[item] = gain
    _dep_leveling._check_level_achievements(player, room)
    return f"✨ {_dep_formatting._display_player(player)} found {item} level {gain} near {_dep_map._player_region(player)}."


def _critical_strike_chance(player: dict[str, Any]) -> float:
    alignment = str(player.get("alignment") or "n")[:1].lower()
    if alignment == "g":
        return max(0.0, float(_dep_config.CRITICAL_STRIKE_CHANCE_GOOD))
    if alignment == "e":
        return max(0.0, float(_dep_config.CRITICAL_STRIKE_CHANCE_EVIL))
    return max(0.0, float(_dep_config.CRITICAL_STRIKE_CHANCE))


def _maybe_critical_strike(winner: dict[str, Any], loser: dict[str, Any], messages: list[str]) -> None:
    if random.random() >= _critical_strike_chance(winner):
        return
    _dep_leveling._award(winner, "critical_striker")
    winner_name = _dep_formatting._display_player(winner)
    loser_name = _dep_formatting._display_player(loser)
    amount = _random_percent_amount(loser, _dep_config.CRITICAL_MIN_PERCENT, _dep_config.CRITICAL_MAX_PERCENT)
    changed = _dep_leveling._add_time(loser, amount)
    loser.setdefault("penalties", {})["critical"] = (
        int(loser.get("penalties", {}).get("critical", 0) or 0) + changed
    )
    messages.append(
        f"💢 {winner_name} has dealt {loser_name} a Critical Strike! "
        f"{_dep_formatting._duration_clock(changed)} is added to {_dep_formatting._possessive(loser_name)} clock."
    )
    messages.append(_dep_formatting._next_level_line(loser))


def _maybe_battle_item_drop(
    winner: dict[str, Any],
    loser: dict[str, Any],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> None:
    if random.random() >= _dep_config.ITEM_DROP_CHANCE:
        return
    winner_items = winner.setdefault("items", {})
    loser_items = loser.setdefault("items", {})
    winner_unique_slots = _unique_item_slots(winner)
    loser_unique_slots = _unique_item_slots(loser)
    candidates: list[tuple[str, int, int]] = []
    for item in _dep_constants.ITEMS:
        if item in winner_unique_slots or item in loser_unique_slots:
            continue
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
    _dep_leveling._check_level_achievements(winner, room)
    _dep_leveling._check_level_achievements(loser, room)
    winner_name = _dep_formatting._display_player(winner)
    loser_name = _dep_formatting._display_player(loser)
    messages.append(
        f"🎒 In the fierce battle, {loser_name} dropped their level {loser_level} {item}! "
        f"{winner_name} picks it up, tossing their old level {winner_level} {item} to {loser_name}."
    )


def _run_item_blessing(
    players: list[tuple[str, dict[str, Any]]],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> None:
    _jid, player = random.choice(players)
    item = random.choice(_dep_constants.ITEMS)
    items = player.setdefault("items", {})
    try:
        old_level = int(items.get(item, 0) or 0)
    except (TypeError, ValueError):
        old_level = 0
    level = max(0, int(player.get("level", 0) or 0))
    gain = max(1, old_level // 10, level // 10)
    items[item] = old_level + gain
    name = _dep_formatting._display_player(player)
    _dep_leveling._award(player, "item_blessed")
    _dep_leveling._inc_stat(player, "item_blessings", 1, room)
    messages.append(
        f"✨ {name}'s {item} has been blessed by a wandering enchanter near {_dep_map._player_region(player)}! "
        f"{_dep_formatting._possessive(name)} {item} gains {gain} level{'s' if gain != 1 else ''}."
    )


def _run_item_damage(
    players: list[tuple[str, dict[str, Any]]],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> None:
    candidates: list[tuple[dict[str, Any], str, int]] = []
    for _jid, player in players:
        items = player.setdefault("items", {})
        unique_slots = _unique_item_slots(player)
        for item in _dep_constants.ITEMS:
            if item in unique_slots:
                continue
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
    _dep_leveling._award(player, "item_damaged")
    _dep_leveling._inc_stat(player, "item_damage_events", 1, room)
    name = _dep_formatting._display_player(player)
    messages.append(
        f"🪨 {name} slipped and damaged their {item} near {_dep_map._player_region(player)}! "
        f"{_dep_formatting._possessive(name)} {item} loses {loss} level{'s' if loss != 1 else ''}."
    )


def _run_item_swap(
    players: list[tuple[str, dict[str, Any]]],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> None:
    pair = _dep_state._choose_two_players(players)
    if pair is None:
        return
    (_winner_jid, winner), (_loser_jid, loser) = pair
    winner_items = winner.setdefault("items", {})
    loser_items = loser.setdefault("items", {})
    winner_unique_slots = _unique_item_slots(winner)
    loser_unique_slots = _unique_item_slots(loser)
    candidates: list[tuple[str, int, int]] = []
    for item in _dep_constants.ITEMS:
        if item in winner_unique_slots or item in loser_unique_slots:
            continue
        try:
            winner_level = int(winner_items.get(item, 0) or 0)
            loser_level = int(loser_items.get(item, 0) or 0)
        except (TypeError, ValueError):
            continue
        # Fairness guard: swap only when the target item is better and the winner gives
        # their old item back. This mirrors classic IdleRPG steal/swap events without
        # deleting progress from either player. Unique item slots are protected and
        # never transferred or replaced by random events.
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
    _dep_leveling._award(winner, "item_swapped")
    _dep_leveling._inc_stat(winner, "item_swaps_won", 1, room)
    _dep_leveling._check_level_achievements(winner, room)
    _dep_leveling._check_level_achievements(loser, room)
    winner_name = _dep_formatting._display_player(winner)
    loser_name = _dep_formatting._display_player(loser)
    messages.append(
        f"🎒 {winner_name} found {loser_name}'s level {loser_level} {item} while they were distracted! "
        f"{winner_name} leaves their old level {winner_level} {item} behind, which {loser_name} then takes."
    )

# Explicit module dependencies; module-qualified access keeps cyclic domain
# relationships visible without copying names into sibling namespaces.
from . import config as _dep_config  # noqa: E402
from . import constants as _dep_constants  # noqa: E402
from . import formatting as _dep_formatting  # noqa: E402
from . import leveling as _dep_leveling  # noqa: E402
from . import map as _dep_map  # noqa: E402
from . import state as _dep_state  # noqa: E402
