"""Backward-compatibility facade for TwitTUI.

The monolithic implementation has been decomposed into cohesive modules under
the ``twittui/`` package (``config``, ``cache``, ``catalog``, ``rss``, ``media``,
``downloader``, ``viewer``, ``rate_limiter``, ``search``, and ``ui``).

This module re-exports ``TwitTUIForm`` and all historical public helpers and
module attributes so existing imports, CLI entrypoints, and test monkeypatches
continue working seamlessly.
"""

from __future__ import annotations

import asyncio  # noqa: F401
import os
import subprocess  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401

import requests  # noqa: F401
import toga  # noqa: F401
from dotenv import set_key  # noqa: F401

from twittui._compat import (
    ApiRateLimiter,
    _is_textual_environment,
    _is_textual_tui_running,
    api_rate_limiter,
    launch_stream_safe,
)
from twittui.cache import (
    SHOW_DATE_BOUNDS_TTL_SECONDS,
    _LazySQLiteEpisodesCache,
    _restrict_file_permissions,
    _shows_cache_key_hash,
    count_normalized_episodes,
    delete_persistent_cache,
    ensure_cache_schema,
    episode_cache_key,
    get_cache_db_path,
    load_episodes_page,
    save_normalized_episodes,
    search_episodes_fts,
    upsert_normalized_episodes,
)
from twittui.config import (
    TWIT_API_DOCS_URL,
    TWIT_API_KEY_URL,
    TWITTUI_HOMEPAGE_URL,
    load_twittui_dotenv,
    write_restricted_file,
)
from twittui.logging_config import configure_logging, get_logger
from twittui.media import (
    build_stream_args,
    is_safe_http_url,
    resolve_stream_url,
    safe_xml_fromstring,
)
from twittui.shows import (
    DEFAULT_SHOWS,
    KNOWN_SHOW_FEEDS,
    MEMBERFUL_HOST_FEEDS,
    MEMBERFUL_SHOW_FEEDS,
    SHOW_ABBREVIATIONS,
    SHOW_REGISTRY,
    SHOW_SEARCH_SLUGS,
    TRANSCRIPT_SLUG_MAP,
    ShowEntry,
    get_show_entry,
)
from twittui.ui.form import (
    TwitTUIForm,
    _close_idle_event_loop,
    _patched_toga_widget_init,
    _unset_gtk_module_env,
    apply_tooltip_to_impl,
    get_widget_tooltip,
    main,
    patch_toga_gtk_app,
    patch_toga_icons,
    patch_toga_tooltips,
    resolve_app_icon,
    set_widget_tooltip,
)
from twittui.viewer import (
    _LocalHTMLHandler,
    _LocalHTMLServer,
    generate_local_server_token,
    sanitize_html_content,
)

try:
    import defusedxml.ElementTree as DefusedET
except ImportError:
    DefusedET = None

_logger = get_logger()

# Ensure environment variables are loaded on direct import
load_twittui_dotenv()

# Initialize Toga tooltip, icon, and backend resilience patches
patch_toga_tooltips()
if __name__ != '__main__' and os.environ.get('TOGA_BACKEND') not in ('toga_textual', 'textual'):
    patch_toga_icons(include_gtk=True)
    patch_toga_gtk_app()
else:
    patch_toga_icons(include_gtk=False)

try:
    from toga_textual_backend import patch_toga_textual
    patch_toga_textual()
except Exception:
    _logger.debug("Ignored exception in %s", '<module>', exc_info=True)

__all__ = [
    "ApiRateLimiter",
    "DEFAULT_SHOWS",
    "DefusedET",
    "KNOWN_SHOW_FEEDS",
    "MEMBERFUL_HOST_FEEDS",
    "MEMBERFUL_SHOW_FEEDS",
    "SHOW_ABBREVIATIONS",
    "SHOW_DATE_BOUNDS_TTL_SECONDS",
    "SHOW_REGISTRY",
    "SHOW_SEARCH_SLUGS",
    "ShowEntry",
    "TRANSCRIPT_SLUG_MAP",
    "TWITTUI_HOMEPAGE_URL",
    "TWIT_API_DOCS_URL",
    "TWIT_API_KEY_URL",
    "TwitTUIForm",
    "_LazySQLiteEpisodesCache",
    "_LocalHTMLHandler",
    "_LocalHTMLServer",
    "_close_idle_event_loop",
    "_is_textual_environment",
    "_is_textual_tui_running",
    "_patched_toga_widget_init",
    "_restrict_file_permissions",
    "_shows_cache_key_hash",
    "_unset_gtk_module_env",
    "api_rate_limiter",
    "apply_tooltip_to_impl",
    "build_stream_args",
    "configure_logging",
    "count_normalized_episodes",
    "delete_persistent_cache",
    "ensure_cache_schema",
    "episode_cache_key",
    "generate_local_server_token",
    "get_cache_db_path",
    "get_logger",
    "get_show_entry",
    "get_widget_tooltip",
    "is_safe_http_url",
    "launch_stream_safe",
    "load_episodes_page",
    "load_twittui_dotenv",
    "main",
    "patch_toga_gtk_app",
    "patch_toga_icons",
    "patch_toga_tooltips",
    "resolve_app_icon",
    "resolve_stream_url",
    "safe_xml_fromstring",
    "sanitize_html_content",
    "save_normalized_episodes",
    "search_episodes_fts",
    "set_key",
    "set_widget_tooltip",
    "upsert_normalized_episodes",
    "write_restricted_file",
]

if __name__ == '__main__':
    from main import resolve_toga_backend
    resolve_toga_backend()
    load_twittui_dotenv()
    app = main()
    app.main_loop()
