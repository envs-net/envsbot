"""Split module for plugins/rss.py: config."""

from utils.config import config

PLUGIN_META = {
    "name": "rss",
    "version": "0.2.11",
    "description": "RSS/Atom feed watcher and poster",
    "category": "info",
    "requires": ["rooms", "_core", "users"],
    "room_state": "custom",
}


RSS_KEY = "RSS"
RSS_DEFAULT_TEMPLATE_KEY = "RSS_DEFAULT_TEMPLATE"
RSS_TEMPLATES_KEY = "RSS_TEMPLATES"
RSS_FEED_TEMPLATES_KEY = "RSS_FEED_TEMPLATES"

DEFAULT_RSS_TEMPLATE = "[RSS] ($feed_title) $title$summary_line\n$link$feed_ref_line"
RSS_TEMPLATE_MAX_LENGTH = max(
    1,
    int(config.get("rss_template_max_length", 1000) or 1000),
)
RSS_TEMPLATE_VARIABLES = frozenset({
    "feed_title",
    "title",
    "summary",
    "summary_line",
    "link",
    "feed_url",
    "feed_link",
    "feed_no",
    "article_no",
    "feed_ref",
    "feed_ref_line",
    "id",
    "date",
})


DEFAULT_POLL_INTERVAL = int(config.get("rss_global_query_interval", 1200) or 1200)


RSS_RETRY_INITIAL_DELAY = max(
    1,
    int(config.get("rss_retry_initial_delay", 300) or 300),
)


RSS_RETRY_BACKOFF_MULTIPLIER = max(
    1.0,
    float(config.get("rss_retry_backoff_multiplier", 2.0) or 2.0),
)


MAX_BACKOFF_TIME = max(
    1,
    int(config.get("rss_max_backoff_time", 3600) or 3600),
)


RSS_USER_AGENT = str(
    config.get("rss_user_agent")
    or config.get("http_user_agent")
    or "Mozilla/5.0 (compatible; envsbot; +https://github.com/envs-net/envsbot)"
)


RSS_FETCH_TIMEOUT_SECONDS = float(
    config.get(
        "rss_fetch_timeout_seconds",
        config.get("http_timeout_seconds", 8),
    )
    or 8
)


_configured_startup_stagger = config.get("rss_startup_stagger_seconds", 2.0)
RSS_STARTUP_STAGGER_SECONDS = max(
    0.0,
    float(
        2.0
        if _configured_startup_stagger is None
        else _configured_startup_stagger
    ),
)


RSS_MAX_REDIRECTS = max(1, int(config.get("rss_max_redirects", 5) or 5))


RSS_MAX_READ_BYTES = max(
    4096,
    int(config.get("rss_max_read_bytes", 1048576) or 1048576),
)


ALLOW_PRIVATE_FETCH_URLS = bool(config.get("allow_private_fetch_urls", False))


RSS_LIST_PAGE_SIZE = max(1, int(config.get("rss_list_page_size", 10) or 10))

_configured_trusted_max_feeds = config.get("rss_trusted_max_feeds", 10)
RSS_TRUSTED_MAX_FEEDS = max(
    0,
    int(10 if _configured_trusted_max_feeds is None else _configured_trusted_max_feeds),
)


RSS_MAX_ENTRIES_PER_POLL = max(
    1,
    int(config.get("rss_max_entries_per_poll", 10) or 10),
)

RSS_BROKEN_ERROR_THRESHOLD = max(
    1,
    int(config.get("rss_broken_error_threshold", 3) or 3),
)

__all__ = [
    'PLUGIN_META',
    'RSS_KEY',
    'RSS_DEFAULT_TEMPLATE_KEY',
    'RSS_TEMPLATES_KEY',
    'RSS_FEED_TEMPLATES_KEY',
    'DEFAULT_RSS_TEMPLATE',
    'RSS_TEMPLATE_MAX_LENGTH',
    'RSS_TEMPLATE_VARIABLES',
    'DEFAULT_POLL_INTERVAL',
    'RSS_RETRY_INITIAL_DELAY',
    'RSS_RETRY_BACKOFF_MULTIPLIER',
    'MAX_BACKOFF_TIME',
    'RSS_USER_AGENT',
    'RSS_FETCH_TIMEOUT_SECONDS',
    'RSS_STARTUP_STAGGER_SECONDS',
    'RSS_MAX_REDIRECTS',
    'RSS_MAX_READ_BYTES',
    'ALLOW_PRIVATE_FETCH_URLS',
    'RSS_LIST_PAGE_SIZE',
    'RSS_TRUSTED_MAX_FEEDS',
    'RSS_MAX_ENTRIES_PER_POLL',
    'RSS_BROKEN_ERROR_THRESHOLD',
]
