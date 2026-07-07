"""Split module for plugins/idlerpg.py: events."""

from __future__ import annotations
import random
from typing import Any


def _alignment_battle_factor(player: dict[str, Any], outcome: str) -> float:
    alignment = str(player.get("alignment") or "n")[:1].lower()
    if alignment == "e" and outcome == "win":
        return 1.10
    if alignment == "g" and outcome == "loss":
        return 0.90
    if alignment == "n":
        return 0.97
    return 1.0


def _battle_amount(player: dict[str, Any], base: int, outcome: str) -> int:
    amount = _penalty_for(int(player.get("level", 0)), base)
    return max(1, int(amount * _alignment_battle_factor(player, outcome)))


async def _maybe_run_random_event(room: dict[str, Any], room_jid: str, messages: list[str]) -> None:
    players = [
        (str(jid), _normalize_player(str(jid), player))
        for jid, player in room.get("players", {}).items()
        if isinstance(player, dict) and _is_player_online(room_jid, str(jid), player)
    ]
    if not players or random.random() >= EVENT_CHANCE:
        return

    events: list[tuple[float, str]] = []
    if len(players) >= 2:
        events.append((BATTLE_EVENT_WEIGHT, "battle"))
    if len(players) >= 6:
        events.append((TEAM_BATTLE_EVENT_WEIGHT, "team_battle"))
    events.append((ITEM_EVENT_WEIGHT, "item"))
    events.append((ITEM_DAMAGE_EVENT_WEIGHT, "item_damage"))
    if len(players) >= 2:
        events.append((ITEM_STEAL_EVENT_WEIGHT, "item_steal"))
        events.append((ALIGNMENT_EVENT_WEIGHT, "alignment"))

    configured_weight = (
        BATTLE_EVENT_WEIGHT
        + TEAM_BATTLE_EVENT_WEIGHT
        + ITEM_EVENT_WEIGHT
        + ITEM_DAMAGE_EVENT_WEIGHT
        + ITEM_STEAL_EVENT_WEIGHT
        + ALIGNMENT_EVENT_WEIGHT
    )
    events.append((max(0.0, 1.0 - configured_weight), "fate"))
    events = [(max(0.0, weight), event) for weight, event in events if weight > 0]
    total_weight = sum(weight for weight, _event in events)
    if total_weight <= 0:
        return

    event_roll = random.random() * total_weight
    selected = "fate"
    for weight, event in events:
        if event_roll < weight:
            selected = event
            break
        event_roll -= weight

    if selected == "battle":
        _run_pvp_battle(players, messages, room)
        return
    if selected == "team_battle":
        _run_team_battle(players, messages, room)
        return
    if selected == "item":
        _run_item_blessing(players, messages, room)
        return
    if selected == "item_damage":
        before = len(messages)
        _run_item_damage(players, messages, room)
        if len(messages) > before:
            return
    if selected == "item_steal":
        before = len(messages)
        _run_item_swap(players, messages, room)
        if len(messages) > before:
            return
    if selected == "alignment" and _run_alignment_bonus(players, messages, room):
        return

    _run_godsend_or_calamity(players, messages, room)


def _run_pvp_battle(
    players: list[tuple[str, dict[str, Any]]],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> None:
    pair = _choose_two_players(players)
    if pair is None:
        return
    (_attacker_jid, attacker), (_defender_jid, defender) = pair
    attacker_power = _battle_power(attacker)
    defender_power = _battle_power(defender)
    attacker_roll = random.randint(0, attacker_power)
    defender_roll = random.randint(0, defender_power)
    attacker_won = attacker_roll >= defender_roll
    attacker_name = _display_player(attacker)
    defender_name = _display_player(defender)

    if attacker_won:
        amount = _battle_clock_delta(attacker, defender, "win")
        changed = _remove_time(attacker, amount)
        messages.append(
            f"⚔️ {attacker_name} [{attacker_roll}/{attacker_power}] has challenged "
            f"{defender_name} [{defender_roll}/{defender_power}] in combat and won! "
            f"{_duration_clock(changed)} is removed from {_possessive(attacker_name)} clock."
        )
        messages.append(_next_level_line(attacker))
        winner, loser = attacker, defender
        _award(winner, "battle_winner")
        _inc_stat(winner, "battles_won", 1, room)
    else:
        amount = _battle_clock_delta(attacker, defender, "loss")
        changed = _add_time(attacker, amount)
        messages.append(
            f"⚔️ {attacker_name} [{attacker_roll}/{attacker_power}] has challenged "
            f"{defender_name} [{defender_roll}/{defender_power}] in combat and lost! "
            f"{_duration_clock(changed)} is added to {_possessive(attacker_name)} clock."
        )
        messages.append(_next_level_line(attacker))
        winner, loser = defender, attacker
        _award(winner, "battle_winner")
        _inc_stat(winner, "battles_won", 1, room)

    _maybe_critical_strike(winner, loser, messages)
    _maybe_battle_item_drop(winner, loser, messages, room)


def _run_team_battle(
    players: list[tuple[str, dict[str, Any]]],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> None:
    if len(players) < 6:
        return
    selected = random.sample(players, 6)
    team_a = selected[:3]
    team_b = selected[3:]
    names_a = [_display_player(player) for _jid, player in team_a]
    names_b = [_display_player(player) for _jid, player in team_b]
    power_a = sum(_battle_power(player) for _jid, player in team_a)
    power_b = sum(_battle_power(player) for _jid, player in team_b)
    roll_a = random.randint(0, max(1, power_a))
    roll_b = random.randint(0, max(1, power_b))
    team_a_won = roll_a >= roll_b
    winners = team_a if team_a_won else team_b
    losers = team_b if team_a_won else team_a
    affected = min(max(1, int(player.get("next", 0) or 0)) for _jid, player in winners)
    changed = max(1, int(affected * max(0, TEAM_BATTLE_PERCENT) / 100))
    for _jid, player in winners:
        _remove_time(player, changed)
        _award(player, "team_battle_winner")
        _inc_stat(player, "team_battles_won", 1, room)
    for _jid, player in losers:
        _add_time(player, changed)
    messages.append(
        f"🛡️ {', '.join(names_a)} [{roll_a}/{power_a}] have team battled "
        f"{', '.join(names_b)} [{roll_b}/{power_b}] and {'won' if team_a_won else 'lost'}! "
        f"{_duration_clock(changed)} is {'removed from their clocks' if team_a_won else 'added to their clocks'}."
    )
    for _jid, player in winners + losers:
        messages.append(_next_level_line(player))


def _run_alignment_bonus(
    players: list[tuple[str, dict[str, Any]]],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> bool:
    groups: dict[str, list[dict[str, Any]]] = {"g": [], "n": [], "e": []}
    for _jid, player in players:
        alignment = str(player.get("alignment") or "n")[:1].lower()
        groups.setdefault(alignment if alignment in groups else "n", []).append(player)
    candidates = [group for group in groups.values() if len(group) >= 2]
    if not candidates:
        return False
    chosen = random.choice(candidates)
    selected = random.sample(chosen, 2)
    names = [_display_player(player) for player in selected]
    alignment = _alignment_name(selected[0].get("alignment"))
    bonus_percent = ALIGNMENT_BONUS_PERCENT + max(_unique_bonus_percent(player, "alignment_bonus") for player in selected)
    if alignment == "good":
        lead = f"{names[0]} and {names[1]} have not let the iniquities of evil men poison them."
    elif alignment == "evil":
        lead = f"{names[0]} and {names[1]} revel in their wickedness and draw power from the darkness."
    else:
        lead = f"{names[0]} and {names[1]} find perfect balance between fortune and disaster."
    messages.append(
        f"⚖️ {lead} {bonus_percent}% of their time is removed from their clocks."
    )
    for player in selected:
        amount = _percent_amount(player, bonus_percent)
        _remove_time(player, amount)
        _award(player, "alignment_blessed")
        _inc_stat(player, "alignment_events", 1, room)
        messages.append(_next_level_line(player))
    return True


def _run_godsend_or_calamity(
    players: list[tuple[str, dict[str, Any]]],
    messages: list[str],
    room: dict[str, Any] | None = None,
) -> None:
    _jid, player = random.choice(players)
    name = _display_player(player)
    level = int(player.get("level", 0) or 0)
    if random.random() < 0.5:
        amount = _random_percent_amount(player, CALAMITY_MIN_PERCENT, CALAMITY_MAX_PERCENT)
        amount = _adjust_percent_amount(amount, player, "calamity_reduction")
        changed = _add_time(player, amount)
        player.setdefault("penalties", {})["calamity"] = (
            int(player.get("penalties", {}).get("calamity", 0) or 0) + changed
        )
        _award(player, "unlucky")
        _inc_stat(player, "calamities", 1, room)
        messages.append(
            f"💥 {name} {random.choice(CALAMITIES)} near {_player_region(player)}. This terrible calamity has slowed them "
            f"{_duration_clock(changed)} from level {level + 1}."
        )
        messages.append(_next_level_line(player))
    else:
        amount = _random_percent_amount(player, GODSEND_MIN_PERCENT, GODSEND_MAX_PERCENT)
        amount = _adjust_percent_amount(amount, player, "godsend_bonus", increase=True)
        changed = _remove_time(player, amount)
        _award(player, "lucky")
        _inc_stat(player, "godsends", 1, room)
        messages.append(
            f"🌟 {name} {random.choice(GODSENDS)} near {_player_region(player)}. This wondrous godsend has accelerated them "
            f"{_duration_clock(changed)} towards level {level + 1}."
        )
        messages.append(_next_level_line(player))
