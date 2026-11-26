"""Preferences window layout, cache controls, and settings event handlers."""

from __future__ import annotations

import os
import threading

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from twittui._compat import (
    _is_textual_tui_running,
    api_rate_limiter,
    compat_attr,
)
from twittui.logging_config import get_logger

_logger = get_logger("ui.preferences")


class PreferencesMixin:
    """Preferences window and configuration handler mixin for TwitTUIForm."""

    def _build_preferences_box(self) -> toga.Box:
        """Build the settings controls shown in the Preferences window."""
        settings_box = toga.Box(style=Pack(direction=COLUMN, margin=5))

        # TWIT API Application ID setting
        app_id_box = toga.Box(style=Pack(direction=ROW, margin=5))
        app_id_label = toga.Label(
            'API Application ID:',
            style=Pack(margin=(0, 5)),
            tooltip='TWiT API 3Scale Application ID'
        )
        self.app_id_label = app_id_label
        initial_app_id = os.getenv('TWITAPI_APPLICATIONID') or os.getenv('twitapi_applicationid') or ''
        self.app_id_input = toga.TextInput(
            value=initial_app_id,
            on_change=self.on_app_id_change,
            style=Pack(flex=1),
            tooltip='Enter your TWiT API Application ID from 3Scale developer portal'
        )
        app_id_box.add(app_id_label)
        app_id_box.add(self.app_id_input)

        # TWIT API Application Key setting
        app_key_box = toga.Box(style=Pack(direction=ROW, margin=5))
        app_key_label = toga.Label(
            'API Application Key:',
            style=Pack(margin=(0, 5)),
            tooltip='TWiT API 3Scale Application Key'
        )
        self.app_key_label = app_key_label
        initial_app_key = os.getenv('TWITAPI_APPLICATIONKEYS') or os.getenv('twitapi_applicationkeys') or ''
        self.app_key_input = toga.PasswordInput(
            value=initial_app_key,
            on_change=self.on_app_key_change,
            style=Pack(flex=1),
            tooltip='Enter your TWiT API Application Key (token) from 3Scale developer portal'
        )
        test_api_button = toga.Button(
            'Test API',
            on_press=self.on_test_api_press,
            style=Pack(margin=5),
            tooltip='Test TWiT API credentials and verify connection to TWiT API'
        )
        self.test_api_button = test_api_button
        app_key_box.add(app_key_label)
        app_key_box.add(self.app_key_input)
        app_key_box.add(test_api_button)

        # TWIT Club URL setting (preserve custom Memberful feed IDs if configured)
        url_box = toga.Box(style=Pack(direction=ROW, margin=5))
        url_label = toga.Label(
            'TWIT Club URL:',
            style=Pack(margin=(0, 5)),
            tooltip='Club TWiT Memberful RSS feed address or authentication key'
        )
        self.url_label = url_label
        default_auth_prefix = 'https://twit.memberfulcontent.com/rss/9041?auth='
        twit_club_url = (os.getenv('twitcluburl') or os.getenv('TWITCLUBURL') or os.getenv('TWIT_CLUB_URL') or '').strip()
        active_prefix = default_auth_prefix
        if twit_club_url.startswith(default_auth_prefix):
            initial_url_key = twit_club_url[len(default_auth_prefix):]
        elif '?auth=' in twit_club_url:
            prefix_part, initial_url_key = twit_club_url.split('?auth=', 1)
            if prefix_part.startswith('http://'):
                prefix_part = 'https://' + prefix_part[7:]
            if prefix_part.startswith('https://'):
                active_prefix = f"{prefix_part}?auth="
        else:
            initial_url_key = twit_club_url
        self._club_url_prefix = active_prefix
        url_prefix = toga.Label(
            active_prefix,
            style=Pack(margin=(0, 5)),
            tooltip='Club TWiT Memberful RSS feed base URL prefix'
        )
        self.url_prefix = url_prefix
        self.url_input = toga.PasswordInput(
            value=initial_url_key,
            on_change=self.on_url_change,
            style=Pack(flex=1),
            tooltip='Enter Club TWiT Memberful authentication key or complete RSS feed URL'
        )
        show_url_button = toga.Button(
            'Show',
            on_press=self.on_show_club_url_press,
            style=Pack(margin=5),
            tooltip='Open Club TWiT feed URL in browser or show feed info'
        )
        self.show_url_button = show_url_button
        url_box.add(url_label)
        url_box.add(url_prefix)
        url_box.add(self.url_input)
        url_box.add(show_url_button)

        # Destination folder setting
        dest_box = toga.Box(style=Pack(direction=ROW, margin=5))
        dest_label = toga.Label(
            'Download Destination:',
            style=Pack(margin=(0, 5)),
            tooltip='Directory where downloaded podcast media files will be stored'
        )
        self.dest_label = dest_label
        initial_dest = os.getenv('twitclubdestination') or os.getenv('TWITCLUBDESTINATION') or os.getenv('TWIT_CLUB_DESTINATION') or ''
        self.dest_input = toga.TextInput(
            value=initial_dest,
            on_change=self.on_dest_change,
            style=Pack(flex=1),
            tooltip='Path to destination directory for downloaded media files'
        )
        dest_button = toga.Button(
            'Browse',
            on_press=self.on_browse_press,
            style=Pack(margin=5),
            tooltip='Browse filesystem to choose download destination directory'
        )
        self.dest_button = dest_button
        dest_open_button = toga.Button(
            'Open',
            on_press=self.on_open_destination_press,
            style=Pack(margin=5),
            tooltip='Open download destination directory in system file manager'
        )
        self.dest_open_button = dest_open_button
        initial_show_folders = self.is_show_folders_enabled()
        self.show_folders_checkbox = toga.Switch(
            'Show Folders',
            value=initial_show_folders,
            on_change=self.on_show_folders_change,
            style=Pack(margin=5),
            tooltip='Automatically create subfolders named after each show when downloading'
        )
        dest_box.add(dest_label)
        dest_box.add(self.dest_input)
        dest_box.add(dest_button)
        dest_box.add(dest_open_button)
        dest_box.add(self.show_folders_checkbox)

        # Block size and Rate limit settings
        block_box = toga.Box(style=Pack(direction=ROW, margin=5))
        block_label = toga.Label(
            'Block Size:',
            style=Pack(margin=(0, 5)),
            tooltip='Download buffer chunk size in bytes'
        )
        self.block_label = block_label
        initial_block = os.getenv('twitclubblocksize') or os.getenv('TWITCLUBBLOCKSIZE') or '8192'
        self.block_input = toga.TextInput(
            value=initial_block,
            on_change=self.on_block_change,
            style=Pack(flex=1),
            tooltip='Download chunk buffer size in bytes (default: 8192)'
        )
        rate_limit_label = toga.Label(
            'Rate Limit:',
            style=Pack(margin=(0, 5)),
            tooltip='Maximum TWiT API calls per minute before throttling'
        )
        self.rate_limit_label = rate_limit_label
        initial_rate_limit = os.getenv('twitapiratelimit') or os.getenv('TWITAPIRATELIMIT') or os.getenv('twitclubratelimit') or os.getenv('TWITCLUBRATELIMIT') or os.getenv('TWIT_API_RATE_LIMIT') or '5'
        self.rate_limit_input = toga.TextInput(
            value=str(initial_rate_limit),
            on_change=self.on_rate_limit_change,
            style=Pack(flex=1),
            tooltip='Maximum TWiT API calls allowed per minute (default: 5)'
        )
        block_box.add(block_label)
        block_box.add(self.block_input)
        block_box.add(rate_limit_label)
        block_box.add(self.rate_limit_input)

        # Streamer setting
        streamer_box = toga.Box(style=Pack(direction=ROW, margin=5))
        streamer_label = toga.Label(
            'Streamer:',
            style=Pack(margin=(0, 5)),
            tooltip='Command-line template for media player to stream episodes'
        )
        self.streamer_label = streamer_label
        initial_streamer = self.get_initial_streamer_setting()
        self.streamer_input = toga.TextInput(
            value=initial_streamer,
            on_change=self.on_streamer_change,
            style=Pack(flex=1),
            tooltip="Media player launch command; %f is replaced with stream URL (e.g. 'env LC_ALL=C vlc %f')"
        )
        streamer_box.add(streamer_label)
        streamer_box.add(self.streamer_input)

        # Search matching options (Fuzzy Match & Phonetic Match)
        search_prefs_box = toga.Box(style=Pack(direction=ROW, margin=5))
        search_prefs_label = toga.Label(
            'Search Options:',
            style=Pack(margin=(0, 5)),
            tooltip='Configure tiered search matching algorithms and fallbacks'
        )
        self.search_prefs_label = search_prefs_label
        initial_fuzzy = self.is_fuzzy_search_enabled()
        self.fuzzy_search_checkbox = toga.Switch(
            'Fuzzy Match',
            value=initial_fuzzy,
            on_change=self.on_fuzzy_search_change,
            style=Pack(margin=5),
            tooltip='Enable ranked fuzzy/subsequence search to tolerate typos (e.g. ballacer -> ballecer)'
        )
        initial_phonetic = self.is_phonetic_search_enabled()
        self.phonetic_search_checkbox = toga.Switch(
            'Phonetic Match',
            value=initial_phonetic,
            on_change=self.on_phonetic_search_change,
            style=Pack(margin=5),
            tooltip='Enable Double Metaphone phonetic matching for sound-alike words'
        )
        search_prefs_box.add(search_prefs_label)
        search_prefs_box.add(self.fuzzy_search_checkbox)
        search_prefs_box.add(self.phonetic_search_checkbox)

        # Add all sections to settings box
        settings_box.add(app_id_box)
        settings_box.add(app_key_box)
        settings_box.add(url_box)
        settings_box.add(dest_box)
        settings_box.add(block_box)
        settings_box.add(streamer_box)
        settings_box.add(search_prefs_box)

        preferences_button_box = toga.Box(style=Pack(direction=ROW, margin=5))
        self.clear_cache_button = toga.Button(
            'Clear Cache',
            on_press=self.on_clear_cache_press,
            style=Pack(margin=5),
            tooltip='Clear all cached TWiT shows, episodes, and media metadata'
        )
        self.preferences_close_button = toga.Button(
            'Close',
            on_press=self.on_preferences_close_press,
            style=Pack(margin=5),
            tooltip='Close Preferences window'
        )
        preferences_button_box.add(self.clear_cache_button)
        preferences_button_box.add(self.preferences_close_button)
        settings_box.add(preferences_button_box)
        return settings_box

    def clear_cache(self) -> None:
        """Clear all cached data retrieved from the TWiT API or scraped from twit.tv."""
        from twittui.cache import _LazySQLiteEpisodesCache

        with self._cache_lock:
            self._next_episode_request()
            self._episodes_backfilling = False
            self._episodes_all_loaded = False
            self._episodes_from_api = False
            self._shows_cache = None
            self._show_date_cache = {}
            self._show_date_cache_ts = {}
            self.show_date_bounds = {}
            self._episodes_cache = _LazySQLiteEpisodesCache(getattr(self, '_cache_db_path', None))
            self._triangulation_archive_cache = {}
            self._episode_detail_cache = {}
            self._media_webpage_cache = {}
            self._api_search_cache = {}
            self._show_rss_cache = {}
            self._club_rss_cache = None
            self._memberful_feeds_cache = {}
            self._search_catalog = None
            self._search_catalog_show = None
            self._delete_from_persistent_cache()

    def on_clear_cache_press(self, widget=None) -> None:
        """Handler for Clear Cache button in Preferences window."""
        self.clear_cache()
        if getattr(self, 'api_status_label', None) is not None:
            try:
                self.api_status_label.text = 'Cache cleared.'
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_clear_cache_press', exc_info=True)
        if compat_attr('_is_textual_tui_running', _is_textual_tui_running)(self):
            try:
                native_app = getattr(getattr(self, '_impl', None), 'native', None)
                if native_app is not None and hasattr(native_app, 'notify'):
                    native_app.notify('Cache cleared.')
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_clear_cache_press', exc_info=True)

    def on_preferences_press(self, widget=None) -> None:
        self.show_preferences_window()

    def show_preferences_window(self) -> None:
        if self._preferences_window is not None and getattr(self._preferences_window, 'closed', False):
            self._preferences_window = None
        if self._preferences_window is None:
            self._preferences_window = toga.Window(
                title='Preferences',
                size=(900, 400),
                on_close=self.on_preferences_window_close
            )
            self._preferences_window.content = self.settings_box
            try:
                window_impl = self._preferences_window._impl
                if window_impl.__class__.__module__.startswith('toga_gtk'):
                    native = window_impl.native
                    if hasattr(native, 'set_modal'):
                        native.set_modal(True)
                    if hasattr(native, 'set_transient_for'):
                        native.set_transient_for(self.main_window._impl.native)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.show_preferences_window', exc_info=True)
        self._preferences_window.show()

    def on_preferences_window_close(self, window, *args, **kwargs) -> bool:
        self._flush_pending_env_saves()
        window.hide()
        return True

    def on_preferences_close_press(self, widget=None) -> None:
        self._flush_pending_env_saves()
        if self._preferences_window is not None:
            self._preferences_window.hide()

    def on_fuzzy_search_change(self, widget=None) -> None:
        """Handle fuzzy search preference change."""
        val = self.is_fuzzy_search_enabled()
        val_str = '1' if val else '0'
        os.environ['TWITFUZZYSEARCH'] = val_str
        self.save_env_setting('TWITFUZZYSEARCH', val_str)

    def on_fuzzy_search_toggle(self, widget=None) -> None:
        """Toggle fuzzy search preference."""
        if hasattr(self, 'fuzzy_search_checkbox') and self.fuzzy_search_checkbox:
            if hasattr(self.fuzzy_search_checkbox, 'value'):
                self.fuzzy_search_checkbox.value = not self.fuzzy_search_checkbox.value
            elif hasattr(self.fuzzy_search_checkbox, 'text'):
                if '☑' in self.fuzzy_search_checkbox.text:
                    self.fuzzy_search_checkbox.text = self.fuzzy_search_checkbox.text.replace('☑', '☐')
                else:
                    self.fuzzy_search_checkbox.text = self.fuzzy_search_checkbox.text.replace('☐', '☑')
            self.on_fuzzy_search_change()
        else:
            val = not self.is_fuzzy_search_enabled()
            val_str = '1' if val else '0'
            os.environ['TWITFUZZYSEARCH'] = val_str
            self.save_env_setting('TWITFUZZYSEARCH', val_str)

    def on_phonetic_search_change(self, widget=None) -> None:
        """Handle phonetic search preference change."""
        val = self.is_phonetic_search_enabled()
        val_str = '1' if val else '0'
        os.environ['TWITPHONETICSEARCH'] = val_str
        self.save_env_setting('TWITPHONETICSEARCH', val_str)

    def on_phonetic_search_toggle(self, widget=None) -> None:
        """Toggle phonetic search preference."""
        if hasattr(self, 'phonetic_search_checkbox') and self.phonetic_search_checkbox:
            if hasattr(self.phonetic_search_checkbox, 'value'):
                self.phonetic_search_checkbox.value = not self.phonetic_search_checkbox.value
            elif hasattr(self.phonetic_search_checkbox, 'text'):
                if '☑' in self.phonetic_search_checkbox.text:
                    self.phonetic_search_checkbox.text = self.phonetic_search_checkbox.text.replace('☑', '☐')
                else:
                    self.phonetic_search_checkbox.text = self.phonetic_search_checkbox.text.replace('☐', '☑')
            self.on_phonetic_search_change()
        else:
            val = not self.is_phonetic_search_enabled()
            val_str = '1' if val else '0'
            os.environ['TWITPHONETICSEARCH'] = val_str
            self.save_env_setting('TWITPHONETICSEARCH', val_str)

    def on_show_folders_change(self, widget=None) -> None:
        """Handle toggling the Show Folders checkbox."""
        is_enabled = self.is_show_folders_enabled()
        val_str = '1' if is_enabled else '0'
        os.environ['TWITCLUBSHOWFOLDERS'] = val_str
        self.save_env_setting('TWITCLUBSHOWFOLDERS', val_str)

    def on_streamer_change(self, widget=None) -> None:
        """Handle streamer template change, update environment, and persist to .env."""
        val = self.streamer_input.value if hasattr(self, 'streamer_input') and self.streamer_input else ''
        val_str = (val or '').strip()
        if not val_str:
            val_str = self._default_streamer_template()
        os.environ['twitclubstreamer'] = val_str
        os.environ['TWITCLUBSTREAMER'] = val_str
        self._schedule_env_save('twitclubstreamer', val_str)

    def on_dest_change(self, widget=None) -> None:
        """Handle download destination change, update environment, and persist to .env."""
        val = self.dest_input.value if hasattr(self, 'dest_input') and self.dest_input else ''
        val_str = (val or '').strip()
        os.environ['twitclubdestination'] = val_str
        os.environ['TWITCLUBDESTINATION'] = val_str
        self._schedule_env_save('twitclubdestination', val_str)

    def on_block_change(self, widget=None) -> None:
        """Handle block size change, validate positive integer, update environment, and persist to .env."""
        val = self.block_input.value if hasattr(self, 'block_input') and self.block_input else ''
        val_str = (val or '').strip()
        if not val_str:
            return
        try:
            parsed = int(val_str)
        except (ValueError, TypeError):
            return
        if parsed <= 0:
            return
        normalized = str(parsed)
        os.environ['twitclubblocksize'] = normalized
        os.environ['TWITCLUBBLOCKSIZE'] = normalized
        self._schedule_env_save('twitclubblocksize', normalized)

    def on_rate_limit_change(self, widget=None) -> None:
        """Handle rate limit change, validate positive integer, update environment, and persist to .env."""
        val = self.rate_limit_input.value if hasattr(self, 'rate_limit_input') and self.rate_limit_input else ''
        val_str = (val or '').strip()
        if val_str:
            try:
                parsed = int(val_str)
            except (ValueError, TypeError):
                return
            if parsed <= 0:
                return
            normalized = str(parsed)
            os.environ['twitapiratelimit'] = normalized
            os.environ['TWITAPIRATELIMIT'] = normalized
            self._schedule_env_save('twitapiratelimit', normalized)
        try:
            # Keep api_rate_limiter.rate_limit bound to the callable getter rather than freezing an int
            api_rate_limiter.rate_limit = self.get_rate_limit
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_rate_limit_change', exc_info=True)

    def on_app_id_change(self, widget=None) -> None:
        """Handle TWiT API App ID change, update environment, and persist to .env."""
        val = self.app_id_input.value if hasattr(self, 'app_id_input') and self.app_id_input else ''
        val_str = (val or '').strip()
        os.environ['TWITAPI_APPLICATIONID'] = val_str
        self._schedule_env_save('TWITAPI_APPLICATIONID', val_str)

    def on_app_key_change(self, widget=None) -> None:
        """Handle TWiT API App Key change, update environment, and persist to .env."""
        val = self.app_key_input.value if hasattr(self, 'app_key_input') and self.app_key_input else ''
        val_str = (val or '').strip()
        os.environ['TWITAPI_APPLICATIONKEYS'] = val_str
        self._schedule_env_save('TWITAPI_APPLICATIONKEYS', val_str)

    def on_url_change(self, widget=None) -> None:
        """Handle TWiT Club URL change, preserving custom feed IDs, updating env, and persisting to .env."""
        val = self.url_input.value if hasattr(self, 'url_input') and self.url_input else ''
        val_str = (val or '').strip()
        auth_prefix = getattr(self, '_club_url_prefix', None) or 'https://twit.memberfulcontent.com/rss/9041?auth='
        if not val_str:
            full_url = ''
        elif val_str.startswith('http://') or val_str.startswith('https://'):
            full_url = ('https://' + val_str[7:]) if val_str.startswith('http://') else val_str
            if '?auth=' in full_url:
                new_prefix = full_url.split('?auth=', 1)[0] + '?auth='
                self._club_url_prefix = new_prefix
                if getattr(self, 'url_prefix', None) is not None:
                    try:
                        self.url_prefix.text = new_prefix
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm.on_url_change', exc_info=True)
        else:
            full_url = f"{auth_prefix}{val_str}"
        os.environ['twitcluburl'] = full_url
        os.environ['TWITCLUBURL'] = full_url
        self._schedule_env_save('twitcluburl', full_url)

    async def on_browse_press(self, widget) -> None:
        """Handle folder selection for download destination."""
        try:
            initial_dir = self.dest_input.value if self.dest_input.value and os.path.isdir(self.dest_input.value) else None
            host_win = self._active_dialog_window()
            if not host_win:
                return
            selected_folder = await host_win.dialog(
                toga.SelectFolderDialog(
                    title="Select Download Destination",
                    initial_directory=initial_dir
                )
            )
            if selected_folder is not None:
                self.dest_input.value = str(selected_folder)
        except Exception as e:
            _logger.warning(f"Error selecting folder: {e}")

    def show_api_test_dialog(self, success: bool, message: str) -> None:
        """Display a modal dialog indicating whether the TWiT API credentials test passed or failed."""
        title = "TWiT API Test: Passed" if success else "TWiT API Test: Failed"
        kind = "info" if success else "error"
        self._show_dialog_threadsafe(kind, title, message)

    def on_test_api_press(self, widget=None) -> None:
        """Handler for Test API button press."""
        app_id = self.get_api_app_id()
        app_key = self.get_api_app_key()

        def _worker():
            success, msg = self.test_api_credentials(app_id, app_key)
            self.show_api_test_dialog(success, msg)

        threading.Thread(target=_worker, daemon=True).start()
