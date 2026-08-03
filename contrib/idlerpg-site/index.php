<?php
/*
 * Generic IdleRPG public website example for EnvsBot.
 *
 * Copy this directory to a PHP-capable webroot and point it at the JSON export
 * written by the IdleRPG plugin. This file is intentionally standalone and does
 * not depend on the envs.net website layout.
 *
 * Recommended layout:
 *
 *   public/idlerpg/index.php
 *   public/idlerpg/data/<room-slug>/room.json
 *   public/idlerpg/data/<room-slug>/leaderboard.json
 *   public/idlerpg/data/<room-slug>/players.json
 *   public/idlerpg/data/<room-slug>/map.json
 *   public/idlerpg/data/<room-slug>/events.json
 *   public/idlerpg/data/<room-slug>/hall_of_fame.json
 *
 * Optional environment variables:
 *
 *   IDLERPG_DATA_DIR   Either the export base directory or a room directory.
 *   IDLERPG_ROOM_SLUG  Room slug, for example room_at_conference.example.org.
 */

const IDLERPG_DEFAULT_ROOM_SLUG = 'room_at_conference.example.org';

function h($value) {
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function idlerpg_load_json($path, $default = []) {
    if (!is_readable($path)) {
        return $default;
    }
    $raw = file_get_contents($path);
    if ($raw === false || trim($raw) === '') {
        return $default;
    }
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : $default;
}

function idlerpg_ttl($seconds) {
    $seconds = max(0, (int) $seconds);
    $days = intdiv($seconds, 86400);
    $seconds %= 86400;
    $hours = intdiv($seconds, 3600);
    $seconds %= 3600;
    $minutes = intdiv($seconds, 60);
    $seconds %= 60;
    $day_label = $days === 1 ? 'day' : 'days';
    return sprintf('%d %s, %02d:%02d:%02d', $days, $day_label, $hours, $minutes, $seconds);
}

function idlerpg_time_value($value) {
    if ($value === null || $value === '') {
        return '';
    }
    if (is_numeric($value)) {
        return date('Y-m-d H:i:s T', (int) $value);
    }
    return (string) $value;
}

function idlerpg_player_name($player) {
    return $player['character'] ?? $player['name'] ?? 'unknown';
}

function idlerpg_player_level($player) {
    return (int) ($player['level'] ?? $player['lvl'] ?? 0);
}

function idlerpg_player_class($player) {
    return $player['class'] ?? $player['char_class'] ?? 'idler';
}

function idlerpg_player_online($player) {
    if (isset($player['online'])) {
        return (bool) $player['online'];
    }
    if (isset($player['status'])) {
        return strtolower((string) $player['status']) === 'online';
    }
    return false;
}

function idlerpg_quest_player_lookup($quest) {
    if (!is_array($quest)) {
        return [];
    }

    $participants = [];
    foreach (['questers', 'participants'] as $field) {
        if (!isset($quest[$field]) || !is_array($quest[$field])) {
            continue;
        }
        foreach ($quest[$field] as $participant) {
            $name = is_array($participant)
                ? idlerpg_player_name($participant)
                : (string) $participant;
            $key = strtolower(trim((string) $name));
            if ($key !== '') {
                $participants[$key] = true;
            }
        }
    }

    return $participants;
}

function idlerpg_player_on_quest($player, $quest_player_lookup) {
    $name = strtolower(trim((string) idlerpg_player_name($player)));
    return $name !== '' && isset($quest_player_lookup[$name]);
}

function idlerpg_player_coord($player, $axis) {
    if (isset($player[$axis]) && is_numeric($player[$axis])) {
        return (float) $player[$axis];
    }
    foreach (['position', 'map', 'coords', 'coordinates'] as $field) {
        if (isset($player[$field]) && is_array($player[$field])) {
            if (isset($player[$field][$axis]) && is_numeric($player[$field][$axis])) {
                return (float) $player[$field][$axis];
            }
            if ($axis === 'x' && isset($player[$field][0]) && is_numeric($player[$field][0])) {
                return (float) $player[$field][0];
            }
            if ($axis === 'y' && isset($player[$field][1]) && is_numeric($player[$field][1])) {
                return (float) $player[$field][1];
            }
        }
    }
    return 0.0;
}

function idlerpg_point_coord($point, $axis) {
    if (!is_array($point)) {
        return 0.0;
    }
    if (isset($point[$axis]) && is_numeric($point[$axis])) {
        return (float) $point[$axis];
    }
    if ($axis === 'x' && isset($point[0]) && is_numeric($point[0])) {
        return (float) $point[0];
    }
    if ($axis === 'y' && isset($point[1]) && is_numeric($point[1])) {
        return (float) $point[1];
    }
    return 0.0;
}


function idlerpg_map_label_width($name, $map_width) {
    $margin = 6;
    return min(max(24, strlen((string) $name) * 7), max(24, $map_width - ($margin * 2)));
}

function idlerpg_map_label_rect($label_x, $label_y, $anchor, $label_width) {
    $padding = 2;
    if ($anchor === 'end') {
        $left = $label_x - $label_width - $padding;
        $right = $label_x + $padding;
    } elseif ($anchor === 'middle') {
        $left = $label_x - ($label_width / 2) - $padding;
        $right = $label_x + ($label_width / 2) + $padding;
    } else {
        $left = $label_x - $padding;
        $right = $label_x + $label_width + $padding;
    }

    return [
        'left' => $left,
        'top' => $label_y - 11,
        'right' => $right,
        'bottom' => $label_y + 3,
    ];
}

function idlerpg_map_rects_overlap($a, $b) {
    $gap = 2;
    return !(
        $a['right'] + $gap <= $b['left']
        || $a['left'] >= $b['right'] + $gap
        || $a['bottom'] + $gap <= $b['top']
        || $a['top'] >= $b['bottom'] + $gap
    );
}

function idlerpg_map_layout_collides($rect, $occupied_rects) {
    foreach ($occupied_rects as $occupied) {
        if (idlerpg_map_rects_overlap($rect, $occupied)) {
            return true;
        }
    }
    return false;
}

function idlerpg_map_clamp_label_layout($label_x, $label_y, $anchor, $label_width, $map_width, $map_height) {
    $margin = 6;
    if ($anchor === 'end') {
        $label_x = max($margin + $label_width, min($map_width - $margin, $label_x));
    } elseif ($anchor === 'middle') {
        $half_width = $label_width / 2;
        $label_x = max($margin + $half_width, min($map_width - $margin - $half_width, $label_x));
    } else {
        $label_x = max($margin, min($map_width - $margin - $label_width, $label_x));
    }
    $label_y = max(14, min($map_height - $margin, $label_y));

    return [
        'x' => $label_x,
        'y' => $label_y,
        'anchor' => $anchor,
        'rect' => idlerpg_map_label_rect($label_x, $label_y, $anchor, $label_width),
    ];
}

function idlerpg_map_marker_label_layout($x, $y, $name, $map_width, $map_height, $occupied_rects = []) {
    $label_gap = 10;
    $label_width = idlerpg_map_label_width($name, $map_width);
    $candidates = [
        [$x + $label_gap, $y - 7, 'start'],
        [$x + $label_gap, $y + 15, 'start'],
        [$x - $label_gap, $y - 7, 'end'],
        [$x - $label_gap, $y + 15, 'end'],
        [$x, $y - 16, 'middle'],
        [$x, $y + 24, 'middle'],
        [$x + $label_gap, $y - 25, 'start'],
        [$x - $label_gap, $y - 25, 'end'],
        [$x + $label_gap, $y + 33, 'start'],
        [$x - $label_gap, $y + 33, 'end'],
    ];

    for ($radius = 44; $radius <= 110; $radius += 18) {
        $candidates[] = [$x + $label_gap, $y + $radius, 'start'];
        $candidates[] = [$x - $label_gap, $y + $radius, 'end'];
        $candidates[] = [$x + $label_gap, $y - $radius, 'start'];
        $candidates[] = [$x - $label_gap, $y - $radius, 'end'];
        $candidates[] = [$x, $y + $radius, 'middle'];
        $candidates[] = [$x, $y - $radius, 'middle'];
    }

    $fallback = null;
    foreach ($candidates as $candidate) {
        [$label_x, $label_y, $anchor] = $candidate;
        $layout = idlerpg_map_clamp_label_layout(
            $label_x,
            $label_y,
            $anchor,
            $label_width,
            $map_width,
            $map_height
        );
        if ($fallback === null) {
            $fallback = $layout;
        }
        if (!idlerpg_map_layout_collides($layout['rect'], $occupied_rects)) {
            return $layout;
        }
    }

    return $fallback;
}

function idlerpg_export_files_exist($dir) {
    if (!is_dir($dir)) {
        return false;
    }
    foreach (['room.json', 'map.json', 'leaderboard.json', 'players.json'] as $file) {
        if (is_readable(rtrim($dir, '/') . '/' . $file)) {
            return true;
        }
    }
    return false;
}

function idlerpg_safe_room_slug($value) {
    $value = trim((string) $value);
    if ($value === '' || strlen($value) > 180) {
        return '';
    }
    return preg_match('/^[A-Za-z0-9._-]+$/', $value) === 1 ? $value : '';
}

function idlerpg_export_base_dirs() {
    $dirs = [];
    $env_dir = getenv('IDLERPG_DATA_DIR');
    if ($env_dir !== false && trim($env_dir) !== '') {
        $dirs[] = rtrim(trim($env_dir), '/');
    }
    $dirs[] = __DIR__ . '/data';
    $dirs[] = __DIR__;
    return array_values(array_unique($dirs));
}

function idlerpg_room_entry($slug, $dir, $summary = []) {
    $slug = idlerpg_safe_room_slug($slug);
    if ($slug === '' || !idlerpg_export_files_exist($dir)) {
        return null;
    }
    $room_payload = idlerpg_load_json(rtrim($dir, '/') . '/room.json', []);
    return [
        'slug' => $slug,
        'room' => (string) ($summary['room'] ?? $room_payload['room'] ?? $slug),
        'dir' => rtrim($dir, '/'),
        'players_total' => max(0, (int) ($summary['players_total'] ?? $room_payload['players_total'] ?? 0)),
        'players_online' => max(0, (int) ($summary['players_online'] ?? $room_payload['players_online'] ?? 0)),
    ];
}

function idlerpg_available_rooms() {
    $rooms = [];
    $base_dirs = idlerpg_export_base_dirs();
    $normalized_base_dirs = array_map(
        fn($dir) => rtrim((string) (realpath($dir) ?: $dir), '/'),
        $base_dirs
    );

    foreach ($base_dirs as $base_dir) {
        if (!is_dir($base_dir)) {
            continue;
        }

        $base_contains_room_exports = false;
        $index = idlerpg_load_json(rtrim($base_dir, '/') . '/index.json', ['rooms' => []]);
        $summaries = is_array($index['rooms'] ?? null) ? $index['rooms'] : [];
        foreach ($summaries as $summary) {
            if (!is_array($summary)) {
                continue;
            }
            $slug = idlerpg_safe_room_slug($summary['slug'] ?? '');
            if ($slug === '') {
                continue;
            }
            $entry = idlerpg_room_entry($slug, rtrim($base_dir, '/') . '/' . $slug, $summary);
            if ($entry !== null) {
                $base_contains_room_exports = true;
                if (!isset($rooms[$slug])) {
                    $rooms[$slug] = $entry;
                }
            }
        }

        $entries = scandir($base_dir);
        if (is_array($entries)) {
            foreach ($entries as $entry_name) {
                if ($entry_name === '.' || $entry_name === '..') {
                    continue;
                }

                $entry_dir = rtrim($base_dir, '/') . '/' . $entry_name;
                $normalized_entry_dir = rtrim((string) (realpath($entry_dir) ?: $entry_dir), '/');
                if (in_array($normalized_entry_dir, $normalized_base_dirs, true)) {
                    continue;
                }

                $slug = idlerpg_safe_room_slug($entry_name);
                if ($slug === '') {
                    continue;
                }
                $entry = idlerpg_room_entry($slug, $entry_dir);
                if ($entry !== null) {
                    $base_contains_room_exports = true;
                    if (!isset($rooms[$slug])) {
                        $rooms[$slug] = $entry;
                    }
                }
            }
        }

        if (!$base_contains_room_exports && idlerpg_export_files_exist($base_dir)) {
            $room_payload = idlerpg_load_json(rtrim($base_dir, '/') . '/room.json', []);
            $slug = idlerpg_safe_room_slug($room_payload['slug'] ?? basename($base_dir));
            if ($slug === '') {
                $slug = IDLERPG_DEFAULT_ROOM_SLUG;
            }
            if (!isset($rooms[$slug])) {
                $entry = idlerpg_room_entry($slug, $base_dir);
                if ($entry !== null) {
                    $rooms[$slug] = $entry;
                }
            }
        }
    }

    uasort($rooms, function ($a, $b) {
        return strcasecmp((string) ($a['room'] ?? ''), (string) ($b['room'] ?? ''));
    });
    return $rooms;
}

function idlerpg_room_slug($rooms = null) {
    $rooms = is_array($rooms) ? $rooms : idlerpg_available_rooms();
    $requested = idlerpg_safe_room_slug($_GET['room'] ?? '');
    if ($requested !== '' && isset($rooms[$requested])) {
        return $requested;
    }

    $preferred_slugs = [
        idlerpg_safe_room_slug(getenv('IDLERPG_ROOM_SLUG') ?: ''),
        idlerpg_safe_room_slug(IDLERPG_DEFAULT_ROOM_SLUG),
    ];
    foreach ($preferred_slugs as $preferred_slug) {
        if ($preferred_slug !== '' && (count($rooms) === 0 || isset($rooms[$preferred_slug]))) {
            return $preferred_slug;
        }
    }

    if (count($rooms) > 0) {
        return (string) array_key_first($rooms);
    }
    return IDLERPG_DEFAULT_ROOM_SLUG;
}

function idlerpg_candidate_dirs($slug = null, $rooms = null) {
    $rooms = is_array($rooms) ? $rooms : idlerpg_available_rooms();
    $slug = idlerpg_safe_room_slug($slug ?? idlerpg_room_slug($rooms));
    $candidates = [];

    if ($slug !== '' && isset($rooms[$slug]['dir'])) {
        $candidates[] = $rooms[$slug]['dir'];
    }
    foreach (idlerpg_export_base_dirs() as $base_dir) {
        if ($slug !== '') {
            $candidates[] = rtrim($base_dir, '/') . '/' . $slug;
        }
        $candidates[] = rtrim($base_dir, '/');
    }
    return array_values(array_unique($candidates));
}

function idlerpg_data_dir($slug = null, $rooms = null) {
    foreach (idlerpg_candidate_dirs($slug, $rooms) as $candidate) {
        if (idlerpg_export_files_exist($candidate)) {
            return $candidate;
        }
    }
    $slug = idlerpg_safe_room_slug($slug ?? idlerpg_room_slug($rooms));
    return __DIR__ . '/data/' . ($slug !== '' ? $slug : IDLERPG_DEFAULT_ROOM_SLUG);
}

function idlerpg_data_file($filename, $data_dir = null) {
    $data_dir = $data_dir ?? idlerpg_data_dir();
    return rtrim($data_dir, '/') . '/' . ltrim($filename, '/');
}

function idlerpg_sort_players($players) {
    usort($players, function ($a, $b) {
        $level_cmp = idlerpg_player_level($b) <=> idlerpg_player_level($a);
        if ($level_cmp !== 0) {
            return $level_cmp;
        }
        return ((int) ($a['ttl'] ?? 0)) <=> ((int) ($b['ttl'] ?? 0));
    });
    return $players;
}

function idlerpg_current_view() {
    $allowed = ['home', 'players', 'achievements', 'map', 'quest', 'events', 'hof', 'rules', 'commands'];
    $view = strtolower(trim((string) ($_GET['view'] ?? 'home')));
    return in_array($view, $allowed, true) ? $view : 'home';
}

function idlerpg_view_url($view, $extra = []) {
    global $selected_room_slug;
    $params = ['view' => $view];
    if (!empty($selected_room_slug)) {
        $params['room'] = $selected_room_slug;
    }
    $params = array_merge($params, $extra);
    foreach ($params as $key => $value) {
        if ($value === null || $value === '') {
            unset($params[$key]);
        }
    }
    return '?' . http_build_query($params);
}

function idlerpg_player_url($name) {
    return idlerpg_view_url('players', ['character' => $name]);
}

function idlerpg_bool_label($value) {
    return $value ? 'enabled' : 'disabled';
}

function idlerpg_human_key($key) {
    return ucwords(trim(str_replace(['_', '-'], ' ', (string) $key)));
}


function idlerpg_ordered_stats($stats) {
    if (!is_array($stats)) {
        return [];
    }

    $preferred = [
        'alignment_events',
        'battles_won',
        'battles_lost',
        'team_battles_won',
        'team_battles_lost',
        'bosses_defeated',
        'bosses_failed',
        'quests_completed',
        'quest_failures',
        'manual_duels_started',
        'manual_duels_received',
        'godsends',
        'calamities',
        'item_blessings',
        'item_damage_events',
        'item_swaps_won',
        'unique_items_found',
        'unique_item_upgrades',
        'messages',
        'logouts',
    ];

    $ordered = [];
    foreach ($preferred as $key) {
        if (array_key_exists($key, $stats)) {
            $ordered[$key] = $stats[$key];
        }
    }

    $remaining = array_diff_key($stats, $ordered);
    ksort($remaining, SORT_NATURAL | SORT_FLAG_CASE);
    return $ordered + $remaining;
}

function idlerpg_rule_value($key, $value) {
    if (is_bool($value)) {
        return idlerpg_bool_label($value);
    }
    if ($value === null || $value === '') {
        return 'not set';
    }
    if (is_array($value)) {
        return implode(', ', array_map('strval', $value));
    }
    if (str_ends_with((string) $key, '_days')) {
        return max(0, (int) $value) . ' days';
    }
    if (str_ends_with((string) $key, '_seconds') || str_contains((string) $key, '_duration') || str_ends_with((string) $key, '_interval')) {
        return idlerpg_ttl((int) $value);
    }
    if ((str_contains((string) $key, 'chance') || str_contains((string) $key, 'percent')) && is_numeric($value)) {
        $number = (float) $value;
        if ($number >= 0 && $number <= 1) {
            return rtrim(rtrim(number_format($number * 100, 2), '0'), '.') . '%';
        }
        return rtrim(rtrim(number_format($number, 2), '0'), '.') . '%';
    }
    if (is_float($value)) {
        return rtrim(rtrim(number_format($value, 4), '0'), '.');
    }
    return (string) $value;
}

function idlerpg_paginate($items, $page, $per_page) {
    $per_page = max(1, (int) $per_page);
    $total = count($items);
    $pages = max(1, (int) ceil($total / $per_page));
    $page = max(1, min($pages, (int) $page));
    return [
        'items' => array_slice($items, ($page - 1) * $per_page, $per_page),
        'page' => $page,
        'pages' => $pages,
        'total' => $total,
    ];
}

function idlerpg_render_pagination($view, $pagination, $extra = []) {
    if (($pagination['pages'] ?? 1) <= 1) {
        return;
    }
    echo '<nav class="pagination" aria-label="Pagination">';
    for ($page = 1; $page <= $pagination['pages']; $page++) {
        $class = $page === $pagination['page'] ? 'active' : '';
        echo '<a class="' . h($class) . '" href="' . h(idlerpg_view_url($view, array_merge($extra, ['page' => $page]))) . '">' . h($page) . '</a>';
    }
    echo '</nav>';
}

function idlerpg_achievement_count($player) {
    return is_array($player['achievements'] ?? null) ? count($player['achievements']) : 0;
}

function idlerpg_player_status_badge($player) {
    $online = idlerpg_player_online($player);
    $class = $online ? 'status online' : 'status offline';
    $label = $online ? 'online' : 'offline';
    return '<span class="' . h($class) . '">' . h($label) . '</span>';
}

function idlerpg_player_created_at($player) {
    if (isset($player['created_at']) && is_numeric($player['created_at'])) {
        return max(0, (int) $player['created_at']);
    }
    if (isset($player['registered_at']) && is_numeric($player['registered_at'])) {
        return max(0, (int) $player['registered_at']);
    }
    return 0;
}

function idlerpg_player_played_seconds($player) {
    if (isset($player['played_for']) && is_numeric($player['played_for'])) {
        return max(0, (int) $player['played_for']);
    }
    $created_at = idlerpg_player_created_at($player);
    return $created_at > 0 ? max(0, time() - $created_at) : 0;
}

function idlerpg_player_created_label($player) {
    $created_at = idlerpg_player_created_at($player);
    return $created_at > 0 ? idlerpg_time_value($created_at) : '';
}

function idlerpg_player_played_label($player) {
    $played = idlerpg_player_played_seconds($player);
    return $played > 0 ? idlerpg_ttl($played) : '';
}

function idlerpg_event_time($event) {
    $ts = (int) ($event['ts'] ?? 0);
    return $ts > 0 ? date('Y-m-d H:i', $ts) : '';
}

function idlerpg_event_matches_player($event, $character) {
    $character = strtolower(trim((string) $character));
    if ($character === '') {
        return false;
    }
    $players = is_array($event['players'] ?? null) ? $event['players'] : [];
    foreach ($players as $player) {
        if (strtolower((string) $player) === $character) {
            return true;
        }
    }
    return stripos((string) ($event['text'] ?? ''), $character) !== false;
}

function idlerpg_render_events($events, $limit = 10) {
    $items = array_slice($events, 0, max(0, (int) $limit));
    if (count($items) === 0) {
        echo '<p class="muted">No recent events yet.</p>';
        return;
    }
    echo '<ol class="events">';
    foreach ($items as $event) {
        $kind = strtolower((string) ($event['kind'] ?? 'event'));
        $icon = str_contains($kind, 'achievement') ? '🏅 ' : '';
        echo '<li><span class="event-time">' . h(idlerpg_event_time($event)) . '</span> ';
        echo '<span class="event-kind">' . h($icon) . '[' . h($event['kind'] ?? 'event') . ']</span> ';
        echo h($event['text'] ?? '') . '</li>';
    }
    echo '</ol>';
}


function idlerpg_player_achievement_keys($player) {
    $keys = [];
    $achievements = is_array($player['achievements'] ?? null) ? $player['achievements'] : [];
    foreach ($achievements as $achievement) {
        $key = is_array($achievement) ? (string) ($achievement['key'] ?? '') : (string) $achievement;
        if ($key !== '') {
            $keys[$key] = true;
        }
    }
    return $keys;
}

function idlerpg_filter_players($players, $query, $status) {
    $query = strtolower(trim((string) $query));
    $status = strtolower(trim((string) $status));
    return array_values(array_filter($players, function ($player) use ($query, $status) {
        if ($status === 'online' && !idlerpg_player_online($player)) {
            return false;
        }
        if ($status === 'offline' && idlerpg_player_online($player)) {
            return false;
        }
        if ($query === '') {
            return true;
        }
        $haystack = implode(' ', [
            idlerpg_player_name($player),
            idlerpg_player_class($player),
            (string) ($player['title'] ?? ''),
            (string) ($player['alignment'] ?? ''),
            (string) ($player['region'] ?? ''),
        ]);
        return str_contains(strtolower($haystack), $query);
    }));
}

function idlerpg_filter_events($events, $query, $kind, $player) {
    $query = strtolower(trim((string) $query));
    $kind = strtolower(trim((string) $kind));
    $player = strtolower(trim((string) $player));
    return array_values(array_filter($events, function ($event) use ($query, $kind, $player) {
        $event_kind = strtolower((string) ($event['kind'] ?? 'event'));
        if ($kind !== '' && $kind !== 'all' && $event_kind !== $kind) {
            return false;
        }
        if ($player !== '' && !idlerpg_event_matches_player($event, $player)) {
            return false;
        }
        if ($query === '') {
            return true;
        }
        $players = is_array($event['players'] ?? null) ? implode(' ', $event['players']) : '';
        return str_contains(strtolower($event_kind . ' ' . (string) ($event['text'] ?? '') . ' ' . $players), $query);
    }));
}

function idlerpg_event_kinds($events) {
    $kinds = [];
    foreach ($events as $event) {
        $kind = strtolower(trim((string) ($event['kind'] ?? 'event')));
        if ($kind !== '') {
            $kinds[$kind] = true;
        }
    }
    $values = array_keys($kinds);
    sort($values, SORT_NATURAL | SORT_FLAG_CASE);
    return $values;
}

function idlerpg_achievement_earners($players, $key) {
    $earners = [];
    foreach ($players as $player) {
        if (isset(idlerpg_player_achievement_keys($player)[$key])) {
            $earners[] = idlerpg_player_name($player);
        }
    }
    natcasesort($earners);
    return array_values($earners);
}

function idlerpg_percent($part, $total) {
    if ((int) $total <= 0) {
        return '0%';
    }
    return rtrim(rtrim(number_format(((int) $part / (int) $total) * 100, 1), '0'), '.') . '%';
}

$available_rooms = idlerpg_available_rooms();
$selected_room_slug = idlerpg_room_slug($available_rooms);
$data_dir = idlerpg_data_dir($selected_room_slug, $available_rooms);
$room_payload = idlerpg_load_json(idlerpg_data_file('room.json', $data_dir), []);
$leaderboard_payload = idlerpg_load_json(idlerpg_data_file('leaderboard.json', $data_dir), ['players' => []]);
$players_payload = idlerpg_load_json(idlerpg_data_file('players.json', $data_dir), ['players' => []]);
$map_payload = idlerpg_load_json(idlerpg_data_file('map.json', $data_dir), ['players' => [], 'width' => 500, 'height' => 500]);
$events_payload = idlerpg_load_json(idlerpg_data_file('events.json', $data_dir), ['events' => []]);
$hof_payload = idlerpg_load_json(idlerpg_data_file('hall_of_fame.json', $data_dir), ['seasons' => []]);
$achievements_payload = idlerpg_load_json(idlerpg_data_file('achievements.json', $data_dir), ['achievements' => []]);

$leaderboard = is_array($leaderboard_payload['players'] ?? null)
    ? $leaderboard_payload['players']
    : (is_array($room_payload['leaderboard'] ?? null) ? $room_payload['leaderboard'] : []);
$players = is_array($players_payload['players'] ?? null)
    ? $players_payload['players']
    : (is_array($room_payload['players'] ?? null) ? $room_payload['players'] : $leaderboard);
$players = idlerpg_sort_players($players);
if (count($leaderboard) === 0 && count($players) > 0) {
    $leaderboard = $players;
}
$map_players = is_array($map_payload['players'] ?? null)
    ? $map_payload['players']
    : (is_array($room_payload['players'] ?? null) ? $room_payload['players'] : $players);
if (count($map_players) === 0 && count($players) > 0) {
    $map_players = $players;
}
$events = is_array($events_payload['events'] ?? null)
    ? $events_payload['events']
    : (is_array($room_payload['events'] ?? null) ? $room_payload['events'] : []);
usort($events, function ($a, $b) {
    return ((int) ($b['ts'] ?? 0)) <=> ((int) ($a['ts'] ?? 0));
});
$seasons = is_array($hof_payload['seasons'] ?? null)
    ? $hof_payload['seasons']
    : (is_array($room_payload['hall_of_fame'] ?? null) ? $room_payload['hall_of_fame'] : []);
$achievement_catalog = is_array($achievements_payload['achievements'] ?? null)
    ? $achievements_payload['achievements']
    : (is_array($room_payload['achievement_catalog'] ?? null) ? $room_payload['achievement_catalog'] : []);
$rules = is_array($room_payload['rules'] ?? null) ? $room_payload['rules'] : [];
$season = is_array($room_payload['season'] ?? null) ? $room_payload['season'] : [];
$room = $room_payload['room'] ?? $leaderboard_payload['room'] ?? $players_payload['room'] ?? $map_payload['room'] ?? '';
$updated = $room_payload['generated_at'] ?? $leaderboard_payload['generated_at'] ?? $players_payload['generated_at'] ?? $map_payload['generated_at'] ?? null;

$selected_character = trim((string) ($_GET['character'] ?? ''));
$selected_profile = null;
foreach ($players as $player) {
    if (strcasecmp(idlerpg_player_name($player), $selected_character) === 0) {
        $selected_profile = $player;
        break;
    }
}
$view = idlerpg_current_view();
$render_map = false;
$quest = is_array($map_payload['quest'] ?? null)
    ? $map_payload['quest']
    : (is_array($room_payload['quest'] ?? null) ? $room_payload['quest'] : null);
$active_quest_type = '';
if ($quest) {
    $active_quest_type = strtolower((string) ($quest['type'] ?? ''));
    if ($active_quest_type !== 'time' && $active_quest_type !== 'grid') {
        $active_quest_type = !empty($quest['route']) ? 'grid' : 'time';
    }
}
$quest_route = $quest && is_array($quest['route'] ?? null) ? $quest['route'] : [];
$has_quest_route = count($quest_route) > 0;
$quest_target = $quest && is_array($quest['target'] ?? null) ? $quest['target'] : null;
$has_quest_target = is_array($quest_target) && count($quest_target) >= 2;
$quest_player_lookup = idlerpg_quest_player_lookup($quest);
$room_map = is_array($room_payload['map'] ?? null) ? $room_payload['map'] : [];
$map_width = max(1, (int) ($map_payload['width'] ?? $map_payload['map_x'] ?? $room_map['width'] ?? 500));
$map_height = max(1, (int) ($map_payload['height'] ?? $map_payload['map_y'] ?? $room_map['height'] ?? 500));
$online_count = 0;
foreach ($players as $player) {
    if (idlerpg_player_online($player)) {
        $online_count++;
    }
}

$player_query = trim((string) ($_GET['q'] ?? ''));
$player_status = strtolower(trim((string) ($_GET['status'] ?? 'all')));
if (!in_array($player_status, ['all', 'online', 'offline'], true)) {
    $player_status = 'all';
}
$filtered_players = idlerpg_filter_players($players, $player_query, $player_status);
$player_pagination = idlerpg_paginate($filtered_players, (int) ($_GET['page'] ?? 1), 40);

$event_query = trim((string) ($_GET['q'] ?? ''));
$event_kind = strtolower(trim((string) ($_GET['kind'] ?? 'all')));
$event_player = trim((string) ($_GET['player'] ?? ''));
$event_kinds = idlerpg_event_kinds($events);
$filtered_events = idlerpg_filter_events($events, $event_query, $event_kind, $event_player);
$event_pagination = idlerpg_paginate($filtered_events, (int) ($_GET['page'] ?? 1), 30);

$current_season_ends_at = max(0, (int) ($season['ends_at'] ?? 0));
$current_season_started_at = max(0, (int) ($season['started_at'] ?? 0));
$current_season_remaining = $current_season_ends_at > 0 ? max(0, $current_season_ends_at - time()) : 0;
$achievement_unlocks = [];
foreach ($achievement_catalog as $achievement) {
    if (!is_array($achievement)) {
        continue;
    }
    $key = (string) ($achievement['key'] ?? '');
    if ($key !== '') {
        $achievement_unlocks[$key] = idlerpg_achievement_earners($players, $key);
    }
}
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IdleRPG<?php if ($room !== ''): ?> · <?php echo h($room); ?><?php endif; ?></title>
<style>
:root {
    color-scheme: dark;
    --bg: #10151a;
    --panel: #151c23;
    --fg: #f4f4f0;
    --muted: #9ca3af;
    --line: #38414a;
    --link: #00c2b8;
    --active: #2563eb;
    --good: #49c27b;
    --warn: #e0a82e;
    --bad: #d65c5c;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font: 15px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
a { color: var(--link); }
a:hover, a:focus { text-decoration-thickness: 2px; }
.container { max-width: 1280px; margin: 0 auto; padding: 1.25rem; }
.header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
.header h1 { margin-bottom: .25rem; }
.header-tools { display: flex; gap: .75rem; align-items: end; flex-wrap: wrap; }
.muted { color: var(--muted); }
.nav { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1rem 0 1.25rem; }
.nav a { border: 1px solid var(--line); padding: .35rem .7rem; text-decoration: none; }
.nav a:hover, .nav a:focus { background: rgba(0, 194, 184, .18); outline: none; }
.nav a.active { background: var(--active); border-color: var(--active); color: white; }
.grid { display: grid; grid-template-columns: minmax(0, 1fr) 19rem; gap: 2rem; align-items: start; }
@media (max-width: 960px) { .grid { grid-template-columns: 1fr; } }
.card { border-left: 4px solid var(--line); padding: .65rem 0 .65rem 1rem; margin-bottom: 1rem; }
.panel { border: 1px solid var(--line); background: var(--panel); padding: 1rem; margin: 1rem 0; }
.panel > :first-child { margin-top: 0; }
.panel > :last-child { margin-bottom: 0; }
table { width: 100%; border-collapse: collapse; margin: 1rem 0 2rem; }
th, td { border-bottom: 1px solid var(--line); padding: .42rem .55rem .42rem 0; text-align: left; vertical-align: top; }
thead th { color: #dce3ea; }
code { background: rgba(255,255,255,.08); padding: .05rem .3rem; overflow-wrap: anywhere; }
.stats { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }
.stats strong { display: block; font-size: 1.35rem; }
.events li { margin-bottom: .45rem; }
.event-time, .event-kind { color: var(--muted); }
.form-row { display: flex; flex-wrap: wrap; gap: .65rem; align-items: end; margin: .75rem 0 1.25rem; }
.form-row label { display: grid; gap: .25rem; color: var(--muted); }
input, select, button {
    font: inherit;
    color: var(--fg);
    background: var(--panel);
    border: 1px solid var(--line);
    padding: .42rem .55rem;
}
button { cursor: pointer; }
button:hover, button:focus { border-color: var(--link); }
.pagination { display: flex; flex-wrap: wrap; gap: .4rem; margin: 1rem 0 2rem; }
.pagination a { min-width: 2rem; text-align: center; border: 1px solid var(--line); padding: .25rem .45rem; text-decoration: none; }
.pagination a.active { background: var(--active); border-color: var(--active); color: white; }
.badges { display: flex; flex-wrap: wrap; gap: .45rem; margin: .75rem 0; }
.badge { display: inline-block; border: 1px solid var(--line); padding: .2rem .45rem; }
.badge.good { border-color: var(--good); color: var(--good); }
.badge.warn { border-color: var(--warn); color: var(--warn); }
.achievement-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: 1rem; }
.achievement { border: 1px solid var(--line); padding: .85rem; background: var(--panel); }
.achievement h3 { margin: 0 0 .35rem; }
.achievement .progress { color: var(--muted); font-size: .92rem; }
.details-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr)); gap: 1rem; }
.compact-list { margin: .4rem 0; padding-left: 1.25rem; }
.rule-groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(21rem, 1fr)); gap: 1rem; }
.rule-group { border: 1px solid var(--line); padding: .75rem; background: var(--panel); }
.rule-group h3 { margin-top: 0; }
details.season { border: 1px solid var(--line); margin: .75rem 0; padding: .65rem .8rem; background: var(--panel); }
details.season summary { cursor: pointer; font-weight: 700; }
.map-wrap { max-width: 760px; margin: 1rem 0 1.5rem; }
.world-map { display: block; width: min(100%, 720px); height: auto; border: 1px solid var(--line); background: #f3edbd; }
.map-label { font-style: italic; font-size: 16px; fill: #4b2d10; opacity: .88; }
.map-small-label { font-size: 11px; fill: #4b2d10; opacity: .8; }
.marker { cursor: pointer; }
.marker text { font-size: 12px; fill: #111; paint-order: stroke; stroke: #f3edbd; stroke-width: 4px; stroke-linejoin: round; pointer-events: none; }
.world-map.map-density-compact .marker text,
.world-map.map-density-dense .marker text { transition: opacity .12s ease; }
.world-map.map-density-compact .marker:not(.quester) text,
.world-map.map-density-dense .marker:not(.quester) text { visibility: hidden; opacity: 0; }
.world-map.map-density-compact .marker text { font-size: 11px; }
.world-map.map-density-dense .marker text { font-size: 10px; stroke-width: 3px; }
.world-map.map-density-compact a:hover .marker text,
.world-map.map-density-compact a:focus .marker text,
.world-map.map-density-dense a:hover .marker text,
.world-map.map-density-dense a:focus .marker text,
.world-map.map-density-compact .marker.quester text,
.world-map.map-density-dense .marker.quester text { visibility: visible; opacity: 1; }
.world-map a:hover .marker circle, .world-map a:focus .marker circle { stroke-width: 2.4; }
.world-map a:hover .marker text, .world-map a:focus .marker text { font-weight: 700; }
.marker.online circle { fill: #2f80ff; }
.marker.offline circle { fill: #b33; }
.marker.quester circle { fill: #d99b00; }
.marker circle { stroke: #111; stroke-width: 1.5; }
.quest-point { fill: #d99b00; stroke: #111; stroke-width: 1.5; }
.quest-line { fill: none; stroke: #d99b00; stroke-width: 2; stroke-dasharray: 6 5; }
.status { display: inline-flex; align-items: center; gap: .45ch; white-space: nowrap; }
.status::before { content: ''; width: .7em; height: .7em; border-radius: 999px; background: currentColor; }
.status.online { color: #2f80ff; }
.status.offline { color: var(--bad); }
.empty { border: 1px dashed var(--line); padding: 1rem; color: var(--muted); }
.footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--line); color: var(--muted); }
@media (max-width: 700px) {
    .container { padding: .8rem; }
    table { display: block; overflow-x: auto; }
    .header-tools { width: 100%; }
    .header-tools form { width: 100%; }
    .header-tools select { max-width: 100%; }
}
</style>
</head>
<body>
<div class="container">
    <header class="header">
        <div>
            <h1>IdleRPG</h1>
            <p class="muted"><?php echo h(count($players)); ?> players · <?php echo h($online_count); ?> online · <?php echo h(count($achievement_catalog)); ?> achievements</p>
        </div>
        <?php if (count($available_rooms) > 1): ?>
            <div class="header-tools">
                <form method="get" action="">
                    <input type="hidden" name="view" value="<?php echo h($view); ?>">
                    <label>Game room
                        <select name="room">
                            <?php foreach ($available_rooms as $slug => $entry): ?>
                                <option value="<?php echo h($slug); ?>" <?php echo $slug === $selected_room_slug ? 'selected' : ''; ?>>
                                    <?php echo h($entry['room'] ?? $slug); ?> (<?php echo h($entry['players_online'] ?? 0); ?>/<?php echo h($entry['players_total'] ?? 0); ?> online)
                                </option>
                            <?php endforeach; ?>
                        </select>
                    </label>
                    <button type="submit">Switch</button>
                </form>
            </div>
        <?php endif; ?>
    </header>

    <nav class="nav" aria-label="IdleRPG navigation">
        <?php foreach ([
            'home' => 'Home',
            'players' => 'Players',
            'achievements' => 'Achievements',
            'quest' => 'Quest',
            'events' => 'Events',
            'map' => 'World Map',
            'hof' => 'Seasons & Hall of Fame',
            'rules' => 'Rules',
            'commands' => 'Commands',
        ] as $tab => $label): ?>
            <a class="<?php echo $view === $tab ? 'active' : ''; ?>" href="<?php echo h(idlerpg_view_url($tab)); ?>"><?php echo h($label); ?></a>
        <?php endforeach; ?>
    </nav>

    <p class="muted">
        <?php if ($room !== ''): ?>Room: <code><?php echo h($room); ?></code><?php endif; ?>
        <?php if ($updated): ?> · updated <?php echo h(idlerpg_time_value($updated)); ?><?php endif; ?>
    </p>

    <?php if (isset($_GET['debug'])): ?>
        <h2>Export debug</h2>
        <p>Selected data directory: <code><?php echo h($data_dir); ?></code></p>
        <table>
            <thead><tr><th>Candidate</th><th>Directory</th><th>map.json</th><th>players.json</th></tr></thead>
            <tbody>
            <?php foreach (idlerpg_candidate_dirs($selected_room_slug, $available_rooms) as $candidate): ?>
                <tr>
                    <td><code><?php echo h($candidate); ?></code></td>
                    <td><?php echo is_dir($candidate) ? 'yes' : 'no'; ?></td>
                    <td><?php echo is_readable(rtrim($candidate, '/') . '/map.json') ? 'readable' : 'not readable'; ?></td>
                    <td><?php echo is_readable(rtrim($candidate, '/') . '/players.json') ? 'readable' : 'not readable'; ?></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php endif; ?>

    <div class="grid">
        <main>
            <?php if ($view === 'home'): ?>
                <p>The IdleRPG is an RPG for patient XMPP users: create a character, log in, remain idle and wait for the next level. Equipment, battles, quests, godsends, calamities, achievements and seasons progress automatically while the game runs.</p>
                <div class="stats">
                    <div class="card"><span>Players</span><strong><?php echo h(count($players)); ?></strong><small class="muted"><?php echo h($online_count); ?> currently online</small></div>
                    <div class="card"><span>Top player</span><strong><?php echo count($leaderboard) > 0 ? h(idlerpg_player_name($leaderboard[0])) : 'n/a'; ?></strong><small class="muted"><?php echo count($leaderboard) > 0 ? 'level ' . h(idlerpg_player_level($leaderboard[0])) : 'no ranking yet'; ?></small></div>
                    <div class="card"><span>Quest</span><strong><?php echo $quest ? h($active_quest_type . '-based') : 'none'; ?></strong><small class="muted"><?php echo $quest ? h(count($quest['questers'] ?? [])) . ' participants' : 'waiting for the next quest'; ?></small></div>
                    <div class="card"><span>Season</span><strong><?php echo h($season['id'] ?? 'manual'); ?></strong><small class="muted"><?php echo $current_season_ends_at > 0 ? h(idlerpg_ttl($current_season_remaining)) . ' remaining' : 'no automatic end'; ?></small></div>
                </div>

                <?php if ($quest): ?>
                    <section class="panel">
                        <h2>Active quest</h2>
                        <p><strong><?php echo h($quest['text'] ?? 'adventure'); ?></strong></p>
                        <p class="muted"><?php echo h(ucfirst($active_quest_type)); ?> quest with <?php echo h(count($quest['questers'] ?? [])); ?> participants<?php if (!empty($quest['complete_at'])): ?> · <?php echo $active_quest_type === 'grid' ? 'deadline in ' : ''; ?><?php echo h(idlerpg_ttl(max(0, (int) $quest['complete_at'] - time()))); ?><?php echo $active_quest_type === 'time' ? ' remaining' : ''; ?><?php endif; ?>.</p>
                        <p><a href="<?php echo h(idlerpg_view_url('quest')); ?>">Open quest details and map →</a></p>
                    </section>
                <?php endif; ?>

                <h2>Top 5 players</h2>
                <?php if (count($leaderboard) > 0): ?>
                    <table><thead><tr><th>#</th><th>Character</th><th>Class</th><th>Level</th><th>Next level</th><th>Status</th></tr></thead><tbody>
                    <?php foreach (array_slice($leaderboard, 0, 5) as $index => $player): $name = idlerpg_player_name($player); ?>
                        <tr><td><?php echo h($player['rank'] ?? $index + 1); ?></td><td><a href="<?php echo h(idlerpg_player_url($name)); ?>"><?php echo h($name); ?></a></td><td><?php echo h(idlerpg_player_class($player)); ?></td><td>lv.<?php echo h(idlerpg_player_level($player)); ?></td><td><?php echo h(idlerpg_ttl($player['ttl'] ?? 0)); ?></td><td><?php echo idlerpg_player_status_badge($player); ?></td></tr>
                    <?php endforeach; ?>
                    </tbody></table>
                <?php else: ?><p class="empty">No players exported yet.</p><?php endif; ?>
                <p><a href="<?php echo h(idlerpg_view_url('players')); ?>">View all players →</a></p>

                <h2>Recent events</h2>
                <?php idlerpg_render_events($events, 8); ?>
                <?php if (count($events) > 8): ?><p><a href="<?php echo h(idlerpg_view_url('events')); ?>">Browse the complete event export →</a></p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'players'): ?>
                <h2><?php echo $selected_profile ? 'Player profile' : 'Players'; ?></h2>
                <?php if ($selected_profile): ?>
                    <?php
                    $profile_name = idlerpg_player_name($selected_profile);
                    $profile_stats = idlerpg_ordered_stats(is_array($selected_profile['stats'] ?? null) ? $selected_profile['stats'] : []);
                    $profile_items = is_array($selected_profile['items'] ?? null) ? $selected_profile['items'] : [];
                    $profile_unique_items = is_array($selected_profile['unique_items'] ?? null) ? $selected_profile['unique_items'] : [];
                    $profile_unique_bonuses = is_array($selected_profile['unique_item_bonuses'] ?? null) ? $selected_profile['unique_item_bonuses'] : [];
                    $profile_achievements = is_array($selected_profile['achievements'] ?? null) ? $selected_profile['achievements'] : [];
                    $player_events = array_values(array_filter($events, function ($event) use ($selected_profile) {
                        return idlerpg_event_matches_player($event, idlerpg_player_name($selected_profile));
                    }));
                    ?>
                    <section class="panel">
                        <h3><?php echo h($profile_name); ?><?php if (!empty($selected_profile['title'])): ?> · <?php echo h($selected_profile['title']); ?><?php endif; ?></h3>
                        <div class="badges">
                            <?php echo idlerpg_player_status_badge($selected_profile); ?>
                            <span class="badge">lv.<?php echo h(idlerpg_player_level($selected_profile)); ?></span>
                            <span class="badge"><?php echo h($selected_profile['alignment'] ?? 'neutral'); ?></span>
                            <span class="badge"><?php echo h($selected_profile['region'] ?? 'unknown region'); ?></span>
                        </div>
                        <div class="details-grid">
                            <div>
                                <h4>Character</h4>
                                <table><tbody>
                                    <tr><th>Class</th><td><?php echo h(idlerpg_player_class($selected_profile)); ?></td></tr>
                                    <tr><th>Rank</th><td>#<?php echo h($selected_profile['rank'] ?? '?'); ?></td></tr>
                                    <tr><th>Next level</th><td><?php echo h(idlerpg_ttl($selected_profile['ttl'] ?? 0)); ?></td></tr>
                                    <tr><th>Playing since</th><td><?php echo h(idlerpg_player_created_label($selected_profile) ?: 'unknown'); ?></td></tr>
                                    <tr><th>Playing for</th><td><?php echo h(idlerpg_player_played_label($selected_profile) ?: 'unknown'); ?></td></tr>
                                    <tr><th>Idled online</th><td><?php echo h(idlerpg_ttl($selected_profile['idled'] ?? 0)); ?></td></tr>
                                    <tr><th>Last seen</th><td><?php echo !empty($selected_profile['last_seen']) ? h(idlerpg_time_value($selected_profile['last_seen'])) : 'unknown'; ?></td></tr>
                                    <tr><th>Map position</th><td><a href="<?php echo h(idlerpg_view_url('map')); ?>">[<?php echo h((int) idlerpg_player_coord($selected_profile, 'x')); ?>,<?php echo h((int) idlerpg_player_coord($selected_profile, 'y')); ?>]</a></td></tr>
                                    <tr><th>Item sum</th><td><?php echo h($selected_profile['item_sum'] ?? 0); ?></td></tr>
                                </tbody></table>
                            </div>
                            <div>
                                <h4>Statistics</h4>
                                <?php if (count($profile_stats) > 0): ?>
                                    <table><tbody>
                                    <?php foreach ($profile_stats as $key => $value): ?>
                                        <tr><th><?php echo h(idlerpg_human_key($key)); ?></th><td><?php echo h($value); ?></td></tr>
                                    <?php endforeach; ?>
                                    </tbody></table>
                                <?php else: ?><p class="muted">No statistics exported yet.</p><?php endif; ?>
                            </div>
                        </div>

                        <div class="details-grid">
                            <div>
                                <h4>Equipment</h4>
                                <?php if (count($profile_items) > 0): ?>
                                    <table><thead><tr><th>Slot</th><th>Level</th><th>Tier</th><th>Bound unique item</th></tr></thead><tbody>
                                    <?php foreach ($profile_items as $slot => $level): ?>
                                        <?php $slot_bonus = null; foreach ($profile_unique_bonuses as $candidate_bonus) { if (is_array($candidate_bonus) && (string) ($candidate_bonus['slot'] ?? '') === (string) $slot) { $slot_bonus = $candidate_bonus; break; } } ?>
                                        <tr><td><?php echo h(idlerpg_human_key($slot)); ?></td><td><?php echo h(max(0, (int) $level)); ?></td><td><?php echo $slot_bonus ? 'T' . h((int) ($slot_bonus['tier'] ?? 1)) : ''; ?></td><td><?php echo h($profile_unique_items[$slot] ?? ''); ?></td></tr>
                                    <?php endforeach; ?>
                                    </tbody></table>
                                <?php else: ?><p class="muted">No equipment exported.</p><?php endif; ?>
                            </div>
                            <div>
                                <h4>Unique-item bonuses</h4>
                                <?php if (count($profile_unique_bonuses) > 0): ?>
                                    <ul class="compact-list">
                                    <?php foreach ($profile_unique_bonuses as $bonus): ?>
                                        <li><strong><?php echo h($bonus['name'] ?? 'Unique item'); ?></strong> — tier <?php echo h((int) ($bonus['tier'] ?? 1)); ?>, <?php echo h(idlerpg_human_key($bonus['bonus'] ?? 'bonus')); ?> +<?php echo h($bonus['bonus_percent'] ?? 0); ?>%<?php if (!empty($bonus['next_upgrade_level'])): ?> · next tier from lv.<?php echo h((int) $bonus['next_upgrade_level']); ?><?php endif; ?></li>
                                    <?php endforeach; ?>
                                    </ul>
                                <?php else: ?><p class="muted">No unique-item bonuses.</p><?php endif; ?>
                            </div>
                        </div>

                        <h4>Achievements (<?php echo h(count($profile_achievements)); ?>/<?php echo h(count($achievement_catalog)); ?>)</h4>
                        <?php if (count($profile_achievements) > 0): ?>
                            <div class="achievement-grid">
                            <?php foreach ($profile_achievements as $achievement): ?>
                                <div class="achievement"><h3>🏅 <?php echo h(is_array($achievement) ? ($achievement['title'] ?? $achievement['key'] ?? '') : $achievement); ?></h3><p><?php echo h(is_array($achievement) ? ($achievement['description'] ?? '') : ''); ?></p></div>
                            <?php endforeach; ?>
                            </div>
                        <?php else: ?><p class="muted">No achievements unlocked yet.</p><?php endif; ?>

                        <h4>Recent player events</h4>
                        <?php idlerpg_render_events($player_events, 12); ?>
                        <?php if (count($player_events) > 12): ?><p><a href="<?php echo h(idlerpg_view_url('events', ['player' => $profile_name])); ?>">Show all events involving <?php echo h($profile_name); ?> →</a></p><?php endif; ?>
                    </section>
                <?php elseif ($selected_character !== ''): ?>
                    <p class="empty">No exported player named <strong><?php echo h($selected_character); ?></strong> was found.</p>
                <?php endif; ?>

                <form class="form-row" method="get" action="">
                    <input type="hidden" name="view" value="players">
                    <input type="hidden" name="room" value="<?php echo h($selected_room_slug); ?>">
                    <label>Search<input type="search" name="q" value="<?php echo h($player_query); ?>" placeholder="Name, class, title, region"></label>
                    <label>Status<select name="status"><option value="all">all</option><option value="online" <?php echo $player_status === 'online' ? 'selected' : ''; ?>>online</option><option value="offline" <?php echo $player_status === 'offline' ? 'selected' : ''; ?>>offline</option></select></label>
                    <button type="submit">Filter</button>
                    <?php if ($player_query !== '' || $player_status !== 'all'): ?><a href="<?php echo h(idlerpg_view_url('players')); ?>">Reset</a><?php endif; ?>
                </form>
                <p class="muted"><?php echo h($player_pagination['total']); ?> matching players.</p>
                <?php if (count($player_pagination['items']) > 0): ?>
                    <table><thead><tr><th>#</th><th>Player</th><th>Class</th><th>Level</th><th>Next level</th><th>Region</th><th>Achievements</th><th>Status</th></tr></thead><tbody>
                    <?php foreach ($player_pagination['items'] as $player): $name = idlerpg_player_name($player); ?>
                        <tr><td><?php echo h($player['rank'] ?? '?'); ?></td><td><a href="<?php echo h(idlerpg_player_url($name)); ?>"><?php echo h($name); ?></a><?php if (!empty($player['title'])): ?><br><small class="muted"><?php echo h($player['title']); ?></small><?php endif; ?></td><td><?php echo h(idlerpg_player_class($player)); ?></td><td>lv.<?php echo h(idlerpg_player_level($player)); ?></td><td><?php echo h(idlerpg_ttl($player['ttl'] ?? 0)); ?></td><td><?php echo h($player['region'] ?? ''); ?></td><td><?php echo h(idlerpg_achievement_count($player)); ?></td><td><?php echo idlerpg_player_status_badge($player); ?></td></tr>
                    <?php endforeach; ?>
                    </tbody></table>
                    <?php idlerpg_render_pagination('players', $player_pagination, ['q' => $player_query, 'status' => $player_status]); ?>
                <?php else: ?><p class="empty">No players match the selected filters.</p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'achievements'): ?>
                <h2>Achievements</h2>
                <p>The catalog contains <?php echo h(count($achievement_catalog)); ?> achievements. Unlock counts are calculated from the current public player export.</p>
                <?php if (count($achievement_catalog) > 0): ?>
                    <div class="achievement-grid">
                    <?php foreach ($achievement_catalog as $achievement): ?>
                        <?php
                        if (!is_array($achievement)) { continue; }
                        $achievement_key = (string) ($achievement['key'] ?? '');
                        $earners = $achievement_unlocks[$achievement_key] ?? [];
                        ?>
                        <article class="achievement">
                            <h3>🏅 <?php echo h($achievement['title'] ?? $achievement_key); ?></h3>
                            <p><?php echo h($achievement['description'] ?? ''); ?></p>
                            <p class="progress"><code><?php echo h($achievement_key); ?></code> · unlocked by <?php echo h(count($earners)); ?>/<?php echo h(count($players)); ?> players (<?php echo h(idlerpg_percent(count($earners), count($players))); ?>)</p>
                            <?php if (count($earners) > 0): ?>
                                <p><?php foreach ($earners as $index => $earner): ?><?php if ($index > 0): ?>, <?php endif; ?><a href="<?php echo h(idlerpg_player_url($earner)); ?>"><?php echo h($earner); ?></a><?php endforeach; ?></p>
                            <?php endif; ?>
                        </article>
                    <?php endforeach; ?>
                    </div>
                <?php else: ?><p class="empty">No achievement catalog is available. Ensure <code>room.json</code> or <code>achievements.json</code> is readable.</p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'events'): ?>
                <h2>Events</h2>
                <form class="form-row" method="get" action="">
                    <input type="hidden" name="view" value="events">
                    <input type="hidden" name="room" value="<?php echo h($selected_room_slug); ?>">
                    <label>Search<input type="search" name="q" value="<?php echo h($event_query); ?>" placeholder="Event text or player"></label>
                    <label>Kind<select name="kind"><option value="all">all</option><?php foreach ($event_kinds as $kind): ?><option value="<?php echo h($kind); ?>" <?php echo $event_kind === $kind ? 'selected' : ''; ?>><?php echo h($kind); ?></option><?php endforeach; ?></select></label>
                    <label>Player<input type="search" name="player" value="<?php echo h($event_player); ?>" placeholder="Character"></label>
                    <button type="submit">Filter</button>
                    <?php if ($event_query !== '' || $event_kind !== 'all' || $event_player !== ''): ?><a href="<?php echo h(idlerpg_view_url('events')); ?>">Reset</a><?php endif; ?>
                </form>
                <p class="muted"><?php echo h($event_pagination['total']); ?> matching events.</p>
                <?php idlerpg_render_events($event_pagination['items'], count($event_pagination['items'])); ?>
                <?php idlerpg_render_pagination('events', $event_pagination, ['q' => $event_query, 'kind' => $event_kind, 'player' => $event_player]); ?>
            <?php endif; ?>

            <?php if ($view === 'quest'): ?>
                <h2>Current Quest</h2>
                <?php if ($quest): ?>
                    <?php
                    $quest_type = $active_quest_type;
                    $quest_remaining = max(0, ((int) ($quest['complete_at'] ?? 0)) - time());
                    ?>
                    <p><strong>Quest:</strong> <?php echo h($quest['text'] ?? $quest['description'] ?? 'adventure'); ?></p>
                    <p>
                        <strong>Type:</strong> <?php echo h($quest_type); ?>-based
                        <?php if (!empty($quest['complete_at'])): ?>
                            · <strong><?php echo $quest_type === 'grid' ? 'Deadline' : 'Time left'; ?>:</strong> <?php echo h(idlerpg_ttl($quest_remaining)); ?>
                        <?php endif; ?>
                    </p>
                    <?php if ($quest_type === 'time'): ?>
                        <p class="muted">
                            Time-based quest: every quester must remain online and avoid message or logout penalties until the timer ends.
                            Random game events do not fail the quest.
                            <?php if ($has_quest_target): ?>
                                The map objective is [<?php echo h((int) idlerpg_point_coord($quest_target, 'x')); ?>,<?php echo h((int) idlerpg_point_coord($quest_target, 'y')); ?>]; it is informational and does not replace the timer.
                            <?php endif; ?>
                        </p>
                    <?php elseif (is_array($quest['current_target'] ?? null)): ?>
                        <p class="muted">Current grid target: [<?php echo h((int) idlerpg_point_coord($quest['current_target'], 'x')); ?>,<?php echo h((int) idlerpg_point_coord($quest['current_target'], 'y')); ?>]. The quest completes as soon as all participants reach every route point; the displayed time is the deadline.</p>
                    <?php endif; ?>
                    <?php if (!empty($quest['questers']) && is_array($quest['questers'])): ?>
                        <table><thead><tr><th>#</th><th>Participant</th></tr></thead><tbody>
                        <?php foreach ($quest['questers'] as $index => $participant): $participant_name = is_array($participant) ? idlerpg_player_name($participant) : (string) $participant; ?>
                            <tr><td><?php echo h($index + 1); ?></td><td><a href="<?php echo h(idlerpg_player_url($participant_name)); ?>"><?php echo h($participant_name); ?></a></td></tr>
                        <?php endforeach; ?>
                        </tbody></table>
                    <?php endif; ?>
                <?php else: ?><p class="muted">No active quest right now.</p><?php endif; ?>
                <?php $render_map = true; ?>
            <?php endif; ?>

            <?php if ($render_map || $view === 'map'): ?>
                <h2><?php echo $view === 'map' ? 'World Map' : 'Quest Map'; ?></h2>
                <p class="muted">
                    Blue circles = online, red circles = offline, orange circles = active quest participants.
                    <?php if ($has_quest_route): ?>
                        The current grid-quest route is shown as orange squares connected by an orange line.
                    <?php elseif ($quest && $active_quest_type === 'time' && $has_quest_target): ?>
                        The time-quest objective is shown as one orange square marked T.
                    <?php elseif ($quest && $active_quest_type === 'time'): ?>
                        The current time quest has no exported map objective.
                    <?php elseif ($quest && $active_quest_type === 'grid'): ?>
                        The current quest is grid-based, but no route coordinates are available in the export yet.
                    <?php else: ?>
                        Grid-quest routes appear as orange squares connected by an orange line when one is active.
                    <?php endif; ?>
                    Labels are staggered when players stand close together; hover a marker for exact details.
                </p>
                <?php if (count($map_players) > 0): ?>
                    <?php
                    $visible_map_players = array_slice($map_players, 0, 120);
                    $visible_map_player_count = count($visible_map_players);
                    if ($visible_map_player_count <= 20) {
                        $map_density_class = 'map-density-normal';
                        $map_marker_radius = 4;
                        $show_all_map_labels = true;
                    } elseif ($visible_map_player_count <= 50) {
                        $map_density_class = 'map-density-compact';
                        $map_marker_radius = 3.5;
                        $show_all_map_labels = false;
                    } else {
                        $map_density_class = 'map-density-dense';
                        $map_marker_radius = 2.75;
                        $show_all_map_labels = false;
                    }
                    ?>
                    <?php if (!$show_all_map_labels): ?>
                        <p class="muted map-density-note">
                            Player names appear on hover or keyboard focus; active quest participants remain labeled.
                        </p>
                    <?php endif; ?>
                    <div class="map-wrap">
                        <svg class="world-map <?php echo h($map_density_class); ?>" viewBox="0 0 <?php echo h($map_width); ?> <?php echo h($map_height); ?>" role="img" aria-label="IdleRPG world map with <?php echo h($visible_map_player_count); ?> players" data-player-count="<?php echo h($visible_map_player_count); ?>">
                            <defs>
                                <pattern id="idlerpgNoise" width="32" height="32" patternUnits="userSpaceOnUse">
                                    <path d="M0 8 L8 0 M20 32 L32 20 M4 28 L28 4 M16 18 L18 16" stroke="#8a5a20" stroke-width="1" opacity=".28"/>
                                </pattern>
                                <filter id="idlerpgRough">
                                    <feTurbulence type="fractalNoise" baseFrequency="0.018" numOctaves="3" seed="7"/>
                                    <feDisplacementMap in="SourceGraphic" scale="2"/>
                                </filter>
                            </defs>

                            <rect x="0" y="0" width="<?php echo h($map_width); ?>" height="<?php echo h($map_height); ?>" fill="#f4edbd"/>
                            <rect x="0" y="0" width="<?php echo h($map_width); ?>" height="<?php echo h($map_height); ?>" fill="url(#idlerpgNoise)" opacity=".45"/>

                            <path d="M0,0 L145,0 C85,35 50,70 0,95 Z" fill="#8a4f12" opacity=".9" filter="url(#idlerpgRough)"/>
                            <path d="M0,345 C85,315 135,345 176,393 C110,415 62,462 0,500 Z" fill="#8a4f12" opacity=".85" filter="url(#idlerpgRough)"/>
                            <path d="M355,500 C415,430 455,395 500,370 L500,500 Z" fill="#8a4f12" opacity=".9" filter="url(#idlerpgRough)"/>
                            <path d="M270,45 C315,20 365,28 388,74 C362,116 315,136 270,115 C245,85 246,58 270,45 Z" fill="#a57937" opacity=".42" filter="url(#idlerpgRough)"/>
                            <path d="M292,230 C330,208 371,218 395,254 C365,285 316,293 282,265 C272,250 276,238 292,230 Z" fill="#7d4d1b" opacity=".55" filter="url(#idlerpgRough)"/>
                            <path d="M230,380 C270,332 318,350 348,403 C318,437 258,445 220,413 Z" fill="#7d4d1b" opacity=".62" filter="url(#idlerpgRough)"/>

                            <text class="map-label" x="27" y="36" transform="rotate(-7 27 36)">Debmark</text>
                            <text class="map-label" x="286" y="42" transform="rotate(-8 286 42)">Mountains of</text>
                            <text class="map-label" x="300" y="64" transform="rotate(-8 300 64)">Qwok</text>
                            <text class="map-label" x="382" y="93" transform="rotate(8 382 93)">The land of</text>
                            <text class="map-label" x="399" y="118" transform="rotate(8 399 118)">Qwok</text>
                            <text class="map-label" x="90" y="160" transform="rotate(-5 90 160)">Jow Boti</text>
                            <text class="map-label" x="82" y="182" transform="rotate(-5 82 182)">Territory</text>
                            <text class="map-label" x="365" y="218" transform="rotate(-3 365 218)">Velbragh</text>
                            <text class="map-small-label" x="40" y="255" transform="rotate(-5 40 255)">Secret Passage</text>
                            <text class="map-small-label" x="50" y="275" transform="rotate(-5 50 275)">to Aharah</text>
                            <text class="map-label" x="4" y="374" transform="rotate(-5 4 374)">The great</text>
                            <text class="map-label" x="3" y="397" transform="rotate(-5 3 397)">Shell</text>
                            <text class="map-label" x="3" y="420" transform="rotate(-5 3 420)">mountains</text>
                            <text class="map-label" x="270" y="390" transform="rotate(-5 270 390)">Tower of</text>
                            <text class="map-label" x="270" y="415" transform="rotate(-5 270 415)">Anh-Allor</text>
                            <text class="map-label" x="410" y="468" transform="rotate(-5 410 468)">Irnalveh</text>

                            <?php if ($has_quest_target && $active_quest_type === 'time'): ?>
                                <?php $tx = idlerpg_point_coord($quest_target, 'x'); $ty = idlerpg_point_coord($quest_target, 'y'); ?>
                                <g>
                                    <title>Time-quest objective [<?php echo h((int) $tx); ?>,<?php echo h((int) $ty); ?>]</title>
                                    <rect class="quest-point" x="<?php echo h($tx - 5); ?>" y="<?php echo h($ty - 5); ?>" width="10" height="10"/>
                                    <text x="<?php echo h($tx + 7); ?>" y="<?php echo h($ty - 7); ?>" class="map-small-label">T</text>
                                </g>
                            <?php endif; ?>

                            <?php if ($has_quest_route): ?>
                                <?php
                                $route_points = [];
                                foreach ($quest_route as $point) {
                                    $route_points[] = (int) idlerpg_point_coord($point, 'x') . ',' . (int) idlerpg_point_coord($point, 'y');
                                }
                                ?>
                                <polyline class="quest-line" points="<?php echo h(implode(' ', $route_points)); ?>"/>
                                <?php foreach ($quest_route as $idx => $point): ?>
                                    <?php $qx = idlerpg_point_coord($point, 'x'); $qy = idlerpg_point_coord($point, 'y'); ?>
                                    <g>
                                        <title>Quest point Q<?php echo h($idx + 1); ?> [<?php echo h((int) $qx); ?>,<?php echo h((int) $qy); ?>]</title>
                                        <rect class="quest-point" x="<?php echo h($qx - 5); ?>" y="<?php echo h($qy - 5); ?>" width="10" height="10"/>
                                        <text x="<?php echo h($qx + 7); ?>" y="<?php echo h($qy - 7); ?>" class="map-small-label">Q<?php echo h($idx + 1); ?></text>
                                    </g>
                                <?php endforeach; ?>
                            <?php endif; ?>

                            <?php
                            $occupied_map_labels = [];
                            foreach ($visible_map_players as $player) {
                                $marker_x = max(6, min($map_width - 6, max(0, min($map_width, idlerpg_player_coord($player, 'x')))));
                                $marker_y = max(6, min($map_height - 6, max(0, min($map_height, idlerpg_player_coord($player, 'y')))));
                                $occupied_map_labels[] = [
                                    'left' => $marker_x - 5,
                                    'top' => $marker_y - 5,
                                    'right' => $marker_x + 5,
                                    'bottom' => $marker_y + 5,
                                ];
                            }
                            ?>
                            <?php foreach ($visible_map_players as $player): ?>
                                <?php
                                $name = idlerpg_player_name($player);
                                $raw_x = max(0, min($map_width, idlerpg_player_coord($player, 'x')));
                                $raw_y = max(0, min($map_height, idlerpg_player_coord($player, 'y')));
                                $x = max(6, min($map_width - 6, $raw_x));
                                $y = max(6, min($map_height - 6, $raw_y));
                                $on_quest = idlerpg_player_on_quest($player, $quest_player_lookup);
                                $label = idlerpg_map_marker_label_layout(
                                    $x,
                                    $y,
                                    $name,
                                    $map_width,
                                    $map_height,
                                    $occupied_map_labels
                                );
                                if ($show_all_map_labels || $on_quest) {
                                    $occupied_map_labels[] = $label['rect'];
                                }
                                $class = $on_quest
                                    ? 'marker quester'
                                    : (idlerpg_player_online($player) ? 'marker online' : 'marker offline');
                                $marker_state = idlerpg_player_online($player) ? 'online' : 'offline';
                                if ($on_quest) {
                                    $marker_state .= ' · quest participant';
                                }
                                ?>
                                <a href="<?php echo h(idlerpg_player_url($name)); ?>" aria-label="<?php echo h($name); ?>, level <?php echo h(idlerpg_player_level($player)); ?>, <?php echo h($marker_state); ?>">
                                    <g class="<?php echo h($class); ?>">
                                        <title><?php echo h($name); ?> [<?php echo h((int) $raw_x); ?>,<?php echo h((int) $raw_y); ?>] · lv.<?php echo h(idlerpg_player_level($player)); ?> · <?php echo h($marker_state); ?></title>
                                        <circle cx="<?php echo h($x); ?>" cy="<?php echo h($y); ?>" r="<?php echo h($map_marker_radius); ?>"/>
                                        <text x="<?php echo h($label['x']); ?>" y="<?php echo h($label['y']); ?>" text-anchor="<?php echo h($label['anchor']); ?>"><?php echo h($name); ?></text>
                                    </g>
                                </a>
                            <?php endforeach; ?>
                        </svg>
                    </div>
                    <h3>Map positions</h3>
                    <table><thead><tr><th>Character</th><th>Position</th><th>Level</th><th>Status</th></tr></thead><tbody>
                    <?php foreach ($map_players as $player): $name = idlerpg_player_name($player); ?>
                        <tr><td><a href="<?php echo h(idlerpg_player_url($name)); ?>"><?php echo h($name); ?></a></td><td>[<?php echo h((int) idlerpg_player_coord($player, 'x')); ?>,<?php echo h((int) idlerpg_player_coord($player, 'y')); ?>]</td><td>lv.<?php echo h(idlerpg_player_level($player)); ?></td><td><?php echo idlerpg_player_status_badge($player); ?></td></tr>
                    <?php endforeach; ?>
                    </tbody></table>
                <?php else: ?><p class="muted">No readable map data found. The website needs <code>map.json</code> or <code>players.json</code> in a readable export directory.</p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'hof'): ?>
                <h2>Seasons & Hall of Fame</h2>
                <section class="panel">
                    <h3>Current season</h3>
                    <?php if (count($season) > 0): ?>
                        <table><tbody>
                            <tr><th>Season ID</th><td><?php echo h($season['id'] ?? 'unknown'); ?></td></tr>
                            <tr><th>Started</th><td><?php echo $current_season_started_at > 0 ? h(idlerpg_time_value($current_season_started_at)) : 'unknown'; ?></td></tr>
                            <tr><th>Scheduled end</th><td><?php echo $current_season_ends_at > 0 ? h(idlerpg_time_value($current_season_ends_at)) : 'manual'; ?></td></tr>
                            <tr><th>Remaining</th><td><?php echo $current_season_ends_at > 0 ? h(idlerpg_ttl($current_season_remaining)) : 'manual season'; ?></td></tr>
                            <tr><th>Current leader</th><td><?php echo count($leaderboard) > 0 ? h(idlerpg_player_name($leaderboard[0])) . ' (lv.' . h(idlerpg_player_level($leaderboard[0])) . ')' : 'n/a'; ?></td></tr>
                        </tbody></table>
                    <?php else: ?><p class="muted">No season metadata is available in <code>room.json</code>.</p><?php endif; ?>
                </section>

                <h3>Completed seasons</h3>
                <?php if (count($seasons) > 0): ?>
                    <?php foreach (array_reverse($seasons) as $historic_season): ?>
                        <?php $historic_top = is_array($historic_season['top'] ?? null) ? $historic_season['top'] : []; ?>
                        <details class="season">
                            <summary><?php echo h($historic_season['id'] ?? '?'); ?> · champion <?php echo h($historic_season['champion'] ?? 'no champion'); ?><?php if (!empty($historic_season['ended_at'])): ?> · <?php echo h(idlerpg_time_value($historic_season['ended_at'])); ?><?php endif; ?></summary>
                            <table><tbody>
                                <tr><th>Started</th><td><?php echo !empty($historic_season['started_at']) ? h(idlerpg_time_value($historic_season['started_at'])) : 'unknown'; ?></td></tr>
                                <tr><th>Ended</th><td><?php echo !empty($historic_season['ended_at']) ? h(idlerpg_time_value($historic_season['ended_at'])) : 'unknown'; ?></td></tr>
                                <tr><th>Champion</th><td><?php echo h($historic_season['champion'] ?? ''); ?></td></tr>
                            </tbody></table>
                            <?php if (count($historic_top) > 0): ?>
                                <h4>Final ranking</h4>
                                <table><thead><tr><th>#</th><th>Character</th><th>Class</th><th>Level</th><th>Next level</th><th>Item sum</th></tr></thead><tbody>
                                <?php foreach ($historic_top as $index => $historic_player): ?>
                                    <tr><td><?php echo h($historic_player['rank'] ?? $index + 1); ?></td><td><?php echo h(idlerpg_player_name($historic_player)); ?></td><td><?php echo h(idlerpg_player_class($historic_player)); ?></td><td>lv.<?php echo h(idlerpg_player_level($historic_player)); ?></td><td><?php echo h(idlerpg_ttl($historic_player['ttl'] ?? 0)); ?></td><td><?php echo h($historic_player['item_sum'] ?? 0); ?></td></tr>
                                <?php endforeach; ?>
                                </tbody></table>
                            <?php else: ?><p class="muted">This historic export contains only the champion summary.</p><?php endif; ?>
                        </details>
                    <?php endforeach; ?>
                <?php else: ?><p class="empty">No completed seasons yet.</p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'rules'): ?>
                <h2>Game rules & exported configuration</h2>
                <p>These values are the public rules exported by the running bot. They reflect the actual configuration of this IdleRPG instance rather than generic defaults.</p>
                <?php
                $rule_groups = [
                    'Leveling & penalties' => ['tick_seconds', 'rp_base', 'rp_step', 'penalty_step', 'message_penalty', 'logout_penalty', 'logout_grace_seconds', 'max_penalty'],
                    'World map' => ['map_x', 'map_y', 'map_step_per_second', 'map_step_per_tick', 'grid_battle_enabled', 'manual_duel_max_distance', 'manual_duel_cooldown_seconds'],
                    'Quests' => ['quest_time_enabled', 'quest_grid_enabled', 'quest_time_weight', 'quest_grid_weight', 'quest_time_min_duration', 'quest_time_max_duration', 'quest_grid_step_seconds', 'quest_grid_min_points', 'quest_grid_max_points', 'quest_max_per_day', 'quest_min_level', 'quest_min_online_seconds', 'quest_interval', 'quest_min_duration', 'quest_max_duration'],
                    'Events & battles' => ['event_chance', 'item_chance', 'battle_event_weight', 'team_battle_event_weight', 'boss_event_weight', 'item_event_weight', 'item_damage_event_weight', 'item_steal_event_weight', 'alignment_event_weight', 'critical_strike_chance', 'critical_strike_chance_good', 'critical_strike_chance_evil', 'item_drop_chance', 'level_battle_chance_below_25', 'level_battle_chance_at_25'],
                    'Bosses' => ['boss_min_players', 'boss_max_players', 'boss_min_level', 'boss_reward_percent', 'boss_loss_percent', 'boss_power_min_factor', 'boss_power_max_factor'],
                    'Items & achievements' => ['unique_items_enabled', 'unique_item_min_level', 'unique_item_chance', 'level_reward_min_level', 'season_achievement_gates_enabled'],
                    'Seasons & history' => ['season_enabled', 'season_duration_days', 'season_reset_on_rollover', 'season_hof_size', 'event_log_limit', 'event_retention_days', 'export_event_limit', 'export_interval_seconds', 'export_top_limit'],
                    'Announcements' => ['announce_login', 'announce_top_interval', 'announce_top_limit', 'update_room_topic', 'topic_update_interval', 'topic_custom_text'],
                ];
                $shown_rule_keys = [];
                ?>
                <?php if (count($rules) > 0): ?>
                    <div class="rule-groups">
                    <?php foreach ($rule_groups as $group_name => $keys): ?>
                        <?php $available_keys = array_values(array_filter($keys, fn($key) => array_key_exists($key, $rules))); ?>
                        <?php if (count($available_keys) === 0) { continue; } ?>
                        <section class="rule-group"><h3><?php echo h($group_name); ?></h3><table><tbody>
                        <?php foreach ($available_keys as $key): $shown_rule_keys[$key] = true; ?>
                            <tr><th><?php echo h(idlerpg_human_key($key)); ?></th><td><?php echo h(idlerpg_rule_value($key, $rules[$key])); ?><br><small class="muted"><code><?php echo h($key); ?></code></small></td></tr>
                        <?php endforeach; ?>
                        </tbody></table></section>
                    <?php endforeach; ?>
                    <?php $other_rules = array_diff_key($rules, $shown_rule_keys); ?>
                    <?php if (count($other_rules) > 0): ?>
                        <section class="rule-group"><h3>Other exported values</h3><table><tbody>
                        <?php foreach ($other_rules as $key => $value): ?>
                            <tr><th><?php echo h(idlerpg_human_key($key)); ?></th><td><?php echo h(idlerpg_rule_value($key, $value)); ?><br><small class="muted"><code><?php echo h($key); ?></code></small></td></tr>
                        <?php endforeach; ?>
                        </tbody></table></section>
                    <?php endif; ?>
                    </div>
                <?php else: ?><p class="empty">No public rule data is available. The complete rules view requires the room-specific <code>room.json</code> export.</p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'commands'): ?>
                <h2>IdleRPG commands</h2>
                <p>Commands are used in an XMPP room where IdleRPG is enabled. The default command prefix is shown as <code>,</code>; installations may configure a different prefix.</p>
                <div class="details-grid">
                    <section class="panel"><h3>Character</h3><ul class="compact-list">
                        <li><code>,idlerpg register &lt;character&gt; &lt;class&gt;</code> — create a character</li>
                        <li><code>,idlerpg login</code> / <code>,idlerpg logout</code> — enter or leave the game</li>
                        <li><code>,idlerpg status [character]</code> — show progress and online state</li>
                        <li><code>,idlerpg profile [character]</code> — show the complete profile and website link</li>
                        <li><code>,idlerpg items [character]</code> — show equipment and item levels</li>
                        <li><code>,idlerpg align &lt;good|neutral|evil&gt;</code> — select alignment</li>
                        <li><code>,idlerpg remove-me</code> — permanently remove your character</li>
                    </ul></section>
                    <section class="panel"><h3>Progress & community</h3><ul class="compact-list">
                        <li><code>,idlerpg top [page|last|all]</code> — leaderboard</li>
                        <li><code>,idlerpg players [page|last|all]</code> — registered characters</li>
                        <li><code>,idlerpg achievements [character|list]</code> — earned or available achievements</li>
                        <li><code>,idlerpg title &lt;achievement|none&gt;</code> — select an earned public title</li>
                        <li><code>,idlerpg duel &lt;character&gt;</code> — challenge a nearby online player</li>
                        <li><code>,idlerpg events [page|last|all]</code> — recent game history</li>
                    </ul></section>
                    <section class="panel"><h3>World & seasons</h3><ul class="compact-list">
                        <li><code>,idlerpg quest</code> — current quest and participants</li>
                        <li><code>,idlerpg map</code> — player positions and website map</li>
                        <li><code>,idlerpg hof</code> — Hall of Fame</li>
                        <li><code>,idlerpg season</code> — current season status</li>
                        <li><code>,idlerpg stats</code> — room-wide balance statistics</li>
                    </ul></section>
                    <section class="panel"><h3>Room administration</h3><ul class="compact-list">
                        <li><code>,idlerpg on</code> / <code>,idlerpg off</code> / <code>,idlerpg enabled</code> — room feature state</li>
                        <li><code>,idlerpg stats</code> — room-wide balance and runtime statistics</li>
                        <li><code>,idlerpg push &lt;character&gt; &lt;duration&gt;</code> — remove time from a character's clock</li>
                        <li><code>,idlerpg setlevel &lt;character&gt; &lt;level&gt;</code> — set a character level</li>
                        <li><code>,idlerpg reset &lt;character&gt;</code> — reset one character's progress and equipment</li>
                        <li><code>,idlerpg delete &lt;character&gt;</code> — delete another room character</li>
                        <li><code>,idlerpg delold &lt;days&gt; [confirm]</code> — preview or delete offline characters inactive for the given number of days</li>
                        <li><code>,idlerpg announce top</code> — post the leaderboard</li>
                        <li><code>,idlerpg topic update [custom text]</code> — refresh the room topic</li>
                        <li><code>,idlerpg export</code> — refresh the public website export</li>
                        <li><code>,idlerpg season end</code> — archive the ranking and start a new season without a player reset</li>
                        <li><code>,idlerpg season reset</code> — archive the ranking and start a new season with a full player reset</li>
                        <li><code>,idlerpg season discard confirm</code> — discard a faulty active season without adding a Hall of Fame entry</li>
                        <li><code>,idlerpg season extend [duration|manual]</code> — extend the active season or make it endless</li>
                        <li><code>,idlerpg season clear-end</code> — remove an automatic end date</li>
                        <li><code>,idlerpg hof clear confirm</code> — clear Hall of Fame history</li>
                    </ul></section>
                </div>
                <p class="muted">Aliases include <code>,idle</code> and <code>,irpg</code>. For role requirements and the exact active command metadata, use <code>,help idlerpg</code> in the bot.</p>
            <?php endif; ?>
        </main>

        <aside>
            <div class="card"><h2>Quick start</h2><ul class="compact-list"><li><code>,idlerpg register &lt;name&gt; &lt;class&gt;</code></li><li><code>,idlerpg login</code></li><li><code>,idlerpg status</code></li><li><code>,idlerpg top</code></li></ul></div>
            <div class="card"><h2>Current game</h2><p class="muted"><?php echo h(count($players)); ?> players, <?php echo h($online_count); ?> online. <?php echo $quest ? 'A ' . h($active_quest_type) . ' quest is active.' : 'No quest is active.'; ?></p><?php if ($current_season_ends_at > 0): ?><p class="muted">Season ends in <?php echo h(idlerpg_ttl($current_season_remaining)); ?>.</p><?php endif; ?></div>
            <div class="card"><h2>Map legend</h2><p class="muted">
                Blue circles = online, red circles = offline, orange circles = active quest participants.
                <?php if ($has_quest_route): ?>Orange squares and lines show the current grid-quest route.
                <?php elseif ($quest && $active_quest_type === 'time' && $has_quest_target): ?>One orange square marked T shows the time-quest objective.
                <?php elseif ($quest && $active_quest_type === 'time'): ?>The current time quest has no exported map objective.
                <?php else: ?>Route markers appear when a grid quest is active.<?php endif; ?>
            </p></div>
            <div class="card"><h2>Privacy</h2><p class="muted">This website reads only the public IdleRPG export. Raw player JIDs and bot administration data are not required.</p></div>
        </aside>
    </div>
    <footer class="footer">Public IdleRPG state generated by EnvsBot · <a href="<?php echo h(idlerpg_view_url('commands')); ?>">command reference</a></footer>
</div>
</body>
</html>
