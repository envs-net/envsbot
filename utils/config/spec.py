"""Declarative configuration schema for envsbot.

Every top-level setting is described here once. Defaults, accepted types, Python
config names and startup/reload behavior are derived from this schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MISSING = object()

@dataclass(frozen=True)
class ConfigField:
    default: Any
    python_key: str
    accepted_type: type | tuple[type, ...]
    startup_only: bool = False
    required: bool = False
    minimum: float | int | None = None
    maximum: float | int | None = None
    minimum_exclusive: bool = False
    choices: tuple[str, ...] = ()
    allow_empty: bool = False
    section: str = "Other"
    description: str = ""
    sensitive: bool = False
    sample: Any = MISSING


@dataclass(frozen=True)
class NestedConfigField:
    """Metadata for one option inside a structured top-level config group."""

    default: Any
    accepted_type: type | tuple[type, ...]
    description: str
    runtime_keys: tuple[str, ...] = ()
    legacy_key: str | None = None
    allow_empty: bool = False

IDLERPG_FIELDS: dict[str, NestedConfigField] = {
    'tick_seconds': NestedConfigField(60, int, 'Game loop interval in seconds.', runtime_keys=('TICK_SECONDS',), legacy_key='idlerpg_tick_seconds', allow_empty=False),
    'rp_base': NestedConfigField(600, int, 'Base value for the IdleRPG level timer formula.', runtime_keys=('RP_BASE',), legacy_key='idlerpg_rp_base', allow_empty=False),
    'rp_step': NestedConfigField(1.16, (int, float), 'Exponent step used by the IdleRPG level timer formula.', runtime_keys=('RP_STEP',), legacy_key='idlerpg_rp_step', allow_empty=False),
    'penalty_step': NestedConfigField(1.14, (int, float), 'Exponent step used to scale message/logout penalties by level.', runtime_keys=('PENALTY_STEP',), legacy_key='idlerpg_penalty_step', allow_empty=False),
    'message_penalty': NestedConfigField(1, int, 'Base multiplier for normal-message penalties.', runtime_keys=('MESSAGE_PENALTY',), legacy_key='idlerpg_message_penalty', allow_empty=False),
    'logout_penalty': NestedConfigField(20, int, 'Base logout penalty.', runtime_keys=('LOGOUT_PENALTY',), legacy_key='idlerpg_logout_penalty', allow_empty=False),
    'logout_grace_seconds': NestedConfigField(300, int, 'Reconnect grace period before applying a logout penalty.', runtime_keys=('LOGOUT_GRACE_SECONDS',), legacy_key='idlerpg_logout_grace_seconds', allow_empty=False),
    'max_penalty': NestedConfigField(604800, int, 'Maximum accumulated penalty; zero keeps the existing no-cap behavior.', runtime_keys=('MAX_PENALTY',), legacy_key='idlerpg_max_penalty', allow_empty=False),
    'count_command_messages': NestedConfigField(False, bool, 'Whether bot command messages also count as IdleRPG activity penalties.', runtime_keys=('COUNT_COMMAND_MESSAGES',), legacy_key='idlerpg_count_command_messages', allow_empty=False),
    'page_size': NestedConfigField(10, int, 'Default page size for IdleRPG list commands.', runtime_keys=('PAGE_SIZE',), legacy_key='idlerpg_page_size', allow_empty=False),
    'map_x': NestedConfigField(500, int, 'IdleRPG map width.', runtime_keys=('MAP_X',), legacy_key='idlerpg_map_x', allow_empty=False),
    'map_y': NestedConfigField(500, int, 'IdleRPG map height.', runtime_keys=('MAP_Y',), legacy_key='idlerpg_map_y', allow_empty=False),
    'map_step_per_second': NestedConfigField(1, int, 'Grid movement steps per simulated second.', runtime_keys=('MAP_STEP_PER_SECOND',), legacy_key='idlerpg_map_step_per_second', allow_empty=False),
    'map_step_per_tick': NestedConfigField(1, int, 'Legacy alias for map_step_per_second.', runtime_keys=('MAP_STEP_PER_TICK',), legacy_key='idlerpg_map_step_per_tick', allow_empty=False),
    'grid_battle_enabled': NestedConfigField(True, bool, 'Enable battles triggered by players sharing a map grid position.', runtime_keys=('GRID_BATTLE_ENABLED',), legacy_key='idlerpg_grid_battle_enabled', allow_empty=False),
    'quest_grid_step_seconds': NestedConfigField(30, int, 'Seconds between directed map steps for grid-quest participants.', runtime_keys=('QUEST_GRID_STEP_SECONDS',), legacy_key='idlerpg_quest_grid_step_seconds', allow_empty=False),
    'quest_min_level': NestedConfigField(40, int, 'Minimum character level for automatic quest selection.', runtime_keys=('QUEST_MIN_LEVEL',), legacy_key='idlerpg_quest_min_level', allow_empty=False),
    'quest_min_online_seconds': NestedConfigField(36000, int, 'Minimum online time required for automatic quest selection.', runtime_keys=('QUEST_MIN_ONLINE_SECONDS',), legacy_key='idlerpg_quest_min_online_seconds', allow_empty=False),
    'quest_interval': NestedConfigField(21600, int, 'Delay between automatic quest opportunities.', runtime_keys=('QUEST_INTERVAL',), legacy_key='idlerpg_quest_interval', allow_empty=False),
    'quest_max_per_day': NestedConfigField(2, int, 'Maximum automatically started quests per UTC day; zero means unlimited.', runtime_keys=('QUEST_MAX_PER_DAY',), legacy_key='idlerpg_quest_max_per_day', allow_empty=False),
    'quest_min_duration': NestedConfigField(43200, int, 'Minimum grid-quest deadline.', runtime_keys=('QUEST_MIN_DURATION',), legacy_key='idlerpg_quest_min_duration', allow_empty=False),
    'quest_max_duration': NestedConfigField(86400, int, 'Maximum grid-quest deadline.', runtime_keys=('QUEST_MAX_DURATION',), legacy_key='idlerpg_quest_max_duration', allow_empty=False),
    'quest_grid_enabled': NestedConfigField(True, bool, 'Enable grid-route quests.', runtime_keys=('QUEST_GRID_ENABLED',), legacy_key='idlerpg_quest_grid_enabled', allow_empty=False),
    'quest_grid_weight': NestedConfigField(0.5, (int, float), 'Relative selection weight for grid quests.', runtime_keys=('QUEST_GRID_WEIGHT',), legacy_key='idlerpg_quest_grid_weight', allow_empty=False),
    'quest_grid_min_points': NestedConfigField(2, int, 'Minimum route points for a grid quest.', runtime_keys=('QUEST_GRID_MIN_POINTS',), legacy_key='idlerpg_quest_grid_min_points', allow_empty=False),
    'quest_grid_max_points': NestedConfigField(3, int, 'Maximum route points for a grid quest.', runtime_keys=('QUEST_GRID_MAX_POINTS',), legacy_key='idlerpg_quest_grid_max_points', allow_empty=False),
    'quest_time_enabled': NestedConfigField(True, bool, 'Enable time-survival quests.', runtime_keys=('QUEST_TIME_ENABLED',), legacy_key='idlerpg_quest_time_enabled', allow_empty=False),
    'quest_time_weight': NestedConfigField(0.5, (int, float), 'Relative selection weight for time quests.', runtime_keys=('QUEST_TIME_WEIGHT',), legacy_key='idlerpg_quest_time_weight', allow_empty=False),
    'quest_time_min_duration': NestedConfigField(43200, int, 'Minimum time-quest duration.', runtime_keys=('QUEST_TIME_MIN_DURATION',), legacy_key='idlerpg_quest_time_min_duration', allow_empty=False),
    'quest_time_max_duration': NestedConfigField(86400, int, 'Maximum time-quest duration.', runtime_keys=('QUEST_TIME_MAX_DURATION',), legacy_key='idlerpg_quest_time_max_duration', allow_empty=False),
    'event_chance': NestedConfigField(0.01, (int, float), 'Chance of a random IdleRPG event on each eligible tick.', runtime_keys=('EVENT_CHANCE',), legacy_key='idlerpg_event_chance', allow_empty=False),
    'item_chance': NestedConfigField(0.2, (int, float), 'Relative random-event weight for ordinary item events.', runtime_keys=('ITEM_CHANCE',), legacy_key='idlerpg_item_chance', allow_empty=False),
    'battle_event_weight': NestedConfigField(0.55, (int, float), 'Relative random-event weight for battles.', runtime_keys=('BATTLE_EVENT_WEIGHT',), legacy_key='idlerpg_battle_event_weight', allow_empty=False),
    'team_battle_event_weight': NestedConfigField(0.08, (int, float), 'Relative random-event weight for team battles.', runtime_keys=('TEAM_BATTLE_EVENT_WEIGHT',), legacy_key='idlerpg_team_battle_event_weight', allow_empty=False),
    'boss_event_weight': NestedConfigField(0.06, (int, float), 'Relative random-event weight for boss battles.', runtime_keys=('BOSS_EVENT_WEIGHT',), legacy_key='idlerpg_boss_event_weight', allow_empty=False),
    'item_event_weight': NestedConfigField(0.15, (int, float), 'Relative random-event weight for item upgrades.', runtime_keys=('ITEM_EVENT_WEIGHT',), legacy_key='idlerpg_item_event_weight', allow_empty=False),
    'item_damage_event_weight': NestedConfigField(0.08, (int, float), 'Relative random-event weight for item damage.', runtime_keys=('ITEM_DAMAGE_EVENT_WEIGHT',), legacy_key='idlerpg_item_damage_event_weight', allow_empty=False),
    'item_steal_event_weight': NestedConfigField(0.04, (int, float), 'Relative random-event weight for item stealing.', runtime_keys=('ITEM_STEAL_EVENT_WEIGHT',), legacy_key='idlerpg_item_steal_event_weight', allow_empty=False),
    'alignment_event_weight': NestedConfigField(0.1, (int, float), 'Relative random-event weight for alignment events.', runtime_keys=('ALIGNMENT_EVENT_WEIGHT',), legacy_key='idlerpg_alignment_event_weight', allow_empty=False),
    'critical_strike_chance': NestedConfigField(0.02857142857142857, (int, float), 'Critical-strike chance for neutral players.', runtime_keys=('CRITICAL_STRIKE_CHANCE',), legacy_key='idlerpg_critical_strike_chance', allow_empty=False),
    'critical_strike_chance_good': NestedConfigField(0.02, (int, float), 'Critical-strike chance for good players.', runtime_keys=('CRITICAL_STRIKE_CHANCE_GOOD',), legacy_key='idlerpg_critical_strike_chance_good', allow_empty=False),
    'critical_strike_chance_evil': NestedConfigField(0.05, (int, float), 'Critical-strike chance for evil players.', runtime_keys=('CRITICAL_STRIKE_CHANCE_EVIL',), legacy_key='idlerpg_critical_strike_chance_evil', allow_empty=False),
    'item_drop_chance': NestedConfigField(0.02, (int, float), 'Chance of an item being stolen/dropped in an eligible battle.', runtime_keys=('ITEM_DROP_CHANCE',), legacy_key='idlerpg_item_drop_chance', allow_empty=False),
    'level_battle_chance_below_25': NestedConfigField(0.25, (int, float), 'Level-up battle chance below level 25.', runtime_keys=('LEVEL_BATTLE_CHANCE_BELOW_25',), legacy_key='idlerpg_level_battle_chance_below_25', allow_empty=False),
    'level_battle_chance_at_25': NestedConfigField(1.0, (int, float), 'Level-up battle chance from level 25 onward.', runtime_keys=('LEVEL_BATTLE_CHANCE_AT_25',), legacy_key='idlerpg_level_battle_chance_at_25', allow_empty=False),
    'battle_win_min_percent': NestedConfigField(7, int, 'Minimum TTL reduction percentage for a battle win.', runtime_keys=('BATTLE_WIN_MIN_PERCENT',), legacy_key='idlerpg_battle_win_min_percent', allow_empty=False),
    'battle_loss_min_percent': NestedConfigField(7, int, 'Minimum TTL penalty percentage for a battle loss.', runtime_keys=('BATTLE_LOSS_MIN_PERCENT',), legacy_key='idlerpg_battle_loss_min_percent', allow_empty=False),
    'critical_min_percent': NestedConfigField(5, int, 'Minimum critical-strike percentage.', runtime_keys=('CRITICAL_MIN_PERCENT',), legacy_key='idlerpg_critical_min_percent', allow_empty=False),
    'critical_max_percent': NestedConfigField(25, int, 'Maximum critical-strike percentage.', runtime_keys=('CRITICAL_MAX_PERCENT',), legacy_key='idlerpg_critical_max_percent', allow_empty=False),
    'godsend_min_percent': NestedConfigField(5, int, 'Minimum godsend percentage.', runtime_keys=('GODSEND_MIN_PERCENT',), legacy_key='idlerpg_godsend_min_percent', allow_empty=False),
    'godsend_max_percent': NestedConfigField(12, int, 'Maximum godsend percentage.', runtime_keys=('GODSEND_MAX_PERCENT',), legacy_key='idlerpg_godsend_max_percent', allow_empty=False),
    'calamity_min_percent': NestedConfigField(5, int, 'Minimum calamity percentage.', runtime_keys=('CALAMITY_MIN_PERCENT',), legacy_key='idlerpg_calamity_min_percent', allow_empty=False),
    'calamity_max_percent': NestedConfigField(12, int, 'Maximum calamity percentage.', runtime_keys=('CALAMITY_MAX_PERCENT',), legacy_key='idlerpg_calamity_max_percent', allow_empty=False),
    'alignment_bonus_percent': NestedConfigField(7, int, 'Alignment-based bonus percentage.', runtime_keys=('ALIGNMENT_BONUS_PERCENT',), legacy_key='idlerpg_alignment_bonus_percent', allow_empty=False),
    'quest_reward_percent': NestedConfigField(25, int, 'Quest reward percentage.', runtime_keys=('QUEST_REWARD_PERCENT',), legacy_key='idlerpg_quest_reward_percent', allow_empty=False),
    'team_battle_percent': NestedConfigField(20, int, 'Team-battle reward/penalty percentage.', runtime_keys=('TEAM_BATTLE_PERCENT',), legacy_key='idlerpg_team_battle_percent', allow_empty=False),
    'boss_min_players': NestedConfigField(3, int, 'Minimum players selected for a boss encounter.', runtime_keys=('BOSS_MIN_PLAYERS',), legacy_key='idlerpg_boss_min_players', allow_empty=False),
    'boss_max_players': NestedConfigField(5, int, 'Maximum players selected for a boss encounter.', runtime_keys=('BOSS_MAX_PLAYERS',), legacy_key='idlerpg_boss_max_players', allow_empty=False),
    'boss_min_level': NestedConfigField(10, int, 'Minimum level for boss participants.', runtime_keys=('BOSS_MIN_LEVEL',), legacy_key='idlerpg_boss_min_level', allow_empty=False),
    'boss_reward_percent': NestedConfigField(12, int, 'Boss victory reward percentage.', runtime_keys=('BOSS_REWARD_PERCENT',), legacy_key='idlerpg_boss_reward_percent', allow_empty=False),
    'boss_loss_percent': NestedConfigField(4, int, 'Boss defeat penalty percentage.', runtime_keys=('BOSS_LOSS_PERCENT',), legacy_key='idlerpg_boss_loss_percent', allow_empty=False),
    'boss_power_min_factor': NestedConfigField(0.75, (int, float), 'Minimum boss power multiplier.', runtime_keys=('BOSS_POWER_MIN_FACTOR',), legacy_key='idlerpg_boss_power_min_factor', allow_empty=False),
    'boss_power_max_factor': NestedConfigField(1.25, (int, float), 'Maximum boss power multiplier.', runtime_keys=('BOSS_POWER_MAX_FACTOR',), legacy_key='idlerpg_boss_power_max_factor', allow_empty=False),
    'manual_duel_max_distance': NestedConfigField(10, int, 'Maximum map distance for a manual duel.', runtime_keys=('MANUAL_DUEL_MAX_DISTANCE',), legacy_key='idlerpg_manual_duel_max_distance', allow_empty=False),
    'manual_duel_cooldown_seconds': NestedConfigField(3600, int, 'Cooldown applied to both manual duelists.', runtime_keys=('MANUAL_DUEL_COOLDOWN_SECONDS',), legacy_key='idlerpg_manual_duel_cooldown_seconds', allow_empty=False),
    'unique_items_enabled': NestedConfigField(True, bool, 'Enable unique themed IdleRPG items.', runtime_keys=('UNIQUE_ITEMS_ENABLED',), legacy_key='idlerpg_unique_items_enabled', allow_empty=False),
    'unique_item_min_level': NestedConfigField(25, int, 'Minimum level for unique items.', runtime_keys=('UNIQUE_ITEM_MIN_LEVEL',), legacy_key='idlerpg_unique_item_min_level', allow_empty=False),
    'unique_item_chance': NestedConfigField(0.025, (int, float), 'Chance of awarding an eligible unique item.', runtime_keys=('UNIQUE_ITEM_CHANCE',), legacy_key='idlerpg_unique_item_chance', allow_empty=False),
    'announce_login': NestedConfigField(True, bool, 'Announce player logins in the game room.', runtime_keys=('ANNOUNCE_LOGIN',), legacy_key='idlerpg_announce_login', allow_empty=False),
    'announce_top_interval': NestedConfigField(21600, int, 'Interval between automatic top-player announcements.', runtime_keys=('ANNOUNCE_TOP_INTERVAL',), legacy_key='idlerpg_announce_top_interval', allow_empty=False),
    'announce_top_limit': NestedConfigField(5, int, 'Number of players included in top-player announcements.', runtime_keys=('ANNOUNCE_TOP_LIMIT',), legacy_key='idlerpg_announce_top_limit', allow_empty=False),
    'update_room_topic': NestedConfigField(False, bool, 'Allow IdleRPG to update the MUC subject/topic.', runtime_keys=('UPDATE_ROOM_TOPIC',), legacy_key='idlerpg_update_room_topic', allow_empty=False),
    'topic_update_interval': NestedConfigField(14400, int, 'Minimum interval between IdleRPG topic updates.', runtime_keys=('TOPIC_UPDATE_INTERVAL',), legacy_key='idlerpg_topic_update_interval', allow_empty=False),
    'topic_custom_text': NestedConfigField('', str, 'Optional custom prefix for IdleRPG room topics.', runtime_keys=('TOPIC_CUSTOM_TEXT',), legacy_key='idlerpg_topic_custom_text', allow_empty=True),
    'level_reward_min_level': NestedConfigField(50, int, 'Minimum level for level-gated reward badges.', runtime_keys=('LEVEL_REWARD_MIN_LEVEL',), legacy_key='idlerpg_level_reward_min_level', allow_empty=False),
    'season_achievement_gates_enabled': NestedConfigField(True, bool, 'Gate long-term achievements by season age.', runtime_keys=('SEASON_ACHIEVEMENT_GATES_ENABLED',), legacy_key='idlerpg_season_achievement_gates_enabled', allow_empty=False),
    'event_log_limit': NestedConfigField(200, int, 'Number of recent events retained in the in-memory room cache.', runtime_keys=('EVENT_LOG_LIMIT',), legacy_key='idlerpg_event_log_limit', allow_empty=False),
    'event_retention_days': NestedConfigField(90, int, 'Database event-retention age used by maintenance.', runtime_keys=('EVENT_RETENTION_DAYS',), legacy_key='idlerpg_event_retention_days', allow_empty=False),
    'export_event_limit': NestedConfigField(50, int, 'Number of recent events exported in the compact website feed.', runtime_keys=('EXPORT_EVENT_LIMIT',), legacy_key='idlerpg_export_event_limit', allow_empty=False),
    'export_full_season_events': NestedConfigField(False, bool, 'Export the complete active-season event history from SQLite.', runtime_keys=('EXPORT_FULL_SEASON_EVENTS',), legacy_key='idlerpg_export_full_season_events', allow_empty=False),
    'export_season_event_chunk_size': NestedConfigField(1000, int, 'Maximum events per append-friendly full-season export chunk.', runtime_keys=('EXPORT_SEASON_EVENT_CHUNK_SIZE',), legacy_key='idlerpg_export_season_event_chunk_size', allow_empty=False),
    'export_enabled': NestedConfigField(True, bool, 'Enable public IdleRPG JSON exports.', runtime_keys=('EXPORT_ENABLED',), legacy_key='idlerpg_export_enabled', allow_empty=False),
    'export_interval_seconds': NestedConfigField(300, int, 'Minimum interval between automatic public exports; zero exports after every state change.', runtime_keys=('EXPORT_INTERVAL_SECONDS',), legacy_key='idlerpg_export_interval_seconds', allow_empty=False),
    'export_path': NestedConfigField('data/idlerpg', str, 'Filesystem path for public IdleRPG JSON exports.', runtime_keys=('EXPORT_PATH',), legacy_key='idlerpg_export_path', allow_empty=False),
    'export_public_base_url': NestedConfigField('', str, 'Public URL corresponding to the exported JSON data.', runtime_keys=('EXPORT_PUBLIC_BASE_URL',), legacy_key='idlerpg_export_public_base_url', allow_empty=True),
    'website_public_base_url': NestedConfigField('', str, 'Human-facing IdleRPG website root; may be derived from the export URL.', runtime_keys=('WEBSITE_PUBLIC_BASE_URL',), legacy_key='idlerpg_website_public_base_url', allow_empty=True),
    'export_top_limit': NestedConfigField(50, int, 'Maximum leaderboard entries in public exports.', runtime_keys=('EXPORT_TOP_LIMIT',), legacy_key='idlerpg_export_top_limit', allow_empty=False),
    'season_enabled': NestedConfigField(False, bool, 'Enable automatic season timing/rollover.', runtime_keys=('SEASON_ENABLED',), legacy_key='idlerpg_season_enabled', allow_empty=False),
    'season_duration_days': NestedConfigField(90, int, 'Automatic season duration in days; zero means manual/endless.', runtime_keys=('SEASON_DURATION_DAYS',), legacy_key='idlerpg_season_duration_days', allow_empty=False),
    'season_reset_on_rollover': NestedConfigField(False, bool, 'Reset player progression when an automatic season rolls over.', runtime_keys=('SEASON_RESET_ON_ROLLOVER',), legacy_key='idlerpg_season_reset_on_rollover', allow_empty=False),
    'season_hof_size': NestedConfigField(10, int, 'Number of completed seasons retained in the Hall of Fame.', runtime_keys=('SEASON_HOF_SIZE',), legacy_key='idlerpg_season_hof_size', allow_empty=False),
}

DUCK_FIELDS: dict[str, NestedConfigField] = {
    'min_messages': NestedConfigField(150, int, 'Minimum room messages before duck spawning becomes eligible.', runtime_keys=('DEFAULT_MIN_MESSAGES',)),
    'max_messages': NestedConfigField(500, int, 'Maximum room-message threshold before a duck spawn roll.', runtime_keys=('DEFAULT_MAX_MESSAGES',)),
    'spawn_chance': NestedConfigField(20, int, 'Chance denominator/weight used when an eligible duck spawn is rolled.', runtime_keys=('DUCK_SPAWN_CHANCE',)),
    'max_ducks_per_day': NestedConfigField(3, int, 'Maximum ducks spawned per room and day.', runtime_keys=('MAX_DUCKS_PER_DAY',)),
    'timeout': NestedConfigField(0, int, 'Seconds before an uncaught duck expires; zero keeps the configured no-timeout behavior.', runtime_keys=('DUCK_TIMEOUT',)),
    'count_commands': NestedConfigField(False, bool, 'Whether bot commands count toward duck spawn message thresholds.', runtime_keys=('COUNT_COMMAND_MESSAGES',)),
    'state_save_every': NestedConfigField(1, int, 'Persist duck state after this many relevant state updates.', runtime_keys=('DUCK_STATE_SAVE_EVERY',)),
}

USER_FIELDS: dict[str, NestedConfigField] = {
    'max_room_nicks': NestedConfigField(5, int, 'Maximum remembered nicknames per room for one tracked user.', runtime_keys=('MAX_ROOM_NICKS',)),
}

NESTED_CONFIG_FIELDS: dict[str, dict[str, NestedConfigField]] = {
    'idlerpg': IDLERPG_FIELDS,
    'ducks': DUCK_FIELDS,
    'users': USER_FIELDS,
}

def nested_config_defaults(group: str) -> dict[str, Any]:
    return {key: field.default for key, field in NESTED_CONFIG_FIELDS.get(group, {}).items()}

CONFIG_FIELDS: dict[str, ConfigField] = {
    'jid': ConfigField(MISSING, 'JID', str, startup_only=True, required=True, section='XMPP Account', description='XMPP account used by the bot.', sample='envsbot@domain.tld'),
    'password': ConfigField(MISSING, 'PASSWORD', str, startup_only=True, required=True, section='XMPP Account', description='Password.', sensitive=True, sample='yourpassword'),
    'nick': ConfigField(MISSING, 'NICK', str, required=True, section='XMPP Account', description='Nick.', sample='EnvsBot'),
    'resource': ConfigField(None, 'RESOURCE', str, startup_only=True, section='XMPP Account', description='Optional XMPP resource. Set to None to let Slixmpp/server choose one.', sample='service'),
    'owner': ConfigField(MISSING, 'OWNER', str, required=True, section='XMPP Account', description='Bare JID of the bot owner. The owner has the highest runtime role.', sample='owner@domain.tld'),
    'admins': ConfigField(MISSING, 'ADMINS', list, section='XMPP Account', description='Optional additional privileged users. Roles can also be managed at runtime through the users commands.', sample=[]),
    'host': ConfigField(None, 'CONNECT_HOST', str, startup_only=True, section='Connection', description='Optional connection host override. None uses the domain from JID.'),
    'port': ConfigField(5222, 'CONNECT_PORT', int, startup_only=True, minimum=1, maximum=65535, section='Connection', description='XMPP client-to-server port. 5222 = normal C2S with STARTTLS 5223 = direct TLS / legacy SSL when your server requires it'),
    'direct_tls': ConfigField(False, 'CONNECT_DIRECT_TLS', bool, startup_only=True, section='Connection', description='False = regular STARTTLS on port 5222. True = direct TLS / legacy SSL, commonly on port 5223.'),
    'xmpp_query_timeout_seconds': ConfigField(8, 'XMPP_QUERY_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='Connection', description='XMPP query timeout used by diagnostic/info commands.'),
    'xmpp_compliance_max_read_bytes': ConfigField(262144, 'XMPP_COMPLIANCE_MAX_READ_BYTES', int, section='Connection', description='Maximum bytes read from compliance.conversations.im for ,xmpp compliance. The command only needs a small HTML preview containing the score marker.'),
    'loglevel': ConfigField('INFO', 'LOG_LEVEL', str, section='Bot Runtime', description='Python logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.'),
    'log_dir': ConfigField('logs', 'LOG_DIR', str, startup_only=True, section='Bot Runtime', description='Directory for the rotating envsbot.log file. Use an absolute path such as /var/log/envsbot with the hardened systemd unit.'),
    'prefix': ConfigField(',', 'COMMAND_PREFIX', str, section='Bot Runtime', description='Command prefix used to trigger bot commands in rooms and direct chats.'),
    'timezone': ConfigField(MISSING, 'TIMEZONE', str, section='Bot Runtime', description='Default timezone for bot-side date/time handling.', sample='Europe/Berlin'),
    'db': ConfigField('bot.db', 'DB_FILE', str, startup_only=True, section='Bot Runtime', description='SQLite database file, relative to the bot directory unless absolute.', sample='data/bot.db'),
    'runtime_data_dir': ConfigField(None, 'RUNTIME_DATA_DIR', str, startup_only=True, section='Bot Runtime', description='Directory for mutable support files such as vcard.py, chat_slang.csv and profile hash markers. None keeps the historical application-root location for compatibility. Hardened systemd installs should set /var/lib/envsbot.', sample=None),
    'restart_notification_file': ConfigField('data/envsbot_restart_notification.json', 'RESTART_NOTIFICATION_FILE', str, section='Bot Runtime', description='File used to remember who requested a bot restart across process restarts. Keep this outside /tmp when systemd PrivateTmp=true is enabled.'),
    'stop_cmd': ConfigField([], 'STOP_CMD', list, section='Bot Runtime', description='Optional external command used by ,bot shutdown. Leave empty to perform a clean internal exit. With systemd, use Restart=on-failure so ,bot restart (exit code 75) restarts while a clean shutdown remains stopped.'),
    'stop_cmd_timeout_seconds': ConfigField(10.0, 'STOP_CMD_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Stop cmd timeout seconds.'),
    'command_timeout_seconds': ConfigField(30, 'COMMAND_TIMEOUT_SECONDS', (int, float), section='Bot Runtime', description='Command execution guardrails. Slow commands are logged; timed-out commands return a friendly error and the traceback stays in the log.'),
    'command_slow_log_seconds': ConfigField(2.0, 'COMMAND_SLOW_LOG_SECONDS', (int, float), section='Bot Runtime', description='Command slow log seconds.'),
    'default_pagination': ConfigField('all', 'DEFAULT_PAGINATION', (str, int), section='Bot Runtime', description='Default paging behavior for commands supporting [page|last|all]. "all" shows the full list by default. A positive integer, e.g. 20, shows page 1 with that many entries unless the user explicitly asks for all/last/page.'),
    'database_busy_timeout_ms': ConfigField(5000, 'DATABASE_BUSY_TIMEOUT_MS', int, startup_only=True, section='Bot Runtime', description='SQLite connection busy timeout in milliseconds. Applied when the database connection is opened.'),
    'database_wal_enabled': ConfigField(False, 'DATABASE_WAL_ENABLED', bool, startup_only=True, section='Bot Runtime', description='Whether SQLite WAL journal mode is enabled. Applied when the database connection is opened.'),
    'database_shutdown_timeout_seconds': ConfigField(15.0, 'DATABASE_SHUTDOWN_TIMEOUT_SECONDS', (int, float), section='Bot Runtime', description='Grace period for shutdown/restart DB cleanup. Keep this larger than the internal flush wait so the SQLite connection can close cleanly.'),
    'database_maintenance_interval_seconds': ConfigField(21600, 'DATABASE_MAINTENANCE_INTERVAL_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Periodic low-impact SQLite maintenance. The worker runs PRAGMA optimize, checkpoints WAL when enabled and prunes old aggregate command statistics.'),
    'database_backup_before_migrate': ConfigField(True, 'DATABASE_BACKUP_BEFORE_MIGRATE', bool, startup_only=True, section='Bot Runtime', description='Create a consistent SQLite snapshot before applying pending schema migrations.'),
    'database_migration_backup_keep': ConfigField(5, 'DATABASE_MIGRATION_BACKUP_KEEP', int, minimum=1, section='Backups', description='Keep this many verified pre-migration SQLite snapshots.'),
    'database_migration_backup_retention_days': ConfigField(90, 'DATABASE_MIGRATION_BACKUP_RETENTION_DAYS', int, minimum=0, section='Backups', description='Also prune pre-migration SQLite snapshots older than this many days. 0 disables age-based pruning.'),
    'command_usage_retention_days': ConfigField(365, 'COMMAND_USAGE_RETENTION_DAYS', int, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Command usage retention days.'),
    'watchdog_enabled': ConfigField(True, 'WATCHDOG_ENABLED', bool, startup_only=True, section='Bot Runtime', description='Event-loop monitor and native systemd watchdog integration. With the bundled service unit, a process that is alive but no longer responsive is restarted.'),
    'watchdog_interval_seconds': ConfigField(20.0, 'WATCHDOG_INTERVAL_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Watchdog interval seconds.'),
    'watchdog_lag_warning_seconds': ConfigField(2.0, 'WATCHDOG_LAG_WARNING_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Watchdog lag warning seconds.'),
    'watchdog_lag_failure_seconds': ConfigField(30.0, 'WATCHDOG_LAG_FAILURE_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Watchdog lag failure seconds.'),
    'task_restart_max_attempts': ConfigField(5, 'TASK_RESTART_MAX_ATTEMPTS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Automatic restart/backoff for protected long-running plugin workers. After this many consecutive failures the circuit opens and an admin is notified.'),
    'task_restart_initial_seconds': ConfigField(5.0, 'TASK_RESTART_INITIAL_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Task restart initial seconds.'),
    'task_restart_max_seconds': ConfigField(300.0, 'TASK_RESTART_MAX_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Task restart max seconds.'),
    'task_restart_reset_seconds': ConfigField(900.0, 'TASK_RESTART_RESET_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True, section='Bot Runtime', description='Task restart reset seconds.'),
    'task_stale_after_seconds': ConfigField(3600.0, 'TASK_STALE_AFTER_SECONDS', (int, float), minimum=60, section='Bot Runtime', description='Heartbeats older than this are reported by `,tasks stale`; values below 60 seconds are rejected.'),
    'outbox_enabled': ConfigField(True, 'OUTBOX_ENABLED', bool, startup_only=True, section='Persistent Outbox', description='Persistent outbound delivery queue. Failed RSS, reminder and admin-report messages are stored in SQLite and retried across reconnects/restarts.'),
    'outbox_poll_seconds': ConfigField(5.0, 'OUTBOX_POLL_SECONDS', (int, float), startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox poll seconds.'),
    'outbox_batch_size': ConfigField(20, 'OUTBOX_BATCH_SIZE', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox batch size.'),
    'outbox_max_attempts': ConfigField(12, 'OUTBOX_MAX_ATTEMPTS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox max attempts.'),
    'outbox_retry_initial_seconds': ConfigField(30, 'OUTBOX_RETRY_INITIAL_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox retry initial seconds.'),
    'outbox_retry_max_seconds': ConfigField(1800, 'OUTBOX_RETRY_MAX_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox retry max seconds.'),
    'outbox_inflight_timeout_seconds': ConfigField(300, 'OUTBOX_INFLIGHT_TIMEOUT_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox inflight timeout seconds.'),
    'outbox_max_pending': ConfigField(10000, 'OUTBOX_MAX_PENDING', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Hard growth limits for long outages or broken destinations.'),
    'outbox_max_bytes': ConfigField(52428800, 'OUTBOX_MAX_BYTES', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox max bytes.'),
    'outbox_max_per_destination': ConfigField(1000, 'OUTBOX_MAX_PER_DESTINATION', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox max per destination.'),
    'outbox_max_per_category': ConfigField(5000, 'OUTBOX_MAX_PER_CATEGORY', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Persistent Outbox', description='Outbox max per category.'),
    'outbox_dead_retention_days': ConfigField(30, 'OUTBOX_DEAD_RETENTION_DAYS', int, minimum=0, section='Persistent Outbox', description='Dead letters older than this are pruned by database maintenance. 0 disables age-based pruning.'),
    'admin_alerts_enabled': ConfigField(True, 'ADMIN_ALERTS_ENABLED', bool, startup_only=True, section='Immediate Admin Alerts', description='Send deduplicated state-change warnings to the same destination used by the admin report. Ongoing incidents are repeated only after the cooldown.'),
    'admin_alert_interval_seconds': ConfigField(60, 'ADMIN_ALERT_INTERVAL_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Immediate Admin Alerts', description='Admin alert interval seconds.'),
    'admin_alert_cooldown_seconds': ConfigField(3600, 'ADMIN_ALERT_COOLDOWN_SECONDS', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Immediate Admin Alerts', description='Admin alert cooldown seconds.'),
    'admin_alert_outbox_oldest_seconds': ConfigField(1800, 'ADMIN_ALERT_OUTBOX_OLDEST_SECONDS', int, minimum=0, minimum_exclusive=True, section='Immediate Admin Alerts', description='Admin alert outbox oldest seconds.'),
    'admin_alert_room_missing_seconds': ConfigField(1800, 'ADMIN_ALERT_ROOM_MISSING_SECONDS', int, minimum=0, minimum_exclusive=True, section='Immediate Admin Alerts', description='Admin alert room missing seconds.'),
    'admin_alert_backup_max_age_hours': ConfigField(36, 'ADMIN_ALERT_BACKUP_MAX_AGE_HOURS', int, minimum=0, minimum_exclusive=True, section='Immediate Admin Alerts', description='Admin alert backup max age hours.'),
    'admin_alert_idlerpg_export_failures': ConfigField(3, 'ADMIN_ALERT_IDLERPG_EXPORT_FAILURES', int, minimum=0, minimum_exclusive=True, section='Immediate Admin Alerts', description='Admin alert idlerpg export failures.'),
    'admin_report_enabled': ConfigField(False, 'ADMIN_REPORT_ENABLED', bool, section='Daily Admin Report', description='Optional compact XMPP-only health report. No HTTP metrics endpoint is opened.'),
    'admin_report_mode': ConfigField('daily', 'ADMIN_REPORT_MODE', str, choices=("daily", "problems_only"), section='Daily Admin Report', description='"daily" always sends; "problems_only" skips a scheduled report when the immediate alert manager currently has no active incident.'),
    'admin_report_jid': ConfigField('', 'ADMIN_REPORT_JID', str, allow_empty=True, section='Daily Admin Report', description='Empty uses VERSION_CHECK_NOTIFY_JID, ROOM_INVITE_NOTIFY_JID or OWNER.'),
    'admin_report_time': ConfigField('08:00', 'ADMIN_REPORT_TIME', str, section='Daily Admin Report', description='Admin report time.'),
    'admin_report_timezone': ConfigField('', 'ADMIN_REPORT_TIMEZONE', str, allow_empty=True, section='Daily Admin Report', description='Empty uses TIMEZONE.'),
    'admin_report_backup_smoke_test': ConfigField(False, 'ADMIN_REPORT_BACKUP_SMOKE_TEST', bool, section='Daily Admin Report', description='Optionally extract the newest backup into a temporary directory and run an SQLite integrity check on the contained bot.db while building the report.'),
    'message_cache_size': ConfigField(100, 'MESSAGE_CACHE_SIZE', int, startup_only=True, minimum=0, minimum_exclusive=True, section='Message Cache', description='Number of recent messages retained per room or private conversation. The cache is shared by all plugins, stored in SQLite and restored on restart. Message bodies are therefore persisted in the bot database and included in normal database backups. Lower this value if less retained history is wanted.'),
    'message_cache_max_age_days': ConfigField(30, 'MESSAGE_CACHE_MAX_AGE_DAYS', int, startup_only=True, minimum=0, section='Message Cache', description='Remove cached messages older than this many days. Set 0 to disable age pruning.'),
    'user_cache_max_entries': ConfigField(5000, 'USER_CACHE_MAX_ENTRIES', int, startup_only=True, minimum=1, section='User Tracking', description='Maximum number of clean user rows kept in the read-through cache. Dirty entries are never evicted.'),
    'user_runtime_cache_max_entries': ConfigField(5000, 'USER_RUNTIME_CACHE_MAX_ENTRIES', int, startup_only=True, minimum=1, section='User Tracking', description='Maximum number of clean per-user runtime JSON blobs kept in memory. Dirty entries and the global plugin runtime blob are never evicted.'),
    'user_cache_ttl_seconds': ConfigField(86400, 'USER_CACHE_TTL_SECONDS', int, startup_only=True, minimum=0, section='User Tracking', description='Evict clean user/runtime cache entries that have not been accessed for this many seconds. 0 disables TTL eviction.'),
    'user_cache_prune_interval_seconds': ConfigField(300, 'USER_CACHE_PRUNE_INTERVAL_SECONDS', int, startup_only=True, minimum=1, section='User Tracking', description='Minimum interval between automatic cache-prune passes.'),
    'backup_dir': ConfigField('data/backups', 'BACKUP_DIR', str, section='Backups', description='Managed ZIP backups are written here. The default is ignored by git. Archives include bot.db, config.py, vcard.py and chat_slang.csv when present.'),
    'backup_keep': ConfigField(15, 'BACKUP_KEEP', int, minimum=0, minimum_exclusive=True, section='Backups', description='Keep this many managed backup archives after creating a new one.'),
    'backup_retention_days': ConfigField(0, 'BACKUP_RETENTION_DAYS', int, section='Backups', description='Also prune managed backup archives older than this many days. Set to 0 to disable age-based pruning.'),
    'backup_on_start': ConfigField(True, 'BACKUP_ON_START', bool, section='Backups', description='Create a managed backup once during each bot process start. This also covers service restarts, because a restart starts a fresh bot process.'),
    'backup_interval_hours': ConfigField(24, 'BACKUP_INTERVAL_HOURS', int, startup_only=True, minimum=0, section='Backups', description='Create an automatic managed backup this many hours after the newest managed backup. Set to 0 to disable periodic backups. Keep this below ADMIN_ALERT_BACKUP_MAX_AGE_HOURS.'),
    'backup_smoke_test_on_create': ConfigField(True, 'BACKUP_SMOKE_TEST_ON_CREATE', bool, section='Backups', description='Restore each newly created backup into a temporary directory and run SQLite integrity_check before accepting it.'),
    'command_rate_limit_enabled': ConfigField(True, 'COMMAND_RATE_LIMIT_ENABLED', bool, section='Command Rate Limits', description='Protect the bot from command spam. Limits are in-memory and reset on restart.'),
    'command_rate_limit_capacity': ConfigField(4, 'COMMAND_RATE_LIMIT_CAPACITY', int, section='Command Rate Limits', description='Command rate limit capacity.'),
    'command_rate_limit_refill_amount': ConfigField(1, 'COMMAND_RATE_LIMIT_REFILL_AMOUNT', int, section='Command Rate Limits', description='Command rate limit refill amount.'),
    'command_rate_limit_refill_interval_seconds': ConfigField(0.5, 'COMMAND_RATE_LIMIT_REFILL_INTERVAL_SECONDS', (int, float), section='Command Rate Limits', description='Command rate limit refill interval seconds.'),
    'command_rate_limit_deny_window_seconds': ConfigField(10.0, 'COMMAND_RATE_LIMIT_DENY_WINDOW_SECONDS', (int, float), section='Command Rate Limits', description='Command rate limit deny window seconds.'),
    'command_rate_limit_deny_threshold': ConfigField(6, 'COMMAND_RATE_LIMIT_DENY_THRESHOLD', int, section='Command Rate Limits', description='Command rate limit deny threshold.'),
    'command_rate_limit_base_block_seconds': ConfigField(30.0, 'COMMAND_RATE_LIMIT_BASE_BLOCK_SECONDS', (int, float), section='Command Rate Limits', description='Command rate limit base block seconds.'),
    'command_rate_limit_backoff_multiplier': ConfigField(2.0, 'COMMAND_RATE_LIMIT_BACKOFF_MULTIPLIER', (int, float), section='Command Rate Limits', description='Command rate limit backoff multiplier.'),
    'command_rate_limit_max_block_seconds': ConfigField(3600.0, 'COMMAND_RATE_LIMIT_MAX_BLOCK_SECONDS', (int, float), section='Command Rate Limits', description='Command rate limit max block seconds.'),
    'command_rate_limit_notify_cooldown_seconds': ConfigField(10.0, 'COMMAND_RATE_LIMIT_NOTIFY_COOLDOWN_SECONDS', (int, float), section='Command Rate Limits', description='Command rate limit notify cooldown seconds.'),
    'command_rate_limit_idle_ttl_seconds': ConfigField(3600, 'COMMAND_RATE_LIMIT_IDLE_TTL_SECONDS', (int, float), minimum=0, section='Command Rate Limits', description='Prune inactive command rate-limit client state after this many seconds. Set 0 to disable TTL pruning; the hard client limit still applies.'),
    'command_rate_limit_prune_interval_seconds': ConfigField(60, 'COMMAND_RATE_LIMIT_PRUNE_INTERVAL_SECONDS', (int, float), minimum=1, section='Command Rate Limits', description='Minimum interval between opportunistic command rate-limit idle-prune passes.'),
    'command_rate_limit_bypass_role': ConfigField('moderator', 'COMMAND_RATE_LIMIT_BYPASS_ROLE', str, section='Command Rate Limits', description='Users with this role or better bypass command rate limits. Use one of: owner, superadmin, admin, moderator, trusted, user, new, none.'),
    'http_timeout_seconds': ConfigField(8, 'HTTP_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='HTTP Defaults', description='Generic HTTP timeout and User-Agent used by plugins unless a plugin-specific value is set below. Keep the User-Agent versionless so it does not have to be updated for every release.'),
    'http_max_redirects': ConfigField(5, 'HTTP_MAX_REDIRECTS', int, minimum=0, minimum_exclusive=True, section='HTTP Defaults', description='Http max redirects.'),
    'http_max_read_bytes': ConfigField(1048576, 'HTTP_MAX_READ_BYTES', int, minimum=0, minimum_exclusive=True, section='HTTP Defaults', description='Http max read bytes.'),
    'http_user_agent': ConfigField('Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)', 'HTTP_USER_AGENT', str, section='HTTP Defaults', description='Http user agent.'),
    'allow_private_fetch_urls': ConfigField(False, 'ALLOW_PRIVATE_FETCH_URLS', bool, section='HTTP Defaults', description='Safety guard for user-supplied URLs fetched by RSS and URL title checks. Keep False for normal public bots. Set True only for trusted/private rooms.'),
    'avatar': ConfigField(MISSING, 'AVATAR_PATH', str, section='vCard / Avatar', description='Bot avatar. Set AVATAR_PATH = None to disable avatar publishing. The default avatar is bundled with envsbot; put custom avatars below data/.', sample='avatar.jpg'),
    'avatar_type': ConfigField(MISSING, 'AVATAR_TYPE', str, section='vCard / Avatar', description='Avatar type.', sample='image/jpeg'),
    'vcard_fetch_timeout_seconds': ConfigField(10, 'VCARD_FETCH_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='vCard / Avatar', description='Timeout for vCard fetches made by vcard, weather and birthday helpers.'),
    'version_check_enabled': ConfigField(False, 'VERSION_CHECK_ENABLED', bool, section='Release Update Check', description='Manual ,checkupdate works even when periodic checks are disabled.'),
    'version_check_interval': ConfigField(3600, 'VERSION_CHECK_INTERVAL', int, minimum=60, section='Release Update Check', description='Version check interval.'),
    'version_check_url': ConfigField('https://github.com/envs-net/envsbot/releases/latest', 'VERSION_CHECK_URL', str, section='Release Update Check', description='Version check url.'),
    'version_check_notify_jid': ConfigField(MISSING, 'VERSION_CHECK_NOTIFY_JID', str, allow_empty=True, section='Release Update Check', description='Empty = notify OWNER. If this is a MUC room, the bot joins it before sending.', sample=''),
    'updatecheck_timeout_seconds': ConfigField(15, 'UPDATECHECK_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='Release Update Check', description='Updatecheck timeout seconds.'),
    'room_invites_enabled': ConfigField(True, 'ROOM_INVITES_ENABLED', bool, section='Room Invites', description='When enabled, incoming MUC invites are stored as pending room invites and announced to ROOM_INVITE_NOTIFY_JID, VERSION_CHECK_NOTIFY_JID, or OWNER. The bot does not join the invited room until an admin accepts the invite.'),
    'room_invite_notify_jid': ConfigField('', 'ROOM_INVITE_NOTIFY_JID', str, allow_empty=True, section='Room Invites', description='Room invite notify jid.'),
    'room_invite_max_age_days': ConfigField(30, 'ROOM_INVITE_MAX_AGE_DAYS', int, section='Room Invites', description='Pending room invites older than this many days are expired automatically. Set to 0 to keep pending invites until accepted/declined/cleanup.'),
    'room_plugin_defaults': ConfigField({'birthday_notify': False, 'dice': True, 'ducks': False, 'help': False, 'information': True, 'karma': False, 'idlerpg': False, 'pin': True, 'poll': False, 'presence': True, 'reminder': True, 'sed': True, 'tell': True, 'tools': True, 'translate': True, 'urlcheck': True, 'vcard': True, 'weather': True, 'xkcd': False, 'xmpp': True}, 'ROOM_PLUGIN_DEFAULTS', dict, section='Room Plugin Defaults', description='Default room feature state used for newly added rooms and for ,rooms set_plugin_defaults. Missing keys keep their internal fallback. Unknown keys are ignored with a warning. Per-room changes are still stored in the database and can be managed with ,rooms enable/disable.'),
    'urlcheck_wait_seconds': ConfigField(120, 'URLCHECK_WAIT_SECONDS', int, minimum=0, minimum_exclusive=True, section='URL Check', description='Suppress repeated output for the same URL in the same room for this many seconds.'),
    'urlcheck_fetch_timeout_seconds': ConfigField(8, 'URLCHECK_FETCH_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='URL Check', description='URL fetch limits for title/description extraction and YouTube metadata.'),
    'urlcheck_max_redirects': ConfigField(5, 'URLCHECK_MAX_REDIRECTS', int, minimum=0, minimum_exclusive=True, section='URL Check', description='Urlcheck max redirects.'),
    'urlcheck_max_read_bytes': ConfigField(65536, 'URLCHECK_MAX_READ_BYTES', int, minimum=0, minimum_exclusive=True, section='URL Check', description='Urlcheck max read bytes.'),
    'urlcheck_user_agent': ConfigField('Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)', 'URLCHECK_USER_AGENT', str, section='URL Check', description='Urlcheck user agent.'),
    'youtube_api_key': ConfigField(MISSING, 'YOUTUBE_API_KEY', str, section='URL Check', description='YouTube Data API key for richer URL metadata lookups. None disables YouTube API data but regular URL title checks still work.', sensitive=True, sample=None),
    'rss_global_query_interval': ConfigField(1200, 'RSS_GLOBAL_QUERY_INTERVAL', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Default global feed check interval in seconds.'),
    'max_new_feed_entries': ConfigField(5, 'MAX_NEW_FEED_ENTRIES', int, minimum=0, section='RSS / Atom', description='Number of existing entries to show when a feed is newly added.'),
    'rss_trusted_max_feeds': ConfigField(10, 'RSS_TRUSTED_MAX_FEEDS', int, minimum=0, section='RSS / Atom', description='Maximum personal DM subscriptions for trusted users. Moderators and higher are unlimited. Set to 0 to disable trusted-user DM subscriptions.'),
    'rss_list_page_size': ConfigField(10, 'RSS_LIST_PAGE_SIZE', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Number of entries shown on one paginated RSS list page.'),
    'rss_max_entries_per_poll': ConfigField(10, 'RSS_MAX_ENTRIES_PER_POLL', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Maximum number of new entries posted per regular feed poll. If a very active feed publishes more than this between two checks, older unseen entries are skipped and the newest item is remembered as seen.'),
    'rss_retry_initial_delay': ConfigField(300, 'RSS_RETRY_INITIAL_DELAY', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Retry/backoff behavior for failing feeds. First failure retries after 5 minutes, second after 10 minutes, then grows exponentially up to the maximum delay.'),
    'rss_retry_backoff_multiplier': ConfigField(2.0, 'RSS_RETRY_BACKOFF_MULTIPLIER', (int, float), minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Rss retry backoff multiplier.'),
    'rss_max_backoff_time': ConfigField(3600, 'RSS_MAX_BACKOFF_TIME', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Rss max backoff time.'),
    'rss_broken_error_threshold': ConfigField(3, 'RSS_BROKEN_ERROR_THRESHOLD', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='A feed is considered broken in ,rss broken after this many consecutive errors.'),
    'rss_similarity_threshold': ConfigField(0.8, 'RSS_SIMILARITY_THRESHOLD', (int, float), minimum=0, maximum=1, minimum_exclusive=True, section='RSS / Atom', description='Duplicate title/description detection threshold, 0 < value <= 1.'),
    'rss_user_agent': ConfigField('Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)', 'RSS_USER_AGENT', str, section='RSS / Atom', description='Rss user agent.'),
    'rss_fetch_timeout_seconds': ConfigField(8, 'RSS_FETCH_TIMEOUT_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Explicit RSS HTTP fetch limits.'),
    'rss_startup_stagger_seconds': ConfigField(2.0, 'RSS_STARTUP_STAGGER_SECONDS', (int, float), minimum=0, section='RSS / Atom', description='Spread initial requests to the same host across a few seconds after startup. This avoids a burst when many feeds are hosted by one slower service.'),
    'rss_max_redirects': ConfigField(5, 'RSS_MAX_REDIRECTS', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Rss max redirects.'),
    'rss_max_read_bytes': ConfigField(1048576, 'RSS_MAX_READ_BYTES', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Rss max read bytes.'),
    'rss_template_max_length': ConfigField(1000, 'RSS_TEMPLATE_MAX_LENGTH', int, minimum=0, minimum_exclusive=True, section='RSS / Atom', description='Maximum length of an RSS message template configured with ,rss template.'),
    'birthday_cache_ttl_seconds': ConfigField(43200, 'BIRTHDAY_CACHE_TTL_SECONDS', int, minimum=0, minimum_exclusive=True, section='Birthday Notify', description='Cache positive and negative vCard BDAY results for this many seconds.'),
    'birthday_initial_scan_delay_seconds': ConfigField(10, 'BIRTHDAY_INITIAL_SCAN_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True, section='Birthday Notify', description='Delay first scan after startup so room joins and presence can settle.'),
    'birthday_check_interval_seconds': ConfigField(3600, 'BIRTHDAY_CHECK_INTERVAL_SECONDS', int, minimum=0, minimum_exclusive=True, section='Birthday Notify', description='Periodic loop interval in seconds. The expensive full scan still only runs once per day.'),
    'reminder_enabled': ConfigField(MISSING, 'REMINDER_ENABLED', bool, section='Reminders', description='Reminder enabled.', sample=True),
    'reminder_max_age_days': ConfigField(MISSING, 'REMINDER_MAX_AGE_DAYS', int, minimum=0, minimum_exclusive=True, section='Reminders', description='Reminder max age days.', sample=365),
    'reminder_default_timezone': ConfigField('UTC', 'REMINDER_DEFAULT_TIMEZONE', str, section='Reminders', description='Fallback timezone for absolute reminder dates when the user has no TIMEZONE set in their bot profile. Explicit command timezones such as CEST, CET, UTC, Europe/Berlin or +02:00 override this per reminder. Use an IANA timezone such as Europe/Berlin when you want automatic DST handling; CET/CEST are treated as explicit fixed offsets.'),
    'ducks': ConfigField(MISSING, 'DUCKS', dict, section='Duck Game', description='Global defaults for rooms with the Ducks plugin enabled. Room owners/admins and bot moderators can override gameplay pacing for one room through a MUC private chat with `,duck config`; see docs/plugins/ducks.md for examples.', sample=nested_config_defaults('ducks')),
    'users': ConfigField(MISSING, 'USERS', dict, section='User Tracking', description='Users.', sample=nested_config_defaults('users')),
    'idlerpg': ConfigField(MISSING, 'IDLERPG', dict, section='IdleRPG', description="Classic IRC-style IdleRPG adapted for XMPP MUCs. Players level up by staying online and idle. Normal room messages add penalty time to the player's timer. See docs/idlerpg.md for details.", sample=nested_config_defaults('idlerpg')),
    'sed_regex_timeout': ConfigField(1.0, 'SED_REGEX_TIMEOUT', (int, float), minimum=0, minimum_exclusive=True, section='Sed Corrections', description='Sed regex timeout.'),
    'sed_max_pattern_length': ConfigField(256, 'SED_MAX_PATTERN_LENGTH', int, minimum=0, minimum_exclusive=True, section='Sed Corrections', description='Sed max pattern length.'),
    'sed_max_replacement_length': ConfigField(1000, 'SED_MAX_REPLACEMENT_LENGTH', int, minimum=0, minimum_exclusive=True, section='Sed Corrections', description='Sed max replacement length.'),
    'sed_max_input_length': ConfigField(5000, 'SED_MAX_INPUT_LENGTH', int, minimum=0, minimum_exclusive=True, section='Sed Corrections', description='Sed max input length.'),
    'sed_max_output_length': ConfigField(8000, 'SED_MAX_OUTPUT_LENGTH', int, minimum=0, minimum_exclusive=True, section='Sed Corrections', description='Sed max output length.'),
    'poll_max_options': ConfigField(10, 'POLL_MAX_OPTIONS', int, minimum=0, minimum_exclusive=True, section='Polls', description='Poll max options.'),
    'poll_max_question_len': ConfigField(200, 'POLL_MAX_QUESTION_LEN', int, minimum=0, minimum_exclusive=True, section='Polls', description='Poll max question len.'),
    'poll_max_option_len': ConfigField(100, 'POLL_MAX_OPTION_LEN', int, minimum=0, minimum_exclusive=True, section='Polls', description='Poll max option len.'),
    'poll_max_history_per_room': ConfigField(50, 'POLL_MAX_HISTORY_PER_ROOM', int, minimum=0, minimum_exclusive=True, section='Polls', description='Poll max history per room.'),
    'poll_default_multi_max_choices': ConfigField(3, 'POLL_DEFAULT_MULTI_MAX_CHOICES', int, section='Polls', description='Poll default multi max choices.'),
    'pin_page_size': ConfigField(10, 'PIN_PAGE_SIZE', int, minimum=0, minimum_exclusive=True, section='Pins', description='Pin page size.'),
    'translate_from': ConfigField('auto', 'TRANSLATE_FROM', str, section='Translate', description='Translate uses the same public Google Translate endpoint as translate. No API key is required, but the endpoint is unofficial and may change. Set TRANSLATE_TO to a language code such as "de" to allow `,tr` for replies and `,tr text` for direct text. None keeps the target argument mandatory.'),
    'translate_to': ConfigField(None, 'TRANSLATE_TO', str, section='Translate', description='Translate to.'),
    'translate_timeout_seconds': ConfigField(8, 'TRANSLATE_TIMEOUT_SECONDS', (int, float), section='Translate', description='Translate timeout seconds.'),
    'translate_max_input_length': ConfigField(2000, 'TRANSLATE_MAX_INPUT_LENGTH', int, section='Translate', description='Translate max input length.'),
    'translate_max_output_length': ConfigField(6000, 'TRANSLATE_MAX_OUTPUT_LENGTH', int, section='Translate', description='Translate max output length.'),
    'translate_max_response_bytes': ConfigField(262144, 'TRANSLATE_MAX_RESPONSE_BYTES', int, section='Translate', description='Translate max response bytes.'),
    'karma_delay_seconds': ConfigField(60, 'KARMA_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True, section='Karma / Tell', description='Karma delay seconds.'),
    'tell_delivery_delay_seconds': ConfigField(5, 'TELL_DELIVERY_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True, section='Karma / Tell', description='Tell delivery delay seconds.'),
    'xkcd_check_interval': ConfigField(3600, 'XKCD_CHECK_INTERVAL', int, minimum=0, minimum_exclusive=True, section='XKCD', description='Xkcd check interval.'),
    'xkcd_index_start_delay_seconds': ConfigField(30, 'XKCD_INDEX_START_DELAY_SECONDS', int, minimum=0, minimum_exclusive=True, section='XKCD', description='Xkcd index start delay seconds.'),
    'xkcd_index_request_delay_seconds': ConfigField(0.15, 'XKCD_INDEX_REQUEST_DELAY_SECONDS', (int, float), minimum=0, minimum_exclusive=True, section='XKCD', description='Xkcd index request delay seconds.'),
    'xkcd_http_timeout': ConfigField(10, 'XKCD_HTTP_TIMEOUT', (int, float), minimum=0, minimum_exclusive=True, section='XKCD', description='Xkcd http timeout.'),
}

OPERATIONAL_CONFIG_FIELDS = CONFIG_FIELDS


def config_display_sections() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return operator-facing sections derived from the field schema."""
    sections: dict[str, list[str]] = {}
    for field in CONFIG_FIELDS.values():
        sections.setdefault(field.section, []).append(field.python_key)
    return tuple((title, tuple(keys)) for title, keys in sections.items())


CONFIG_DISPLAY_SECTIONS = config_display_sections()

def config_defaults() -> dict[str, Any]:
    return {name: field.default for name, field in CONFIG_FIELDS.items() if field.default is not MISSING}


def sample_config_defaults() -> dict[str, Any]:
    """Return documented sample values entirely from the declarative schema."""
    result: dict[str, Any] = {}
    for name, field in CONFIG_FIELDS.items():
        value = field.sample if field.sample is not MISSING else field.default
        if value is not MISSING:
            result[name] = value
    return result

def required_config_types() -> dict[str, type | tuple[type, ...]]:
    return {name: field.accepted_type for name, field in CONFIG_FIELDS.items() if field.required}

def optional_config_types() -> dict[str, type | tuple[type, ...]]:
    return {name: field.accepted_type for name, field in CONFIG_FIELDS.items() if not field.required}

def python_config_key_map() -> dict[str, str]:
    return {field.python_key: name for name, field in CONFIG_FIELDS.items()}

def startup_only_keys() -> set[str]:
    return {name for name, field in CONFIG_FIELDS.items() if field.startup_only}


def sensitive_keys() -> set[str]:
    return {name for name, field in CONFIG_FIELDS.items() if field.sensitive}

# Compatibility names used by older imports/tests.
operational_defaults = config_defaults
operational_types = optional_config_types
operational_python_key_map = python_config_key_map
operational_startup_only_keys = startup_only_keys
