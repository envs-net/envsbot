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
    return sprintf('%d days, %02d:%02d:%02d', $days, $hours, $minutes, $seconds);
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


function idlerpg_map_label_position($x, $y, $name, $map_width, $map_height, &$occupied) {
    $bucket_x = (int) floor(((float) $x) / 42);
    $bucket_y = (int) floor(((float) $y) / 24);
    $bucket = $bucket_x . ':' . $bucket_y;
    $slot = (int) ($occupied[$bucket] ?? 0);
    $occupied[$bucket] = $slot + 1;

    $offsets = [
        [8, -8, 'start'],
        [8, 16, 'start'],
        [-8, -8, 'end'],
        [-8, 16, 'end'],
        [0, -20, 'middle'],
        [0, 28, 'middle'],
    ];
    $choice = $offsets[$slot % count($offsets)];
    $extra = intdiv($slot, count($offsets)) * 14;
    $dy = $choice[1] < 0 ? $choice[1] - $extra : $choice[1] + $extra;

    $label_x = max(8, min((float) $map_width - 8, (float) $x + $choice[0]));
    $label_y = max(14, min((float) $map_height - 8, (float) $y + $dy));

    return [
        'x' => $label_x,
        'y' => $label_y,
        'anchor' => $choice[2],
        'crowded' => $slot > 0,
        'title' => $name . ' [' . (int) $x . ',' . (int) $y . ']',
    ];
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

function idlerpg_find_room_slug($base_dir) {
    if (!is_dir($base_dir)) {
        return '';
    }
    $entries = scandir($base_dir);
    if (!is_array($entries)) {
        return '';
    }
    foreach ($entries as $entry) {
        if ($entry === '.' || $entry === '..') {
            continue;
        }
        $path = rtrim($base_dir, '/') . '/' . $entry;
        if (is_dir($path) && idlerpg_export_files_exist($path)) {
            return $entry;
        }
    }
    return '';
}

function idlerpg_room_slug() {
    $env_slug = getenv('IDLERPG_ROOM_SLUG');
    if ($env_slug !== false && trim($env_slug) !== '') {
        return trim($env_slug);
    }

    $env_dir = getenv('IDLERPG_DATA_DIR');
    if ($env_dir !== false && trim($env_dir) !== '') {
        $slug = idlerpg_find_room_slug(rtrim(trim($env_dir), '/'));
        if ($slug !== '') {
            return $slug;
        }
    }

    $local_slug = idlerpg_find_room_slug(__DIR__ . '/data');
    return $local_slug !== '' ? $local_slug : IDLERPG_DEFAULT_ROOM_SLUG;
}

function idlerpg_candidate_dirs() {
    $slug = idlerpg_room_slug();
    $candidates = [];

    $env_dir = getenv('IDLERPG_DATA_DIR');
    if ($env_dir !== false && trim($env_dir) !== '') {
        $env_dir = rtrim(trim($env_dir), '/');
        $candidates[] = $env_dir;
        $candidates[] = $env_dir . '/' . $slug;
    }

    $candidates[] = __DIR__ . '/data/' . $slug;
    $candidates[] = __DIR__ . '/data';
    $candidates[] = __DIR__;

    return array_values(array_unique($candidates));
}

function idlerpg_data_dir() {
    foreach (idlerpg_candidate_dirs() as $candidate) {
        if (idlerpg_export_files_exist($candidate)) {
            return $candidate;
        }
    }
    return __DIR__ . '/data/' . idlerpg_room_slug();
}

function idlerpg_data_file($filename) {
    return rtrim(idlerpg_data_dir(), '/') . '/' . ltrim($filename, '/');
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
    $allowed = ['home', 'players', 'map', 'quest', 'events', 'hof', 'commands'];
    $view = strtolower(trim((string) ($_GET['view'] ?? 'home')));
    return in_array($view, $allowed, true) ? $view : 'home';
}

function idlerpg_view_url($view, $extra = []) {
    $params = array_merge(['view' => $view], $extra);
    return '?' . http_build_query($params);
}

function idlerpg_player_url($name) {
    return idlerpg_view_url('players', ['character' => $name]);
}

function idlerpg_achievement_count($player) {
    return is_array($player['achievements'] ?? null) ? count($player['achievements']) : 0;
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

$data_dir = idlerpg_data_dir();
$leaderboard_payload = idlerpg_load_json(idlerpg_data_file('leaderboard.json'), ['players' => []]);
$players_payload = idlerpg_load_json(idlerpg_data_file('players.json'), ['players' => []]);
$map_payload = idlerpg_load_json(idlerpg_data_file('map.json'), ['players' => [], 'width' => 500, 'height' => 500]);
$events_payload = idlerpg_load_json(idlerpg_data_file('events.json'), ['events' => []]);
$hof_payload = idlerpg_load_json(idlerpg_data_file('hall_of_fame.json'), ['seasons' => []]);

$leaderboard = is_array($leaderboard_payload['players'] ?? null) ? $leaderboard_payload['players'] : [];
$players = is_array($players_payload['players'] ?? null) ? $players_payload['players'] : $leaderboard;
$players = idlerpg_sort_players($players);
if (count($leaderboard) === 0 && count($players) > 0) {
    $leaderboard = $players;
}
$map_players = is_array($map_payload['players'] ?? null) ? $map_payload['players'] : $players;
if (count($map_players) === 0 && count($players) > 0) {
    $map_players = $players;
}
$events = is_array($events_payload['events'] ?? null) ? $events_payload['events'] : [];
usort($events, function ($a, $b) {
    return ((int) ($b['ts'] ?? 0)) <=> ((int) ($a['ts'] ?? 0));
});
$seasons = is_array($hof_payload['seasons'] ?? null) ? $hof_payload['seasons'] : [];
$room = $leaderboard_payload['room'] ?? $players_payload['room'] ?? $map_payload['room'] ?? '';
$updated = $leaderboard_payload['generated_at'] ?? $players_payload['generated_at'] ?? $map_payload['generated_at'] ?? null;
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
$quest = is_array($map_payload['quest'] ?? null) ? $map_payload['quest'] : null;
$map_width = max(1, (int) ($map_payload['width'] ?? $map_payload['map_x'] ?? 500));
$map_height = max(1, (int) ($map_payload['height'] ?? $map_payload['map_y'] ?? 500));
$online_count = 0;
foreach ($players as $player) {
    if (idlerpg_player_online($player)) {
        $online_count++;
    }
}
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IdleRPG</title>
<style>
:root {
    color-scheme: dark;
    --bg: #10151a;
    --fg: #f4f4f0;
    --muted: #9ca3af;
    --line: #38414a;
    --link: #00c2b8;
    --active: #2563eb;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font: 15px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
a { color: var(--link); }
.container { max-width: 1200px; margin: 0 auto; padding: 1.25rem; }
.header { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
.muted { color: var(--muted); }
.nav { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1rem 0 1.5rem; }
.nav a { border: 1px solid var(--line); padding: .35rem .7rem; text-decoration: none; }
.nav a:hover, .nav a:focus { background: rgba(0, 194, 184, .18); outline: none; }
.nav a.active { background: var(--active); border-color: var(--active); color: white; }
.grid { display: grid; grid-template-columns: minmax(0, 1fr) 18rem; gap: 2rem; align-items: start; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
.card { border-left: 4px solid var(--line); padding: .5rem 0 .5rem 1rem; margin-bottom: 1rem; }
table { width: 100%; border-collapse: collapse; margin: 1rem 0 2rem; }
th, td { border-bottom: 1px solid var(--line); padding: .35rem .5rem .35rem 0; text-align: left; vertical-align: top; }
code { background: rgba(255,255,255,.08); padding: .05rem .3rem; }
.stats { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); }
.stats strong { display: block; font-size: 1.4rem; }
.events li { margin-bottom: .45rem; }
.event-time, .event-kind { color: var(--muted); }
.world-map { display: block; width: min(100%, 720px); height: auto; border: 1px solid var(--line); background: #f3edbd; }
.map-label { font-style: italic; font-size: 16px; fill: #4b2d10; opacity: .88; }
.map-small-label { font-size: 11px; fill: #4b2d10; opacity: .8; }
.marker { cursor: pointer; }
.marker text { font-size: 12px; fill: #111; paint-order: stroke; stroke: #f3edbd; stroke-width: 4px; stroke-linejoin: round; pointer-events: none; }
.marker.crowded text { font-size: 10px; }
.marker:hover text, .marker:focus text { font-weight: 700; }
.marker.online circle { fill: #2f80ff; }
.marker.offline circle { fill: #b33; }
.marker circle { stroke: #111; stroke-width: 1.5; }
.quest-point { fill: #d99b00; stroke: #111; stroke-width: 1.5; }
.quest-line { fill: none; stroke: #d99b00; stroke-width: 2; stroke-dasharray: 6 5; }
</style>
</head>
<body>
<div class="container">
    <header class="header">
        <h1>IdleRPG</h1>
        <p class="muted"><?php echo h(count($players)); ?> players · <?php echo h($online_count); ?> online</p>
    </header>

    <nav class="nav" aria-label="IdleRPG navigation">
        <?php foreach (['home' => 'Home', 'players' => 'Player Info', 'quest' => 'Quest Info', 'events' => 'Events', 'map' => 'World Map', 'hof' => 'Hall of Fame', 'commands' => 'Commands'] as $tab => $label): ?>
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
            <?php foreach (idlerpg_candidate_dirs() as $candidate): ?>
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
                <p>The IdleRPG is just what it sounds like: an RPG where players idle. Create a character, log in, stay quiet, and wait for your next level. Items, battles, quests, godsends and calamities happen automatically.</p>
                <div class="stats">
                    <div class="card"><span>Top player</span><strong><?php echo count($leaderboard) > 0 ? h(idlerpg_player_name($leaderboard[0])) : 'n/a'; ?></strong></div>
                    <div class="card"><span>Highest level</span><strong><?php echo count($leaderboard) > 0 ? 'lv.' . h(idlerpg_player_level($leaderboard[0])) : 'n/a'; ?></strong></div>
                    <div class="card"><span>Quest</span><strong><?php echo $quest ? 'active' : 'none'; ?></strong></div>
                </div>
                <h2>Top 5 players</h2>
                <?php if (count($leaderboard) > 0): ?>
                    <table><thead><tr><th>#</th><th>Character</th><th>Class</th><th>Level</th><th>Next level</th></tr></thead><tbody>
                    <?php foreach (array_slice($leaderboard, 0, 5) as $index => $player): $name = idlerpg_player_name($player); ?>
                        <tr><td><?php echo h($index + 1); ?></td><td><a href="<?php echo h(idlerpg_player_url($name)); ?>"><?php echo h($name); ?></a></td><td><?php echo h(idlerpg_player_class($player)); ?></td><td>lv.<?php echo h(idlerpg_player_level($player)); ?></td><td><?php echo h(idlerpg_ttl($player['ttl'] ?? 0)); ?></td></tr>
                    <?php endforeach; ?>
                    </tbody></table>
                <?php else: ?><p class="muted">No players exported yet.</p><?php endif; ?>
                <h2>Recent events</h2>
                <?php idlerpg_render_events($events, 8); ?>
            <?php endif; ?>

            <?php if ($view === 'players'): ?>
                <h2><?php echo $selected_profile ? 'Player profile' : 'Pick a player to view'; ?></h2>
                <?php if ($selected_profile): ?>
                    <section class="card">
                        <h3><?php echo h(idlerpg_player_name($selected_profile)); ?></h3>
                        <table><tbody>
                            <tr><th>Class</th><td><?php echo h(idlerpg_player_class($selected_profile)); ?></td></tr>
                            <tr><th>Title</th><td><?php echo h($selected_profile['title'] ?? ''); ?></td></tr>
                            <tr><th>Level</th><td>lv.<?php echo h(idlerpg_player_level($selected_profile)); ?></td></tr>
                            <tr><th>Next level</th><td><?php echo h(idlerpg_ttl($selected_profile['ttl'] ?? 0)); ?></td></tr>
                            <tr><th>Playing since</th><td><?php echo h(idlerpg_player_created_label($selected_profile) !== '' ? idlerpg_player_created_label($selected_profile) : 'unknown'); ?></td></tr>
                            <tr><th>Playing for</th><td><?php echo h(idlerpg_player_played_label($selected_profile) !== '' ? idlerpg_player_played_label($selected_profile) : 'unknown'); ?></td></tr>
                            <tr><th>Idled online</th><td><?php echo h(idlerpg_ttl($selected_profile['idled'] ?? 0)); ?></td></tr>
                            <tr><th>Alignment</th><td><?php echo h($selected_profile['alignment'] ?? 'neutral'); ?></td></tr>
                            <tr><th>Map</th><td>[<?php echo h((int) idlerpg_player_coord($selected_profile, 'x')); ?>,<?php echo h((int) idlerpg_player_coord($selected_profile, 'y')); ?>]</td></tr>
                            <tr><th>Item sum</th><td><?php echo h($selected_profile['item_sum'] ?? 0); ?></td></tr>
                            <?php $profile_stats = is_array($selected_profile['stats'] ?? null) ? $selected_profile['stats'] : []; ?>
                            <tr><th>Bosses defeated</th><td><?php echo h($profile_stats['bosses_defeated'] ?? 0); ?></td></tr>
                            <tr><th>Random battles won</th><td><?php echo h($profile_stats['battles_won'] ?? 0); ?></td></tr>
                            <tr><th>Quests completed</th><td><?php echo h($profile_stats['quests_completed'] ?? 0); ?></td></tr>
                            <tr><th>Status</th><td><?php echo idlerpg_player_online($selected_profile) ? 'online' : 'offline'; ?></td></tr>
                        </tbody></table>
                    </section>
                    <h3>Recent player events</h3>
                    <?php
                    $player_events = array_values(array_filter($events, function ($event) use ($selected_profile) {
                        return idlerpg_event_matches_player($event, idlerpg_player_name($selected_profile));
                    }));
                    idlerpg_render_events($player_events, 8);
                    ?>
                <?php endif; ?>
                <table><thead><tr><th>#</th><th>Player</th><th>Class</th><th>Level</th><th>Next level</th><th>Achievements</th></tr></thead><tbody>
                <?php foreach ($players as $index => $player): $name = idlerpg_player_name($player); ?>
                    <tr><td><?php echo h($index + 1); ?></td><td><a href="<?php echo h(idlerpg_player_url($name)); ?>"><?php echo h($name); ?></a></td><td><?php echo h(idlerpg_player_class($player)); ?></td><td>lv.<?php echo h(idlerpg_player_level($player)); ?></td><td><?php echo h(idlerpg_ttl($player['ttl'] ?? 0)); ?></td><td><?php echo h(idlerpg_achievement_count($player)); ?></td></tr>
                <?php endforeach; ?>
                </tbody></table>
            <?php endif; ?>

            <?php if ($view === 'events'): ?>
                <h2>Recent Events</h2>
                <?php idlerpg_render_events($events, 50); ?>
            <?php endif; ?>

            <?php if ($view === 'quest'): ?>
                <h2>Current Quest</h2>
                <?php if ($quest): ?>
                    <?php
                    $quest_type = strtolower((string) ($quest['type'] ?? ''));
                    if ($quest_type !== 'time' && $quest_type !== 'grid') {
                        $quest_type = !empty($quest['route']) ? 'grid' : 'time';
                    }
                    $quest_remaining = max(0, ((int) ($quest['complete_at'] ?? 0)) - time());
                    ?>
                    <p><strong>Quest:</strong> <?php echo h($quest['text'] ?? $quest['description'] ?? 'adventure'); ?></p>
                    <p>
                        <strong>Type:</strong> <?php echo h($quest_type); ?>-based
                        <?php if (!empty($quest['complete_at'])): ?>
                            · <strong>Time left:</strong> <?php echo h(idlerpg_ttl($quest_remaining)); ?>
                        <?php endif; ?>
                    </p>
                    <?php if ($quest_type === 'time'): ?>
                        <p class="muted">Time-based quest: no quester may receive a penalty before the timer ends.</p>
                    <?php elseif (is_array($quest['current_target'] ?? null)): ?>
                        <p class="muted">Current grid target: [<?php echo h((int) idlerpg_point_coord($quest['current_target'], 'x')); ?>,<?php echo h((int) idlerpg_point_coord($quest['current_target'], 'y')); ?>]</p>
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
                <p class="muted">Blue = online, red = offline, orange = grid quest point. Labels are staggered when players stand close together; hover a marker for exact details.</p>
                <?php if (count($map_players) > 0): ?>
                    <svg class="world-map" viewBox="0 0 <?php echo h($map_width); ?> <?php echo h($map_height); ?>" role="img" aria-label="IdleRPG world map">
                        <defs><pattern id="noise" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M0 8 L8 0 M20 32 L32 20 M4 28 L28 4 M16 18 L18 16" stroke="#8a5a20" stroke-width="1" opacity=".28"/></pattern></defs>
                        <rect x="0" y="0" width="<?php echo h($map_width); ?>" height="<?php echo h($map_height); ?>" fill="#f4edbd"/>
                        <rect x="0" y="0" width="<?php echo h($map_width); ?>" height="<?php echo h($map_height); ?>" fill="url(#noise)" opacity=".45"/>
                        <path d="M0,0 L145,0 C85,35 50,70 0,95 Z" fill="#8a4f12" opacity=".9"/>
                        <path d="M0,345 C85,315 135,345 176,393 C110,415 62,462 0,500 Z" fill="#8a4f12" opacity=".85"/>
                        <path d="M355,500 C415,430 455,395 500,370 L500,500 Z" fill="#8a4f12" opacity=".9"/>
                        <path d="M270,45 C315,20 365,28 388,74 C362,116 315,136 270,115 C245,85 246,58 270,45 Z" fill="#a57937" opacity=".42"/>
                        <path d="M292,230 C330,208 371,218 395,254 C365,285 316,293 282,265 C272,250 276,238 292,230 Z" fill="#7d4d1b" opacity=".55"/>
                        <text class="map-label" x="27" y="36">Debmark</text><text class="map-label" x="286" y="42">Mountains of Qwok</text><text class="map-label" x="365" y="218">Velbragh</text><text class="map-label" x="270" y="390">Tower of Anh-Allor</text>
                        <?php if ($quest && is_array($quest['route'] ?? null) && count($quest['route']) > 0): ?>
                            <?php $route_points = []; foreach ($quest['route'] as $point) { $route_points[] = (int) idlerpg_point_coord($point, 'x') . ',' . (int) idlerpg_point_coord($point, 'y'); } ?>
                            <polyline class="quest-line" points="<?php echo h(implode(' ', $route_points)); ?>"/>
                            <?php foreach ($quest['route'] as $idx => $point): $qx = idlerpg_point_coord($point, 'x'); $qy = idlerpg_point_coord($point, 'y'); ?>
                                <rect class="quest-point" x="<?php echo h($qx - 5); ?>" y="<?php echo h($qy - 5); ?>" width="10" height="10"/>
                            <?php endforeach; ?>
                        <?php endif; ?>
                        <?php $occupied_labels = []; ?>
                        <?php foreach (array_slice($map_players, 0, 120) as $player): $name = idlerpg_player_name($player); $x = max(0, min($map_width, idlerpg_player_coord($player, 'x'))); $y = max(0, min($map_height, idlerpg_player_coord($player, 'y'))); $label = idlerpg_map_label_position($x, $y, $name, $map_width, $map_height, $occupied_labels); $class = idlerpg_player_online($player) ? 'marker online' : 'marker offline'; if ($label['crowded']) { $class .= ' crowded'; } ?>
                            <a href="<?php echo h(idlerpg_player_url($name)); ?>"><g class="<?php echo h($class); ?>"><title><?php echo h($label['title'] . ' · lv.' . idlerpg_player_level($player)); ?></title><circle cx="<?php echo h($x); ?>" cy="<?php echo h($y); ?>" r="4"/><text text-anchor="<?php echo h($label['anchor']); ?>" x="<?php echo h($label['x']); ?>" y="<?php echo h($label['y']); ?>"><?php echo h($name); ?></text></g></a>
                        <?php endforeach; ?>
                    </svg>
                    <h3>Map positions</h3>
                    <table><thead><tr><th>Character</th><th>Position</th><th>Level</th><th>Status</th></tr></thead><tbody>
                    <?php foreach (array_slice($map_players, 0, 25) as $player): $name = idlerpg_player_name($player); ?>
                        <tr><td><a href="<?php echo h(idlerpg_player_url($name)); ?>"><?php echo h($name); ?></a></td><td>[<?php echo h((int) idlerpg_player_coord($player, 'x')); ?>,<?php echo h((int) idlerpg_player_coord($player, 'y')); ?>]</td><td>lv.<?php echo h(idlerpg_player_level($player)); ?></td><td><?php echo idlerpg_player_online($player) ? 'online' : 'offline'; ?></td></tr>
                    <?php endforeach; ?>
                    </tbody></table>
                <?php else: ?><p class="muted">No readable map data found.</p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'hof'): ?>
                <h2>Hall of Fame</h2>
                <?php if (count($seasons) > 0): ?>
                    <table><thead><tr><th>Season</th><th>Champion</th><th>Ended</th></tr></thead><tbody>
                    <?php foreach (array_reverse($seasons) as $season): ?>
                        <tr><td><?php echo h($season['id'] ?? '?'); ?></td><td><?php echo h($season['champion'] ?? ''); ?></td><td><?php echo !empty($season['ended_at']) ? h(idlerpg_time_value($season['ended_at'])) : ''; ?></td></tr>
                    <?php endforeach; ?>
                    </tbody></table>
                <?php else: ?><p class="muted">No completed seasons yet.</p><?php endif; ?>
            <?php endif; ?>

            <?php if ($view === 'commands'): ?>
                <h2>Commands</h2>
                <ul>
                    <li><code>,idlerpg register &lt;character&gt; &lt;class&gt;</code> — create a character</li>
                    <li><code>,idlerpg login</code> / <code>,idlerpg logout</code> — start or stop idling</li>
                    <li><code>,idlerpg status [character]</code> — show character progress</li>
                    <li><code>,idlerpg profile [character]</code> — show a detailed profile</li>
                    <li><code>,idlerpg achievements [character]</code> — show achievements</li>
                    <li><code>,idlerpg title &lt;achievement|none&gt;</code> — choose a public title</li>
                    <li><code>,idlerpg top</code> / <code>,idlerpg players</code> — show rankings and players</li>
                    <li><code>,idlerpg events</code> / <code>,idlerpg map</code> / <code>,idlerpg hof</code> — show events, map and Hall of Fame</li>
                </ul>
            <?php endif; ?>
        </main>

        <aside>
            <div class="card"><h2>Quick start</h2><ul><li><code>,idlerpg register &lt;name&gt; &lt;class&gt;</code></li><li><code>,idlerpg login</code></li><li><code>,idlerpg status</code></li><li><code>,idlerpg top</code></li></ul></div>
            <div class="card"><h2>Data setup</h2><p class="muted">Put JSON exports in <code>data/&lt;room-slug&gt;/</code> or set <code>IDLERPG_DATA_DIR</code>. Open <code>?debug=1</code> to check readable paths.</p></div>
            <div class="card"><h2>Map legend</h2><p class="muted">Blue = online, red = offline, orange = quest point. <code>[293,133] lv.16</code> means x=293, y=133 and level 16.</p></div>
        </aside>
    </div>
</div>
</body>
</html>
