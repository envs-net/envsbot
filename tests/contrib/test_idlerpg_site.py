from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest


PHP = shutil.which("php")


def _checkout_root(path: Path) -> Path:
    """Return the real checkout root when tests run from mutmut's copy.

    mutmut copies the test suite below ``<repo>/mutants`` while the contrib
    website remains in the normal checkout.  Walk upwards until both the
    project marker and the website entrypoint are present instead of assuming
    that ``parents[2]`` is always the repository root.
    """
    resolved = path.resolve()
    search_from = resolved if resolved.is_dir() else resolved.parent
    for candidate in (search_from, *search_from.parents):
        site = candidate / "contrib" / "idlerpg-site" / "index.php"
        if (candidate / "pyproject.toml").is_file() and site.is_file():
            return candidate
    return search_from


ROOT = _checkout_root(Path(__file__))
SITE = ROOT / "contrib" / "idlerpg-site" / "index.php"

pytestmark = pytest.mark.skipif(PHP is None, reason="PHP CLI is not installed")


def test_checkout_root_uses_repository_outside_mutmut_copy(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    site = checkout / "contrib" / "idlerpg-site" / "index.php"
    site.parent.mkdir(parents=True)
    site.write_text("<?php\n", encoding="utf-8")
    (checkout / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    mutant_test = checkout / "mutants" / "tests" / "contrib" / "test_idlerpg_site.py"
    mutant_test.parent.mkdir(parents=True)
    mutant_test.write_text("", encoding="utf-8")

    assert _checkout_root(mutant_test) == checkout
    assert _checkout_root(site) == checkout


def _player(name: str, *, rank: int, online: bool, level: int) -> dict[str, object]:
    now = int(time.time())
    return {
        "rank": rank,
        "name": name,
        "character": name,
        "class": "sysadmin" if name == "Alice" else "wizard",
        "title": "Founder" if name == "Alice" else "",
        "level": level,
        "ttl": 12_345 + rank,
        "alignment": "good" if name == "Alice" else "neutral",
        "idled": 90_000,
        "played_for": 500_000,
        "item_sum": 200,
        "items": {"weapon": 150, "shield": 50},
        "unique_items": {"weapon": "The Great Hammer of /bin/sh"} if name == "Alice" else {},
        "unique_item_bonuses": [
            {
                "slot": "weapon",
                "name": "The Great Hammer of /bin/sh",
                "tier": 1,
                "item_level": 150,
                "min_level": 40,
                "next_upgrade_level": 52,
                "bonus": "battle_bonus",
                "bonus_percent": 8,
            }
        ]
        if name == "Alice"
        else [],
        "stats": {"quests_completed": 4, "battles_lost": 5, "battles_won": 12, "team_battles_lost": 2},
        "achievements": [
            {
                "key": "founder",
                "title": "Founder",
                "description": "registered an IdleRPG character",
            }
        ],
        "x": 300 + rank,
        "y": 230 + rank,
        "region": "Velbragh",
        "online": online,
        "created_at": now - 500_000,
        "last_seen": now - 30,
    }


def _write_room(root: Path, slug: str, room: str, players: list[dict[str, object]]) -> None:
    now = int(time.time())
    room_dir = root / slug
    room_dir.mkdir(parents=True)
    achievements = [
        {
            "key": "founder",
            "title": "Founder",
            "description": "registered an IdleRPG character",
        }
    ]
    quest = {
        "type": "grid",
        "text": "Cross the quiet roads",
        "started_at": now - 500,
        "complete_at": now + 3_600,
        "route": [[100, 100], [200, 180], [300, 230]],
        "route_index": 1,
        "current_target": [200, 180],
        "questers": [player["name"] for player in players[:2]],
    }
    events = [
        {
            "ts": now - 10,
            "kind": "achievement",
            "text": "Alice unlocked Founder",
            "players": ["Alice"],
        },
        {
            "ts": now - 20,
            "kind": "quest",
            "text": "The quest started",
            "players": [player["name"] for player in players[:2]],
        },
    ]
    hall_of_fame = [
        {
            "id": "20260101-000000",
            "started_at": now - 1_000_000,
            "ended_at": now - 500_000,
            "champion": players[0]["name"],
            "top": players,
        }
    ]
    payload = {
        "generated_at": now,
        "room": room,
        "slug": slug,
        "map": {"width": 500, "height": 500},
        "season": {
            "id": "20260701-000000",
            "started_at": now - 10_000,
            "ends_at": now + 50_000,
        },
        "players_total": len(players),
        "players_online": sum(bool(player["online"]) for player in players),
        "leaderboard": players,
        "players": players,
        "quest": quest,
        "events": events,
        "hall_of_fame": hall_of_fame,
        "achievement_catalog": achievements,
        "rules": {
            "tick_seconds": 60,
            "message_penalty": 30,
            "quest_interval": 3_600,
            "event_chance": 0.25,
            "season_enabled": True,
            "season_duration_days": 30,
            "unique_items_enabled": True,
        },
    }
    files = {
        "room.json": payload,
        "leaderboard.json": {"generated_at": now, "room": room, "players": players},
        "players.json": {"generated_at": now, "room": room, "players": players},
        "map.json": {
            "generated_at": now,
            "room": room,
            "width": 500,
            "height": 500,
            "players": players,
            "quest": quest,
        },
        "events.json": {"generated_at": now, "room": room, "events": events},
        "hall_of_fame.json": {
            "generated_at": now,
            "room": room,
            "seasons": hall_of_fame,
        },
        "achievements.json": {
            "generated_at": now,
            "room": room,
            "achievements": achievements,
        },
    }
    for filename, value in files.items():
        (room_dir / filename).write_text(json.dumps(value), encoding="utf-8")


def _export_tree(tmp_path: Path) -> Path:
    alpha = [_player("Alice", rank=1, online=True, level=52), _player("Bob", rank=2, online=False, level=40)]
    beta = [_player("Carol", rank=1, online=True, level=33)]
    _write_room(tmp_path, "alpha_at_conference.example.org", "alpha@conference.example.org", alpha)
    _write_room(tmp_path, "beta_at_conference.example.org", "beta@conference.example.org", beta)
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "generated_at": int(time.time()),
                "rooms": [
                    {
                        "room": "alpha@conference.example.org",
                        "slug": "alpha_at_conference.example.org",
                        "players_total": 2,
                        "players_online": 1,
                    },
                    {
                        "room": "beta@conference.example.org",
                        "slug": "beta_at_conference.example.org",
                        "players_total": 1,
                        "players_online": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _render(data_dir: Path, *, site: Path = SITE, **query: str) -> str:
    env = dict(os.environ, IDLERPG_DATA_DIR=str(data_dir))
    result = subprocess.run(
        [
            PHP,
            "-d",
            "display_errors=1",
            "-d",
            "error_reporting=32767",
            "-r",
            "parse_str($argv[1], $_GET); include $argv[2];",
            urlencode(query),
            str(site),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.stderr == ""
    lowered = result.stdout.lower()
    assert "warning" not in lowered
    assert "notice" not in lowered
    assert "fatal error" not in lowered
    return result.stdout


def test_idlerpg_site_renders_complete_views(tmp_path: Path) -> None:
    data_dir = _export_tree(tmp_path)
    expected = {
        "home": "Top 5 players",
        "players": "Players",
        "achievements": "unlocked by 2/2 players",
        "quest": "Current Quest",
        "events": "Events",
        "map": "World Map",
        "hof": "Current season",
        "rules": "Game rules & exported configuration",
        "commands": "Room administration",
    }
    for view, marker in expected.items():
        html = _render(data_dir, view=view, room="alpha_at_conference.example.org")
        assert marker in html
        if view == "quest":
            assert "<strong>Deadline:</strong>" in html
            assert "the displayed time is the deadline" in html


def test_idlerpg_site_profile_filters_and_room_switching(tmp_path: Path) -> None:
    data_dir = _export_tree(tmp_path)
    profile = _render(
        data_dir,
        view="players",
        room="alpha_at_conference.example.org",
        character="Alice",
    )
    assert "Unique-item bonuses" in profile
    assert "The Great Hammer of /bin/sh" in profile
    assert "tier 1" in profile
    assert "next tier from lv.52" in profile
    assert "Battles Lost" in profile
    assert "Team Battles Lost" in profile
    assert profile.index("Battles Won") < profile.index("Battles Lost")
    assert profile.index("Battles Lost") < profile.index("Team Battles Lost")
    assert profile.index("Team Battles Lost") < profile.index("Quests Completed")

    filtered = _render(
        data_dir,
        view="players",
        room="alpha_at_conference.example.org",
        q="alice",
        status="online",
    )
    assert "1 matching players" in filtered
    assert "Bob" not in filtered

    beta = _render(data_dir, view="home", room="beta_at_conference.example.org")
    assert "beta@conference.example.org" in beta
    assert "Carol" in beta
    assert "character=Alice" not in beta


def test_idlerpg_site_rejects_unknown_or_unsafe_room_slug(tmp_path: Path) -> None:
    data_dir = _export_tree(tmp_path)
    html = _render(data_dir, view="home", room="../../etc/passwd")
    assert "../../etc/passwd" not in html
    assert "alpha@conference.example.org" in html


def test_idlerpg_site_prefers_configured_default_room(tmp_path: Path) -> None:
    data_dir = _export_tree(tmp_path)
    configured_site = tmp_path / "index.php"
    source = SITE.read_text(encoding="utf-8")
    configured_site.write_text(
        source.replace(
            "const IDLERPG_DEFAULT_ROOM_SLUG = 'room_at_conference.example.org';",
            "const IDLERPG_DEFAULT_ROOM_SLUG = 'beta_at_conference.example.org';",
            1,
        ),
        encoding="utf-8",
    )

    html = _render(data_dir, site=configured_site, view="home")

    assert "beta@conference.example.org" in html
    assert "Carol" in html
    assert "alpha@conference.example.org" in html  # still available in selector


def test_idlerpg_site_commands_match_available_admin_commands(tmp_path: Path) -> None:
    data_dir = _export_tree(tmp_path)
    html = _render(
        data_dir,
        view="commands",
        room="alpha_at_conference.example.org",
    )

    for command in (
        ",idlerpg push",
        ",idlerpg setlevel",
        ",idlerpg reset",
        ",idlerpg delete",
        ",idlerpg export",
        ",idlerpg season end",
        ",idlerpg season reset",
        ",idlerpg season discard confirm",
        ",idlerpg season extend",
        ",idlerpg season clear-end",
        ",idlerpg hof clear confirm",
    ):
        assert command in html


def test_idlerpg_site_uses_singular_day_label(tmp_path: Path) -> None:
    data_dir = _export_tree(tmp_path)
    html = _render(
        data_dir,
        view="players",
        room="alpha_at_conference.example.org",
        character="Alice",
    )

    assert "1 day, 01:00:00" in html
    assert "1 days, 01:00:00" not in html
