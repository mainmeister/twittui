"""Primary TwitTUIForm Toga application controller and main window layout."""

from __future__ import annotations

import asyncio
import builtins
import copy
import inspect
import json
import os
import re
import sqlite3
import sys
import threading
import time
import weakref
from types import SimpleNamespace
from typing import Any

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from tiered_search import compute_match_score, rank_and_filter_episodes
from twittui._compat import (
    PACKAGE_ROOT,
    PROJECT_ROOT,
    _is_textual_environment,
    _is_textual_tui_running,
    api_rate_limiter,
    compat_attr,
    launch_stream_safe,
)
from twittui.cache import (
    SHOW_DATE_BOUNDS_TTL_SECONDS,
    _LazySQLiteEpisodesCache,
    _shows_cache_key_hash,
    delete_persistent_cache,
    ensure_cache_schema,
    get_cache_db_path,
    save_normalized_episodes,
)
from twittui.catalog import CatalogMixin
from twittui.config import ConfigMixin, TWITTUI_HOMEPAGE_URL
from twittui.downloader import DownloaderMixin
from twittui.logging_config import get_logger, safe_url_for_log
from twittui.media import MediaMixin, resolve_stream_url
from twittui.rss import RssMixin
from twittui.ui.metadata import MetadataMixin
from twittui.ui.preferences import PreferencesMixin
from twittui.viewer import ViewerMixin

_logger = get_logger("ui.form")

_ORIG_TOGA_WIDGET_INIT = toga.Widget.__init__


def apply_tooltip_to_impl(impl: Any, tooltip_text: str | None) -> None:
    """Apply tooltip text to native backend widgets across GTK, Textual, and other platforms."""
    if impl is None:
        return
    targets = []
    for attr in ('native', 'native_table', 'native_switch', 'native_label', 'native_textview'):
        obj = getattr(impl, attr, None)
        if obj is not None and obj not in targets:
            targets.append(obj)
    if not targets and (hasattr(impl, 'set_tooltip_text') or hasattr(impl, 'tooltip')):
        targets.append(impl)

    for target in targets:
        # GTK backend support (Gtk.Widget)
        if hasattr(target, 'set_tooltip_text'):
            try:
                target.set_tooltip_text(tooltip_text if tooltip_text else None)
            except Exception:
                _logger.debug("Ignored exception in %s", 'apply_tooltip_to_impl', exc_info=True)
        # Textual backend support (textual.widget.Widget)
        if hasattr(target, 'tooltip'):
            try:
                target.tooltip = tooltip_text if tooltip_text else None
            except Exception:
                _logger.debug("Ignored exception in %s", 'apply_tooltip_to_impl', exc_info=True)


def get_widget_tooltip(widget: toga.Widget) -> str | None:
    """Retrieve tooltip associated with a Toga widget."""
    return getattr(widget, '_twittui_tooltip', None)


def set_widget_tooltip(widget: toga.Widget, tooltip_text: str | None) -> toga.Widget:
    """Set tooltip on a Toga widget and propagate to underlying native elements."""
    setattr(widget, '_twittui_tooltip', tooltip_text)
    impl = getattr(widget, '_impl', None)
    if impl is not None:
        apply_tooltip_to_impl(impl, tooltip_text)
    return widget


def _patched_toga_widget_init(self: toga.Widget, *args: Any, tooltip: str | None = None, **kwargs: Any) -> None:
    """Patched Toga Widget __init__ accepting optional tooltip parameter."""
    _ORIG_TOGA_WIDGET_INIT(self, *args, **kwargs)
    if tooltip is not None:
        self.tooltip = tooltip


def patch_toga_tooltips() -> None:
    """Patch toga.Widget to support tooltip property and constructor keyword."""
    if not getattr(toga.Widget, '_twittui_tooltips_patched', False):
        toga.Widget.tooltip = property(get_widget_tooltip, set_widget_tooltip)
        toga.Widget.__init__ = _patched_toga_widget_init
        toga.Widget._twittui_tooltips_patched = True


def _unset_gtk_module_env() -> None:
    """Clear host GTK/Qt module variables before importing GTK bindings."""
    env_vars = (
        "GTK_MODULES",
        "GTK_PATH",
        "GTK3_MODULES",
        "UBUNTU_MENUPROXY",
        "QT_STYLE_OVERRIDE",
        "QT_QPA_PLATFORMTHEME",
    )
    for var in env_vars:
        os.environ.pop(var, None)
    try:
        import ctypes
        libc = ctypes.CDLL(None)
        if hasattr(libc, "unsetenv"):
            for var in env_vars:
                libc.unsetenv(var.encode("ascii"))
    except Exception:
        _logger.debug("Ignored exception in %s", '_unset_gtk_module_env', exc_info=True)


def patch_toga_icons(include_gtk: bool = True) -> None:
    """Patch Toga and (optionally) Toga-GTK Icon classes to prevent infinite recursion if icon loading fails."""
    try:
        import toga.icons

        if not getattr(toga.icons.CachedIcon, "_twittui_cached_icon_patched", False):
            orig_cached_get = toga.icons.CachedIcon.__get__

            def safe_cached_get(self: Any, obj: object, owner: type[toga.icons.Icon]) -> Any:
                cls = owner if obj is None else obj.__class__
                attr_name = f"_{self.name}"
                if hasattr(cls, attr_name):
                    return getattr(cls, attr_name)
                try:
                    placeholder = toga.icons.Icon.__new__(toga.icons.Icon)
                    placeholder.factory = toga.platform.get_factory()
                    placeholder.path = getattr(self, "name", "toga")
                    placeholder.system = getattr(self, "system", False)
                    try:
                        placeholder._impl = placeholder.factory.Icon(interface=placeholder, path={})
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'patch_toga_icons.safe_cached_get', exc_info=True)
                    setattr(cls, attr_name, placeholder)

                    value = orig_cached_get(self, obj, owner)
                    setattr(cls, attr_name, value)
                    return value
                except Exception:
                    _logger.debug("Fallback to placeholder icon in patch_toga_icons.safe_cached_get", exc_info=True)
                    return getattr(cls, attr_name, None)

            toga.icons.CachedIcon.__get__ = safe_cached_get
            toga.icons.CachedIcon._twittui_cached_icon_patched = True
    except Exception:
        _logger.debug("Ignored exception in %s", 'patch_toga_icons', exc_info=True)

    if not include_gtk:
        return

    try:
        _unset_gtk_module_env()
        import toga_gtk.icons
        from gi.repository import GdkPixbuf

        if not getattr(toga_gtk.icons.Icon, "_twittui_gtk_icon_patched", False):
            orig_gtk_icon_init = toga_gtk.icons.Icon.__init__

            def safe_gtk_icon_init(self: Any, interface: Any, path: Any) -> None:
                self.interface = interface
                self.path = path or {}
                self._native = {}
                try:
                    orig_gtk_icon_init(self, interface, path)
                except Exception:
                    _logger.debug("Fallback to blank GdkPixbuf in patch_toga_icons.safe_gtk_icon_init", exc_info=True)
                    for size in getattr(toga_gtk.icons.Icon, "SIZES", [512, 256, 128, 72, 64, 32, 16]):
                        try:
                            self._native[size] = GdkPixbuf.Pixbuf.new(
                                GdkPixbuf.Colorspace.RGB, True, 8, size, size
                            )
                        except Exception:
                            _logger.debug("Ignored exception in %s", 'patch_toga_icons.safe_gtk_icon_init', exc_info=True)

            toga_gtk.icons.Icon.__init__ = safe_gtk_icon_init
            toga_gtk.icons.Icon._twittui_gtk_icon_patched = True
    except Exception:
        _logger.debug("Ignored exception in %s", 'patch_toga_icons', exc_info=True)


def _close_idle_event_loop(loop: Any) -> None:
    """Close an idle, non-running event loop owned by a discarded App instance."""
    if loop is None:
        return
    try:
        if not loop.is_closed() and not loop.is_running():
            try:
                policy_local = getattr(asyncio.get_event_loop_policy(), "_local", None)
                if getattr(policy_local, "_loop", None) is loop:
                    asyncio.set_event_loop(None)
            except (AttributeError, RuntimeError):
                _logger.debug("Ignored exception clearing thread-local loop reference", exc_info=True)
            loop.close()
    except Exception:
        _logger.debug("Ignored exception in %s", '_close_idle_event_loop', exc_info=True)


def patch_toga_gtk_app() -> None:
    """Patch toga_gtk.app.App to use None application_id and NON_UNIQUE flags, preventing AppArmor D-Bus ownership denials in sandboxes."""
    try:
        _unset_gtk_module_env()
        import toga_gtk.app
        from gi.repository import Gio

        orig_init = toga_gtk.app.App.__init__

        def safe_gtk_app_init(self: Any, interface: Any) -> None:
            orig_app_id = getattr(interface, '_app_id', None)
            try:
                interface._app_id = None
                orig_init(self, interface)
            finally:
                interface._app_id = orig_app_id
            loop = getattr(self, 'loop', None)
            if loop is not None:
                weakref.finalize(self, _close_idle_event_loop, loop)
            try:
                current_flags = self.native.get_flags()
                self.native.set_flags(current_flags | Gio.ApplicationFlags.NON_UNIQUE)
            except Exception:
                _logger.debug("Ignored exception in %s", 'patch_toga_gtk_app.safe_gtk_app_init', exc_info=True)

        if not getattr(toga_gtk.app.App, "_twittui_non_unique_patched", False):
            toga_gtk.app.App.__init__ = safe_gtk_app_init
            toga_gtk.app.App._twittui_non_unique_patched = True
    except Exception:
        _logger.debug("Ignored exception in %s", 'patch_toga_gtk_app', exc_info=True)


def resolve_app_icon() -> str | None:
    """Find and return the base path or file path of the application icon."""
    candidate_bases = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate_bases.append(getattr(sys, "_MEIPASS"))
    if os.environ.get("SNAP"):
        candidate_bases.append(os.environ["SNAP"])
    candidate_bases.extend([
        PROJECT_ROOT,
        PACKAGE_ROOT,
        os.getcwd(),
    ])
    for base in candidate_bases:
        for fname in ("twittui.png", "twittui.ico", "twittui"):
            target = os.path.join(base, "resources", fname)
            if os.path.isfile(target) or os.path.isfile(f"{target}.png"):
                return os.path.join(base, "resources", "twittui")
    return None


class TwitTUIForm(
    PreferencesMixin,
    MetadataMixin,
    ViewerMixin,
    DownloaderMixin,
    MediaMixin,
    RssMixin,
    CatalogMixin,
    ConfigMixin,
    toga.App,
):
    """Main TwitTUI application controller composing all domain and UI mixins."""

    def __init__(self, formal_name='TwitTUI', app_id='org.twit.twittui', **kwargs):
        self._cache_db_path = kwargs.pop('cache_db_path', None) or get_cache_db_path(app_id=app_id)
        self.show_ids = {}
        self.show_active = {}
        self.show_date_bounds = {}
        self._shows_cache = {}
        self._show_date_cache = {}
        self._show_names_by_display = {}
        self.current_episodes = []
        self.current_page = 1
        self._episodes_cache = {}
        self._triangulation_archive_cache = {}
        self._episode_detail_cache = {}
        self._media_webpage_cache = {}
        self._api_search_cache = {}
        self._club_rss_cache = None
        self._memberful_feeds_cache = {}
        self._show_rss_cache = {}
        self._local_server = None
        self._init_persistent_cache_db()
        self.show_label = None
        self.show_combo = None
        self.fetch_button = None
        self.next_button = None
        self.search_label = None
        self.search_input = None
        self.search_button = None
        self.clear_button = None
        self.sort_label = None
        self.date_radio = None
        self.episode_radio = None
        self.title_radio = None
        self.length_radio = None
        self.size_radio = None
        self.sort_order_button = None
        self.audio_only_checkbox = None
        self.episodes_label = None
        self.episodes_list = None
        self.button_box = None
        self.download_button = None
        self.stream_button = None
        self.preferences_button = None
        self.cancel_button = None
        self.close_button = None
        self.settings_box = None
        self.preferences_close_button = None
        self.app_id_label = None
        self.app_id_input = None
        self.app_key_label = None
        self.app_key_input = None
        self.test_api_button = None
        self.url_label = None
        self.url_prefix = None
        self.url_input = None
        self.show_url_button = None
        self.dest_label = None
        self.dest_input = None
        self.dest_button = None
        self.dest_open_button = None
        self.show_folders_checkbox = None
        self.block_label = None
        self.block_input = None
        self.rate_limit_label = None
        self.rate_limit_input = None
        self.streamer_label = None
        self.streamer_input = None
        self.search_prefs_label = None
        self.fuzzy_search_checkbox = None
        self.phonetic_search_checkbox = None
        self.progress_bar = None
        self.readme_cmd = None
        self.apib_cmd = None
        self.api_key_cmd = None
        self.preferences_cmd = None
        self._preferences_window = None
        self._is_downloading = False
        self._download_starting = False
        self._cancel_download = False
        self._active_download_proc = None
        self._download_lock = threading.Lock()
        self._cache_lock = threading.RLock()
        self._pending_env_saves: dict[str, str] = {}
        self._env_save_timer = None
        self._last_saved_env: dict[str, str] = {}
        self._club_url_prefix = 'https://twit.memberfulcontent.com/rss/9041?auth='
        self._hover_lock = threading.Lock()
        self._hover_timer = None
        self._hover_row_index = None
        self._hover_generation = 0
        self._dialog_open = False
        self._metadata_window = None
        self._splash_window = None
        self._gtk_maximize_handler_connected = False
        self._gtk_window_maximized = None
        if "home_page" not in kwargs or kwargs["home_page"] is None:
            kwargs["home_page"] = TWITTUI_HOMEPAGE_URL
        if "icon" not in kwargs or kwargs["icon"] is None:
            resolved_icon = resolve_app_icon()
            if resolved_icon:
                kwargs["icon"] = resolved_icon
        try:
            super().__init__(formal_name=formal_name, app_id=app_id, **kwargs)
        except Exception as e:
            # If icon creation triggered a backend error or recursion, retry without explicit icon
            if "icon" in kwargs:
                kwargs.pop("icon", None)
                try:
                    super().__init__(formal_name=formal_name, app_id=app_id, **kwargs)
                except Exception:
                    raise
            else:
                raise
        impl_loop = getattr(getattr(self, '_impl', None), 'loop', None)
        if impl_loop is not None:
            weakref.finalize(self, _close_idle_event_loop, impl_loop)

    def _is_textual_app(self) -> bool:
        """Return True if this form instance is backed by Toga Textual."""
        return _is_textual_environment(self)

    def _active_dialog_window(self) -> Any:
        """Return the active window for dialogs (Preferences window when visible, else main_window)."""
        prefs_win = getattr(self, '_preferences_window', None)
        if prefs_win is not None and not getattr(prefs_win, 'closed', False):
            try:
                if getattr(prefs_win, 'visible', False):
                    return prefs_win
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._active_dialog_window', exc_info=True)
        return getattr(self, 'main_window', None)

    def _present_window_dialog(
        self,
        win: Any,
        kind: str,
        title: str,
        message: str,
        on_result: Any = None,
    ) -> None:
        """Display a Toga 0.5 InfoDialog/ErrorDialog without emitting 0.4 deprecation warnings."""
        if not win:
            return
        if isinstance(win, toga.Window) and hasattr(win, 'dialog'):
            dlg = (
                toga.ErrorDialog(title, message)
                if kind == 'error'
                else toga.InfoDialog(title, message)
            )
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is not None:
                task = running_loop.create_task(win.dialog(dlg))
                if callable(on_result):
                    task.add_done_callback(lambda _t: on_result(win, None))
                return
            res = dlg._show(win)
            if callable(on_result):
                fut = getattr(res, 'future', None)
                if fut is not None and not fut.done():
                    fut.add_done_callback(lambda _f: on_result(win, None))
                else:
                    on_result(win, None)
            return
        # Fallback for mock windows in unit tests
        if kind == 'error':
            if on_result is not None:
                win.error_dialog(title, message, on_result=on_result)
            else:
                win.error_dialog(title, message)
        else:
            if on_result is not None:
                win.info_dialog(title, message, on_result=on_result)
            else:
                win.info_dialog(title, message)

    def _show_dialog_threadsafe(
        self,
        kind: str,
        title: str,
        message: str,
        host_win: Any = None,
        on_result: Any = None,
        *,
        prefer_main: bool = False,
    ) -> None:
        """Display an info or error dialog safely on the UI thread."""
        def _present() -> None:
            try:
                if host_win is not None:
                    win = host_win
                elif prefer_main:
                    win = getattr(self, 'main_window', None)
                else:
                    win = self._active_dialog_window()
                if not win:
                    return
                self._present_window_dialog(win, kind, title, message, on_result=on_result)
            except Exception as e:
                _logger.warning(f"Error displaying {kind} dialog '{title}': {e}")

        loop = getattr(self, 'loop', None)
        if threading.current_thread() is not threading.main_thread():
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(_present)
                except Exception:
                    _logger.debug(
                        "Dropped off-thread %s dialog '%s' because UI loop rejected scheduling",
                        kind,
                        title,
                        exc_info=True,
                    )
                return
            # Avoid touching real native GTK/Textual windows from a background thread
            candidate_win = host_win if host_win is not None else getattr(self, '_main_window', None)
            if isinstance(candidate_win, toga.Window):
                _logger.debug("Skipped off-thread %s dialog '%s' without running UI loop", kind, title)
                return
        _present()

    def _cleanup_resources_for_exit(self) -> None:
        """Flush pending settings, cancel active downloads, terminate child downloaders, and shut down _LocalHTMLServer."""
        self._flush_pending_env_saves()
        if getattr(self, '_is_downloading', False):
            self._cancel_download = True
        self._terminate_active_download_proc()
        server = getattr(self, '_local_server', None)
        if server is not None:
            self._local_server = None
            try:
                # Run shutdown() on a helper thread with brief join so exit never deadlocks
                def _stop_srv(srv=server) -> None:
                    try:
                        srv.shutdown()
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm._cleanup_resources_for_exit._stop_srv', exc_info=True)
                    try:
                        srv.server_close()
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm._cleanup_resources_for_exit._stop_srv', exc_info=True)

                t = threading.Thread(target=_stop_srv, daemon=True)
                t.start()
                t.join(timeout=1.0)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._cleanup_resources_for_exit', exc_info=True)

    def set_tooltip(self, widget: Any, tooltip_text: str | None) -> Any:
        """Helper to assign a tooltip to any UI widget or command."""
        if hasattr(widget, 'tooltip'):
            widget.tooltip = tooltip_text
        set_widget_tooltip(widget, tooltip_text)
        return widget

    def get_tooltip(self, widget: Any) -> str | None:
        """Helper to retrieve the tooltip of any UI widget or command."""
        if hasattr(widget, 'tooltip') and widget.tooltip is not None:
            return widget.tooltip
        return get_widget_tooltip(widget)

    def _init_persistent_cache_db(self, db_path: str | None = None) -> None:
        """Initialize normalized SQLite cache (WAL mode, 24h date-bound TTL, lazy episode loading)."""
        if db_path:
            self._cache_db_path = db_path
        elif not getattr(self, '_cache_db_path', None):
            self._cache_db_path = get_cache_db_path(getattr(self, 'app_id', None))

        if self._cache_db_path and self._cache_db_path != ':memory:':
            try:
                parent = os.path.dirname(os.path.abspath(self._cache_db_path))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                    default_cache_dir = os.path.abspath(os.path.join(os.path.expanduser('~'), '.cache', 'twittui'))
                    if os.path.abspath(parent) == default_cache_dir:
                        os.chmod(parent, 0o700)
            except OSError:
                _logger.debug("Could not prepare cache directory for %s", self._cache_db_path, exc_info=True)

        try:
            with sqlite3.connect(self._cache_db_path, timeout=10.0) as conn:
                ensure_cache_schema(conn, db_path=self._cache_db_path)
                conn.commit()

                now = time.time()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT category, cache_key, data_json, created_at, updated_at FROM twittui_cache WHERE category != 'episodes'"
                )
                rows = cursor.fetchall()
                legacy_shows_migrations: list[tuple[str, str, str, float, float]] = []
                expired_date_bound_keys: list[str] = []
                for category, key, data_json, created_at, updated_at in rows:
                    try:
                        val = json.loads(data_json)
                        if category == 'shows':
                            if self._shows_cache is None or not isinstance(self._shows_cache, dict):
                                self._shows_cache = {}
                            if ':' in key:
                                parts = key.split(':', 1)
                                hashed_key = _shows_cache_key_hash(parts[0], parts[1])
                                self._shows_cache[hashed_key] = val
                                legacy_shows_migrations.append((key, hashed_key, data_json, created_at, updated_at))
                            else:
                                self._shows_cache[key] = val
                        elif category == 'show_date_bounds':
                            age = now - float(updated_at or 0.0)
                            if age <= SHOW_DATE_BOUNDS_TTL_SECONDS:
                                self._show_date_cache[key] = tuple(val) if isinstance(val, (list, tuple)) else val
                            else:
                                expired_date_bound_keys.append(key)
                        elif category == 'episode_detail':
                            self._episode_detail_cache[key] = val
                        elif category == 'media_webpage':
                            parts = key.split('|||', 1)
                            clean_p = parts[0]
                            audio_flag = bool(int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else False
                            self._media_webpage_cache[(clean_p, audio_flag)] = val
                        elif category == 'triangulation_archive':
                            parts = key.split('|||', 1)
                            page_num = int(parts[0]) if parts[0].isdigit() else 1
                            sort_flag = bool(int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else False
                            self._triangulation_archive_cache[(page_num, sort_flag)] = val
                        elif category == 'api_search':
                            self._api_search_cache[key] = val
                    except (ValueError, TypeError):
                        _logger.debug("Skipping corrupted cache row (%s, %s)", category, key, exc_info=True)

                if expired_date_bound_keys:
                    try:
                        conn.executemany(
                            "DELETE FROM twittui_cache WHERE category = 'show_date_bounds' AND cache_key = ?",
                            [(k,) for k in expired_date_bound_keys],
                        )
                        conn.commit()
                    except sqlite3.Error:
                        _logger.debug("Failed purging expired show_date_bounds rows", exc_info=True)

                # Migrate legacy plaintext 'app_id:app_key' cache keys to SHA-256 hashes immediately
                if legacy_shows_migrations:
                    try:
                        conn.execute("PRAGMA secure_delete = ON")
                        for old_key, hashed_key, data_json, created_at, updated_at in legacy_shows_migrations:
                            conn.execute(
                                """
                                INSERT INTO twittui_cache (category, cache_key, data_json, created_at, updated_at)
                                VALUES ('shows', ?, ?, ?, ?)
                                ON CONFLICT(category, cache_key) DO NOTHING
                                """,
                                (hashed_key, data_json, created_at, updated_at),
                            )
                            conn.execute(
                                "DELETE FROM twittui_cache WHERE category = 'shows' AND cache_key = ?",
                                (old_key,),
                            )
                        conn.commit()
                    except sqlite3.Error:
                        _logger.debug("Legacy shows cache key migration failed", exc_info=True)

                # Discover available cached shows across normalized & legacy tables without eager JSON decoding
                cursor.execute("SELECT DISTINCT show_id FROM twittui_episodes")
                norm_keys = {str(r[0]) for r in cursor.fetchall() if r and r[0] is not None}
                cursor.execute("SELECT cache_key FROM twittui_cache WHERE category = 'episodes'")
                legacy_keys = {str(r[0]) for r in cursor.fetchall() if r and r[0] is not None}
                episode_keys = norm_keys | legacy_keys
                lazy_eps = _LazySQLiteEpisodesCache(self._cache_db_path, episode_keys)
                if isinstance(getattr(self, '_episodes_cache', None), dict):
                    for k, v in dict.items(self._episodes_cache):
                        lazy_eps[k] = v
                self._episodes_cache = lazy_eps
        except sqlite3.Error:
            _logger.debug("Failed to initialize SQLite cache at %s", self._cache_db_path, exc_info=True)

    def _save_to_persistent_cache(self, category: str, cache_key: str, data: Any) -> None:
        """Save a cache entry dynamically to persistent SQLite database (normalized for episodes)."""
        db_path = getattr(self, '_cache_db_path', None) or get_cache_db_path(getattr(self, 'app_id', None))
        try:
            now = time.time()
            with sqlite3.connect(db_path, timeout=10.0) as conn:
                ensure_cache_schema(conn, db_path=db_path)
                if category == 'episodes' and isinstance(data, list):
                    save_normalized_episodes(conn, str(cache_key), data, now=now, db_path=db_path)
                else:
                    data_json = json.dumps(data)
                    conn.execute(
                        """
                        INSERT INTO twittui_cache (category, cache_key, data_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(category, cache_key) DO UPDATE SET
                            data_json = excluded.data_json,
                            updated_at = excluded.updated_at
                        """,
                        (category, str(cache_key), data_json, now, now)
                    )
                conn.commit()
        except (sqlite3.Error, TypeError, ValueError):
            _logger.debug("Failed saving cache entry (%s, %s)", category, cache_key, exc_info=True)

    def _delete_from_persistent_cache(self, category: str | None = None) -> None:
        """Clear entries from persistent SQLite database."""
        db_path = getattr(self, '_cache_db_path', None) or get_cache_db_path(getattr(self, 'app_id', None))
        delete_persistent_cache(db_path, category=category)

    def _network_snapshot(self):
        """Capture UI state before running network helpers in a worker."""
        worker = object.__new__(type(self))
        worker.__dict__ = self.__dict__.copy()
        for name in ('show_combo', 'sort_order_button', 'date_radio', 'episode_radio',
                     'title_radio', 'length_radio', 'size_radio', 'audio_only_checkbox',
                     'fuzzy_search_checkbox', 'phonetic_search_checkbox', 'app_id_input',
                     'app_key_input', 'url_input', 'api_status_label', 'block_input',
                     'rate_limit_input', 'dest_input', 'show_folders_checkbox', 'streamer_input'):
            widget = getattr(self, name, None)
            if widget is not None:
                values = {key: getattr(widget, key) for key in ('value', 'text')
                          if hasattr(widget, key)}
                setattr(worker, name, SimpleNamespace(**values))
        cache_lock = getattr(self, '_cache_lock', None)
        def _copy_caches() -> None:
            for name in ('show_ids', 'show_active', 'show_date_bounds', '_show_date_cache',
                         '_show_names_by_display', '_memberful_feeds_cache', '_show_rss_cache',
                         '_shows_cache', '_episodes_cache', '_triangulation_archive_cache',
                         '_episode_detail_cache', '_media_webpage_cache', '_api_search_cache'):
                val = getattr(self, name, None)
                if isinstance(val, dict):
                    setattr(worker, name, val.copy())
                elif isinstance(val, list):
                    setattr(worker, name, list(val))
        if cache_lock is not None:
            with cache_lock:
                _copy_caches()
        else:
            _copy_caches()
        worker._cache_db_path = getattr(self, '_cache_db_path', None)
        current_eps = getattr(self, 'current_episodes', None)
        if isinstance(current_eps, list):
            worker.current_episodes = [ep.copy() if isinstance(ep, dict) else ep for ep in current_eps]
        else:
            worker.current_episodes = copy.copy(current_eps)
        return worker

    def _snapshot_episode(self, target):
        if isinstance(target, (dict, tuple, list)):
            return copy.deepcopy(target)
        return SimpleNamespace(**{name: copy.deepcopy(getattr(target, name))
                                  for name in ('episode_data', 'episode', 'number', 'title',
                                               'date', 'length', 'duration', 'size', 'file_size',
                                               'show', 'media_url', '_search_match_context', 'match_context') if hasattr(target, name)})

    def _run_network(self, work, done, on_error=None, on_finally=None):
        """Run ``work`` off the UI thread and invoke ``done``/``on_error``/``on_finally`` on the UI loop.

        ``on_finally`` is guaranteed to execute exactly once on the UI event loop inside a
        ``finally:`` block (and via ``task.add_done_callback`` if cancelled before the first
        event-loop tick) even when ``work`` raises, ``done`` raises, the task is cancelled
        (``CancelledError``), or ``loop.create_task`` fails to schedule the coroutine.
        """
        finally_called = False

        def _invoke_finally() -> None:
            nonlocal finally_called
            if finally_called:
                return
            finally_called = True
            if callable(on_finally):
                try:
                    on_finally()
                except Exception as fin_err:
                    _logger.debug("Network finally callback failed: %s", fin_err, exc_info=True)

        async def run():
            try:
                try:
                    result = await asyncio.to_thread(work)
                except Exception as e:
                    _logger.debug("Network operation failed: %s", e, exc_info=True)
                    if callable(on_error):
                        try:
                            on_error(e)
                        except Exception as cb_err:
                            _logger.debug("Network error callback failed: %s", cb_err, exc_info=True)
                    return
                try:
                    done(result)
                except Exception as e:
                    _logger.debug("Network completion callback failed: %s", e, exc_info=True)
                    if callable(on_error):
                        try:
                            on_error(e)
                        except Exception as cb_err:
                            _logger.debug("Network error callback failed: %s", cb_err, exc_info=True)
            finally:
                _invoke_finally()

        coro = run()
        try:
            task = self.loop.create_task(coro)
            if callable(on_finally) and hasattr(task, "add_done_callback"):
                task.add_done_callback(lambda _t: _invoke_finally())
            return task
        except Exception as e:
            coro.close()
            _logger.debug("Failed to schedule network operation: %s", e, exc_info=True)
            if callable(on_error):
                try:
                    on_error(e)
                except Exception as cb_err:
                    _logger.debug("Network error callback failed: %s", cb_err, exc_info=True)
            _invoke_finally()
            return None

    def _call_run_network(self, work, done, *, on_error=None, on_finally=None):
        """Dispatch to ``self._run_network`` with ``on_error``/``on_finally`` while honoring 2-arg test stubs."""
        run_net = self._run_network
        if getattr(run_net, '__func__', None) is TwitTUIForm._run_network:
            return run_net(work, done, on_error=on_error, on_finally=on_finally)

        target_callable = getattr(run_net, 'side_effect', None)
        inspect_target = target_callable if callable(target_callable) else run_net
        accepts_callbacks = False
        try:
            sig = inspect.signature(inspect_target)
            params = sig.parameters
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            accepts_callbacks = has_var_kw or ('on_error' in params and 'on_finally' in params)
        except (TypeError, ValueError):
            accepts_callbacks = False

        if accepts_callbacks and (target_callable is not None or not hasattr(run_net, 'assert_called')):
            return run_net(work, done, on_error=on_error, on_finally=on_finally)

        def _wrapped_done(result):
            try:
                return done(result)
            except Exception as exc:
                if callable(on_error):
                    on_error(exc)
                raise
            finally:
                if callable(on_finally):
                    on_finally()

        try:
            return run_net(work, _wrapped_done)
        except Exception as exc:
            _logger.debug("Network stub execution raised exception: %s", exc, exc_info=True)
            if callable(on_error):
                try:
                    on_error(exc)
                except Exception:
                    _logger.debug("Network stub error callback failed", exc_info=True)
            if callable(on_finally):
                try:
                    on_finally()
                except Exception:
                    _logger.debug("Network stub finally callback failed", exc_info=True)
            return None

    def _rate_limit_wait_changed(self, waiting):
        loop = self.loop
        if waiting and threading.current_thread() is threading.main_thread() and loop.is_running():
            raise RuntimeError('TWiT API requests must run off the UI thread')
        try:
            if waiting and threading.current_thread() is not threading.main_thread() and loop.is_running():
                ready = threading.Event()

                def show():
                    try:
                        self._set_rate_limit_wait(True)
                    finally:
                        loop.call_later(0.01, ready.set)

                loop.call_soon_threadsafe(show)
                if not ready.wait(timeout=5):
                    loop.call_soon_threadsafe(self._set_rate_limit_wait, False)
                    raise TimeoutError('Timed out waiting for the TWiT API dialog')
            else:
                loop.call_soon_threadsafe(self._set_rate_limit_wait, waiting)
        except RuntimeError:
            pass

    def _set_rate_limit_wait(self, waiting):
        count = getattr(self, '_api_wait_count', 0)
        if waiting:
            self._api_wait_count = count + 1
            if getattr(self, '_rate_limit_window', None):
                return
            try:
                native_app = self._impl.native
                if native_app.__class__.__module__.startswith('toga_textual'):
                    from toga_textual_backend import RateLimitScreen
                    screen = RateLimitScreen()
                    self._rate_limit_window = screen
                    native_app.push_screen(screen)
                else:
                    window = toga.Window(title='Waiting for TWiT API', size=(440, 220),
                                         closable=False, resizable=False, minimizable=False)
                    self._rate_limit_window = window
                    x, y = self.main_window.position
                    width, height = self.main_window.size
                    window.position = (x + (width - 440) // 2, y + (height - 220) // 2)
                    box = toga.Box(style=Pack(direction=COLUMN, margin=20))
                    box.add(toga.Label('Please wait.'))
                    indicator = toga.ActivityIndicator(style=Pack(margin=10, width=128, height=128, color='red'))
                    box.add(indicator)
                    window.content = box
                    native = window._impl.native
                    if hasattr(native, 'set_decorated'):
                        native.set_decorated(True)
                    if window._impl.__class__.__module__.startswith('toga_gtk'):
                        from toga_gtk.libs import Gtk
                        headerbar = getattr(window._impl, 'headerbar', None)
                        if headerbar is None:
                            headerbar = Gtk.HeaderBar()
                            if hasattr(headerbar, 'set_title'):
                                headerbar.set_title('Waiting for TWiT API')
                            native.set_titlebar(headerbar)
                        headerbar.set_decoration_layout(':')
                    if hasattr(native, 'set_transient_for'):
                        native.set_transient_for(self.main_window._impl.native)
                    if native.__class__.__module__.startswith('gi.repository') and hasattr(native, 'set_position'):
                        from toga_gtk.libs import Gtk
                        native.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
                    if hasattr(native, 'set_modal'):
                        native.set_modal(True)
                    window.show()
                    indicator.start()
            except Exception as e:
                _logger.warning(f"Unable to display API wait indicator: {e}")
        else:
            self._api_wait_count = max(0, count - 1)
            if self._api_wait_count:
                return
            window = getattr(self, '_rate_limit_window', None)
            self._rate_limit_window = None
            if window:
                try:
                    if hasattr(window, 'close_wait'):
                        window.close_wait()
                    else:
                        window.hide()
                        window.close()
                except Exception as e:
                    _logger.warning(f"Unable to close API wait indicator: {e}")

    def _next_episode_request(self):
        self._episode_request = getattr(self, '_episode_request', 0) + 1
        return self._episode_request

    def show_splash_screen(self, message: str = "Loading TwitTUI. Please wait...", title: str = "TWiT.tv TUI") -> None:
        """Display a splash screen modal or window informing the user what is happening."""
        if getattr(self, '_splash_window', None) is not None:
            try:
                if hasattr(self._splash_window, 'update_message'):
                    self._splash_window.update_message(message)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.show_splash_screen', exc_info=True)
            return

        try:
            native_app = getattr(getattr(self, '_impl', None), 'native', None)
            if native_app and native_app.__class__.__module__.startswith('toga_textual'):
                from toga_textual_backend import SplashScreen
                screen = SplashScreen(title=title, message=message)
                self._splash_window = screen
                native_app.push_screen(screen)
            elif hasattr(self, 'main_window') and self.main_window:
                window = toga.Window(
                    title=title,
                    size=(460, 220),
                    closable=False,
                    resizable=False,
                    minimizable=False
                )
                self._splash_window = window
                try:
                    x, y = self.main_window.position
                    width, height = self.main_window.size
                    window.position = (x + (width - 460) // 2, y + (height - 220) // 2)
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm.show_splash_screen', exc_info=True)
                box = toga.Box(style=Pack(direction=COLUMN, margin=20))
                box.add(toga.Label(title, style=Pack(margin=(0, 5))))
                box.add(toga.Label(message, style=Pack(margin=(5, 5))))
                indicator = toga.ActivityIndicator(style=Pack(margin=10, width=128, height=128, color='red'))
                box.add(indicator)
                window.content = box
                native = getattr(window, '_impl', None) and getattr(window._impl, 'native', None)
                if native:
                    if hasattr(native, 'set_decorated'):
                        native.set_decorated(True)
                    if window._impl.__class__.__module__.startswith('toga_gtk'):
                        from toga_gtk.libs import Gtk
                        headerbar = getattr(window._impl, 'headerbar', None)
                        if headerbar is None:
                            headerbar = Gtk.HeaderBar()
                            if hasattr(headerbar, 'set_title'):
                                headerbar.set_title(title)
                            native.set_titlebar(headerbar)
                        headerbar.set_decoration_layout(':')
                    if hasattr(native, 'set_transient_for') and hasattr(self.main_window, '_impl') and hasattr(self.main_window._impl, 'native'):
                        native.set_transient_for(self.main_window._impl.native)
                    if native.__class__.__module__.startswith('gi.repository') and hasattr(native, 'set_position'):
                        from toga_gtk.libs import Gtk
                        native.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
                    if hasattr(native, 'set_modal'):
                        native.set_modal(True)
                window.show()
                indicator.start()
        except Exception as e:
            _logger.warning(f"Unable to display splash screen: {e}")

    def close_splash_screen(self) -> None:
        """Dismiss the active splash screen window or modal."""
        window = getattr(self, '_splash_window', None)
        self._splash_window = None
        if window:
            try:
                if hasattr(window, 'close_splash'):
                    window.close_splash()
                elif hasattr(window, 'close_wait'):
                    window.close_wait()
                else:
                    window.hide()
                    window.close()
            except Exception as e:
                _logger.warning(f"Unable to close splash screen: {e}")

    def _refresh_catalog(self):
        self._catalog_request = getattr(self, '_catalog_request', 0) + 1
        token = self._catalog_request
        self._next_episode_request()
        if getattr(self, 'api_status_label', None):
            self.api_status_label.text = 'Loading shows; API rate limits may require a wait.'
        worker = self._network_snapshot()

        if getattr(self, '_catalog_wait_held', False):
            pass
        else:
            self._catalog_wait_held = True
            self._set_rate_limit_wait(True)

        pending = {'shows': True, 'episodes': True}
        catalog_released = False
        subtasks_started = False

        def check_finished(task):
            nonlocal catalog_released
            if token != getattr(self, '_catalog_request', 0):
                return
            pending[task] = False
            if not pending['shows'] and not pending['episodes'] and not catalog_released:
                catalog_released = True
                self.close_splash_screen()
                if getattr(self, '_catalog_wait_held', False):
                    self._catalog_wait_held = False
                    self._set_rate_limit_wait(False)

        def _release_catalog_if_unstarted():
            if not subtasks_started:
                check_finished('shows')
                check_finished('episodes')

        def done(shows):
            nonlocal subtasks_started
            if token != getattr(self, '_catalog_request', 0):
                return
            try:
                if shows is None:
                    shows = sorted(self.show_ids, key=str.casefold) if getattr(self, 'show_ids', None) else []
                self.show_ids = worker.show_ids
                self.show_active = getattr(worker, 'show_active', {})
                self.show_date_bounds = getattr(worker, 'show_date_bounds', {}) or {
                    name: self._show_date_cache.get(str(show_id), (None, None))
                    for name, show_id in self.show_ids.items()
                }
                if getattr(self, '_show_date_cache', None) is not None:
                    self._show_date_cache.update(getattr(worker, '_show_date_cache', {}))
                if getattr(worker, '_shows_cache', None) is not None:
                    self._shows_cache = getattr(worker, '_shows_cache', None)
                if getattr(self, 'api_status_label', None):
                    self.api_status_label.text = worker.api_status_label.text
                selection = self._selected_show_name()
                self._setting_catalog = True
                try:
                    self._set_show_selector_items(shows, selection)
                finally:
                    self._setting_catalog = False
                if not shows:
                    check_finished('shows')
                    check_finished('episodes')
                    return
                subtasks_started = True
                self.load_episodes_for_selected_show(callback=lambda: check_finished('episodes'))
                self._refresh_show_dates(token, shows, callback=lambda: check_finished('shows'))
            except Exception as e:
                _logger.warning(f"Error processing fetched show catalog: {e}")
                check_finished('shows')
                check_finished('episodes')

        def _safe_fetch_shows():
            try:
                return worker.fetch_shows()
            except Exception as e:
                _logger.warning(f"Unexpected error fetching shows: {e}")
                return None

        self._call_run_network(
            _safe_fetch_shows,
            done,
            on_finally=_release_catalog_if_unstarted,
        )

    def _format_show_option(self, show_name):
        first_date, last_date = self.show_date_bounds.get(show_name, (None, None))
        active = self.show_active.get(show_name)
        status = 'Active' if active is True else 'Ended' if active is False else 'Unknown'
        first_date = str(first_date or 'Unknown')[:10].ljust(10)
        last_date = str(last_date or 'Unknown')[:10].ljust(10)
        return f'{first_date} - {last_date}  {status:<7}  {show_name}'

    def _set_show_selector_items(self, shows, selected_show=None):
        self._show_names_by_display = {
            self._format_show_option(name): name for name in shows
        }
        self.show_combo.items = list(self._show_names_by_display)
        if selected_show in self.show_ids:
            self.show_combo.value = self._format_show_option(selected_show)

    def _selected_show_name(self):
        selected = self.show_combo.value if getattr(self, 'show_combo', None) else ''
        return getattr(self, '_show_names_by_display', {}).get(selected, selected or '')

    def _refresh_show_dates(self, token, shows, index=0, callback=None, max_concurrent=4):
        """Scrape missing show date bounds using bounded concurrency (up to ``max_concurrent`` in flight)."""
        if token != getattr(self, '_catalog_request', 0):
            return

        pending_shows: list[tuple[str, Any]] = []
        for show_name in shows[index:]:
            show_id = self.show_ids.get(show_name)
            cached = (
                self._show_date_cache.get(str(show_id))
                if show_id and getattr(self, '_show_date_cache', None) is not None
                else None
            )
            if cached and cached[1] is not None:
                current_start = self.show_date_bounds.get(show_name, (None, None))[0]
                self.show_date_bounds[show_name] = (current_start or cached[0], cached[1])
                continue
            if not show_id:
                continue
            if self.show_date_bounds.get(show_name, (None, None))[1] is not None:
                continue
            pending_shows.append((show_name, show_id))

        if not pending_shows:
            if callable(callback):
                callback()
            return

        concurrency = max(1, int(max_concurrent or 1))
        state = {
            'next_idx': 0,
            'in_flight': 0,
            'finished': False,
        }

        def _complete_if_done() -> None:
            if state['finished']:
                return
            if state['in_flight'] == 0 and state['next_idx'] >= len(pending_shows):
                state['finished'] = True
                if callable(callback):
                    callback()

        def _dispatch_next() -> None:
            if token != getattr(self, '_catalog_request', 0):
                return
            while state['in_flight'] < concurrency and state['next_idx'] < len(pending_shows):
                show_name, show_id = pending_shows[state['next_idx']]
                state['next_idx'] += 1
                state['in_flight'] += 1
                worker = self._network_snapshot()

                settled_box = [False]

                def _settle_job(settled=settled_box) -> None:
                    if settled[0]:
                        return
                    settled[0] = True
                    state['in_flight'] = max(0, state['in_flight'] - 1)
                    if token == getattr(self, '_catalog_request', 0):
                        _dispatch_next()
                        _complete_if_done()

                def done(bounds, current_name=show_name, current_id=show_id, settle=_settle_job):
                    try:
                        if token != getattr(self, '_catalog_request', 0):
                            return
                        if bounds:
                            current_start = self.show_date_bounds.get(current_name, (None, None))[0]
                            resolved_bounds = (current_start or bounds[0], bounds[1])
                            if getattr(self, '_show_date_cache', None) is not None:
                                self._show_date_cache[str(current_id)] = resolved_bounds
                            self.show_date_bounds[current_name] = resolved_bounds
                            selected = self._selected_show_name()
                            self._setting_catalog = True
                            try:
                                self._set_show_selector_items(shows, selected)
                            finally:
                                self._setting_catalog = False
                    finally:
                        settle()

                def _safe_fetch_bounds(target_id=show_id, w=worker):
                    try:
                        return w.fetch_show_date_bounds(target_id)
                    except Exception as e:
                        _logger.debug("Unexpected error fetching show date bounds for %s: %s", target_id, e, exc_info=True)
                        return None

                self._call_run_network(_safe_fetch_bounds, done, on_finally=_settle_job)
            _complete_if_done()

        _dispatch_next()

    def on_audio_only_toggle(self, widget=None) -> None:
        """Toggle Audio Only checkbox state, persist preference, and refresh displayed episodes."""
        if hasattr(self, 'audio_only_checkbox') and self.audio_only_checkbox:
            if hasattr(self.audio_only_checkbox, 'text'):
                if '☑' in self.audio_only_checkbox.text:
                    self.audio_only_checkbox.text = self.audio_only_checkbox.text.replace('☑', '☐')
                else:
                    self.audio_only_checkbox.text = self.audio_only_checkbox.text.replace('☐', '☑')
            elif hasattr(self.audio_only_checkbox, 'value'):
                self.audio_only_checkbox.value = not self.audio_only_checkbox.value

        is_audio = self.is_audio_only()
        if hasattr(self, 'audio_only_checkbox') and self.audio_only_checkbox:
            self.audio_only_checkbox.tooltip = "Currently showing audio-only feed. Click to switch to video feeds" if is_audio else "Currently showing video feeds. Click to switch to audio-only feed"

        val_str = '1' if is_audio else '0'
        os.environ['TWITAUDIOONLY'] = val_str
        self.save_env_setting('TWITAUDIOONLY', val_str)

        self.load_episodes_for_selected_show()

    def on_sort_order_toggle(self, widget=None) -> None:
        """Toggle between Descending and Ascending sort order and reload episodes from API."""
        if self.is_sort_ascending():
            self.sort_order_button.text = '▼ Descending'
            self.sort_order_button.tooltip = "Currently descending (newest first). Click to sort ascending (oldest first)"
        else:
            self.sort_order_button.text = '▲ Ascending'
            self.sort_order_button.tooltip = "Currently ascending (oldest first). Click to sort descending (newest first)"

        if (getattr(self, '_episodes_all_loaded', False) or getattr(self, '_episodes_backfilling', False)) and getattr(self, 'current_episodes', None):
            self.update_episodes_display()
        else:
            self.load_episodes_for_selected_show()

    def update_progress(self, current: float, total: float | None = None) -> None:
        """Thread-safe update of the progress bar value and maximum."""
        if not hasattr(self, 'progress_bar') or self.progress_bar is None:
            return

        def _update():
            try:
                if total is not None and total > 0:
                    if self.progress_bar.max != total:
                        self.progress_bar.max = float(total)
                    self.progress_bar.value = max(0.0, min(float(current), float(total)))
                else:
                    if self.progress_bar.max != 100.0:
                        self.progress_bar.max = 100.0
                    self.progress_bar.value = max(0.0, min(float(current), 100.0))
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.update_progress._update', exc_info=True)

        loop = getattr(self, 'loop', None)
        if threading.current_thread() is not threading.main_thread():
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(_update)
                except Exception:
                    _logger.debug("Dropped off-thread progress update because UI loop rejected scheduling", exc_info=True)
                return
            if isinstance(self.progress_bar, toga.Widget):
                _logger.debug("Skipped off-thread progress update without running UI loop")
                return
        elif loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(_update)
                return
            except Exception:
                _logger.debug("Falling back to direct UI-thread progress update", exc_info=True)
        _update()

    def reset_progress(self) -> None:
        """Reset progress bar to 0."""
        self.update_progress(0, 100)

    def startup(self) -> None:
        api_rate_limiter.wait_callback = self._rate_limit_wait_changed
        api_rate_limiter.rate_limit = self.get_rate_limit
        # Hover tracking state for episode metadata popup
        self._hover_timer = None
        self._hover_row_index = None
        self._dialog_open = False
        self._metadata_window = None
        self._hover_lock = threading.Lock()
        self._table_hover_connected = False
        self._gtk_maximize_handler_connected = False
        self._gtk_window_maximized = None

        # Main box with vertical layout
        main_box = toga.Box(style=Pack(direction=COLUMN, margin=5))

        # Show selection section
        show_label = toga.Label(
            'Show:',
            style=Pack(margin=(0, 5)),
            tooltip='Select which TWiT show to browse'
        )
        self.show_label = show_label
        self.api_status_label = toga.Label('', style=Pack(margin=(0, 5)))
        self.show_combo = toga.Selection(
            on_change=self.on_show_select,
            style=Pack(flex=1),
            tooltip='Choose a TWiT show from the list of available shows'
        )
        fetch_button = toga.Button(
            'Fetch',
            on_press=self.on_fetch_press,
            style=Pack(margin=5),
            tooltip='Fetch the latest episodes for the selected show'
        )
        self.fetch_button = fetch_button
        self.next_button = toga.Button(
            'Next',
            on_press=self.on_next_press,
            style=Pack(margin=5),
            tooltip='Load the next page of older episodes for the selected show'
        )
        show_box = toga.Box(style=Pack(direction=ROW, margin=5))
        show_box.add(show_label)
        show_box.add(self.show_combo)
        show_box.add(fetch_button)
        show_box.add(self.next_button)

        # Search section
        search_label = toga.Label(
            'Search:',
            style=Pack(margin=(0, 5)),
            tooltip='Filter episodes in the selected show'
        )
        self.search_label = search_label
        self.search_input = toga.TextInput(
            placeholder='Search episodes in selected show...',
            on_confirm=self.on_search_press,
            style=Pack(flex=1),
            tooltip='Enter search keywords or episode number to filter episodes'
        )
        search_button = toga.Button(
            'Search',
            on_press=self.on_search_press,
            style=Pack(margin=5),
            tooltip='Apply search filter to episode list'
        )
        self.search_button = search_button
        clear_button = toga.Button(
            'Clear',
            on_press=self.on_clear_search_press,
            style=Pack(margin=5),
            tooltip='Clear search input and restore all episodes'
        )
        self.clear_button = clear_button
        search_box = toga.Box(style=Pack(direction=ROW, margin=5))
        search_box.add(search_label)
        search_box.add(self.search_input)
        search_box.add(search_button)
        search_box.add(clear_button)

        # Sort options section
        sort_label = toga.Label(
            'Sort by:',
            style=Pack(margin=(0, 5)),
            tooltip='Choose criterion for sorting episodes'
        )
        self.sort_label = sort_label
        self.date_radio = toga.Button(
            '☑ Date',
            on_press=self.on_sort_button_press,
            style=Pack(margin=5),
            tooltip='Sort episodes by release date (active)'
        )
        self.episode_radio = toga.Button(
            '☐ Episode Number',
            on_press=self.on_sort_button_press,
            style=Pack(margin=5),
            tooltip='Sort episodes by episode number'
        )
        self.title_radio = toga.Button(
            '☐ Episode Title',
            on_press=self.on_sort_button_press,
            style=Pack(margin=5),
            tooltip='Sort episodes alphabetically by title'
        )
        self.length_radio = toga.Button(
            '☐ Length',
            on_press=self.on_sort_button_press,
            style=Pack(margin=5),
            tooltip='Sort episodes by duration/length'
        )
        self.size_radio = toga.Button(
            '☐ Size',
            on_press=self.on_sort_button_press,
            style=Pack(margin=5),
            tooltip='Sort episodes by file size'
        )
        self.sort_order_button = toga.Button(
            '▼ Descending',
            on_press=self.on_sort_order_toggle,
            style=Pack(margin=5),
            tooltip='Currently descending (newest first). Click to sort ascending (oldest first)'
        )

        env_audio = os.getenv('TWITAUDIOONLY') or os.getenv('twitaudioonly') or os.getenv('TWIT_AUDIO_ONLY') or ''
        initial_audio_only = env_audio.strip().lower() in ('1', 'true', 'yes', 'on')
        audio_symbol = '☑' if initial_audio_only else '☐'
        self.audio_only_checkbox = toga.Button(
            f'{audio_symbol} Audio Only',
            on_press=self.on_audio_only_toggle,
            style=Pack(margin=5),
            tooltip='Currently showing audio-only feed. Click to switch to video feeds' if initial_audio_only else 'Currently showing video feeds. Click to switch to audio-only feed'
        )

        sort_box = toga.Box(style=Pack(direction=ROW, margin=5))
        sort_box.add(sort_label)
        sort_box.add(self.date_radio)
        sort_box.add(self.episode_radio)
        sort_box.add(self.title_radio)
        sort_box.add(self.length_radio)
        sort_box.add(self.size_radio)
        sort_box.add(self.sort_order_button)
        sort_box.add(self.audio_only_checkbox)

        # Episodes list section
        episodes_label = toga.Label(
            'Episodes:',
            style=Pack(margin=(0, 5)),
            tooltip='Episodes available for streaming or downloading'
        )
        self.episodes_label = episodes_label
        self.episodes_list = toga.Table(
            columns=['Episode', 'Title', 'Date', 'Length', 'Size'],
            multiple_select=True,
            on_select=self.on_episode_select,
            on_activate=self.on_episode_activate,
            style=Pack(flex=1, margin=5),
            tooltip='Episode list: select episodes to download (Space / Shift+Arrows / Ctrl+A in TUI), or double-click / press Enter to stream'
        )
        self._enable_table_horizontal_scroll()
        self._setup_table_hover_events()

        self.episodes_list.data = []

        # Buttons section
        button_box = toga.Box(style=Pack(direction=ROW, margin=5))
        self.button_box = button_box
        download_button = toga.Button(
            'Download',
            on_press=self.on_download_press,
            style=Pack(margin=5),
            tooltip='Download selected episodes to destination directory'
        )
        self.download_button = download_button
        stream_button = toga.Button(
            'Stream',
            on_press=self.on_stream_press,
            style=Pack(margin=5),
            tooltip='Stream selected episode in external media player'
        )
        self.stream_button = stream_button
        preferences_button = toga.Button(
            'Preferences',
            on_press=self.on_preferences_press,
            style=Pack(margin=5),
            tooltip='Open application Preferences (F2 / Ctrl+P)'
        )
        self.preferences_button = preferences_button
        cancel_button = toga.Button(
            'Cancel',
            on_press=self.on_cancel_press,
            style=Pack(margin=5),
            tooltip='Cancel active download or exit application'
        )
        self.cancel_button = cancel_button
        close_button = toga.Button(
            'Close',
            on_press=self.on_close_press,
            style=Pack(margin=5),
            tooltip='Exit TwitTUI application'
        )
        self.close_button = close_button

        button_box.add(download_button)
        button_box.add(stream_button)
        if self._is_textual_app():
            button_box.add(preferences_button)
        button_box.add(cancel_button)
        button_box.add(close_button)

        self.settings_box = self._build_preferences_box()

        # Progress bar section at the bottom of the form
        self.progress_bar = toga.ProgressBar(
            max=100.0,
            value=0.0,
            style=Pack(margin=5),
            tooltip='Progress indicator for active download or operation'
        )

        # Add all components to main box
        main_box.add(show_box)
        main_box.add(self.api_status_label)
        main_box.add(search_box)
        main_box.add(sort_box)
        main_box.add(episodes_label)
        main_box.add(self.episodes_list)
        main_box.add(button_box)
        main_box.add(self.progress_bar)

        # Create main window
        self.main_window = toga.MainWindow(title='TWIT.tv TUI')
        self.main_window.content = main_box
        self._configure_gtk_episodes_layout()

        self.preferences_cmd = toga.Command(
            self.on_preferences_press,
            text='Preferences',
            group=toga.Group.APP,
            section=sys.maxsize - 1,
            tooltip='Open application Preferences'
        )
        self.commands.add(self.preferences_cmd)

        # Help Menu commands
        readme_cmd = toga.Command(
            self.on_open_readme,
            text='View README Documentation',
            tooltip='View TwitTUI documentation and usage guide',
            group=toga.Group.HELP,
            section=0,
            order=1
        )
        self.readme_cmd = readme_cmd
        apib_cmd = toga.Command(
            self.on_open_apib,
            text='View API Specification (twittv.apib)',
            tooltip='View TWiT API Blueprint specification',
            group=toga.Group.HELP,
            section=0,
            order=2
        )
        self.apib_cmd = apib_cmd
        api_key_cmd = toga.Command(
            self.on_open_api_key_url,
            text='Get TWiT API Key',
            tooltip='Open TWiT API developer portal in browser to obtain API key',
            group=toga.Group.HELP,
            section=0,
            order=3
        )
        self.api_key_cmd = api_key_cmd
        self.commands.add(readme_cmd)
        self.commands.add(apib_cmd)
        self.commands.add(api_key_cmd)

        self.main_window.show()
        self.show_splash_screen('Loading TwitTUI. Initializing show catalog and episodes...', title='TWiT.tv TUI')
        self._refresh_catalog()

    def _update_episodes_selection_label(self) -> None:
        """Update the Episodes header label with active multi-selection count."""
        label = getattr(self, 'episodes_label', None)
        table = getattr(self, 'episodes_list', None)
        if label is None or table is None:
            return
        try:
            native = getattr(getattr(table, '_impl', None), 'native', None)
            if native is not None and hasattr(native, '_marked_rows'):
                marked_count = len(native._marked_rows)
                label.text = f'Episodes ({marked_count} selected):' if marked_count > 0 else 'Episodes:'
                return
            sel = table.selection
            if isinstance(sel, (list, tuple, set)) and len(sel) > 1:
                label.text = f'Episodes ({len(sel)} selected):'
            else:
                label.text = 'Episodes:'
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm._update_episodes_selection_label', exc_info=True)

    def on_episode_select(self, widget=None, **kwargs) -> None:
        self._update_episodes_selection_label()

    async def on_episode_activate(self, widget, row, **kwargs) -> None:
        await self.on_stream_press(widget, target_row=row)

    async def on_stream_press(self, widget=None, target_row=None) -> None:
        """Process selected or explicitly activated episode for streaming."""
        try:
            self._cancel_hover_timer()
            if target_row is not None:
                selected_target = target_row
            else:
                selected = self.episodes_list.selection
                if not selected:
                    _logger.info("No episode selected for streaming")
                    return
                selected_target = selected[0] if isinstance(selected, list) else selected

            target = self._snapshot_episode(selected_target)
            is_audio = self.is_audio_only()
            worker = self._network_snapshot()
            token = getattr(self, '_episode_request', 0)
            stream_token = getattr(self, '_stream_request', 0) + 1
            self._stream_request = stream_token

            def stale():
                if stream_token != getattr(self, '_stream_request', 0):
                    return True
                if target_row is not None:
                    return token != getattr(self, '_episode_request', 0)
                current = self.episodes_list.selection
                current = current[0] if isinstance(current, list) and current else current
                return token != getattr(self, '_episode_request', 0) or current is not selected_target

            resolutions = await asyncio.to_thread(worker.get_available_resolutions, target, audio_only=is_audio)
            if stale():
                return
            target_title = getattr(target, 'title', str(target[1] if isinstance(target, (tuple, list)) and len(target) > 1 else 'Episode'))

            if len(resolutions) > 1:
                chosen_res = await self.prompt_resolution_choice(
                    title="Select Audio Stream" if is_audio else "Select Stream Resolution",
                    message=f"Multiple audio options available for '{target_title}'. Which format do you prefer to stream?" if is_audio else f"Multiple resolutions available for '{target_title}'. Which resolution do you prefer to stream?",
                    resolutions=resolutions
                )
                if not chosen_res:
                    _logger.info("Stream cancelled by user.")
                    return
                media_url = chosen_res.get('url')
            elif len(resolutions) == 1:
                media_url = resolutions[0].get('url')
            else:
                media_url = await asyncio.to_thread(worker.resolve_target_media_url, target, audio_only=is_audio)

            if stale():
                return

            if not media_url:
                _logger.warning("No media URL found for the selected episode")
                return

            resolved_media_url = await asyncio.to_thread(compat_attr('resolve_stream_url', resolve_stream_url), media_url)
            if stale():
                return

            if self.is_youtube_url(resolved_media_url) or self.is_youtube_url(media_url):
                target_yt_url = resolved_media_url if self.is_youtube_url(resolved_media_url) else media_url
                _logger.info("Opening YouTube video in browser: %s", safe_url_for_log(target_yt_url))
                try:
                    await asyncio.to_thread(self._open_browser_quietly, target_yt_url)
                except Exception as e:
                    _logger.warning("Error opening YouTube in browser (%s)", type(e).__name__)
                return

            streamer_template = self.streamer_input.value if getattr(self, 'streamer_input', None) and self.streamer_input.value else 'env LC_ALL=C vlc %f'
            sanitized_log_url = safe_url_for_log(resolved_media_url)
            _logger.info(f"Launching stream player for: {sanitized_log_url}")

            def _launch_stream():
                try:
                    stream_launcher = compat_attr('launch_stream_safe', launch_stream_safe)
                    sig = inspect.signature(stream_launcher)
                    if 'resolve' in sig.parameters:
                        return stream_launcher(streamer_template, resolved_media_url, resolve=False)
                except (TypeError, ValueError):
                    pass
                return compat_attr('launch_stream_safe', launch_stream_safe)(streamer_template, resolved_media_url)

            await asyncio.to_thread(_launch_stream)
        except Exception as e:
            _logger.warning("Error launching stream (%s)", type(e).__name__)

    def on_cancel_press(self, widget) -> None:
        self._cancel_hover_timer()
        if getattr(self, '_metadata_window', None) is not None:
            try:
                self._metadata_window.close()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_cancel_press', exc_info=True)
            self._metadata_window = None
        if getattr(self, '_is_downloading', False):
            _logger.info("Cancelling active download...")
            self._cancel_download = True
            self._terminate_active_download_proc()
            self.reset_progress()
        else:
            self._cleanup_resources_for_exit()
            self.show_splash_screen("Closing TwitTUI. Please wait...", title="TWiT.tv TUI")
            self.exit()

    def on_close_press(self, widget) -> None:
        self._cancel_hover_timer()
        self._cleanup_resources_for_exit()
        if getattr(self, '_metadata_window', None) is not None:
            try:
                self._metadata_window.close()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_close_press', exc_info=True)
            self._metadata_window = None
        if self._preferences_window is not None:
            try:
                self._preferences_window.on_close = None
                self._preferences_window.close()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_close_press', exc_info=True)
            self._preferences_window = None
        self.show_splash_screen("Closing TwitTUI. Please wait...", title="TWiT.tv TUI")
        if getattr(self, 'api_status_label', None):
            self.api_status_label.text = "Closing TwitTUI. Please wait..."
        if not self._is_textual_app():
            try:
                if sys.stdout and hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
                    builtins.print("\n======================================================================", flush=True)
                    builtins.print("  TwitTUI: Exiting, please wait...", flush=True)
                    builtins.print("======================================================================\n", flush=True)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_close_press', exc_info=True)

        def _do_exit():
            try:
                self.exit()
            except Exception:
                _logger.debug("Falling back to sys.exit(0) after exit() failure", exc_info=True)
                sys.exit(0)

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_later(0.05, _do_exit)
            except Exception:
                _logger.debug("Falling back to direct exit() after loop.call_later failure", exc_info=True)
                self.exit()
        else:
            self.exit()

    def _enable_table_horizontal_scroll(self) -> None:
        """Enable horizontal scrolling on the episodes table when titles or columns exceed available width."""
        if not hasattr(self, 'episodes_list') or not self.episodes_list:
            return

        impl = getattr(self.episodes_list, '_impl', None)
        if not impl:
            return

        # GTK backend: Configure Gtk.ScrolledWindow horizontal scrollbar policy to AUTOMATIC
        native = getattr(impl, 'native', None)
        if native and hasattr(native, 'set_policy'):
            try:
                from toga_gtk.libs import Gtk
                native.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            except Exception:
                _logger.debug("GTK PolicyType import failed; retrying with numeric scrollbar policy", exc_info=True)
                try:
                    native.set_policy(1, 1)  # 1 corresponds to PolicyType.AUTOMATIC in GTK3/4
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm._enable_table_horizontal_scroll', exc_info=True)

        # Cocoa / macOS backend
        if hasattr(impl, 'native') and hasattr(impl.native, 'setHasHorizontalScroller_'):
            try:
                impl.native.setHasHorizontalScroller_(True)
                if hasattr(impl.native, 'setAutohidesScrollers_'):
                    impl.native.setAutohidesScrollers_(True)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._enable_table_horizontal_scroll', exc_info=True)

    def _refresh_gtk_episodes_layout(self) -> bool:
        """Refresh main window layout so episodes_list fills available vertical height."""
        try:
            if getattr(self, 'episodes_list', None) is not None:
                if getattr(self.episodes_list.style, 'height', None) not in (None, 'none'):
                    del self.episodes_list.style.height
                if getattr(self.episodes_list.style, 'flex', 0) != 1:
                    self.episodes_list.style.flex = 1
            win = getattr(self, 'main_window', None)
            if win is not None and getattr(win, 'content', None) is not None:
                win.content.refresh()
                win_impl = getattr(win, '_impl', None)
                container = getattr(win_impl, 'container', None)
                if container is not None and hasattr(container, 'make_dirty'):
                    container.make_dirty(getattr(self.episodes_list, '_impl', None))
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm._refresh_gtk_episodes_layout', exc_info=True)
        return False

    def _on_gtk_window_state_event(self, widget, event=None) -> bool:
        """Handle GTK window maximize/unmaximize transitions to expand or restore episodes_list."""
        try:
            is_maximized = False
            if event is not None and hasattr(event, 'new_window_state'):
                from toga_gtk.libs import Gdk
                is_maximized = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
            elif hasattr(widget, 'is_maximized'):
                is_maximized = bool(widget.is_maximized())

            if getattr(self, '_gtk_window_maximized', None) != is_maximized:
                self._gtk_window_maximized = is_maximized
                self._refresh_gtk_episodes_layout()
                try:
                    from toga_gtk.libs import GLib
                    GLib.idle_add(self._refresh_gtk_episodes_layout)
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm._on_gtk_window_state_event', exc_info=True)
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm._on_gtk_window_state_event', exc_info=True)
        return False

    def _configure_gtk_episodes_layout(self) -> None:
        """Configure GTK table minimum height and window maximize handling so episodes_list fills vertical space."""
        if not getattr(self, 'episodes_list', None):
            return

        table_impl = getattr(self.episodes_list, '_impl', None)
        if not table_impl or not table_impl.__class__.__module__.startswith('toga_gtk'):
            return

        try:
            self.episodes_list._MIN_HEIGHT = 200
            table_impl.rehint()
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_gtk_episodes_layout', exc_info=True)

        native_scroller = getattr(table_impl, 'native', None)
        if native_scroller is not None:
            for method_name in ('set_vexpand', 'set_hexpand'):
                method = getattr(native_scroller, method_name, None)
                if callable(method):
                    try:
                        method(True)
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_gtk_episodes_layout', exc_info=True)

        win = getattr(self, 'main_window', None)
        win_impl = getattr(win, '_impl', None) if win else None
        if not win_impl:
            return

        container = getattr(win_impl, 'container', None)
        if container is not None:
            for method_name in ('set_vexpand', 'set_hexpand'):
                method = getattr(container, method_name, None)
                if callable(method):
                    try:
                        method(True)
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_gtk_episodes_layout', exc_info=True)

        native_win = getattr(win_impl, 'native', None)
        if native_win is not None and hasattr(native_win, 'connect') and not getattr(self, '_gtk_maximize_handler_connected', False):
            try:
                from toga_gtk.libs import GTK_VERSION
                if GTK_VERSION < (4, 0, 0):
                    native_win.connect('window-state-event', self._on_gtk_window_state_event)
                else:
                    native_win.connect('notify::maximized', self._on_gtk_window_state_event)
                self._gtk_maximize_handler_connected = True
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_gtk_episodes_layout', exc_info=True)

        if getattr(win, 'content', None) is not None:
            try:
                win.content.refresh()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._configure_gtk_episodes_layout', exc_info=True)

    def update_episodes_display(self) -> None:
        """Format and display current episodes based on selected sort order."""
        if not hasattr(self, 'episodes_list') or self.episodes_list is None:
            return

        self._cancel_hover_timer()

        if not self.current_episodes:
            self.episodes_list.data = []
            self._update_episodes_selection_label()
            self._enable_table_horizontal_scroll()
            self._setup_table_hover_events()
            return

        episodes = list(self.current_episodes)
        sort_by = 'date'
        if hasattr(self, 'episode_radio') and self.episode_radio and '☑' in self.episode_radio.text:
            sort_by = 'number'
        elif hasattr(self, 'title_radio') and self.title_radio and '☑' in self.title_radio.text:
            sort_by = 'title'
        elif hasattr(self, 'length_radio') and self.length_radio and '☑' in self.length_radio.text:
            sort_by = 'length'
        elif hasattr(self, 'size_radio') and self.size_radio and '☑' in self.size_radio.text:
            sort_by = 'size'

        is_asc = self.is_sort_ascending()
        if sort_by == 'date':
            episodes.sort(key=lambda x: str(x.get('date', '')), reverse=not is_asc)
        elif sort_by == 'number':
            def parse_num(val):
                num = val.get('number', 0)
                try:
                    return (0, int(num))
                except (ValueError, TypeError):
                    return (1, str(num))
            episodes.sort(key=parse_num, reverse=not is_asc)
        elif sort_by == 'title':
            episodes.sort(key=lambda x: str(x.get('title', '')), reverse=not is_asc)
        elif sort_by == 'length':
            def parse_len(val):
                raw = val.get('length') or val.get('duration') or val.get('runningTime') or val.get('running_time')
                if not raw and hasattr(self, 'extract_duration'):
                    raw = self.extract_duration(val)
                sec = self.parse_duration_to_seconds(raw)
                return (0, sec) if sec >= 0 else (1, str(raw or ''))
            episodes.sort(key=parse_len, reverse=not is_asc)
        elif sort_by == 'size':
            def parse_sz(val):
                raw = val.get('size') or val.get('file_size') or val.get('fileSize') or val.get('enclosure_length') or val.get('bytes')
                if not raw and hasattr(self, 'extract_size'):
                    raw = self.extract_size(val)
                b = self.parse_size_to_bytes(raw)
                return (0, b) if b >= 0 else (1, str(raw or ''))
            episodes.sort(key=parse_sz, reverse=not is_asc)

        table_data = []
        for episode in episodes:
            title = episode.get('title', 'Unknown Title')
            date = episode.get('date', 'Unknown Date')
            number = episode.get('number', 'Unknown Number')
            length = episode.get('length') or episode.get('duration') or self.extract_duration(episode) or ''
            formatted_length = self.format_duration(length) if length else ''
            size_val = episode.get('size') or episode.get('file_size') or episode.get('enclosure_length') or self.extract_size(episode) or ''
            formatted_size = self.format_file_size(size_val) if size_val else ''
            media_url = self.extract_media_url(episode) or episode.get('media_url') or ''
            row_dict = {
                'episode': str(number),
                'title': str(title),
                'date': str(date),
                'length': str(formatted_length),
                'duration': str(formatted_length),
                'size': str(formatted_size),
                'file_size': str(formatted_size),
                'media_url': media_url,
                'episode_data': episode
            }
            if isinstance(episode, dict) and '_search_match_context' in episode:
                row_dict['_search_match_context'] = episode['_search_match_context']
            elif hasattr(episode, '_search_match_context'):
                row_dict['_search_match_context'] = getattr(episode, '_search_match_context')
            table_data.append(row_dict)

        self.episodes_list.data = table_data
        self._update_episodes_selection_label()
        self._enable_table_horizontal_scroll()
        self._setup_table_hover_events()

    def on_search_press(self, widget=None) -> None:
        """Execute search query against selected show episodes and populate table with matches."""
        self._cancel_hover_timer()
        query = self.search_input.value.strip() if hasattr(self, 'search_input') and self.search_input and self.search_input.value else ''
        if not query:
            self.load_episodes_for_selected_show()
            return

        selected_show = self._selected_show_name()
        show_id = self.show_ids.get(selected_show) if hasattr(self, 'show_ids') and selected_show in self.show_ids else None

        token = self._next_episode_request()
        if getattr(self, '_search_catalog_show', None) == selected_show and getattr(self, '_search_catalog', None) is not None:
            self.current_page = 1
            self.current_episodes = rank_and_filter_episodes(
                self._search_catalog,
                query,
                fuzzy_enabled=self.is_fuzzy_search_enabled(),
                phonetic_enabled=self.is_phonetic_search_enabled()
            )
            self.update_episodes_display()
            return
        worker = self._network_snapshot()
        if getattr(self, '_search_catalog_show', None) != selected_show:
            worker.current_episodes = []

        def done(results):
            if token == self._episode_request and (self.search_input.value or '').strip() == query:
                self.current_page = 1
                self.current_episodes = rank_and_filter_episodes(
                    results,
                    query,
                    fuzzy_enabled=self.is_fuzzy_search_enabled(),
                    phonetic_enabled=self.is_phonetic_search_enabled()
                )
                self.update_episodes_display()

        def _safe_search():
            try:
                return worker.search_episodes(query, show_id=show_id, show_name=selected_show)
            except Exception as e:
                _logger.warning(f"Unexpected error searching episodes: {e}")
                return []

        self._call_run_network(_safe_search, done)

    def on_clear_search_press(self, widget=None) -> None:
        """Clear search input text and restore full episode catalog for selected show."""
        self._cancel_hover_timer()
        if hasattr(self, 'search_input') and self.search_input:
            self.search_input.value = ''
        selected_show = self._selected_show_name()
        if getattr(self, '_search_catalog_show', None) == selected_show and getattr(self, '_search_catalog', None) is not None:
            self._next_episode_request()
            self.current_page = 1
            self.current_episodes = list(self._search_catalog)
            self.update_episodes_display()
            return
        self.load_episodes_for_selected_show()

    def load_episodes_for_selected_show(self, callback=None) -> None:
        """Fetch and display episodes for currently selected show in the combo box.

        Loads page 1 immediately under the modal wait dialog so the UI unlocks
        right away, then asynchronously backfills any remaining pages in the
        background without blocking the UI behind a modal wait screen and with
        a single deferred SQLite persistence write.
        """
        self._cancel_hover_timer()
        token = self._next_episode_request()
        self.current_page = 1
        self._episodes_backfilling = False
        selected_show = self._selected_show_name()
        self._search_catalog = None
        self._search_catalog_show = None
        if selected_show and hasattr(self, 'show_ids') and selected_show in self.show_ids:
            show_id = self.show_ids[selected_show]
            show_id_key = str(show_id) if show_id is not None else ''
            worker = self._network_snapshot()

            held = False
            if not getattr(self, '_catalog_wait_held', False):
                held = True
                self._set_rate_limit_wait(True)

            persisted_box = [False]

            def _persist_worker_episodes() -> None:
                if persisted_box[0]:
                    return
                if (
                    show_id_key
                    and getattr(worker, '_episodes_from_api', False)
                    and isinstance(getattr(worker, '_episodes_cache', None), dict)
                    and show_id_key in worker._episodes_cache
                ):
                    try:
                        worker._save_to_persistent_cache(
                            'episodes', show_id_key, worker._episodes_cache[show_id_key]
                        )
                        persisted_box[0] = True
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm.load_episodes_for_selected_show._persist_worker_episodes', exc_info=True)

            def fetch_all():
                # Phase 1: fetch page 1 immediately; defer SQLite persistence across pages
                # so multi-page shows persist once instead of incurring O(N^2) write amplification.
                worker._defer_episodes_persist = True
                batch = []
                try:
                    if token == self._episode_request:
                        batch = worker.fetch_episodes(show_id, page=1) or []
                except Exception as e:
                    _logger.warning(f"Unexpected error loading episodes for show {show_id}: {e}")
                finally:
                    all_done = getattr(worker, '_episodes_all_loaded', False) or not batch or token != self._episode_request
                    if all_done:
                        worker._defer_episodes_persist = False
                        _persist_worker_episodes()
                return list(batch), 1

            released = False

            def _release_episode_wait() -> None:
                nonlocal released
                if released:
                    return
                released = True
                if held:
                    self._set_rate_limit_wait(False)
                if callable(callback):
                    callback()

            def _apply_episodes_to_ui(episodes_list: list, page_num: int) -> None:
                self.current_page = page_num
                self._triangulation_rss_fallback = getattr(worker, '_triangulation_rss_fallback', False)
                self._episodes_from_api = getattr(worker, '_episodes_from_api', False)
                self._episodes_all_loaded = getattr(worker, '_episodes_all_loaded', False)
                status = getattr(worker, '_episode_api_status', '')
                if getattr(self, 'api_status_label', None):
                    if status or self.api_status_label.text == getattr(self, '_episode_api_status', None):
                        self.api_status_label.text = status
                self._episode_api_status = status
                if hasattr(self, '_episodes_cache') and hasattr(worker, '_episodes_cache'):
                    self._episodes_cache.update(worker._episodes_cache)
                self.current_episodes = episodes_list
                if self._episodes_all_loaded:
                    self._search_catalog = list(episodes_list)
                    self._search_catalog_show = selected_show
                query = (self.search_input.value or '').strip() if getattr(self, 'search_input', None) else ''
                if query:
                    self.current_episodes = rank_and_filter_episodes(
                        episodes_list,
                        query,
                        fuzzy_enabled=self.is_fuzzy_search_enabled(),
                        phonetic_enabled=self.is_phonetic_search_enabled()
                    )
                self.update_episodes_display()

            def done_page_1(result):
                page1_episodes: list = []
                page_num = 1
                should_backfill = False
                try:
                    if token == self._episode_request:
                        if isinstance(result, tuple) and len(result) == 2:
                            page1_episodes, page_num = result
                        else:
                            page1_episodes, page_num = (result if isinstance(result, list) else []), 1
                        _apply_episodes_to_ui(list(page1_episodes), page_num)
                        should_backfill = bool(page1_episodes) and not self._episodes_all_loaded
                finally:
                    # Unlock the UI immediately after page 1 (never hold modal wait across multi-page backfill)
                    _release_episode_wait()

                if not should_backfill:
                    return

                self._episodes_backfilling = True

                def fetch_remaining():
                    extra_episodes = []
                    page = page_num + 1
                    last_batch = []
                    worker._defer_episodes_persist = True
                    try:
                        with api_rate_limiter.suppress_wait_notifications():
                            while token == self._episode_request:
                                last_batch = worker.fetch_episodes(show_id, page=page) or []
                                if not last_batch:
                                    break
                                extra_episodes.extend(last_batch)
                                if getattr(worker, '_episodes_all_loaded', False):
                                    break
                                page += 1
                    except Exception as e:
                        _logger.warning(f"Unexpected error backfilling episodes for show {show_id}: {e}")
                    finally:
                        worker._defer_episodes_persist = False
                        _persist_worker_episodes()
                    return extra_episodes, page if last_batch else max(page_num, page - 1)

                def _finish_backfill() -> None:
                    if token == self._episode_request:
                        self._episodes_backfilling = False
                    worker._defer_episodes_persist = False
                    _persist_worker_episodes()

                def done_remaining(rem_result):
                    try:
                        if token != self._episode_request:
                            return
                        if isinstance(rem_result, tuple) and len(rem_result) == 2:
                            extra_episodes, final_page = rem_result
                        else:
                            extra_episodes, final_page = (rem_result if isinstance(rem_result, list) else []), page_num
                        combined = list(page1_episodes)
                        seen_keys = {self._episode_cache_key(e) for e in combined if self._episode_cache_key(e) is not None}
                        for ep in (extra_episodes or []):
                            k = self._episode_cache_key(ep)
                            if not k or k not in seen_keys:
                                combined.append(ep)
                                if k:
                                    seen_keys.add(k)
                        _apply_episodes_to_ui(combined, final_page)
                    finally:
                        _finish_backfill()

                self._call_run_network(fetch_remaining, done_remaining, on_finally=_finish_backfill)

            self._call_run_network(fetch_all, done_page_1, on_finally=_release_episode_wait)
        else:
            self.current_episodes = []
            self.update_episodes_display()
            if callable(callback):
                callback()

    def on_show_select(self, widget) -> None:
        """Handle show selection change."""
        if getattr(self, '_setting_catalog', False):
            return
        self.current_page = 1
        self.load_episodes_for_selected_show()

    def on_fetch_press(self, widget) -> None:
        """Fetch episodes for the selected show and refresh the show list."""
        self._refresh_catalog()

    def on_next_press(self, widget) -> None:
        """Fetch the next page of episodes for the currently selected show."""
        selected_show = self._selected_show_name()
        if not selected_show or not hasattr(self, 'show_ids') or selected_show not in self.show_ids:
            return

        show_id = self.show_ids[selected_show]
        next_page = getattr(self, 'current_page', 1) + 1
        token = self._next_episode_request()
        worker = self._network_snapshot()
        self._set_rate_limit_wait(True)
        released = False

        def _release_next_wait() -> None:
            nonlocal released
            if released:
                return
            released = True
            self._set_rate_limit_wait(False)

        def done(episodes):
            try:
                if token != self._episode_request:
                    return
                self._episodes_all_loaded = getattr(worker, '_episodes_all_loaded', False)
                status = getattr(worker, '_episode_api_status', '')
                if getattr(self, 'api_status_label', None):
                    if status or self.api_status_label.text == getattr(self, '_episode_api_status', None):
                        self.api_status_label.text = status
                self._episode_api_status = status
                self._append_episode_page(token, next_page, episodes)
            finally:
                _release_next_wait()

        def _safe_fetch_next():
            try:
                return worker.fetch_episodes(show_id, page=next_page)
            except Exception as e:
                _logger.warning(f"Unexpected error fetching next episode page: {e}")
                return []

        self._call_run_network(_safe_fetch_next, done, on_finally=_release_next_wait)

    def _append_episode_page(self, token, next_page, new_episodes):
        if token != self._episode_request:
            return
        if new_episodes:
            self.current_page = next_page
            existing_keys = set()
            for ep in (self.current_episodes or []):
                ep_id = ep.get('id')
                clean_path = ep.get('cleanPath')
                num = ep.get('number')
                title = ep.get('title')
                if ep_id:
                    existing_keys.add(f"id:{ep_id}")
                if clean_path:
                    existing_keys.add(f"path:{clean_path}")
                if num or title:
                    existing_keys.add(f"nt:{num}:{title}")

            if self.current_episodes is None:
                self.current_episodes = []

            added_count = 0
            for ep in new_episodes:
                ep_id = ep.get('id')
                clean_path = ep.get('cleanPath')
                num = ep.get('number')
                title = ep.get('title')

                is_dup = False
                if ep_id and f"id:{ep_id}" in existing_keys:
                    is_dup = True
                elif clean_path and f"path:{clean_path}" in existing_keys:
                    is_dup = True
                elif (num or title) and f"nt:{num}:{title}" in existing_keys:
                    is_dup = True

                if not is_dup:
                    self.current_episodes.append(ep)
                    if ep_id:
                        existing_keys.add(f"id:{ep_id}")
                    if clean_path:
                        existing_keys.add(f"path:{clean_path}")
                    if num or title:
                        existing_keys.add(f"nt:{num}:{title}")
                    added_count += 1

            self.update_episodes_display()

    def on_sort_button_press(self, widget) -> None:
        """Handle radio button behavior for checkbox-like sort type buttons and reload from API."""
        if hasattr(self, 'date_radio') and self.date_radio:
            self.date_radio.text = self.date_radio.text.replace('☑', '☐')
        if hasattr(self, 'episode_radio') and self.episode_radio:
            self.episode_radio.text = self.episode_radio.text.replace('☑', '☐')
        if hasattr(self, 'title_radio') and self.title_radio:
            self.title_radio.text = self.title_radio.text.replace('☑', '☐')
        if hasattr(self, 'length_radio') and self.length_radio:
            self.length_radio.text = self.length_radio.text.replace('☑', '☐')
        if hasattr(self, 'size_radio') and self.size_radio:
            self.size_radio.text = self.size_radio.text.replace('☑', '☐')

        if hasattr(self, 'date_radio') and widget == self.date_radio:
            self.date_radio.text = self.date_radio.text.replace('☐', '☑')
        elif hasattr(self, 'episode_radio') and widget == self.episode_radio:
            self.episode_radio.text = self.episode_radio.text.replace('☐', '☑')
        elif hasattr(self, 'title_radio') and widget == self.title_radio:
            self.title_radio.text = self.title_radio.text.replace('☐', '☑')
        elif hasattr(self, 'length_radio') and widget == self.length_radio:
            self.length_radio.text = self.length_radio.text.replace('☐', '☑')
        elif hasattr(self, 'size_radio') and widget == self.size_radio:
            self.size_radio.text = self.size_radio.text.replace('☐', '☑')

        if hasattr(self, 'date_radio') and self.date_radio:
            self.date_radio.tooltip = "Sort episodes by release date" + (" (active)" if widget == self.date_radio else "")
        if hasattr(self, 'episode_radio') and self.episode_radio:
            self.episode_radio.tooltip = "Sort episodes by episode number" + (" (active)" if widget == self.episode_radio else "")
        if hasattr(self, 'title_radio') and self.title_radio:
            self.title_radio.tooltip = "Sort episodes alphabetically by title" + (" (active)" if widget == self.title_radio else "")
        if hasattr(self, 'length_radio') and self.length_radio:
            self.length_radio.tooltip = "Sort episodes by duration/length" + (" (active)" if widget == self.length_radio else "")
        if hasattr(self, 'size_radio') and self.size_radio:
            self.size_radio.tooltip = "Sort episodes by file size" + (" (active)" if widget == self.size_radio else "")

        if (getattr(self, '_episodes_all_loaded', False) or getattr(self, '_episodes_backfilling', False)) and getattr(self, 'current_episodes', None):
            self.update_episodes_display()
        else:
            self.load_episodes_for_selected_show()


def main() -> TwitTUIForm:
    """Create and return the TwitTUI application instance."""
    return TwitTUIForm('TWIT.tv TUI', 'org.beeware.twittui')
