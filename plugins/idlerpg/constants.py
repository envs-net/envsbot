"""Split module for plugins/idlerpg.py: constants."""

from __future__ import annotations


PLUGIN_META = {
    "name": "idlerpg",
    "version": "1.0.12",
    "description": "IdleRPG game for MUCs, inspired by the classic IRC game",
    "category": "games",
    "requires": ["rooms", "_core"],
}


IDLERPG_ENABLED_KEY = "IDLERPG"


IDLERPG_DATA_KEY = "IDLERPG_DATA"


PLUGIN_NAME = "idlerpg"


ACHIEVEMENTS = {
    "founder": ("Founder", "registered an IdleRPG character"),
    "silent_24h": ("Silent Idler", "stayed online and idle for 24 hours"),
    "silent_week": ("Ancient Patience", "stayed online and idle for 7 days"),
    "season_day_3": ("Season Settler", "stayed active for at least 3 season days"),
    "season_week_1": ("Season Regular", "stayed active for at least 7 season days"),
    "level_10": ("Novice Idler", "reached level 10"),
    "level_25": ("Seasoned Idler", "reached level 25"),
    "level_50": ("Ancient Idler", "reached level 50"),
    "level_75": ("Legendary Idler", "reached level 75"),
    "level_100": ("Mythic Idler", "reached level 100"),
    "level_reward_50": ("Cloaked Traveler", "unlocked the level 50 reward badge"),
    "level_reward_75": ("Rare Title Bearer", "unlocked the level 75 rare title pool"),
    "battle_winner": ("Duelist", "won a random battle"),
    "battle_scarred": ("Battle Scarred", "won 10 random battles"),
    "critical_striker": ("Critical Striker", "landed a critical strike"),
    "team_battle_winner": ("Team Fighter", "won a team battle"),
    "team_veteran": ("Team Veteran", "won 5 team battles"),
    "boss_slayer": ("Boss Slayer", "helped defeat a room boss"),
    "boss_veteran": ("Raid Veteran", "helped defeat 5 room bosses"),
    "unique_item": ("Relic Finder", "found a unique artifact"),
    "artifact_finder": ("Artifact Finder", "collected unique artifacts in 3 equipment slots"),
    "item_blessed": ("Blessed Gear", "had an item blessed"),
    "item_damaged": ("Dented Gear", "had an item damaged"),
    "item_swapped": ("Light Fingers", "won a fair item swap"),
    "quester": ("Quest Chosen", "was chosen for a quest"),
    "quest_hero": ("Quest Hero", "completed a quest"),
    "quest_walker": ("Quest Walker", "completed 3 quests"),
    "lucky": ("Blessed", "received a godsend"),
    "very_lucky": ("Favoured by the RNG", "received 10 godsends"),
    "unlucky": ("Cursed", "suffered a calamity"),
    "the_unlucky": ("The Unlucky", "suffered 10 calamities"),
    "alignment_blessed": ("Aligned", "benefited from an alignment group event"),
    "collector": ("Collector", "collected at least 100 total item levels"),
    "hoarder": ("Hoarder", "collected at least 500 total item levels"),
}


ITEMS = (
    "ring",
    "amulet",
    "charm",
    "weapon",
    "helm",
    "tunic",
    "pair of gloves",
    "shield",
    "set of leggings",
    "pair of boots",
)


ALIGNMENT_ITEM_POWER_FACTORS = {
    "good": 1.10,
    "neutral": 1.00,
    "evil": 0.90,
}
UNIQUE_BONUS_CAP_PERCENT = 35


UNIQUE_ITEMS = (
    {"name": "The Ancient Shell of envs.net", "slot": "shield", "tier": 1, "min_level": 25, "min_item_level": 50, "max_item_level": 74, "bonus": "calamity_reduction", "bonus_percent": 5},
    {"name": "The Amulet of Uptime", "slot": "amulet", "tier": 1, "min_level": 25, "min_item_level": 50, "max_item_level": 74, "bonus": "logout_penalty_reduction", "bonus_percent": 10},
    {"name": "The Boots of Silent Idling", "slot": "pair of boots", "tier": 1, "min_level": 30, "min_item_level": 75, "max_item_level": 99, "bonus": "quest_reward_bonus", "bonus_percent": 5},
    {"name": "The Lantern of Quiet Roads", "slot": "charm", "tier": 1, "min_level": 35, "min_item_level": 100, "max_item_level": 140, "bonus": "quest_reward_bonus", "bonus_percent": 5},
    {"name": "The Crown of Boring Technology", "slot": "helm", "tier": 1, "min_level": 35, "min_item_level": 100, "max_item_level": 124, "bonus": "alignment_bonus", "bonus_percent": 5},
    {"name": "The Gloves of Quiet Keystrokes", "slot": "pair of gloves", "tier": 1, "min_level": 35, "min_item_level": 100, "max_item_level": 140, "bonus": "message_penalty_reduction", "bonus_percent": 5},
    {"name": "The Helm of Patient Stars", "slot": "helm", "tier": 2, "min_level": 40, "min_item_level": 150, "max_item_level": 190, "bonus": "calamity_reduction", "bonus_percent": 5},
    {"name": "The Great Hammer of /bin/sh", "slot": "weapon", "tier": 1, "min_level": 40, "min_item_level": 150, "max_item_level": 174, "bonus": "battle_bonus", "bonus_percent": 5},
    {"name": "The Ring of Long Silence", "slot": "ring", "tier": 1, "min_level": 45, "min_item_level": 180, "max_item_level": 230, "bonus": "message_penalty_reduction", "bonus_percent": 5},
    {"name": "The Cloak of Found on the Shell", "slot": "tunic", "tier": 1, "min_level": 45, "min_item_level": 175, "max_item_level": 200, "bonus": "message_penalty_reduction", "bonus_percent": 5},
    {"name": "The Leggings of Endless Uptime", "slot": "set of leggings", "tier": 1, "min_level": 45, "min_item_level": 180, "max_item_level": 230, "bonus": "logout_penalty_reduction", "bonus_percent": 8},
    {"name": "The Ring of Quiet Services", "slot": "ring", "tier": 2, "min_level": 48, "min_item_level": 250, "max_item_level": 300, "bonus": "godsend_bonus", "bonus_percent": 5},
    {"name": "The Shield of Gentle Fortune", "slot": "shield", "tier": 2, "min_level": 50, "min_item_level": 220, "max_item_level": 270, "bonus": "godsend_bonus", "bonus_percent": 5},
    {"name": "The Cluehammer of Good Documentation", "slot": "weapon", "tier": 2, "min_level": 52, "min_item_level": 300, "max_item_level": 350, "bonus": "battle_bonus", "bonus_percent": 8},
    {"name": "The Silver Compass of Dawn", "slot": "charm", "tier": 2, "min_level": 55, "min_item_level": 280, "max_item_level": 330, "bonus": "alignment_bonus", "bonus_percent": 6},
    {"name": "The Mantle of the Sleeping King", "slot": "tunic", "tier": 2, "min_level": 58, "min_item_level": 320, "max_item_level": 370, "bonus": "logout_penalty_reduction", "bonus_percent": 10},
    {"name": "The Starforged Blade of Patience", "slot": "weapon", "tier": 3, "min_level": 65, "min_item_level": 380, "max_item_level": 450, "bonus": "battle_bonus", "bonus_percent": 8},
    {"name": "The Moonstone Amulet of Still Waters", "slot": "amulet", "tier": 2, "min_level": 70, "min_item_level": 420, "max_item_level": 500, "bonus": "calamity_reduction", "bonus_percent": 8},
    {"name": "The Boots of Persistent Sessions", "slot": "pair of boots", "tier": 2, "min_level": 75, "min_item_level": 520, "max_item_level": 600, "bonus": "quest_reward_bonus", "bonus_percent": 8},
    {"name": "The Gauntlets of Graceful Restarts", "slot": "pair of gloves", "tier": 2, "min_level": 75, "min_item_level": 520, "max_item_level": 600, "bonus": "battle_bonus", "bonus_percent": 9},
    {"name": "The Firewall of the Seventh Layer", "slot": "shield", "tier": 3, "min_level": 75, "min_item_level": 520, "max_item_level": 600, "bonus": "calamity_reduction", "bonus_percent": 10},
    {"name": "The Greaves of the Long-Running Daemon", "slot": "set of leggings", "tier": 2, "min_level": 85, "min_item_level": 620, "max_item_level": 700, "bonus": "calamity_reduction", "bonus_percent": 10},
    {"name": "The Crown of the Patient Operator", "slot": "helm", "tier": 3, "min_level": 85, "min_item_level": 620, "max_item_level": 700, "bonus": "alignment_bonus", "bonus_percent": 9},
    {"name": "The Talisman of Stable Latency", "slot": "charm", "tier": 3, "min_level": 85, "min_item_level": 620, "max_item_level": 700, "bonus": "godsend_bonus", "bonus_percent": 9},
    {"name": "The Amulet of Four Nines", "slot": "amulet", "tier": 3, "min_level": 100, "min_item_level": 760, "max_item_level": 850, "bonus": "calamity_reduction", "bonus_percent": 12},
    {"name": "The Ring of One Hundred Silent Levels", "slot": "ring", "tier": 3, "min_level": 100, "min_item_level": 760, "max_item_level": 850, "bonus": "message_penalty_reduction", "bonus_percent": 10},
    {"name": "The Robe of the Long-Term Maintainer", "slot": "tunic", "tier": 3, "min_level": 100, "min_item_level": 760, "max_item_level": 850, "bonus": "logout_penalty_reduction", "bonus_percent": 15},
    {"name": "The Root Shell of Final Authority", "slot": "weapon", "tier": 4, "min_level": 100, "min_item_level": 780, "max_item_level": 880, "bonus": "battle_bonus", "bonus_percent": 12},
    {"name": "The Bastion of Immutable State", "slot": "shield", "tier": 4, "min_level": 125, "min_item_level": 950, "max_item_level": 1050, "bonus": "godsend_bonus", "bonus_percent": 14},
    {"name": "The Amulet of Five Nines", "slot": "amulet", "tier": 4, "min_level": 125, "min_item_level": 1100, "max_item_level": 1200, "bonus": "calamity_reduction", "bonus_percent": 15},
    {"name": "The Boots of Endless Roaming", "slot": "pair of boots", "tier": 3, "min_level": 125, "min_item_level": 950, "max_item_level": 1050, "bonus": "quest_reward_bonus", "bonus_percent": 12},
    {"name": "The Beacon of Distributed Calm", "slot": "charm", "tier": 4, "min_level": 125, "min_item_level": 1050, "max_item_level": 1150, "bonus": "alignment_bonus", "bonus_percent": 12},
    {"name": "The Helm of the Last Watch", "slot": "helm", "tier": 4, "min_level": 125, "min_item_level": 1050, "max_item_level": 1150, "bonus": "calamity_reduction", "bonus_percent": 15},
    {"name": "The Cluehammer of Production", "slot": "weapon", "tier": 5, "min_level": 125, "min_item_level": 1150, "max_item_level": 1250, "bonus": "battle_bonus", "bonus_percent": 15},
    {"name": "The Ring of Persistent Silence", "slot": "ring", "tier": 4, "min_level": 125, "min_item_level": 1100, "max_item_level": 1200, "bonus": "message_penalty_reduction", "bonus_percent": 15},
    {"name": "The Mantle of the Evergreen Release", "slot": "tunic", "tier": 4, "min_level": 125, "min_item_level": 1100, "max_item_level": 1200, "bonus": "logout_penalty_reduction", "bonus_percent": 18},
    {"name": "The Root Gloves of Zero Downtime", "slot": "pair of gloves", "tier": 3, "min_level": 125, "min_item_level": 950, "max_item_level": 1050, "bonus": "battle_bonus", "bonus_percent": 13},
    {"name": "The Trousers of the Hundred-Year Process", "slot": "set of leggings", "tier": 3, "min_level": 125, "min_item_level": 950, "max_item_level": 1050, "bonus": "quest_reward_bonus", "bonus_percent": 12},
)


MAP_REGIONS = (
    {"name": "Debmark", "x1": 0, "y1": 0, "x2": 145, "y2": 95},
    {"name": "Mountains of Qwok", "x1": 245, "y1": 20, "x2": 390, "y2": 140},
    {"name": "The land of Qwok", "x1": 360, "y1": 75, "x2": 500, "y2": 165},
    {"name": "Jow Boti Territory", "x1": 55, "y1": 120, "x2": 210, "y2": 220},
    {"name": "Secret Passage to Aharah", "x1": 20, "y1": 235, "x2": 160, "y2": 300},
    {"name": "Velbragh", "x1": 285, "y1": 190, "x2": 430, "y2": 300},
    {"name": "The great Shell mountains", "x1": 0, "y1": 335, "x2": 190, "y2": 500},
    {"name": "Tower of Anh-Allor", "x1": 220, "y1": 345, "x2": 360, "y2": 445},
    {"name": "Irnalveh", "x1": 355, "y1": 365, "x2": 500, "y2": 500},
)


CALAMITIES = (
    "was bitten by a rabid cow",
    "fell into a hole",
    "ate a poisonous fruit",
    "was struck by lightning",
    "got lost in the woods",
    "walked face-first into a tree",
    "was caught in a terrible snowstorm",
    "was bitten by a moose",
    "lost their glasses",
    "misplaced their map",
    "was bucked from a horse",
    "ate a plate of discounted, day-old sushi",
    "bit their tongue",
    "was tipped by a cow",
    "was caught in quicksand",
    "was chased by angry bees",
    "dropped their lucky coin into a well",
    "was cursed by a wandering oracle",
    "fell asleep in a haunted forest",
    "angered a jealous goblin",
    "was trapped in a sudden hailstorm",
    "tripped over a sleeping goat",
    "dropped their pack into a river",
    "took a wrong turn in the fog",
    "was delayed by a broken bridge",
    "lost a boot in the mud",
    "angered a very small but determined goblin",
    "forgot where they were going",
    "fell asleep under the wrong tree",
    "was distracted by a suspiciously shiny rock",
    "had their provisions stolen by raccoons",
    "wandered into a patch of singing nettles",
    "was followed all day by an ominous crow",
    "mistook a swamp for a shortcut",
    "was challenged to a riddle contest by a rude sphinx",
    "lost an argument with a stubborn mule",
    "was delayed by a parade of turtles",
)


GODSENDS = (
    "found a one-time-use spell of quickness",
    "discovered a secret underground passage",
    "was taught to run quickly by a secret tribe",
    "tamed a wild horse",
    "drank from a magic stream",
    "found a faster pair of boots",
    "caught a unicorn",
    "invented the wheel",
    "discovered caffeinated coffee",
    "found a kitten",
    "stopped using dial-up",
    "found an exploit in the IRPG code",
    "got a kiss from a mysterious stranger",
    "was blessed by a passing cleric",
    "found a pair of Nikes",
    "learned Python",
    "grew an extra leg",
    "found a shimmering shortcut",
    "was carried by a friendly giant eagle",
    "received a lucky charm from a travelling merchant",
    "found a hidden cache of golden apples",
    "found a lucky copper coin",
    "was blessed by a wandering healer",
    "discovered a shortcut through the hills",
    "found fresh water in the desert",
    "was carried forward by a friendly wind",
    "received help from a mysterious stranger",
    "found an old map with a faster route",
    "was granted a moment of perfect focus",
    "rested beneath a sacred tree",
    "found a warm cloak on a cold night",
    "heard a song that lifted their spirit",
    "followed a trail of golden fireflies",
    "was guided by a white owl",
    "found a hidden spring beneath the stones",
    "was invited to a feast by grateful villagers",
    "borrowed a swift pony from a kindly farmer",
)


QUEST_TEXTS = (
    "locate the ancient tomes of the forgotten prophet",
    "guard the secret passage until the full moon has passed",
    "rescue the beautiful princess from a terrible beast",
    "destroy the bandits terrorizing the mountain roads",
    "map the dark lands beyond the eastern hills",
    "return the stolen relics to the city temple",
    "learn the ancient magick of the tribe of pygmie people",
    "carry the silver lantern through the valley of echoes",
    "recover the crown from the sleeping dragon",
    "escort a wandering sage across the haunted marshes",
    "decode the riddle carved into the black obelisk",
    "retrieve the lost banner from the broken tower",
    "retrieve the lost banner from the ruined keep",
    "cross the crystal bridge before dawn",
    "carry a sealed message through the misty valley",
    "seek the oracle beneath the old mountain",
    "recover the moonstone from the flooded temple",
    "escort a caravan through bandit country",
    "break the curse on the silent bell tower",
    "follow the silver stag into the ancient forest",
    "find the hidden gate under the western hills",
    "return the sleeping king's sword to its shrine",
    "search the old battlefield for a forgotten standard",
    "light the beacon at the edge of the world",
    "gather starflowers from the midnight meadow",
    "deliver a royal pardon to the lonely fortress",
    "seal the cracked mirror in the abandoned chapel",
    "bring peace to the ghosts of the old road",
)


_ALIGNMENT_NAMES = {"g": "good", "n": "neutral", "e": "evil"}

__all__ = [
    'PLUGIN_META',
    'IDLERPG_ENABLED_KEY',
    'IDLERPG_DATA_KEY',
    'PLUGIN_NAME',
    'ACHIEVEMENTS',
    'ITEMS',
    'ALIGNMENT_ITEM_POWER_FACTORS',
    'UNIQUE_BONUS_CAP_PERCENT',
    'UNIQUE_ITEMS',
    'MAP_REGIONS',
    'CALAMITIES',
    'GODSENDS',
    'QUEST_TEXTS',
    '_ALIGNMENT_NAMES',
]
