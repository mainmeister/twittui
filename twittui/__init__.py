"""TwitTUI modular core package.

Provides structured logging, a unified show registry, secure configuration
helpers, API rate limiting, media/stream utilities, HTML sanitization and
local viewer server primitives, and a normalized SQLite cache store.
"""

from twittui.cache import (
    SHOW_DATE_BOUNDS_TTL_SECONDS,
    _LazySQLiteEpisodesCache,
    _restrict_file_permissions,
    _shows_cache_key_hash,
    delete_persistent_cache,
    ensure_cache_schema,
    episode_cache_key,
    episode_cache_key_str,
    get_cache_db_path,
    load_normalized_episodes,
    save_normalized_episodes,
)
from twittui.config import (
    TWIT_API_DOCS_URL,
    TWIT_API_KEY_URL,
    TWITTUI_HOMEPAGE_URL,
    load_twittui_dotenv,
    write_restricted_file,
)
from twittui.logging_config import (
    LOGGER_NAME,
    configure_logging,
    get_logger,
    reset_logging,
)
from twittui.media import (
    build_stream_args,
    is_safe_http_url,
    launch_stream_safe,
    resolve_stream_url,
    safe_xml_fromstring,
)
from twittui.rate_limiter import ApiRateLimiter
from twittui.shows import (
    DEFAULT_SHOWS,
    KNOWN_SHOW_FEEDS,
    MEMBERFUL_HOST_FEEDS,
    MEMBERFUL_SHOW_FEEDS,
    SHOW_REGISTRY,
    SHOW_SEARCH_SLUGS,
    TRANSCRIPT_SLUG_MAP,
    ShowEntry,
    get_show_entry,
)
from twittui.viewer import (
    _LocalHTMLHandler,
    _LocalHTMLServer,
    generate_local_server_token,
    sanitize_html_content,
)

__version__ = "1.1.0"

__all__ = [
    "__version__",
    "LOGGER_NAME",
    "get_logger",
    "configure_logging",
    "reset_logging",
    "ShowEntry",
    "SHOW_REGISTRY",
    "KNOWN_SHOW_FEEDS",
    "MEMBERFUL_SHOW_FEEDS",
    "MEMBERFUL_HOST_FEEDS",
    "SHOW_SEARCH_SLUGS",
    "TRANSCRIPT_SLUG_MAP",
    "DEFAULT_SHOWS",
    "get_show_entry",
    "TWIT_API_KEY_URL",
    "TWIT_API_DOCS_URL",
    "TWITTUI_HOMEPAGE_URL",
    "load_twittui_dotenv",
    "write_restricted_file",
    "ApiRateLimiter",
    "is_safe_http_url",
    "safe_xml_fromstring",
    "resolve_stream_url",
    "build_stream_args",
    "launch_stream_safe",
    "generate_local_server_token",
    "_LocalHTMLServer",
    "_LocalHTMLHandler",
    "sanitize_html_content",
    "SHOW_DATE_BOUNDS_TTL_SECONDS",
    "_shows_cache_key_hash",
    "_restrict_file_permissions",
    "get_cache_db_path",
    "episode_cache_key",
    "episode_cache_key_str",
    "ensure_cache_schema",
    "save_normalized_episodes",
    "load_normalized_episodes",
    "delete_persistent_cache",
    "_LazySQLiteEpisodesCache",
]
