"""Configuration, URL constants, and secure file-persistence helpers for TwitTUI."""

from __future__ import annotations

import os
from dotenv import find_dotenv, load_dotenv, set_key
import tempfile
import threading
import urllib.parse

from twittui._compat import PROJECT_ROOT, compat_attr

from twittui.logging_config import get_logger

_logger = get_logger("config")

# TWiT API Documentation URLs
TWIT_API_KEY_URL = "https://apidocs.twit.tv/"
TWIT_API_DOCS_URL = "https://apidocs.twit.tv/"

# TwitTUI Project Homepage URL
TWITTUI_HOMEPAGE_URL = "https://github.com/mainmeister/twittui"


def load_twittui_dotenv(base_dir: str | None = None) -> None:
    """Load environment variables from ``.env`` with ``override=True``.

    Resolution order:
    1. ``$SNAP_USER_DATA/.env`` or ``$SNAP_USER_COMMON/.env`` when running in a Snap.
    2. Nearest ``.env`` discovered from the current working directory.
    3. ``.env`` located alongside the application root directory.
    4. Default ``python-dotenv`` discovery.
    """
    try:
        dotenv_path: str | None = None
        snap_data = os.environ.get("SNAP_USER_DATA") or os.environ.get("SNAP_USER_COMMON")
        if snap_data:
            snap_env = os.path.join(snap_data, ".env")
            if os.path.exists(snap_env):
                dotenv_path = snap_env
        if not dotenv_path:
            dotenv_path = find_dotenv(usecwd=True) or None
        if not dotenv_path:
            root_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidate = os.path.join(root_dir, ".env")
            if os.path.exists(candidate):
                dotenv_path = candidate
        if dotenv_path:
            load_dotenv(dotenv_path, override=True)
        else:
            load_dotenv(override=True)
    except OSError:
        _logger.debug("Fallback dotenv load triggered after OSError", exc_info=True)
        load_dotenv(override=True)


def write_restricted_file(file_path: str, content: str) -> None:
    """Write sensitive content to disk with owner-only (``0o600``) permissions."""
    flags: int = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd: int = os.open(file_path, flags, 0o600)
    fd_owned: bool = True
    try:
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            else:
                os.chmod(file_path, 0o600)
        except OSError:
            try:
                os.chmod(file_path, 0o600)
            except OSError:
                _logger.debug("Unable to tighten permissions on %s", file_path, exc_info=True)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd_owned = False
        with handle:
            handle.write(content)
    finally:
        if fd_owned:
            try:
                os.close(fd)
            except OSError:
                _logger.debug("Unable to close file descriptor %d for %s", fd, file_path, exc_info=True)


class ConfigMixin:
    """Configuration, settings, and debounced .env persistence mixin for TwitTUIForm."""

    def _schedule_env_save(self, key: str, value: str, delay: float = 0.35) -> None:
        """Debounce rapid .env writes on interactive UI loops while remaining immediate in sync tests."""
        last_saved = getattr(self, '_last_saved_env', None)
        if isinstance(last_saved, dict) and last_saved.get(key) == value:
            pending = getattr(self, '_pending_env_saves', None)
            if isinstance(pending, dict):
                pending.pop(key, None)
            return
        loop = getattr(self, 'loop', None)
        instance_overridden = 'save_env_setting' in getattr(self, '__dict__', {})
        if (
            delay > 0
            and not instance_overridden
            and loop is not None
            and loop.is_running()
            and threading.current_thread() is threading.main_thread()
        ):
            pending = getattr(self, '_pending_env_saves', None)
            if not isinstance(pending, dict):
                pending = {}
                self._pending_env_saves = pending
            pending[key] = value
            timer = getattr(self, '_env_save_timer', None)
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm._schedule_env_save', exc_info=True)
            try:
                self._env_save_timer = loop.call_later(delay, self._flush_pending_env_saves)
                return
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._schedule_env_save', exc_info=True)
        self.save_env_setting(key, value)
        if isinstance(last_saved, dict):
            last_saved[key] = value

    def _flush_pending_env_saves(self) -> None:
        """Immediately persist any debounced .env updates."""
        timer = getattr(self, '_env_save_timer', None)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm._flush_pending_env_saves', exc_info=True)
            self._env_save_timer = None
        pending = getattr(self, '_pending_env_saves', None)
        if not isinstance(pending, dict) or not pending:
            return
        items = list(pending.items())
        pending.clear()
        last_saved = getattr(self, '_last_saved_env', None)
        for k, v in items:
            try:
                self.save_env_setting(k, v)
                if isinstance(last_saved, dict):
                    last_saved[k] = v
            except Exception as e:
                _logger.warning(f"Error flushing setting {k} to .env: {e}")

    @staticmethod
    def _default_streamer_template() -> str:
        """Prefer the bundled mpv in a strict Snap, regardless of host VLC visibility."""
        snap_root = os.environ.get('SNAP')
        if snap_root:
            bundled_mpv_paths = (
                os.path.join(snap_root, 'usr', 'bin', 'mpv'),
                os.path.join(snap_root, 'bin', 'mpv'),
            )
            if any(os.access(path, os.X_OK) for path in bundled_mpv_paths):
                return 'mpv %f'
        return 'env LC_ALL=C vlc %f'

    def get_initial_streamer_setting(self) -> str:
        """Resolve and migrate streamer command template, persisting if migrating legacy defaults."""
        raw = os.getenv('twitclubstreamer')
        if raw is None or not raw.strip():
            raw = os.getenv('TWITCLUBSTREAMER')
        if raw is None or not raw.strip():
            raw = os.getenv('TWIT_CLUB_STREAMER')
        val = (raw or '').strip()
        default_tpl = self._default_streamer_template()
        if (
            not val
            or val in ('vlc {url}', 'vlc %f', 'vlc', '{url}', '%f')
            or (default_tpl == 'mpv %f' and val == 'env LC_ALL=C vlc %f')
        ):
            val = default_tpl
            self.save_env_setting('twitclubstreamer', val)
        os.environ['twitclubstreamer'] = val
        os.environ['TWITCLUBSTREAMER'] = val
        return val

    def is_audio_only(self) -> bool:
        """Return True if Audio Only checkbox is enabled."""
        if hasattr(self, 'audio_only_checkbox') and self.audio_only_checkbox:
            if hasattr(self.audio_only_checkbox, 'text'):
                return '☑' in self.audio_only_checkbox.text
            if hasattr(self.audio_only_checkbox, 'value'):
                return bool(self.audio_only_checkbox.value)
        env_audio = os.getenv('TWITAUDIOONLY') or os.getenv('twitaudioonly') or os.getenv('TWIT_AUDIO_ONLY') or ''
        return env_audio.strip().lower() in ('1', 'true', 'yes', 'on')

    def save_env_setting(self, key: str, value: str) -> None:
        """Persist a configuration setting key-value pair to the .env file with restricted permissions."""
        snap_data = os.environ.get('SNAP_USER_DATA') or os.environ.get('SNAP_USER_COMMON')
        if not snap_data:
            app_id = getattr(self, 'app_id', '') or ''
            if app_id == 'org.twit.test' or app_id.startswith('org.twit.test.'):
                _logger.debug("Skipping .env write for isolated test app_id=%s (%s)", app_id, key)
                return
        if snap_data:
            try:
                os.makedirs(snap_data, exist_ok=True)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.save_env_setting', exc_info=True)
            target_path = os.path.join(snap_data, '.env')
        else:
            candidate_paths = [
                os.path.join(PROJECT_ROOT, '.env'),
                os.path.join(os.getcwd(), '.env'),
                os.path.abspath('.env')
            ]
            target_path = None
            for path in candidate_paths:
                if os.path.isfile(path) and os.access(path, os.W_OK):
                    target_path = path
                    break
            if not target_path:
                for path in candidate_paths:
                    parent = os.path.dirname(path) or '.'
                    if os.path.exists(parent) and os.access(parent, os.W_OK):
                        target_path = path
                        break
            if not target_path:
                target_path = candidate_paths[0]

        try:
            compat_attr('set_key', set_key)(target_path, key, str(value))
            if os.path.exists(target_path):
                try:
                    os.chmod(target_path, 0o600)
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm.save_env_setting', exc_info=True)
        except Exception:
            _logger.debug("dotenv.set_key failed for %s; falling back to restricted file write", key, exc_info=True)
            try:
                lines = []
                if os.path.exists(target_path):
                    with open(target_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                found = False
                for i, line in enumerate(lines):
                    if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key.lower()}="):
                        lines[i] = f"{key}={value}\n"
                        found = True
                        break
                if not found:
                    lines.append(f"{key}={value}\n")
                compat_attr("write_restricted_file", write_restricted_file)(target_path, "".join(lines))
            except Exception as e:
                _logger.warning(f"Warning: Could not save {key} to {target_path}: {e}")

    def is_fuzzy_search_enabled(self) -> bool:
        """Return True if Fuzzy Match search preference is enabled."""
        if hasattr(self, 'fuzzy_search_checkbox') and self.fuzzy_search_checkbox:
            if hasattr(self.fuzzy_search_checkbox, 'value'):
                return bool(self.fuzzy_search_checkbox.value)
            if hasattr(self.fuzzy_search_checkbox, 'text'):
                return '☑' in self.fuzzy_search_checkbox.text
        env_val = os.getenv('TWITFUZZYSEARCH') or os.getenv('twitfuzzysearch') or os.getenv('TWIT_FUZZY_SEARCH')
        if env_val is None:
            return True
        return env_val.strip().lower() in ('1', 'true', 'yes', 'on')

    def is_phonetic_search_enabled(self) -> bool:
        """Return True if Phonetic Match search preference is enabled."""
        if hasattr(self, 'phonetic_search_checkbox') and self.phonetic_search_checkbox:
            if hasattr(self.phonetic_search_checkbox, 'value'):
                return bool(self.phonetic_search_checkbox.value)
            if hasattr(self.phonetic_search_checkbox, 'text'):
                return '☑' in self.phonetic_search_checkbox.text
        env_val = os.getenv('TWITPHONETICSEARCH') or os.getenv('twitphoneticsearch') or os.getenv('TWIT_PHONETIC_SEARCH')
        if env_val is None:
            return True
        return env_val.strip().lower() in ('1', 'true', 'yes', 'on')

    def is_sort_ascending(self) -> bool:
        """Return True if Ascending sort order is selected, False if Descending."""
        if hasattr(self, 'sort_order_button') and self.sort_order_button:
            if hasattr(self.sort_order_button, 'text'):
                return 'Ascending' in self.sort_order_button.text or '▲' in self.sort_order_button.text
        return False

    def get_current_sort_param(self) -> str:
        """Determine API sort query parameter based on UI sort selection and direction."""
        is_asc = self.is_sort_ascending()
        sort_by = 'date'
        if hasattr(self, 'episode_radio') and self.episode_radio and '☑' in self.episode_radio.text:
            sort_by = 'number'
        elif hasattr(self, 'title_radio') and self.title_radio and '☑' in self.title_radio.text:
            sort_by = 'title'
        elif hasattr(self, 'length_radio') and self.length_radio and '☑' in self.length_radio.text:
            sort_by = 'length'
        elif hasattr(self, 'size_radio') and self.size_radio and '☑' in self.size_radio.text:
            sort_by = 'size'

        if sort_by == 'date':
            field = 'airingDate'
        elif sort_by == 'number':
            field = 'episodeNumber'
        elif sort_by == 'title':
            field = 'label'
        elif sort_by in ('length', 'size'):
            return None
        else:
            field = 'airingDate'

        return field if is_asc else f"-{field}"

    def get_api_app_id(self) -> str:
        """Get the configured TWiT API Application ID from input or environment variable."""
        val = self.app_id_input.value if hasattr(self, 'app_id_input') and self.app_id_input and self.app_id_input.value else ''
        if not val:
            val = os.getenv('TWITAPI_APPLICATIONID') or os.getenv('twitapi_applicationid') or os.getenv('TWIT_API_APPLICATION_ID') or ''
        return val.strip()

    def get_api_app_key(self) -> str:
        """Get the configured TWiT API Application Key from input or environment variable."""
        val = self.app_key_input.value if hasattr(self, 'app_key_input') and self.app_key_input and self.app_key_input.value else ''
        if not val:
            val = os.getenv('TWITAPI_APPLICATIONKEYS') or os.getenv('twitapi_applicationkeys') or os.getenv('TWIT_API_APPLICATION_KEYS') or os.getenv('TWITAPI_APPLICATIONKEY') or ''
        return val.strip()

    def get_club_twit_auth_key(self) -> str:
        """Extract the unique authorization key from the Club TWiT configuration."""
        url_val = self.url_input.value if hasattr(self, 'url_input') and self.url_input and self.url_input.value else ''
        if not url_val:
            url_val = os.getenv('twitcluburl') or os.getenv('TWITCLUBURL') or os.getenv('TWIT_CLUB_URL') or ''

        url_val = url_val.strip()
        if not url_val:
            return ''

        if '?auth=' in url_val:
            return url_val.split('?auth=', 1)[1].strip()
        elif url_val.startswith('http://') or url_val.startswith('https://'):
            parsed = urllib.parse.urlparse(url_val)
            query = urllib.parse.parse_qs(parsed.query)
            if 'auth' in query and query['auth']:
                return query['auth'][0].strip()
        return url_val

    def get_club_twit_rss_url(self, feed_id: int | str = 9041) -> str:
        """Construct the full Club TWiT RSS URL for a specific feed ID or the default configured URL."""
        auth_key = self.get_club_twit_auth_key()
        if not auth_key:
            return ''
        return f"https://twit.memberfulcontent.com/rss/{feed_id}?auth={auth_key}"

    def get_app_cache_dir(self) -> str:
        """Get or create user cache directory accessible by sandboxed web browsers."""
        cache_dir = os.path.expanduser("~/.cache/twittui")
        try:
            os.makedirs(cache_dir, mode=0o700, exist_ok=True)
            try:
                os.chmod(cache_dir, 0o700)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.get_app_cache_dir', exc_info=True)
            return cache_dir
        except OSError:
            _logger.debug("Unable to create cache directory %s; falling back to temp dir", cache_dir, exc_info=True)
            return tempfile.gettempdir()

    def get_full_club_twit_url(self) -> str:
        """Construct or return the full Club TWiT URL from user input or environment."""
        raw_val = self.url_input.value.strip() if hasattr(self, 'url_input') and self.url_input and self.url_input.value else ''
        if raw_val.startswith('http://') or raw_val.startswith('https://'):
            if raw_val.startswith('http://'):
                raw_val = 'https://' + raw_val[7:]
            return raw_val
        active_prefix = getattr(self, '_club_url_prefix', None) or 'https://twit.memberfulcontent.com/rss/9041?auth='
        auth_key = self.get_club_twit_auth_key()
        if auth_key:
            return f"{active_prefix}{auth_key}"
        return active_prefix.split('?auth=', 1)[0]

    def get_destination_folder(self) -> str:
        """Get the configured download destination directory."""
        dest = self.dest_input.value if hasattr(self, 'dest_input') and self.dest_input and self.dest_input.value else ''
        if not dest:
            dest = os.getenv('twitclubdestination') or os.getenv('TWITCLUBDESTINATION') or os.getenv('TWIT_CLUB_DESTINATION') or ''
        if not dest:
            downloads_dir = os.path.expanduser('~/Downloads')
            if os.path.isdir(downloads_dir) and os.access(downloads_dir, os.W_OK):
                dest = downloads_dir
            elif os.access('.', os.W_OK):
                dest = '.'
            else:
                dest = os.environ.get('SNAP_USER_DATA') or os.path.expanduser('~')
        dest = os.path.expanduser(dest.strip())
        return dest or '.'

    def is_show_folders_enabled(self) -> bool:
        """Check if Show Folders organization is enabled."""
        if hasattr(self, 'show_folders_checkbox') and self.show_folders_checkbox is not None:
            try:
                return bool(self.show_folders_checkbox.value)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.is_show_folders_enabled', exc_info=True)
        env_val = os.getenv('twitclubshowfolders') or os.getenv('TWITCLUBSHOWFOLDERS') or os.getenv('TWIT_CLUB_SHOW_FOLDERS') or ''
        return env_val.strip().lower() in ('1', 'true', 'yes', 'on')

    def get_block_size(self) -> int:
        """Get the configured block size in bytes for download chunking."""
        block_str = self.block_input.value if hasattr(self, 'block_input') and self.block_input and self.block_input.value else ''
        if not block_str:
            block_str = os.getenv('twitclubblocksize') or os.getenv('TWITCLUBBLOCKSIZE') or '8192'
        try:
            val = int(block_str)
            return val if val > 0 else 8192
        except (ValueError, TypeError):
            return 8192

    def get_rate_limit(self) -> int:
        """Get the configured rate limit (max API calls per minute) for TWiT API requests."""
        rate_str = self.rate_limit_input.value if hasattr(self, 'rate_limit_input') and self.rate_limit_input and self.rate_limit_input.value else ''
        if not rate_str:
            rate_str = os.getenv('twitapiratelimit') or os.getenv('TWITAPIRATELIMIT') or os.getenv('twitclubratelimit') or os.getenv('TWITCLUBRATELIMIT') or os.getenv('TWIT_API_RATE_LIMIT') or '5'
        try:
            val = int(rate_str)
            return val if val > 0 else 5
        except (ValueError, TypeError):
            return 5
