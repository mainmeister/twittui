import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW
import asyncio
import os
import sys
import shutil
import glob
import re
import secrets
import shlex
import subprocess
import threading
from typing import Any
import urllib.parse
import email.utils
import xml.etree.ElementTree as ET
import tempfile
import pathlib
import webbrowser
import html
import requests
import hashlib
import http.server
from dotenv import find_dotenv, load_dotenv, set_key

try:
    import defusedxml.ElementTree as DefusedET
except ImportError:
    DefusedET = None


def load_twittui_dotenv() -> None:
    """Ensure environment variables are loaded from .env with override=True so file values take precedence."""
    try:
        dotenv_path = find_dotenv(usecwd=True)
        if not dotenv_path:
            candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
            if os.path.exists(candidate):
                dotenv_path = candidate
        if dotenv_path:
            load_dotenv(dotenv_path, override=True)
        else:
            load_dotenv(override=True)
    except Exception:
        load_dotenv(override=True)


# Ensure environment variables are loaded
load_twittui_dotenv()

# Universal Toga Widget Tooltip Support
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
                pass
        # Textual backend support (textual.widget.Widget)
        if hasattr(target, 'tooltip'):
            try:
                target.tooltip = tooltip_text if tooltip_text else None
            except Exception:
                pass


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


_ORIG_TOGA_WIDGET_INIT = toga.Widget.__init__


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


# Initialize Toga tooltip support
patch_toga_tooltips()

# Apply Textual backend widget extensions if available
try:
    from toga_textual_backend import patch_toga_textual
    patch_toga_textual()
except Exception:
    pass

# Mapping of known show names/slugs to feeds.twit.tv feed filenames
KNOWN_SHOW_FEEDS = {
    'this week in tech': ['twit_video_hd.xml', 'twit.xml'],
    'security now': ['sn_video_hd.xml', 'sn.xml'],
    'macbreak weekly': ['mbw_video_hd.xml', 'mbw.xml'],
    'windows weekly': ['ww_video_hd.xml', 'ww.xml'],
    'tech news weekly': ['tnw_video_hd.xml', 'tnw.xml'],
    'hands-on tech': ['hot_video_hd.xml', 'hot.xml'],
    'hands-on ai': ['hoa_video_hd.xml', 'hoa.xml'],
    'hands-on mac': ['hom_video_hd.xml', 'hom.xml'],
    'hands-on windows': ['how_video_hd.xml', 'how.xml'],
    'this week in space': ['twis_video_hd.xml', 'twis.xml'],
    'untitled linux show': ['uls_video_hd.xml', 'uls.xml'],
    'ios today': ['iost_video_hd.xml', 'iost.xml'],
    'intelligent machines': ['im_video_hd.xml', 'im.xml'],
    'ask the tech guys': ['attg_video_hd.xml', 'attg.xml'],
    'ask the tech guy': ['attg_video_hd.xml', 'attg.xml'],
    'the tech guy': ['ttg_video_hd.xml', 'ttg.xml'],
    'triangulation': ['tri_video_hd.xml', 'tri.xml'],
    'home theater geeks': ['htg_video_hd.xml', 'htg.xml'],
    'all about android': ['aaa_video_hd.xml', 'aaa.xml'],
    'all twit.tv shows': ['twit_video_hd.xml', 'twit.xml']
}

# Mapping of show names to Memberful / Club TWiT feed IDs (Video & Audio)
MEMBERFUL_SHOW_FEEDS = {
    'all twit.tv shows': [9041, 9040],
    'this week in tech': [9067, 9066],
    'security now': [9055, 9054],
    'macbreak weekly': [9051, 9050],
    'windows weekly': [9079, 9078],
    'tech news weekly': [9059, 9058],
    'ask the tech guys': [9061, 9060],
    'ask the tech guy': [9061, 9060],
    'ios today': [9049, 9048],
    'intelligent machines': [9065, 9064],
    'hands-on tech': [9047, 9046],
    'hands-on photography': [9045, 9044],
    'floss weekly': [9043, 9042],
    'all about android': [9039, 9038],
    'smart tech today': [9057, 9056],
    'this week in enterprise tech': [9063, 9062],
    'twit news': [9077, 9076],
    'twit+ news': [9077, 9076],
    'twit events': [9037, 9036],
    'twit+ clips': [9162, 9161],
    'twit+ club shows': [9162, 9161, 9073, 9072, 9053, 9052, 9075, 9074, 9069, 9068],
    'ai inside': [9073, 9072],
    'total jason': [9073, 9072],
    'total leo': [9053, 9052],
    'total mikah': [9075, 9074],
    'total ant': [9069, 9068]
}

# Host and network-wide Club TWiT feeds for deeper episode discovery
MEMBERFUL_HOST_FEEDS = [9073, 9072, 9053, 9052, 9075, 9074, 9069, 9068, 9162, 9161]

# TWiT API 3Scale Developer Portal URL for obtaining API credentials
TWIT_API_KEY_URL = 'https://twit-tv.3scale.net'

DEFAULT_SHOWS = [
    ("AI Inside", "846616"),
    ("Abby's Road", "1652"),
    ("All About Android", "1665"),
    ("All TWiT.tv Shows", "65161"),
    ("Android App Arena", "1684"),
    ("Ask The Tech Guy", "791331"),
    ("Ask The Tech Guys", "1642"),
    ("Hands-On AI", "862716"),
    ("Hands-On Tech", "726171"),
    ("Hands-On Windows", "837161"),
    ("Home Theater Geeks", "1657"),
    ("Intelligent Machines", "1653"),
    ("MacBreak Weekly", "1643"),
    ("Security Now", "1636"),
    ("TWiT+ Clips", "825225"),
    ("TWiT+ Club Shows", "856957"),
    ("TWiT+ News", "856956"),
    ("Tech News Weekly", "540261"),
    ("This Week in Space", "832621"),
    ("This Week in Tech", "1635"),
    ("Total Leo", "1647"),
    ("Total Mikah", "813334"),
    ("Untitled Linux Show", "832795"),
    ("Windows Weekly", "1645"),
    ("iOS Today", "1660")
]


def generate_local_server_token() -> str:
    """Generate a random URL-safe token for local server requests."""
    return secrets.token_urlsafe(24)


def write_restricted_file(file_path: str, content: str) -> None:
    """Write sensitive content to disk with 0o600 (owner-only) permissions."""
    flags: int = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd: int = os.open(file_path, flags, 0o600)
    try:
        try:
            os.chmod(file_path, 0o600)
        except Exception:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def safe_xml_fromstring(xml_data: bytes | str) -> ET.Element:
    """Parse XML string or bytes safely using defusedxml if available."""
    if isinstance(xml_data, str):
        data_bytes = xml_data.encode('utf-8', errors='replace')
    else:
        data_bytes = xml_data

    if DefusedET is not None:
        return DefusedET.fromstring(data_bytes)

    return ET.fromstring(data_bytes)


def is_safe_http_url(url: str) -> bool:
    """Check if a URL uses a safe web scheme (http or https)."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return u.startswith('http://') or u.startswith('https://')


def resolve_stream_url(media_url: str, timeout: float = 10.0) -> str:
    """Resolve redirect chains (e.g. podcast tracking/analytics URLs) to the final playable media stream URL.

    Args:
        media_url: The source media URL (may be wrapped by podcast analytics or multi-hop redirects).
        timeout: Maximum duration in seconds for HTTP redirect resolution.

    Returns:
        The resolved destination media URL, or the unwrapped / original URL upon failure.
    """
    if not media_url or not isinstance(media_url, str):
        return media_url

    clean_url: str = media_url.strip()
    parsed: urllib.parse.SplitResult = urllib.parse.urlsplit(clean_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return clean_url

    # Do not follow redirects for YouTube stream URLs
    if re.search(r'(?:youtube\.com/|youtu\.be/)', clean_url, re.IGNORECASE):
        return clean_url

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'}
        head_resp = requests.head(clean_url, headers=headers, allow_redirects=True, timeout=timeout)
        if head_resp.status_code < 400 and head_resp.url:
            return head_resp.url
        with requests.get(clean_url, headers=headers, stream=True, allow_redirects=True, timeout=timeout) as get_resp:
            if get_resp.status_code < 400 and get_resp.url:
                return get_resp.url
    except Exception as e:
        print(f"Note: Could not resolve redirects for stream URL: {e}")

    # Fallback: Unwrap known podcast tracking / redirect prefixes if HTTP resolution failed or was unreachable
    try:
        match = re.search(r'(https?://(?:cdn\.twit\.tv|twit\.cachefly\.net|episodes\.captivate\.fm|podcasts\.captivate\.fm)/.+)$', clean_url)
        if match:
            return match.group(1)
        elif re.search(r'/(?:pdst\.fm|pscrb\.fm|mgln\.ai|dts\.podtrac\.com|chrt\.fm|traffic\.megaphone\.fm)/', clean_url):
            match = re.search(r'(https?://[^/]+/(?:cap|video|members)/.+)$', clean_url)
            if match:
                return match.group(1)
            else:
                match = re.search(r'/(cdn\.twit\.tv/.+)$', clean_url)
                if match:
                    return f"https://{match.group(1)}"
    except Exception:
        pass

    return clean_url


def build_stream_args(
    streamer_template: str,
    media_url: str,
) -> list[str]:
    """Build a safe argument list for subprocess.Popen without shell=True.

    Args:
        streamer_template: Command template (e.g., 'env LC_ALL=C vlc %f').
        media_url: Validated stream URL.

    Returns:
        List of command arguments for subprocess execution.

    Raises:
        ValueError: If media_url uses an unsupported scheme or contains whitespace.
    """
    if not media_url or not isinstance(media_url, str):
        raise ValueError("Invalid media URL.")

    clean_url: str = media_url.strip()
    parsed: urllib.parse.SplitResult = urllib.parse.urlsplit(clean_url)
    if parsed.scheme.lower() not in {"https", "http", "rtsp", "mms"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    if any(ch.isspace() for ch in clean_url):
        raise ValueError("Media URL must not contain whitespace.")

    template: str = (streamer_template or "env LC_ALL=C vlc %f").strip()
    try:
        tokens: list[str] = shlex.split(template)
    except Exception:
        tokens = [template]

    if not tokens:
        tokens = ["env", "LC_ALL=C", "vlc", "%f"]

    placeholders: tuple[str, ...] = (
        "{url}",
        "{URL}",
        "{stream_url}",
        "{media_url}",
        "{file}",
        "%f",
        "%s",
        "%u",
        "{}",
    )

    replaced: bool = False
    final_args: list[str] = []
    for token in tokens:
        matched_ph: str | None = next(
            (ph for ph in placeholders if ph in token),
            None,
        )
        if matched_ph is not None:
            final_args.append(token.replace(matched_ph, clean_url))
            replaced = True
        else:
            final_args.append(token)

    if not replaced:
        final_args.append(clean_url)

    return final_args


def launch_stream_safe(
    streamer_template: str,
    media_url: str,
) -> subprocess.Popen:
    """Spawn the external media player safely with shell=False.

    Args:
        streamer_template: Command template configured by the user.
        media_url: Target stream URL.

    Returns:
        The spawned Popen process instance.
    """
    resolved_url: str = resolve_stream_url(media_url)
    args: list[str] = build_stream_args(streamer_template, resolved_url)
    return subprocess.Popen(args, shell=False)


class _LocalHTMLServer(http.server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.pages = {}
        self.lock = threading.Lock()
        self.secret_token = generate_local_server_token()


class _LocalHTMLHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]

        # Require secret session token as the first path segment
        if not path_parts or path_parts[0] != getattr(self.server, 'secret_token', ''):
            self.send_response(403)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'403 Forbidden: Invalid or missing session token')
            return

        path_key = path_parts[1] if len(path_parts) > 1 else 'index.html'

        with self.server.lock:
            content_bytes = self.server.pages.get(path_key) or self.server.pages.get('index.html')

        if content_bytes:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content_bytes)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(content_bytes)
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'404 Not Found')

    def log_message(self, format, *args):
        # Mute server request logging to preserve clean console output
        pass


class TwitTUIForm(toga.App):
    def __init__(self, formal_name='TwitTUI', app_id='org.twit.twittui', **kwargs):
        self.show_ids = {}
        self.current_episodes = []
        self.current_page = 1
        self._club_rss_cache = None
        self._memberful_feeds_cache = {}
        self._show_rss_cache = {}
        self._local_server = None
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
        self.sort_order_button = None
        self.audio_only_checkbox = None
        self.episodes_label = None
        self.episodes_list = None
        self.download_button = None
        self.stream_button = None
        self.cancel_button = None
        self.close_button = None
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
        self.streamer_label = None
        self.streamer_input = None
        self.progress_bar = None
        self.readme_cmd = None
        self.apib_cmd = None
        self.api_key_cmd = None
        self._is_downloading = False
        self._cancel_download = False
        super().__init__(formal_name=formal_name, app_id=app_id, **kwargs)

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

    def get_initial_streamer_setting(self) -> str:
        """Resolve and migrate streamer command template, persisting if migrating legacy defaults."""
        raw = os.getenv('twitclubstreamer')
        if raw is None or not raw.strip():
            raw = os.getenv('TWITCLUBSTREAMER')
        if raw is None or not raw.strip():
            raw = os.getenv('TWIT_CLUB_STREAMER')
        val = (raw or '').strip()
        if not val or val in ('vlc {url}', 'vlc %f', 'vlc', '{url}', '%f'):
            val = 'env LC_ALL=C vlc %f'
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
        candidate_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
            os.path.join(os.getcwd(), '.env'),
            os.path.abspath('.env')
        ]
        target_path = None
        for path in candidate_paths:
            if os.path.isfile(path):
                target_path = path
                break
        if not target_path:
            target_path = candidate_paths[0]

        try:
            set_key(target_path, key, str(value))
            if os.path.exists(target_path):
                try:
                    os.chmod(target_path, 0o600)
                except Exception:
                    pass
        except Exception:
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
                write_restricted_file(target_path, "".join(lines))
            except Exception as e:
                print(f"Warning: Could not save {key} to {target_path}: {e}")

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

        self.update_episodes_display()

    def is_sort_ascending(self) -> bool:
        """Return True if Ascending sort order is selected, False if Descending."""
        if hasattr(self, 'sort_order_button') and self.sort_order_button:
            if hasattr(self.sort_order_button, 'text'):
                return 'Ascending' in self.sort_order_button.text or '▲' in self.sort_order_button.text
        return False

    def on_sort_order_toggle(self, widget=None) -> None:
        """Toggle between Descending and Ascending sort order and reload episodes from API."""
        if self.is_sort_ascending():
            self.sort_order_button.text = '▼ Descending'
            self.sort_order_button.tooltip = "Currently descending (newest first). Click to sort ascending (oldest first)"
        else:
            self.sort_order_button.text = '▲ Ascending'
            self.sort_order_button.tooltip = "Currently ascending (oldest first). Click to sort descending (newest first)"

        self.load_episodes_for_selected_show()

    def get_current_sort_param(self) -> str:
        """Determine API sort query parameter based on UI sort selection and direction."""
        is_asc = self.is_sort_ascending()
        sort_by = 'date'
        if hasattr(self, 'episode_radio') and self.episode_radio and '☑' in self.episode_radio.text:
            sort_by = 'number'
        elif hasattr(self, 'title_radio') and self.title_radio and '☑' in self.title_radio.text:
            sort_by = 'title'

        if sort_by == 'date':
            field = 'airingDate'
        elif sort_by == 'number':
            field = 'episodeNumber'
        elif sort_by == 'title':
            field = 'label'
        else:
            field = 'airingDate'

        return field if is_asc else f"-{field}"

    @staticmethod
    def format_duration(val) -> str:
        """Format duration into hour:minutes:seconds (HH:MM:SS) string."""
        if val is None or val == '':
            return ''

        if isinstance(val, (int, float)):
            tot = int(val)
            if tot < 0:
                return ''
            h = tot // 3600
            m = (tot % 3600) // 60
            s = tot % 60
            return f"{h:02d}:{m:02d}:{s:02d}"

        if isinstance(val, dict):
            if 'runningTime' in val and val['runningTime']:
                return TwitTUIForm.format_duration(val['runningTime'])
            if 'duration' in val and val['duration']:
                return TwitTUIForm.format_duration(val['duration'])
            if 'hours' in val or 'minutes' in val or 'seconds' in val:
                try:
                    h = int(val.get('hours') or 0)
                    m = int(val.get('minutes') or 0)
                    s = int(val.get('seconds') or 0)
                    return f"{h:02d}:{m:02d}:{s:02d}"
                except Exception:
                    pass
            return ''

        s_val = str(val).strip()
        if not s_val:
            return ''

        # Check if purely digits or float seconds
        if re.match(r'^\d+(\.\d+)?$', s_val):
            tot = int(float(s_val))
            h = tot // 3600
            m = (tot % 3600) // 60
            s = tot % 60
            return f"{h:02d}:{m:02d}:{s:02d}"

        # Colon-separated string: HH:MM:SS, MM:SS, or D:HH:MM:SS
        if ':' in s_val:
            parts = s_val.split(':')
            try:
                if len(parts) == 3:
                    h = int(parts[0])
                    m = int(parts[1])
                    s = int(float(parts[2]))
                    return f"{h:02d}:{m:02d}:{s:02d}"
                elif len(parts) == 2:
                    m = int(parts[0])
                    s = int(float(parts[1]))
                    h = m // 60
                    m = m % 60
                    return f"{h:02d}:{m:02d}:{s:02d}"
                elif len(parts) == 4:
                    d = int(parts[0])
                    h = int(parts[1]) + d * 24
                    m = int(parts[2])
                    s = int(float(parts[3]))
                    return f"{h:02d}:{m:02d}:{s:02d}"
            except Exception:
                return s_val

        return s_val

    def extract_duration(self, episode_dict: dict) -> str:
        """Extract and format running time/duration from an episode data dictionary."""
        if not isinstance(episode_dict, dict):
            return ''

        for direct_key in ['runningTime', 'duration', 'length', 'running_time']:
            if direct_key in episode_dict and episode_dict[direct_key]:
                formatted = self.format_duration(episode_dict[direct_key])
                if formatted:
                    return formatted

        for fmt in ['video_hd', 'video_large', 'video_small', 'video_audio', 'video_youtube', 'audio']:
            val = episode_dict.get(fmt)
            if isinstance(val, dict):
                formatted = self.format_duration(val)
                if formatted:
                    return formatted

        if 'hours' in episode_dict or 'minutes' in episode_dict:
            formatted = self.format_duration(episode_dict)
            if formatted:
                return formatted

        return ''

    @staticmethod
    def format_file_size(val) -> str:
        """Format file size in bytes into a human-readable string (bytes, KB, MB, GB)."""
        if val is None or val == '':
            return ''

        try:
            if isinstance(val, str):
                val_clean = val.strip().replace(',', '')
                if not val_clean:
                    return ''
                if any(u in val_clean.upper() for u in ['GB', 'MB', 'KB', 'BYTES', 'BYTE']) and not val_clean.isdigit():
                    return val_clean
                num = float(val_clean)
            elif isinstance(val, (int, float)):
                num = float(val)
            elif isinstance(val, dict):
                for k in ['file_size', 'fileSize', 'size', 'length', 'enclosure_length', 'bytes']:
                    if k in val and val[k]:
                        res = TwitTUIForm.format_file_size(val[k])
                        if res:
                            return res
                return ''
            else:
                return ''

            if num < 0:
                return ''
            if num == 0:
                return '0 B'
            if num < 1024:
                return f"{int(num)} B"
            elif num < 1024 * 1024:
                kb = num / 1024.0
                return f"{kb:.1f} KB" if kb < 100 else f"{round(kb)} KB"
            elif num < 1024 * 1024 * 1024:
                mb = num / (1024.0 * 1024.0)
                return f"{mb:.1f} MB"
            else:
                gb = num / (1024.0 * 1024.0 * 1024.0)
                return f"{gb:.2f} GB"
        except Exception:
            return ''

    def extract_size(self, episode_dict: dict, audio_only: bool = None) -> int | str | None:
        """Extract file size in bytes from an episode data dictionary."""
        if not isinstance(episode_dict, dict):
            return None

        if audio_only is None:
            audio_only = self.is_audio_only()

        # Direct top-level size keys
        for k in ['file_size', 'fileSize', 'enclosure_length', 'bytes', 'content_length', 'size']:
            val = episode_dict.get(k)
            if val is not None and str(val).strip():
                val_str = str(val).strip()
                if val_str.isdigit() and int(val_str) > 0:
                    return int(val_str)
                elif not val_str.isdigit() and any(u in val_str.upper() for u in ['B', 'KB', 'MB', 'GB']):
                    return val_str

        # Format sub-dictionaries
        formats = ['video_audio', 'audio', 'video_hd', 'video_large', 'video_small'] if audio_only else ['video_hd', 'video_large', 'video_small', 'video_audio', 'audio']
        for fmt in formats:
            fmt_val = episode_dict.get(fmt)
            if isinstance(fmt_val, dict):
                for k in ['file_size', 'fileSize', 'size', 'length', 'bytes']:
                    v = fmt_val.get(k)
                    if v is not None and str(v).strip():
                        v_str = str(v).strip()
                        if v_str.isdigit() and int(v_str) > 0:
                            return int(v_str)
                        elif not v_str.isdigit() and any(u in v_str.upper() for u in ['B', 'KB', 'MB', 'GB']):
                            return v_str

        return None

    @staticmethod
    def is_audio_url(url: str) -> bool:
        """Check if URL points to an audio stream or file format."""
        if not url or not isinstance(url, str):
            return False
        clean = url.split('?')[0].split('#')[0].lower()
        return clean.endswith(('.mp3', '.m4a', '.aac', '.ogg', '.opus', '.flac', '.wav')) or '/audio' in clean

    @staticmethod
    def is_video_url(url: str) -> bool:
        """Check if URL points to a video stream or file format."""
        if not url or not isinstance(url, str):
            return False
        clean = url.split('?')[0].split('#')[0].lower()
        return clean.endswith(('.mp4', '.webm', '.m4v', '.mov', '.flv', '.m3u8', '.mkv')) or '/video' in clean or 'youtube.com' in clean or 'youtu.be' in clean

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        """Check if URL points to a YouTube video or stream."""
        if not url or not isinstance(url, str):
            return False
        clean = url.strip().lower()
        return (
            'youtube.com' in clean
            or 'youtu.be' in clean
            or 'youtube-nocookie.com' in clean
            or 'yt.be' in clean
            or clean.startswith('youtube:')
        )

    @staticmethod
    def is_valid_media_file(file_path: str) -> bool:
        """Check if a file exists and contains valid binary media rather than an HTML page or text error document."""
        if not file_path or not os.path.exists(file_path):
            return False
        try:
            if os.path.getsize(file_path) < 512:
                return False
            with open(file_path, 'rb') as f:
                header = f.read(512).strip().lower()
                if header.startswith((b'<!doctype', b'<html', b'<?xml', b'<head', b'<body', b'<div', b'<table', b'<![cdata[')):
                    return False
            return True
        except Exception:
            return False

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
                pass

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(_update)
            except Exception:
                _update()
        else:
            _update()

    def reset_progress(self) -> None:
        """Reset progress bar to 0."""
        self.update_progress(0, 100)

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

    def fetch_memberful_feed_items(self, feed_id: int | str) -> list:
        """Fetch and cache items from a specific Memberful feed ID."""
        fid_str = str(feed_id)
        if fid_str in self._memberful_feeds_cache:
            return self._memberful_feeds_cache[fid_str]

        feed_url = self.get_club_twit_rss_url(feed_id)
        if not feed_url:
            return []

        try:
            resp = requests.get(feed_url, headers={'User-Agent': 'TwitTUI/1.0'}, timeout=10)
            if resp.status_code == 200:
                root = safe_xml_fromstring(resp.content)
                items = []
                for item in root.findall('.//item'):
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    guid_elem = item.find('guid')
                    enclosure_elem = item.find('enclosure')
                    pubdate_elem = item.find('pubDate')

                    duration_str = ''
                    dur_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}duration')
                    if dur_elem is None:
                        dur_elem = item.find('duration')
                    if dur_elem is None:
                        for elem in item:
                            if elem.tag.endswith('duration'):
                                dur_elem = elem
                                break
                    if dur_elem is not None and dur_elem.text:
                        duration_str = self.format_duration(dur_elem.text.strip())

                    desc_elem = item.find('description')
                    summary_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}summary')
                    if summary_elem is None:
                        summary_elem = item.find('summary')
                    desc_str = ''
                    if desc_elem is not None and desc_elem.text:
                        desc_str = desc_elem.text.strip()
                    elif summary_elem is not None and summary_elem.text:
                        desc_str = summary_elem.text.strip()

                    pub_str = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ''
                    date_str = ''
                    if pub_str:
                        try:
                            dt = email.utils.parsedate_to_datetime(pub_str)
                            date_str = dt.strftime('%Y-%m-%d')
                        except Exception:
                            date_str = pub_str[:10]

                    title_str = title_elem.text.strip() if title_elem is not None and title_elem.text else ''
                    num_match = re.search(r'\b(beta\d+|\d+)\b', title_str, re.IGNORECASE)
                    ep_num = num_match.group(1) if num_match else ''

                    enc_url = enclosure_elem.attrib.get('url', '').strip() if enclosure_elem is not None else ''
                    enc_len = enclosure_elem.attrib.get('length', '').strip() if enclosure_elem is not None else ''

                    transcript_url = ''
                    transcript_elem = item.find('{https://podcastindex.org/namespace/1.0}transcript')
                    if transcript_elem is None:
                        for elem in item:
                            if elem.tag.endswith('transcript'):
                                transcript_elem = elem
                                break
                    if transcript_elem is not None:
                        transcript_url = transcript_elem.attrib.get('url', '').strip() or (transcript_elem.text.strip() if transcript_elem.text else '')

                    item_data = {
                        'title': title_str,
                        'number': ep_num,
                        'date': date_str,
                        'length': duration_str,
                        'duration': duration_str,
                        'size': enc_len,
                        'file_size': enc_len,
                        'enclosure_length': enc_len,
                        'description': desc_str,
                        'summary': desc_str,
                        'link': link_elem.text.strip() if link_elem is not None and link_elem.text else '',
                        'guid': guid_elem.text.strip() if guid_elem is not None and guid_elem.text else '',
                        'pubDate': pub_str,
                        'enclosure_url': enc_url,
                        'transcript_url': transcript_url
                    }
                    if enc_url and self.is_valid_media_url(enc_url):
                        items.append(item_data)
                self._memberful_feeds_cache[fid_str] = items
                return items
        except Exception as e:
            print(f"Error fetching Memberful RSS feed {feed_id}: {e}")

        return []

    def fetch_club_twit_rss_items(self, show_name: str = None, audio_only: bool = None) -> list:
        """Fetch and cache episode items from the Club TWiT RSS feeds relevant to the show."""
        if audio_only is None:
            audio_only = self.is_audio_only()

        feed_ids_to_fetch = []
        if show_name:
            show_key = show_name.lower().strip()
            if show_key in MEMBERFUL_SHOW_FEEDS:
                show_fids = list(MEMBERFUL_SHOW_FEEDS[show_key])
                if audio_only:
                    show_fids.reverse()
                feed_ids_to_fetch.extend(show_fids)

        # Also include default network feed and host feeds
        configured_url = os.getenv('twitcluburl') or os.getenv('TWITCLUBURL') or os.getenv('TWIT_CLUB_URL') or ''
        default_fid = 9040 if audio_only else 9041
        if '/rss/' in configured_url:
            fid_match = re.search(r'/rss/(\d+)', configured_url)
            if fid_match:
                default_fid = int(fid_match.group(1))

        if default_fid not in feed_ids_to_fetch:
            feed_ids_to_fetch.append(default_fid)

        # Fetch and accumulate items
        all_items = []
        seen_urls = set()
        for fid in feed_ids_to_fetch:
            items = self.fetch_memberful_feed_items(fid)
            for it in items:
                enc = it.get('enclosure_url')
                if enc and enc not in seen_urls:
                    seen_urls.add(enc)
                    all_items.append(it)

        if not show_name:
            self._club_rss_cache = all_items

        return all_items

    def fetch_show_rss_items(self, show_name: str, audio_only: bool = None) -> list:
        """Fetch public RSS feed items for a given show name."""
        if not show_name:
            return []

        if audio_only is None:
            audio_only = self.is_audio_only()

        show_key = show_name.lower().strip()
        cache_key = f"{show_key}_audio" if audio_only else f"{show_key}_video"
        if cache_key in self._show_rss_cache:
            return self._show_rss_cache[cache_key]

        feed_files = list(KNOWN_SHOW_FEEDS.get(show_key, []))
        if not feed_files:
            slug = re.sub(r'[^a-zA-Z0-9]+', '', show_key)
            feed_files = [f"{slug}.xml", f"{slug}_video_hd.xml"] if audio_only else [f"{slug}_video_hd.xml", f"{slug}.xml"]
        else:
            if audio_only:
                feed_files.reverse()

        items = []
        for feed_file in feed_files:
            try:
                url = f"https://feeds.twit.tv/{feed_file}"
                resp = requests.get(url, headers={'User-Agent': 'TwitTUI/1.0'}, timeout=8)
                if resp.status_code == 200:
                    root = safe_xml_fromstring(resp.content)
                    for item in root.findall('.//item'):
                        title_elem = item.find('title')
                        link_elem = item.find('link')
                        enclosure_elem = item.find('enclosure')
                        pubdate_elem = item.find('pubDate')

                        duration_str = ''
                        dur_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}duration')
                        if dur_elem is None:
                            dur_elem = item.find('duration')
                        if dur_elem is None:
                            for elem in item:
                                if elem.tag.endswith('duration'):
                                    dur_elem = elem
                                    break
                        if dur_elem is not None and dur_elem.text:
                            duration_str = self.format_duration(dur_elem.text.strip())

                        desc_elem = item.find('description')
                        summary_elem = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}summary')
                        if summary_elem is None:
                            summary_elem = item.find('summary')
                        desc_str = ''
                        if desc_elem is not None and desc_elem.text:
                            desc_str = desc_elem.text.strip()
                        elif summary_elem is not None and summary_elem.text:
                            desc_str = summary_elem.text.strip()

                        pub_str = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ''
                        date_str = ''
                        if pub_str:
                            try:
                                dt = email.utils.parsedate_to_datetime(pub_str)
                                date_str = dt.strftime('%Y-%m-%d')
                            except Exception:
                                date_str = pub_str[:10]

                        title_str = title_elem.text.strip() if title_elem is not None and title_elem.text else ''
                        num_match = re.search(r'\b(\d+)\b', title_str)
                        ep_num = num_match.group(1) if num_match else ''

                        enc_url = enclosure_elem.attrib.get('url', '').strip() if enclosure_elem is not None else ''
                        enc_len = enclosure_elem.attrib.get('length', '').strip() if enclosure_elem is not None else ''

                        transcript_url = ''
                        transcript_elem = item.find('{https://podcastindex.org/namespace/1.0}transcript')
                        if transcript_elem is None:
                            for elem in item:
                                if elem.tag.endswith('transcript'):
                                    transcript_elem = elem
                                    break
                        if transcript_elem is not None:
                            transcript_url = transcript_elem.attrib.get('url', '').strip() or (transcript_elem.text.strip() if transcript_elem.text else '')

                        if enc_url and self.is_valid_media_url(enc_url):
                            items.append({
                                'title': title_str,
                                'number': ep_num,
                                'date': date_str,
                                'length': duration_str,
                                'duration': duration_str,
                                'size': enc_len,
                                'file_size': enc_len,
                                'enclosure_length': enc_len,
                                'description': desc_str,
                                'summary': desc_str,
                                'link': link_elem.text.strip() if link_elem is not None and link_elem.text else '',
                                'transcript_url': transcript_url,
                                'enclosure_url': enc_url
                            })
                    if items:
                        break
            except Exception as e:
                print(f"Error fetching show feed {feed_file}: {e}")

        self._show_rss_cache[cache_key] = items
        return items

    def fetch_media_from_webpage(self, clean_path_or_url: str, audio_only: bool = None) -> str | None:
        """Scrape direct media stream URL from episode webpage."""
        if not clean_path_or_url or not isinstance(clean_path_or_url, str):
            return None

        if audio_only is None:
            audio_only = self.is_audio_only()

        clean_path = clean_path_or_url.strip()
        if clean_path.startswith('http://') or clean_path.startswith('https://'):
            url = clean_path
        else:
            url = f"https://twit.tv/{clean_path.lstrip('/')}"

        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}, timeout=8)
            if resp.status_code == 200:
                html = resp.text
                media_matches = re.findall(r'https?://[^\s\"\'<>]+\.(?:mp4|mp3|m4a|webm|ogg|m4v|aac)', html)
                if audio_only:
                    for candidate in media_matches:
                        if self.is_valid_media_url(candidate) and self.is_audio_url(candidate):
                            return candidate
                    for candidate in media_matches:
                        if self.is_valid_media_url(candidate):
                            return candidate
                else:
                    for candidate in media_matches:
                        if self.is_valid_media_url(candidate) and (candidate.endswith('.mp4') or 'video' in candidate or self.is_video_url(candidate)):
                            return candidate
                    for candidate in media_matches:
                        if self.is_valid_media_url(candidate):
                            return candidate

                yt_matches = re.findall(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[a-zA-Z0-9_-]+', html)
                if yt_matches and not audio_only:
                    return yt_matches[0]
        except Exception as e:
            print(f"Error scraping episode webpage {url}: {e}")

        return None

    def fetch_shows(self):
        """Fetch shows from the TWIT API and return a list of show names."""
        try:
            load_twittui_dotenv()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()

            if not app_id or not app_key:
                print("API credentials not found in settings or .env file, using default shows")
                self.show_ids = {name: sid for name, sid in DEFAULT_SHOWS}
                return sorted(list(self.show_ids.keys()))

            headers = {
                'Accept': 'application/json',
                'app-id': app_id,
                'app-key': app_key
            }

            response = requests.get('https://twit.tv/api/v1.0/shows', headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                shows = []
                self.show_ids = {}
                if 'shows' in data and isinstance(data['shows'], list):
                    for show in data['shows']:
                        if 'label' in show and 'id' in show:
                            show_name = show['label']
                            show_id = show['id']
                            shows.append(show_name)
                            self.show_ids[show_name] = show_id
                    shows.sort()
                if shows:
                    return shows

            print(f"Shows API returned {response.status_code}, using fallback show list")
            self.show_ids = {name: sid for name, sid in DEFAULT_SHOWS}
            return sorted(list(self.show_ids.keys()))
        except Exception as e:
            print(f"Error fetching shows: {e}")
            self.show_ids = {name: sid for name, sid in DEFAULT_SHOWS}
            return sorted(list(self.show_ids.keys()))

    def startup(self) -> None:
        # Hover tracking state for episode metadata popup
        self._hover_timer = None
        self._hover_row_index = None
        self._dialog_open = False
        self._metadata_window = None
        self._hover_lock = threading.Lock()
        self._table_hover_connected = False

        # Main box with vertical layout
        main_box = toga.Box(style=Pack(direction=COLUMN, margin=5))

        # Show selection section
        show_label = toga.Label(
            'Show:',
            style=Pack(margin=(0, 5)),
            tooltip='Select which TWiT show to browse'
        )
        self.show_label = show_label
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
            on_activate=lambda widget, row: self.on_stream_press(widget),
            style=Pack(flex=1, margin=5, height=200),
            tooltip='Episode list: select episodes to download, or double-click / press Enter to stream'
        )
        self._enable_table_horizontal_scroll()
        self._setup_table_hover_events()

        # Populate the show combo with show names and load initial episodes
        shows = self.fetch_shows()
        if shows:
            self.show_combo.items = shows
            self.load_episodes_for_selected_show()
        else:
            self.episodes_list.data = []

        # Buttons section
        button_box = toga.Box(style=Pack(direction=ROW, margin=5))
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
        button_box.add(cancel_button)
        button_box.add(close_button)

        # Settings section
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

        # TWIT Club URL setting
        url_box = toga.Box(style=Pack(direction=ROW, margin=5))
        url_label = toga.Label(
            'TWIT Club URL:',
            style=Pack(margin=(0, 5)),
            tooltip='Club TWiT Memberful RSS feed address or authentication key'
        )
        self.url_label = url_label
        url_prefix = toga.Label(
            'https://twit.memberfulcontent.com/rss/9041?auth=',
            style=Pack(margin=(0, 5)),
            tooltip='Club TWiT Memberful RSS feed base URL prefix'
        )
        self.url_prefix = url_prefix
        twit_club_url = os.getenv('twitcluburl') or os.getenv('TWITCLUBURL') or os.getenv('TWIT_CLUB_URL') or ''
        auth_prefix = 'https://twit.memberfulcontent.com/rss/9041?auth='
        if twit_club_url.startswith(auth_prefix):
            initial_url_key = twit_club_url[len(auth_prefix):]
        elif '?auth=' in twit_club_url:
            initial_url_key = twit_club_url.split('?auth=', 1)[1]
        else:
            initial_url_key = twit_club_url
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

        # Block size setting
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
        block_box.add(block_label)
        block_box.add(self.block_input)

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

        # Add all sections to settings box
        settings_box.add(app_id_box)
        settings_box.add(app_key_box)
        settings_box.add(url_box)
        settings_box.add(dest_box)
        settings_box.add(block_box)
        settings_box.add(streamer_box)

        # Progress bar section at the bottom of the form
        self.progress_bar = toga.ProgressBar(
            max=100.0,
            value=0.0,
            style=Pack(flex=1, margin=5),
            tooltip='Progress indicator for active download or operation'
        )

        # Add all components to main box
        main_box.add(show_box)
        main_box.add(search_box)
        main_box.add(sort_box)
        main_box.add(episodes_label)
        main_box.add(self.episodes_list)
        main_box.add(button_box)
        main_box.add(settings_box)
        main_box.add(self.progress_bar)

        # Create main window
        self.main_window = toga.MainWindow(title='TWIT.tv TUI')
        self.main_window.content = main_box

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

    def sanitize_html(self, html_str: str) -> str:
        """Sanitize HTML content to prevent script injection and malicious payloads."""
        if not html_str:
            return ""

        # Pre-strip dangerous container tags and their inner content
        dangerous_tags = [
            "script", "style", "iframe", "object", "embed", "applet",
            "form", "input", "button", "link", "meta", "svg", "base"
        ]
        sanitized = html_str
        for _ in range(5):
            prev = sanitized
            for tag in dangerous_tags:
                sanitized = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", "", sanitized, flags=re.IGNORECASE | re.DOTALL)
                sanitized = re.sub(rf"<{tag}\b[^>]*/>", "", sanitized, flags=re.IGNORECASE)
                sanitized = re.sub(rf"<{tag}\b[^>]*>", "", sanitized, flags=re.IGNORECASE)
            if sanitized == prev:
                break

        # Attempt to use bleach if available
        try:
            import bleach
            return bleach.clean(
                sanitized,
                tags=[
                    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
                    "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                    "blockquote", "strong", "em", "a", "hr", "br", "span", "div", "img"
                ],
                attributes={
                    "a": ["href", "title", "id", "name", "target", "rel"],
                    "img": ["src", "alt", "title", "width", "height"],
                    "th": ["align"],
                    "td": ["align"],
                    "*": ["class", "id"]
                },
                protocols=["http", "https", "mailto"],
                strip=True,
                strip_comments=True
            )
        except ImportError:
            pass

        # Attempt to use nh3 if available
        try:
            import nh3
            return nh3.clean(
                sanitized,
                tags={
                    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
                    "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                    "blockquote", "strong", "em", "a", "hr", "br", "span", "div", "img"
                },
                attributes={
                    "a": {"href", "title", "id", "name", "target", "rel"},
                    "img": {"src", "alt", "title", "width", "height"},
                    "th": {"align"},
                    "td": {"align"},
                    "*": {"class", "id"}
                },
                url_schemes={"http", "https", "mailto"}
            )
        except ImportError:
            pass

        # Strip all inline event handlers (e.g., onload, onclick, onerror)
        sanitized = re.sub(r"\s+on[a-zA-Z]+\s*=\s*(?:\"[^\"]*\"|\'[^\']*\'|[^\s>]+)", "", sanitized, flags=re.IGNORECASE)

        # Neutralize unsafe URI schemes in links or source attributes (including entity-encoded)
        def _neutralize_schemes(match):
            attr = match.group(1)
            eq = match.group(2)
            quote = match.group(3) or ''
            val = match.group(4)
            unescaped_val = html.unescape(val).strip().lower()
            if any(unescaped_val.startswith(scheme) for scheme in ('javascript:', 'data:', 'vbscript:', 'file:')):
                return f'{attr}{eq}{quote}#{quote}'
            return match.group(0)

        sanitized = re.sub(
            r'\b(href|src)(\s*=\s*)([\"\']?)([^\"\'\s>]+)',
            _neutralize_schemes,
            sanitized,
            flags=re.IGNORECASE
        )

        return sanitized

    @staticmethod
    def _slugify(text: str) -> str:
        """Generate a GitHub-compatible URL slug from a heading text string."""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.lower().strip()
        clean = re.sub(r"[^\w\s-]", "", clean)
        clean = re.sub(r"\s", "-", clean)
        return clean

    def _ensure_heading_ids(self, html_content: str) -> str:
        """Ensure all <h1-6> headings have unique id attributes matching standard slug format."""
        slug_counts = {}

        def replace_heading(match):
            level = match.group(1)
            attrs = match.group(2)
            inner_text = match.group(3)
            # If id attribute already exists, track it and keep
            id_match = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
            if id_match:
                existing_id = id_match.group(1)
                slug_counts[existing_id] = slug_counts.get(existing_id, 0) + 1
                return match.group(0)

            # Generate slug from inner heading text
            clean_text = re.sub(r'<[^>]+>', '', inner_text).strip()
            slug = self._slugify(clean_text)
            if not slug:
                slug = f"heading-{level}"

            count = slug_counts.get(slug, 0)
            slug_counts[slug] = count + 1
            final_id = slug if count == 0 else f"{slug}-{count}"

            return f'<h{level}{attrs} id="{final_id}">{inner_text}</h{level}>'

        return re.sub(r'<h([1-6])([^>]*)>(.*?)</h\1>', replace_heading, html_content, flags=re.IGNORECASE | re.DOTALL)

    def render_markdown_to_html(self, md_text: str, title: str = "TwitTUI Documentation") -> str:
        """Convert Markdown text to fully sanitized and styled HTML with anchor navigation."""
        body_html = ""

        # Try markdown-it-py (with raw HTML disabled) and anchors plugin
        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt("gfm-like", {"html": False})
            try:
                from mdit_py_plugins.anchors import anchors_plugin
                md.use(anchors_plugin, min_level=1, max_level=6)
            except ImportError:
                pass
            body_html = md.render(md_text)
        except ImportError:
            pass

        # Try standard python markdown library if markdown-it-py unavailable
        if not body_html:
            try:
                import markdown
                body_html = markdown.markdown(md_text, extensions=["extra", "tables", "toc"])
            except ImportError:
                pass

        # Fallback to escaped preformatted text
        if not body_html:
            body_html = f"<pre><code>{html.escape(md_text)}</code></pre>"

        # Guarantee heading IDs are present for Table of Contents navigation
        body_html = self._ensure_heading_ids(body_html)

        # Enforce sanitization on the generated HTML
        safe_body_html = self.sanitize_html(body_html)

        # Detect Table of Contents presence for navigation button
        has_toc = 'id="table-of-contents"' in safe_body_html or 'id="toc"' in safe_body_html
        toc_target = "#table-of-contents" if has_toc else "#top"
        toc_label = "↑ Table of Contents" if has_toc else "↑ Top"
        toc_title = "Jump to Table of Contents" if has_toc else "Return to top of document"

        # Wrap in clean, readable stylesheet
        styled_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
  html {{
    scroll-behavior: smooth;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.6;
    padding: 24px 32px;
    color: #24292e;
    background-color: #ffffff;
    max-width: 960px;
    margin: 0 auto;
  }}
  h1, h2, h3, h4, h5, h6 {{
    border-bottom: 1px solid #eaecef;
    padding-bottom: 0.3em;
    margin-top: 24px;
    margin-bottom: 16px;
    font-weight: 600;
    scroll-margin-top: 16px;
  }}
  h1 {{ font-size: 2em; }}
  h2 {{ font-size: 1.5em; }}
  h3 {{ font-size: 1.25em; }}
  code {{
    background-color: #f6f8fa;
    padding: 0.2em 0.4em;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    font-size: 85%;
  }}
  pre {{
    background-color: #f6f8fa;
    padding: 16px;
    overflow: auto;
    border-radius: 6px;
    line-height: 1.45;
  }}
  pre code {{
    background-color: transparent;
    padding: 0;
    font-size: 100%;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
    display: block;
    overflow-x: auto;
  }}
  table th, table td {{
    border: 1px solid #dfe2e5;
    padding: 8px 14px;
    text-align: left;
  }}
  table th {{
    background-color: #f2f4f8;
    font-weight: 600;
  }}
  table tr:nth-child(2n) {{
    background-color: #f8f9fa;
  }}
  blockquote {{
    border-left: 0.25em solid #dfe2e5;
    color: #6a737d;
    padding: 0 1em;
    margin: 16px 0;
  }}
  a {{
    color: #0366d6;
    text-decoration: none;
  }}
  a:hover {{
    text-decoration: underline;
  }}
  hr {{
    height: 0.25em;
    padding: 0;
    margin: 24px 0;
    background-color: #e1e4e8;
    border: 0;
  }}
  .back-to-toc {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    background-color: #0366d6;
    color: #ffffff;
    padding: 8px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
    opacity: 0.85;
    transition: opacity 0.2s ease, transform 0.2s ease, background-color 0.2s ease;
    z-index: 1000;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    user-select: none;
    cursor: pointer;
  }}
  .back-to-toc:hover {{
    opacity: 1.0;
    color: #ffffff;
    background-color: #0255b5;
    text-decoration: none;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
  }}
  .back-to-toc:active {{
    transform: translateY(0);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
  }}
</style>
</head>
<body>
<div id="top"></div>
{safe_body_html}
<a href="{toc_target}" class="back-to-toc" title="{toc_title}" aria-label="{toc_label}">{toc_label}</a>
</body>
</html>"""
        return styled_html

    def get_app_cache_dir(self) -> str:
        """Get or create user cache directory accessible by sandboxed web browsers."""
        cache_dir = os.path.expanduser("~/.cache/twittui")
        try:
            os.makedirs(cache_dir, mode=0o700, exist_ok=True)
            try:
                os.chmod(cache_dir, 0o700)
            except Exception:
                pass
            return cache_dir
        except Exception:
            return tempfile.gettempdir()

    def _ensure_local_server(self) -> _LocalHTMLServer | None:
        """Ensure local background HTTP server is running on 127.0.0.1 for displaying HTML in browsers."""
        if not hasattr(self, '_local_server') or self._local_server is None:
            try:
                self._local_server = _LocalHTMLServer(('127.0.0.1', 0), _LocalHTMLHandler)
                server_thread = threading.Thread(target=self._local_server.serve_forever, daemon=True)
                server_thread.start()
            except Exception as e:
                print(f"Warning: Could not start local HTTP server ({e})")
                self._local_server = None
        return self._local_server

    def open_html_in_browser(self, html_content: str, page_name: str = "index.html") -> None:
        """Open rendered HTML in web browser via local HTTP server with file fallback."""
        html_bytes = html_content.encode('utf-8')
        server = self._ensure_local_server()
        if server:
            with server.lock:
                server.pages[page_name] = html_bytes
                server.pages['index.html'] = html_bytes
            port = server.server_address[1]
            token = getattr(server, 'secret_token', '')
            webbrowser.open(f"http://127.0.0.1:{port}/{token}/{page_name}")
            return

        # Fallback to local HTML file in cache directory if local HTTP server unavailable
        cache_dir = self.get_app_cache_dir()
        temp_file = tempfile.NamedTemporaryFile("w", dir=cache_dir, delete=False, suffix=".html", encoding="utf-8")
        temp_file.write(html_content)
        temp_file.close()
        try:
            os.chmod(temp_file.name, 0o600)
        except Exception:
            pass
        file_uri = pathlib.Path(os.path.abspath(temp_file.name)).as_uri()
        webbrowser.open(file_uri)

    def show_document_viewer(self, filename: str, doc_title: str) -> None:
        """Display a Markdown/APIB document using the Hybrid Resilient Pattern (WebView with Browser fallback)."""
        candidate_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
            os.path.join(os.getcwd(), filename),
            os.path.abspath(filename)
        ]

        doc_path = None
        for path in candidate_paths:
            if os.path.isfile(path):
                doc_path = path
                break

        if not doc_path:
            err_msg = f"Could not locate {filename} file in the application directory."
            print(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                try:
                    self.main_window.error_dialog("Documentation Not Found", err_msg)
                except Exception:
                    pass
            return

        try:
            with open(doc_path, "r", encoding="utf-8", errors="replace") as f:
                md_text = f.read()
        except Exception as e:
            err_msg = f"Failed to read {filename}: {e}"
            print(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                try:
                    self.main_window.error_dialog("Read Error", err_msg)
                except Exception:
                    pass
            return

        styled_html = self.render_markdown_to_html(md_text, title=doc_title)

        # Primary Tier: In-App toga.WebView window
        try:
            help_window = toga.Window(title=doc_title, size=(900, 700))
            web_view = toga.WebView(style=Pack(flex=1))
            web_view.set_content(f"file://{doc_path}", styled_html)
            help_window.content = web_view
            help_window.show()
            return
        except Exception as webview_err:
            print(f"In-app WebView viewer unavailable ({webview_err}), falling back to system browser.")

        # Fallback Tier: System default web browser
        try:
            doc_slug = os.path.splitext(filename)[0].lower().replace('_', '-').replace('.', '-')
            self.open_html_in_browser(styled_html, page_name=f"{doc_slug}.html")
        except Exception as browser_err:
            err_msg = f"Unable to display documentation: {browser_err}"
            print(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                try:
                    self.main_window.error_dialog("Documentation Viewer Error", err_msg)
                except Exception:
                    pass

    def show_readme_viewer(self) -> None:
        """Display README.md using the Hybrid Resilient Pattern (WebView with Browser fallback)."""
        self.show_document_viewer("README.md", "TwitTUI Documentation")

    def show_apib_viewer(self) -> None:
        """Display twittv.apib using the Hybrid Resilient Pattern (WebView with Browser fallback)."""
        self.show_document_viewer("twittv.apib", "TWiT API Specification (twittv.apib)")

    def on_open_readme(self, widget=None) -> None:
        """Handler for Help menu command to view README documentation."""
        self.show_readme_viewer()

    def on_open_apib(self, widget=None) -> None:
        """Handler for Help menu command to view twittv.apib API specification."""
        self.show_apib_viewer()

    def open_api_key_url(self) -> None:
        """Open the TWiT API key registration URL (3Scale Developer Portal) in the default browser."""
        try:
            webbrowser.open(TWIT_API_KEY_URL)
        except Exception as e:
            err_msg = f"Failed to open API key registration URL: {e}"
            print(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                try:
                    self.main_window.error_dialog("Browser Error", err_msg)
                except Exception:
                    pass

    def on_open_api_key_url(self, widget=None) -> None:
        """Handler for Help menu command to open the TWiT API key registration URL."""
        self.open_api_key_url()

    def get_full_club_twit_url(self) -> str:
        """Construct or return the full Club TWiT URL from user input or environment."""
        raw_val = self.url_input.value.strip() if hasattr(self, 'url_input') and self.url_input and self.url_input.value else ''
        if raw_val.startswith('http://') or raw_val.startswith('https://'):
            if raw_val.startswith('http://'):
                raw_val = 'https://' + raw_val[7:]
            return raw_val
        auth_key = self.get_club_twit_auth_key()
        if auth_key:
            return f"https://twit.memberfulcontent.com/rss/9041?auth={auth_key}"
        return "https://twit.memberfulcontent.com/rss/9041"

    def render_rss_feed_to_html(self, xml_content: str | bytes) -> str:
        """Render RSS 2.0 XML podcast feed content into styled HTML using CSS/XSL styling."""
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode('utf-8', errors='replace')
        else:
            xml_bytes = xml_content

        # Load CSS file if available
        css_content = ""
        candidate_css_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed-style.css"),
            os.path.join(os.getcwd(), "feed-style.css"),
            os.path.abspath("feed-style.css")
        ]
        for cpath in candidate_css_paths:
            if os.path.isfile(cpath):
                try:
                    with open(cpath, "r", encoding="utf-8") as f:
                        css_content = f.read()
                        break
                except Exception:
                    pass

        # If lxml and feed-style.xsl are available, attempt XSLT transformation with hardened parser
        candidate_xsl_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed-style.xsl"),
            os.path.join(os.getcwd(), "feed-style.xsl"),
            os.path.abspath("feed-style.xsl")
        ]
        xsl_path = None
        for xpath in candidate_xsl_paths:
            if os.path.isfile(xpath):
                xsl_path = xpath
                break

        if xsl_path:
            try:
                import lxml.etree as etree
                safe_parser = etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    dtd_validation=False,
                    load_dtd=False
                )
                with open(xsl_path, "rb") as xf:
                    xslt_doc = etree.XML(xf.read(), parser=safe_parser)
                transform = etree.XSLT(xslt_doc)
                src_doc = etree.fromstring(xml_bytes, parser=safe_parser)
                result_tree = transform(src_doc)
                html_out = str(result_tree)
                if css_content and '<style>' in html_out and '</style>' in html_out:
                    style_start = html_out.find('<style>') + 7
                    style_end = html_out.find('</style>')
                    html_out = html_out[:style_start] + "\n" + css_content + "\n" + html_out[style_end:]
                return self.sanitize_html(html_out)
            except Exception as xslt_err:
                print(f"XSLT rendering fallback ({xslt_err}), using Python RSS renderer.")

        # ElementTree parser fallback
        try:
            root = safe_xml_fromstring(xml_bytes)
            channel = root.find('channel')
            if channel is None:
                channel = root.find('.//channel')

            ch_title = channel.findtext('title', 'Podcast RSS Feed') if channel is not None else 'Podcast RSS Feed'
            ch_desc = channel.findtext('description', '') if channel is not None else ''
            ch_link = channel.findtext('link', '') if channel is not None else ''
            ch_author = ''
            ch_lang = ''
            ch_image = ''

            if channel is not None:
                for elem in channel:
                    tag = elem.tag.lower()
                    if tag.endswith('author'):
                        ch_author = elem.text or ''
                    elif tag.endswith('language'):
                        ch_lang = elem.text or ''
                    elif tag.endswith('image'):
                        if elem.attrib.get('href'):
                            ch_image = elem.attrib['href']
                        else:
                            url_sub = elem.find('url')
                            if url_sub is not None and url_sub.text:
                                ch_image = url_sub.text.strip()

            items_html = []
            raw_items = channel.findall('.//item') if channel is not None else root.findall('.//item')
            for item in raw_items:
                title = item.findtext('title', 'Untitled Episode')
                link = item.findtext('link', '')
                pub_date = item.findtext('pubDate', '')

                desc = ''
                duration = ''
                episode_no = ''
                for elem in item:
                    tag = elem.tag.lower()
                    if tag.endswith('encoded'):
                        desc = elem.text or ''
                    elif tag.endswith('description') and not desc:
                        desc = elem.text or ''
                    elif tag.endswith('summary') and not desc:
                        desc = elem.text or ''
                    elif tag.endswith('duration'):
                        duration = elem.text or ''
                    elif tag.endswith('episode'):
                        episode_no = elem.text or ''

                enclosure = item.find('enclosure')
                enc_url = enclosure.attrib.get('url', '') if enclosure is not None else ''
                enc_type = enclosure.attrib.get('type', '') if enclosure is not None else ''
                enc_length = enclosure.attrib.get('length', '') if enclosure is not None else ''

                size_str = ''
                if enc_length:
                    try:
                        mb = round(int(enc_length) / 1048576)
                        if mb > 0:
                            size_str = f" • {mb} MB"
                    except Exception:
                        pass

                title_html = f'<a href="{html.escape(link)}" target="_blank" rel="noopener noreferrer">{html.escape(title)}</a>' if (link and is_safe_http_url(link)) else html.escape(title)

                meta_parts = []
                if pub_date:
                    meta_parts.append(f'<span>Published: {html.escape(pub_date)}</span>')
                if duration:
                    meta_parts.append(f'<span>Duration: {html.escape(duration)}</span>')
                if episode_no:
                    meta_parts.append(f'<span>Episode #{html.escape(episode_no)}</span>')
                meta_html = f'<div class="episode-meta">{" ".join(meta_parts)}</div>' if meta_parts else ''

                media_html = ''
                if enc_url and is_safe_http_url(enc_url):
                    media_html = f"""<div class="media-controls">
  <a class="media-link" href="{html.escape(enc_url)}" target="_blank" rel="noopener noreferrer">&#9654; Stream / Download Media</a>
  <span class="media-type">{html.escape(enc_type)}{size_str}</span>
</div>"""

                safe_desc = self.sanitize_html(desc) if hasattr(self, 'sanitize_html') else desc

                card_html = f"""<div class="episode-card">
  <h2 class="episode-title">{title_html}</h2>
  {meta_html}
  <div class="episode-description">{safe_desc}</div>
  {media_html}
</div>"""
                items_html.append(card_html)

            image_html = f'<img class="channel-image" src="{html.escape(ch_image)}" alt="Podcast Cover Art" />' if (ch_image and is_safe_http_url(ch_image)) else ''
            author_html = f'<span>Author: {html.escape(ch_author)}</span>' if ch_author else ''
            lang_html = f'<span>Language: {html.escape(ch_lang)}</span>' if ch_lang else ''
            link_html = f'<a href="{html.escape(ch_link)}" target="_blank" rel="noopener noreferrer">Visit Website</a>' if (ch_link and is_safe_http_url(ch_link)) else ''

            return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(ch_title)} - RSS Feed</title>
  <style>
{css_content}
  </style>
</head>
<body>
  <div class="container">
    <div class="notice-banner">
      <strong>Podcast RSS Feed View:</strong> Formatted with <code>feed-style.css</code>. You can copy this URL into your podcast client.
    </div>
    <div class="header">
      {image_html}
      <div class="header-info">
        <h1>{html.escape(ch_title)}</h1>
        <p class="channel-desc">{html.escape(ch_desc)}</p>
        <div class="header-meta">
          {link_html}
          {author_html}
          {lang_html}
        </div>
      </div>
    </div>
    <div class="episodes-heading">
      Episodes ({len(items_html)})
    </div>
    <div class="episodes-list">
      {"".join(items_html)}
    </div>
  </div>
</body>
</html>"""
        except Exception as parse_err:
            print(f"Error parsing RSS XML: {parse_err}")
            return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>RSS Feed Error</title><style>{css_content}</style></head>
<body><div class="container"><h1>Unable to parse RSS feed</h1><p>{html.escape(str(parse_err))}</p></div></body></html>"""

    def open_club_twit_url(self) -> None:
        """Fetch and render the Club TWiT RSS feed with CSS styling and open in default web browser."""
        target_url = self.get_full_club_twit_url()
        try:
            resp = requests.get(target_url, headers={'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'}, timeout=15)
            if resp.status_code == 200 and resp.content:
                styled_html = self.render_rss_feed_to_html(resp.content)
                self.open_html_in_browser(styled_html, page_name="club-twit-feed.html")
                return
            else:
                print(f"Warning: HTTP {resp.status_code} while fetching Club TWiT feed, opening direct URL.")
        except Exception as e:
            print(f"Error fetching Club TWiT RSS feed ({e}), opening direct URL.")

        try:
            webbrowser.open(target_url)
        except Exception as e:
            err_msg = f"Failed to open Club TWiT URL: {e}"
            print(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                try:
                    self.main_window.error_dialog("Browser Error", err_msg)
                except Exception:
                    pass

    def on_show_club_url_press(self, widget=None) -> None:
        """Handler for Show button press next to the Club TWiT URL field."""
        threading.Thread(target=self.open_club_twit_url, daemon=True).start()

    def get_destination_folder(self) -> str:
        """Get the configured download destination directory."""
        dest = self.dest_input.value if hasattr(self, 'dest_input') and self.dest_input and self.dest_input.value else ''
        if not dest:
            dest = os.getenv('twitclubdestination') or os.getenv('TWITCLUBDESTINATION') or os.getenv('TWIT_CLUB_DESTINATION') or '.'
        dest = os.path.expanduser(dest.strip())
        return dest or '.'

    def open_destination_folder(self, folder_path: str = None) -> bool:
        """Open the configured or specified download destination folder in the system file manager."""
        if not folder_path:
            folder_path = self.get_destination_folder()

        target_dir = os.path.abspath(os.path.expanduser(folder_path or '.'))
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            print(f"Could not create destination directory '{target_dir}': {e}")

        try:
            if sys.platform == 'win32':
                os.startfile(target_dir)
                return True
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', target_dir])
                return True
            else:
                # Linux and other Unix/BSD systems
                subprocess.Popen(['xdg-open', target_dir])
                return True
        except Exception as e:
            print(f"Failed to launch file manager for '{target_dir}': {e}")
            try:
                file_uri = pathlib.Path(target_dir).as_uri()
                webbrowser.open(file_uri)
                return True
            except Exception as e2:
                print(f"Fallback to browser for folder URI failed: {e2}")
                if hasattr(self, 'main_window') and self.main_window:
                    try:
                        self.main_window.error_dialog(
                            "File Manager Error",
                            f"Could not open download folder:\n{target_dir}\n\nError: {e}"
                        )
                    except Exception:
                        pass
                return False

    def on_open_destination_press(self, widget=None) -> None:
        """Handler for Open button press next to Download Destination."""
        threading.Thread(target=self.open_destination_folder, daemon=True).start()

    def is_show_folders_enabled(self) -> bool:
        """Check if Show Folders organization is enabled."""
        if hasattr(self, 'show_folders_checkbox') and self.show_folders_checkbox is not None:
            try:
                return bool(self.show_folders_checkbox.value)
            except Exception:
                pass
        env_val = os.getenv('twitclubshowfolders') or os.getenv('TWITCLUBSHOWFOLDERS') or os.getenv('TWIT_CLUB_SHOW_FOLDERS') or ''
        return env_val.strip().lower() in ('1', 'true', 'yes', 'on')

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
            val_str = 'env LC_ALL=C vlc %f'
        os.environ['twitclubstreamer'] = val_str
        os.environ['TWITCLUBSTREAMER'] = val_str
        self.save_env_setting('twitclubstreamer', val_str)

    def on_dest_change(self, widget=None) -> None:
        """Handle download destination change, update environment, and persist to .env."""
        val = self.dest_input.value if hasattr(self, 'dest_input') and self.dest_input else ''
        val_str = (val or '').strip()
        os.environ['twitclubdestination'] = val_str
        os.environ['TWITCLUBDESTINATION'] = val_str
        self.save_env_setting('twitclubdestination', val_str)

    def on_block_change(self, widget=None) -> None:
        """Handle block size change, update environment, and persist to .env."""
        val = self.block_input.value if hasattr(self, 'block_input') and self.block_input else ''
        val_str = (val or '').strip()
        if val_str:
            os.environ['twitclubblocksize'] = val_str
            os.environ['TWITCLUBBLOCKSIZE'] = val_str
            self.save_env_setting('twitclubblocksize', val_str)

    def on_app_id_change(self, widget=None) -> None:
        """Handle TWiT API App ID change, update environment, and persist to .env."""
        val = self.app_id_input.value if hasattr(self, 'app_id_input') and self.app_id_input else ''
        val_str = (val or '').strip()
        os.environ['TWITAPI_APPLICATIONID'] = val_str
        self.save_env_setting('TWITAPI_APPLICATIONID', val_str)

    def on_app_key_change(self, widget=None) -> None:
        """Handle TWiT API App Key change, update environment, and persist to .env."""
        val = self.app_key_input.value if hasattr(self, 'app_key_input') and self.app_key_input else ''
        val_str = (val or '').strip()
        os.environ['TWITAPI_APPLICATIONKEYS'] = val_str
        self.save_env_setting('TWITAPI_APPLICATIONKEYS', val_str)

    def on_url_change(self, widget=None) -> None:
        """Handle TWiT Club URL change, update environment, and persist to .env."""
        val = self.url_input.value if hasattr(self, 'url_input') and self.url_input else ''
        val_str = (val or '').strip()
        auth_prefix = 'https://twit.memberfulcontent.com/rss/9041?auth='
        if not val_str:
            full_url = ''
        elif val_str.startswith('http://') or val_str.startswith('https://'):
            full_url = val_str
        else:
            full_url = f"{auth_prefix}{val_str}"
        os.environ['twitcluburl'] = full_url
        os.environ['TWITCLUBURL'] = full_url
        self.save_env_setting('twitcluburl', full_url)

    def get_show_folder_name(self, target) -> str:
        """Determine a clean, filesystem-safe show folder name for the target episode."""
        show = ''
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            show = target.episode_data.get('show_name') or target.episode_data.get('show') or ''
        elif isinstance(target, dict):
            if 'episode_data' in target and isinstance(target['episode_data'], dict):
                show = target['episode_data'].get('show_name') or target['episode_data'].get('show') or ''
            else:
                show = target.get('show_name') or target.get('show') or ''

        if not show:
            show = getattr(target, 'show', '') or ''

        if not show and hasattr(self, 'show_combo') and self.show_combo and self.show_combo.value:
            show = self.show_combo.value or ''

        if isinstance(show, dict):
            show = show.get('label') or show.get('title') or ''

        show_str = str(show or '').strip()

        # If show is generic like "All TWiT.tv Shows" or "All Shows", try extracting from target title
        if not show_str or show_str.lower() in ('all twit.tv shows', 'all shows', 'all', 'twit'):
            target_title = getattr(target, 'title', '') or (target.get('title', '') if isinstance(target, dict) else '')
            if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
                target_title = target.episode_data.get('title') or target_title
            target_title_str = str(target_title or '').strip()
            m = re.match(r'^([A-Za-z0-9\s\+\.\-\'\&]+?)\s+\d{1,5}\b', target_title_str)
            if m:
                show_str = m.group(1).strip()
            elif target_title_str:
                show_str = target_title_str.split(':')[0].strip() if ':' in target_title_str else target_title_str
            else:
                show_str = "TWiT"

        # Normalize TWiT+ prefix (e.g. TWiT+ Club Shows -> TWiT Club Shows)
        show_str = re.sub(r'^TWiT\+\s*', 'TWiT ', show_str)

        # Sanitize folder name for filesystem safety
        clean_show = re.sub(r'[/\\:*?"<>|]', '', show_str)
        clean_show = re.sub(r'\s+', ' ', clean_show).strip()

        return clean_show or "TWiT"

    def get_target_destination_folder(self, target) -> str:
        """Get the destination directory for downloading the specified episode, accounting for Show Folders."""
        base_dest = self.get_destination_folder()
        if self.is_show_folders_enabled():
            show_folder = self.get_show_folder_name(target)
            if show_folder:
                return os.path.join(base_dest, show_folder)
        return base_dest

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

    def determine_download_filename(self, target, media_url: str) -> str:
        """Determine a clean, descriptive filename matching the actual episode name."""
        parsed = urllib.parse.urlparse(media_url)
        url_filename = os.path.basename(urllib.parse.unquote(parsed.path))

        # Check if URL filename has a known media extension
        _, ext = os.path.splitext(url_filename)
        valid_extensions = {'.mp4', '.mp3', '.m4a', '.webm', '.ogg', '.m4v', '.mov', '.flv', '.aac', '.m3u8'}
        file_ext = ext.lower() if ext and ext.lower() in valid_extensions else ('.mp3' if self.is_audio_only() else '.mp4')

        show = self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo and self.show_combo.value else ''
        ep_num = getattr(target, 'episode', '') or (target.get('number', '') if isinstance(target, dict) else '')
        ep_title = getattr(target, 'title', '') or (target.get('title', '') if isinstance(target, dict) else '')

        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            if not ep_num or str(ep_num) == 'Unknown Number':
                ep_num = target.episode_data.get('number', '')
            if not ep_title or str(ep_title) == 'Unknown Title':
                ep_title = target.episode_data.get('title', '')

        ep_title_str = str(ep_title or '').strip()
        ep_num_str = str(ep_num or '').strip()
        if ep_num_str in ('Unknown Number', 'None'):
            ep_num_str = ''
        if ep_title_str in ('Unknown Title', 'None'):
            ep_title_str = ''

        # Normalize TWiT+ prefix in titles (e.g. TWiT+ Club Shows -> TWiT Club Shows)
        ep_title_str = re.sub(r'^TWiT\+\s*', 'TWiT ', ep_title_str)

        # Replace colons and other separator artifacts with spaces
        ep_title_str = ep_title_str.replace(':', ' ')

        # Construct base filename
        if not show or show.strip().lower() in ('all twit.tv shows', 'all shows', 'twit'):
            base_name = ep_title_str or f"twit_episode_{ep_num_str}".strip('_')
        else:
            clean_show = show.strip()
            if ep_title_str:
                if ep_title_str.lower().startswith(clean_show.lower()):
                    base_name = ep_title_str
                else:
                    if ep_num_str and ep_num_str not in ep_title_str:
                        base_name = f"{clean_show} {ep_num_str} {ep_title_str}"
                    else:
                        base_name = f"{clean_show} {ep_title_str}"
            elif ep_num_str:
                base_name = f"{clean_show} {ep_num_str}"
            else:
                base_name = clean_show

        # Sanitize filename for filesystem compatibility
        clean_base = re.sub(r'[/\\:*?"<>|]', '', base_name)
        clean_base = re.sub(r'\s+', ' ', clean_base).strip()

        if not clean_base:
            clean_base = os.path.splitext(url_filename)[0] if url_filename else "twit_episode"
            clean_base = re.sub(r'[/\\:*?"<>|]', '_', clean_base).strip()

        return f"{clean_base}{file_ext}"

    def is_existing_file_identical(self, dest_path: str, url: str, expected_size: int = None) -> bool:
        """Check whether an existing local file is confirmed to be identical to the remote media file."""
        if not dest_path or not os.path.exists(dest_path):
            return False

        if not self.is_valid_media_file(dest_path):
            return False

        try:
            local_size = os.path.getsize(dest_path)
        except Exception:
            return False

        if local_size <= 0:
            return False

        if self.is_youtube_url(url):
            # For YouTube streams, consider existing if file is substantial (> 1MB) and valid binary
            return local_size > 1024 * 1024

        if expected_size is not None and expected_size > 0 and local_size != expected_size:
            return False

        # Verify against remote server headers via HTTP HEAD
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'}
            head_resp = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
            if head_resp.status_code == 200:
                remote_length = head_resp.headers.get('content-length')
                etag = head_resp.headers.get('etag', '').strip('"').strip('W/').strip('"')

                if remote_length and remote_length.isdigit():
                    remote_size = int(remote_length)
                    if remote_size > 0 and local_size != remote_size:
                        return False

                # If remote server provides an MD5 hex ETag, verify cryptographic checksum
                if len(etag) == 32 and all(c in '0123456789abcdefABCDEF' for c in etag):
                    try:
                        hasher = hashlib.md5()
                        with open(dest_path, 'rb') as f:
                            for chunk in iter(lambda: f.read(65536), b''):
                                hasher.update(chunk)
                        if hasher.hexdigest().lower() == etag.lower():
                            return True
                        else:
                            return False
                    except Exception as e:
                        print(f"Error calculating MD5 checksum for {dest_path}: {e}")

                if remote_length and remote_length.isdigit() and int(remote_length) == local_size:
                    return True

            elif head_resp.status_code == 304:
                return True
        except Exception as e:
            print(f"Could not verify existing file headers via HEAD request: {e}")
            if expected_size is not None and expected_size > 0 and local_size == expected_size:
                return True

        return False

    def download_youtube_video(self, url: str, dest_path: str, progress_callback=None) -> bool:
        """Extract and download a YouTube video or audio stream using yt-dlp or youtube-dl."""
        if self.is_existing_file_identical(dest_path, url):
            local_size = os.path.getsize(dest_path)
            print(f"Skipping download: '{dest_path}' already exists ({local_size} bytes).")
            if progress_callback:
                progress_callback(100.0, 100.0)
            else:
                self.update_progress(100.0, 100.0)
            return True

        ytdlp_bin = shutil.which('yt-dlp') or shutil.which('youtube-dl')
        has_py_module = False
        if not ytdlp_bin:
            try:
                import yt_dlp
                has_py_module = True
            except ImportError:
                has_py_module = False

        if not ytdlp_bin and not has_py_module:
            error_msg = (
                f"Cannot download YouTube URL '{url}'.\n\n"
                "Extracting YouTube video streams requires 'yt-dlp' or 'youtube-dl' to be installed on your system.\n"
                "Please install yt-dlp (e.g. 'pip install yt-dlp' or via your package manager) and try again."
            )
            print(f"Error: {error_msg}")

            def _show_err():
                try:
                    main_win = None
                    try:
                        main_win = self.main_window
                    except Exception:
                        main_win = None
                    if main_win:
                        main_win.error_dialog("YouTube Downloader Required", error_msg)
                except Exception:
                    pass

            if hasattr(self, 'loop') and self.loop and self.loop.is_running():
                try:
                    self.loop.call_soon_threadsafe(_show_err)
                except Exception:
                    _show_err()
            else:
                _show_err()
            return False

        dest_dir = os.path.dirname(os.path.abspath(dest_path)) or '.'
        os.makedirs(dest_dir, exist_ok=True)
        base_filename = os.path.basename(dest_path)
        base_stem, target_ext = os.path.splitext(base_filename)
        temp_prefix = os.path.join(dest_dir, f".twittui_yt_{base_stem}")
        outtmpl = f"{temp_prefix}.%(ext)s"

        def _cleanup_stale_parts() -> None:
            cleanup_patterns = [
                f"{temp_prefix}*",
                f"{dest_path}.part*",
                f"{dest_path}*.part*",
            ]
            for pattern in cleanup_patterns:
                for p in glob.glob(pattern):
                    try:
                        if os.path.isfile(p) or os.path.islink(p):
                            os.remove(p)
                        elif os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                    except Exception:
                        pass

        # Clean up any leftover partial pieces before starting
        _cleanup_stale_parts()

        if progress_callback is None:
            self.reset_progress()

        has_ffmpeg = bool(shutil.which('ffmpeg'))
        audio_only = self.is_audio_only()

        if ytdlp_bin:
            cmd = [
                ytdlp_bin,
                '--no-playlist',
                '--newline',
                '--no-colors',
                '--force-overwrites',
            ]
            if has_ffmpeg:
                if audio_only:
                    cmd.extend(['-x', '--audio-format', 'mp3'])
                else:
                    cmd.extend([
                        '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                        '--merge-output-format', 'mp4'
                    ])
            else:
                if audio_only:
                    cmd.extend(['-f', 'bestaudio[ext=m4a]/bestaudio/best'])
                else:
                    cmd.extend(['-f', 'best[ext=mp4]/best'])

            cmd.extend(['-o', outtmpl, url])

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                pct_regex = re.compile(r'\[download\]\s+([\d\.]+)%')
                merger_regex = re.compile(r'\[(?:Merger|ffmpeg|ExtractAudio)\]')
                while True:
                    if getattr(self, '_cancel_download', False):
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        _cleanup_stale_parts()
                        return False

                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        match = pct_regex.search(line)
                        if match:
                            pct = float(match.group(1))
                            if progress_callback:
                                progress_callback(pct, 100.0)
                            else:
                                self.update_progress(pct, 100.0)
                        elif merger_regex.search(line):
                            if progress_callback:
                                progress_callback(99.0, 100.0)
                            else:
                                self.update_progress(99.0, 100.0)

                retcode = proc.wait()
                if retcode != 0:
                    print(f"yt-dlp returned error code {retcode}")
                    _cleanup_stale_parts()
                    return False

                # Locate finalized output file
                candidates = glob.glob(f"{temp_prefix}.*")
                if not candidates:
                    candidates = glob.glob(f"{temp_prefix}*")

                found_file = None
                if candidates:
                    for c in sorted(candidates, key=lambda x: (not x.endswith('.mp4'), not x.endswith('.m4a'), not x.endswith('.mp3'), len(x))):
                        if os.path.isfile(c) and os.path.getsize(c) > 1024:
                            found_file = c
                            break

                if found_file and os.path.exists(found_file):
                    if os.path.exists(dest_path):
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                    os.rename(found_file, dest_path)

                _cleanup_stale_parts()

                if os.path.exists(dest_path) and self.is_valid_media_file(dest_path):
                    if progress_callback:
                        progress_callback(100.0, 100.0)
                    else:
                        self.update_progress(100.0, 100.0)
                    print(f"Finished downloading YouTube video: {dest_path}")
                    return True
                return False
            except Exception as e:
                print(f"Error executing yt-dlp for {url}: {e}")
                _cleanup_stale_parts()
                return False
        else:
            # Python yt_dlp module fallback
            try:
                import yt_dlp

                def _ytdlp_hook(d):
                    if getattr(self, '_cancel_download', False):
                        raise Exception("Download cancelled by user")
                    status = d.get('status')
                    if status == 'downloading':
                        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 100
                        downloaded = d.get('downloaded_bytes', 0)
                        pct = (downloaded / total) * 100.0 if total else 0.0
                        if progress_callback:
                            progress_callback(pct, 100.0)
                        else:
                            self.update_progress(pct, 100.0)
                    elif status == 'finished':
                        if progress_callback:
                            progress_callback(99.0, 100.0)
                        else:
                            self.update_progress(99.0, 100.0)

                ydl_opts = {
                    'outtmpl': outtmpl,
                    'noplaylist': True,
                    'progress_hooks': [_ytdlp_hook],
                    'quiet': True,
                    'overwrites': True,
                }
                if has_ffmpeg:
                    if audio_only:
                        ydl_opts['format'] = 'bestaudio/best'
                        ydl_opts['postprocessors'] = [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                        }]
                    else:
                        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'
                        ydl_opts['merge_output_format'] = 'mp4'
                else:
                    if audio_only:
                        ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
                    else:
                        ydl_opts['format'] = 'best[ext=mp4]/best'

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                candidates = glob.glob(f"{temp_prefix}.*")
                if not candidates:
                    candidates = glob.glob(f"{temp_prefix}*")

                found_file = None
                if candidates:
                    for c in sorted(candidates, key=lambda x: (not x.endswith('.mp4'), not x.endswith('.m4a'), not x.endswith('.mp3'), len(x))):
                        if os.path.isfile(c) and os.path.getsize(c) > 1024:
                            found_file = c
                            break

                if found_file and os.path.exists(found_file):
                    if os.path.exists(dest_path):
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                    os.rename(found_file, dest_path)

                _cleanup_stale_parts()

                if os.path.exists(dest_path) and self.is_valid_media_file(dest_path):
                    if progress_callback:
                        progress_callback(100.0, 100.0)
                    else:
                        self.update_progress(100.0, 100.0)
                    print(f"Finished downloading YouTube video: {dest_path}")
                    return True
                return False
            except Exception as e:
                print(f"Error downloading YouTube video with yt_dlp module: {e}")
                _cleanup_stale_parts()
                return False

    def download_episode_file(self, url: str, dest_path: str, block_size: int = 8192, progress_callback=None, expected_size: int = None) -> bool:
        """Stream and save a media file in chunks using the specified block size, skipping identical existing files."""
        # Handle YouTube URLs via specialized stream extractor/downloader (yt-dlp)
        if self.is_youtube_url(url):
            return self.download_youtube_video(url, dest_path, progress_callback=progress_callback)

        # Check if identical file already exists on disk
        if self.is_existing_file_identical(dest_path, url, expected_size=expected_size):
            local_size = os.path.getsize(dest_path)
            print(f"Skipping download: '{dest_path}' already exists and is confirmed identical ({local_size} bytes).")
            if progress_callback:
                progress_callback(local_size, local_size)
            else:
                self.update_progress(local_size, local_size)
            return True

        temp_path = dest_path + '.part'
        try:
            if progress_callback is None:
                self.reset_progress()
            os.makedirs(os.path.dirname(dest_path) or '.', exist_ok=True)
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'}
            with requests.get(url, stream=True, headers=headers, timeout=30) as r:
                r.raise_for_status()

                # Check if final redirected URL is a YouTube stream
                if self.is_youtube_url(r.url) or self.is_youtube_url(url):
                    return self.download_youtube_video(r.url if self.is_youtube_url(r.url) else url, dest_path, progress_callback=progress_callback)

                content_type = r.headers.get('content-type', '').lower()
                if content_type.startswith('text/html') or 'text/html' in content_type:
                    # Server returned HTML page instead of binary media
                    html_content = r.text
                    yt_matches = re.findall(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[a-zA-Z0-9_-]+', html_content)
                    if yt_matches:
                        return self.download_youtube_video(yt_matches[0], dest_path, progress_callback=progress_callback)

                    media_matches = re.findall(r'https?://[^\s\"\'<>]+\.(?:mp4|mp3|m4a|webm|ogg|m4v|aac)', html_content)
                    for cand in media_matches:
                        if self.is_valid_media_url(cand) and (not self.is_audio_only() or self.is_audio_url(cand)):
                            return self.download_episode_file(cand, dest_path, block_size, progress_callback=progress_callback, expected_size=expected_size)

                    print(f"Error: URL '{url}' returned an HTML document instead of a playable media stream.")
                    return False

                total_bytes = 0
                content_length = r.headers.get('content-length')
                if content_length and content_length.isdigit():
                    total_bytes = int(content_length)

                # Check if destination file exists and matches GET response headers
                if os.path.exists(dest_path) and total_bytes > 0:
                    local_size = os.path.getsize(dest_path)
                    if local_size == total_bytes:
                        etag = r.headers.get('etag', '').strip('"').strip('W/').strip('"')
                        if len(etag) == 32 and all(c in '0123456789abcdefABCDEF' for c in etag):
                            try:
                                hasher = hashlib.md5()
                                with open(dest_path, 'rb') as f:
                                    for chunk in iter(lambda: f.read(65536), b''):
                                        hasher.update(chunk)
                                if hasher.hexdigest().lower() == etag.lower():
                                    print(f"Skipping download: '{dest_path}' already exists and matches MD5 checksum ({etag}).")
                                    if progress_callback:
                                        progress_callback(total_bytes, total_bytes)
                                    else:
                                        self.update_progress(total_bytes, total_bytes)
                                    return True
                            except Exception:
                                pass
                        else:
                            print(f"Skipping download: '{dest_path}' already exists with matching size ({local_size} bytes).")
                            if progress_callback:
                                progress_callback(total_bytes, total_bytes)
                            else:
                                self.update_progress(total_bytes, total_bytes)
                            return True

                downloaded_bytes = 0
                if progress_callback:
                    progress_callback(0, total_bytes)
                else:
                    if total_bytes > 0:
                        self.update_progress(0, total_bytes)
                    else:
                        self.update_progress(0, 100)

                with open(temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=block_size):
                        if getattr(self, '_cancel_download', False):
                            print("Download cancelled by user")
                            break
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded_bytes, total_bytes)
                            else:
                                if total_bytes > 0:
                                    self.update_progress(downloaded_bytes, total_bytes)
                                else:
                                    self.update_progress(min(downloaded_bytes / (1024 * 1024), 100), 100)

            if getattr(self, '_cancel_download', False):
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                if progress_callback is None:
                    self.reset_progress()
                return False

            if not self.is_valid_media_file(temp_path):
                print(f"Error: Downloaded content from '{url}' contains text/HTML rather than valid media.")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                if progress_callback is None:
                    self.reset_progress()
                return False

            if os.path.exists(dest_path):
                os.remove(dest_path)
            os.rename(temp_path, dest_path)
            if progress_callback:
                progress_callback(total_bytes if total_bytes > 0 else downloaded_bytes, total_bytes)
            else:
                if total_bytes > 0:
                    self.update_progress(total_bytes, total_bytes)
            print(f"Finished downloading: {dest_path} ({downloaded_bytes} bytes)")
            return True
        except Exception as e:
            print(f"Error downloading {url} to {dest_path}: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            if progress_callback is None:
                self.reset_progress()
            return False

    def resolve_target_media_url(self, target, audio_only: bool = None) -> str | None:
        """Resolve the media stream/download URL for a selected table row or episode object."""
        if target is None:
            return None

        if audio_only is None:
            audio_only = self.is_audio_only()

        # Direct attribute on target
        media_url = getattr(target, 'media_url', None)
        if self.is_valid_media_url(media_url):
            if (audio_only and self.is_audio_url(media_url)) or (not audio_only and self.is_video_url(media_url)):
                return media_url
        else:
            media_url = None

        show_name = self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo else ''

        # Check target.episode_data
        if hasattr(target, 'episode_data'):
            ep_data = target.episode_data
            if isinstance(ep_data, dict):
                resolved = self.resolve_media_url(ep_data, show_name, audio_only=audio_only)
                if resolved:
                    return resolved

        # Check by matching in self.current_episodes
        target_num = getattr(target, 'episode', str(target[0] if isinstance(target, (tuple, list)) else ''))
        target_title = getattr(target, 'title', str(target[1] if isinstance(target, (tuple, list)) and len(target) > 1 else ''))
        if hasattr(self, 'current_episodes') and self.current_episodes:
            for ep in self.current_episodes:
                if (target_num and str(ep.get('number', '')) == str(target_num)) or (target_title and ep.get('title') == target_title):
                    resolved = self.resolve_media_url(ep, show_name, audio_only=audio_only)
                    if resolved:
                        return resolved

        # Fallback candidate dictionary
        candidate_dict = {}
        target_num = getattr(target, 'episode', str(target[0] if isinstance(target, (tuple, list)) else ''))
        target_title = getattr(target, 'title', str(target[1] if isinstance(target, (tuple, list)) and len(target) > 1 else ''))
        if target_num:
            candidate_dict['number'] = target_num
        if target_title:
            candidate_dict['title'] = target_title
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            candidate_dict.update(target.episode_data)
        elif isinstance(target, dict):
            candidate_dict.update(target)
        resolved = self.resolve_media_url(candidate_dict, show_name, audio_only=audio_only)

        if resolved and self.is_valid_media_url(resolved):
            return resolved

        return media_url if self.is_valid_media_url(media_url) else None

    def show_download_complete_dialog(self, dest_dir: str, downloaded_files: list) -> None:
        """Display a modal dialog listing the destination folder and all downloaded filenames."""
        if not downloaded_files:
            return

        folder_line = f"Folder: {dest_dir}"
        files_text = "\n".join(str(fn) for fn in downloaded_files)
        message = f"{folder_line}\n\n{files_text}"
        title = "Downloads Complete"

        def _show():
            try:
                if hasattr(self, 'main_window') and self.main_window:
                    self.main_window.info_dialog(title, message)
            except Exception as e:
                print(f"Error displaying download complete dialog: {e}")

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(_show)
            except Exception:
                _show()
        else:
            _show()

    def download_episodes_batch(self, targets: list, preferred_resolution: str = None) -> None:
        """Background worker to download multiple selected episodes."""
        self._is_downloading = True
        self._cancel_download = False
        self.reset_progress()
        base_dest_dir = self.get_destination_folder()
        block_size = self.get_block_size()
        downloaded_files = []
        total_targets = len(targets) if targets else 1

        print(f"Starting batch download for {len(targets)} episode(s) to '{base_dest_dir}' (block size: {block_size})...")
        try:
            os.makedirs(base_dest_dir, exist_ok=True)
        except Exception as e:
            print(f"Error creating destination directory '{base_dest_dir}': {e}")
            self._is_downloading = False
            self.reset_progress()
            return

        try:
            for idx_0, target in enumerate(targets):
                if getattr(self, '_cancel_download', False):
                    print("Batch download cancelled.")
                    break
                target_title = getattr(target, 'title', str(target))
                target_num = getattr(target, 'episode', '')

                if hasattr(target, 'selected_media_url') and target.selected_media_url:
                    media_url = target.selected_media_url
                elif preferred_resolution:
                    cand_res = self.get_available_resolutions(target)
                    matching = next((r['url'] for r in cand_res if r.get('id') == preferred_resolution or r.get('type') == preferred_resolution), None)
                    media_url = matching or self.resolve_target_media_url(target)
                else:
                    media_url = self.resolve_target_media_url(target)

                if not media_url:
                    print(f"[{idx_0 + 1}/{total_targets}] No media URL found for episode: {target_num} {target_title}")
                    batch_pct = ((idx_0 + 1) / total_targets) * 100.0
                    self.update_progress(batch_pct, 100.0)
                    continue

                item_dest_dir = self.get_target_destination_folder(target)
                try:
                    os.makedirs(item_dest_dir, exist_ok=True)
                except Exception as e:
                    print(f"Error creating destination directory '{item_dest_dir}': {e}")
                    item_dest_dir = base_dest_dir

                filename = self.determine_download_filename(target, media_url)
                dest_filepath = os.path.join(item_dest_dir, filename)

                # Attempt to extract known expected enclosure size
                expected_size = None
                if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
                    for k in ['file_size', 'enclosure_length', 'length', 'size', 'bytes', 'content_length']:
                        v = target.episode_data.get(k)
                        if v and str(v).isdigit() and int(v) > 1000:
                            expected_size = int(v)
                            break
                elif isinstance(target, dict):
                    for k in ['file_size', 'enclosure_length', 'length', 'size', 'bytes', 'content_length']:
                        v = target.get(k)
                        if v and str(v).isdigit() and int(v) > 1000:
                            expected_size = int(v)
                            break

                sanitized_log_url = re.sub(r'([?&]auth=)[^&]+', r'\1[REDACTED]', media_url)
                print(f"[{idx_0 + 1}/{total_targets}] Downloading '{target_title}' -> {dest_filepath} from {sanitized_log_url}")

                def _item_progress(downloaded_bytes: int, total_bytes: int, item_idx=idx_0):
                    if total_bytes > 0:
                        item_frac = min(1.0, max(0.0, downloaded_bytes / total_bytes))
                    else:
                        item_frac = 0.0
                    batch_pct = ((item_idx + item_frac) / total_targets) * 100.0
                    self.update_progress(batch_pct, 100.0)

                success = self.download_episode_file(media_url, dest_filepath, block_size, progress_callback=_item_progress, expected_size=expected_size)
                if success:
                    if self.is_show_folders_enabled():
                        show_folder = self.get_show_folder_name(target)
                        rel_path = os.path.join(show_folder, filename) if show_folder else filename
                        downloaded_files.append(rel_path)
                    else:
                        downloaded_files.append(filename)

                batch_pct = ((idx_0 + 1) / total_targets) * 100.0
                self.update_progress(batch_pct, 100.0)
        finally:
            self._is_downloading = False
            if getattr(self, '_cancel_download', False):
                self.reset_progress()
            if downloaded_files:
                self.show_download_complete_dialog(base_dest_dir, downloaded_files)

    async def on_download_press(self, widget=None) -> None:
        """Process selected episodes for batch download with resolution prompt if multiple are available."""
        try:
            self._cancel_hover_timer()
            selected = self.episodes_list.selection
            if not selected:
                print("No episode selected for download")
                return

            if isinstance(selected, (list, tuple, set)):
                targets = [t for t in selected if t is not None]
            else:
                targets = [selected] if selected is not None else []

            if not targets:
                print("No episode selected for download")
                return

            preferred_resolution = None

            if len(targets) == 1:
                target = targets[0]
                is_audio = self.is_audio_only()
                resolutions = self.get_available_resolutions(target, audio_only=is_audio)
                target_title = getattr(target, 'title', str(target[1] if isinstance(target, (tuple, list)) and len(target) > 1 else 'Episode'))
                if len(resolutions) > 1:
                    chosen_res = await self.prompt_resolution_choice(
                        title="Select Download Format" if is_audio else "Select Download Resolution",
                        message=f"Multiple audio options available for '{target_title}'. Which format do you prefer to download?" if is_audio else f"Multiple resolutions available for '{target_title}'. Which resolution do you prefer to download?",
                        resolutions=resolutions
                    )
                    if not chosen_res:
                        print("Download cancelled by user.")
                        return
                    target.selected_media_url = chosen_res.get('url')
                    target.selected_resolution = chosen_res.get('id')
                elif len(resolutions) == 1:
                    target.selected_media_url = resolutions[0].get('url')
                    target.selected_resolution = resolutions[0].get('id')
            else:
                is_audio = self.is_audio_only()
                # Check if multiple resolutions exist across batch
                has_multi = any(len(self.get_available_resolutions(t, audio_only=is_audio)) > 1 for t in targets)
                if has_multi:
                    if is_audio:
                        seen_ids = set()
                        batch_options = []
                        for t in targets:
                            for r in self.get_available_resolutions(t, audio_only=True):
                                if r['id'] not in seen_ids:
                                    seen_ids.add(r['id'])
                                    batch_options.append({
                                        'id': r['id'],
                                        'name': r['name'],
                                        'label': r['label'],
                                        'type': 'audio'
                                    })
                        if not batch_options:
                            batch_options = [
                                {'id': 'video_audio', 'name': 'Audio Only (MP3/M4A)', 'label': 'Audio Only (MP3/M4A) - Audio Only', 'type': 'audio'},
                            ]
                        prompt_title = "Select Batch Download Format"
                        prompt_msg = f"Multiple audio formats available across the {len(targets)} selected episodes. Which format do you prefer?"
                    else:
                        batch_options = [
                            {'id': 'video_hd', 'name': 'HD Video (1080p/720p)', 'label': 'HD Video (1080p/720p) - High Quality', 'type': 'video'},
                            {'id': 'video_large', 'name': 'Large Video (540p/480p)', 'label': 'Large Video (540p/480p) - Medium Quality', 'type': 'video'},
                            {'id': 'video_small', 'name': 'Small / Mobile Video (360p)', 'label': 'Small / Mobile Video (360p) - Low Bandwidth', 'type': 'video'},
                            {'id': 'video_audio', 'name': 'Audio Only (MP3/M4A)', 'label': 'Audio Only (MP3/M4A) - Audio Only', 'type': 'audio'},
                        ]
                        prompt_title = "Select Batch Download Resolution"
                        prompt_msg = f"Multiple resolutions available across the {len(targets)} selected episodes. Which resolution do you prefer?"

                    if len(batch_options) > 1:
                        chosen_batch = await self.prompt_resolution_choice(
                            title=prompt_title,
                            message=prompt_msg,
                            resolutions=batch_options
                        )
                        if not chosen_batch:
                            print("Batch download cancelled by user.")
                            return
                        preferred_resolution = chosen_batch.get('id')
                    elif len(batch_options) == 1:
                        preferred_resolution = batch_options[0].get('id')

            # Start download in background thread so GUI remains responsive
            thread = threading.Thread(target=self.download_episodes_batch, args=(targets, preferred_resolution), daemon=True)
            thread.start()
        except Exception as e:
            print(f"Error initiating download: {e}")

    def format_stream_command(self, streamer_template: str, url: str) -> str:
        """Format the streamer command string with the episode media URL safely."""
        try:
            args = build_stream_args(streamer_template, url)
            return shlex.join(args)
        except Exception:
            template = (streamer_template or 'env LC_ALL=C vlc %f').strip()
            placeholders = ['{url}', '{URL}', '{stream_url}', '{media_url}', '{file}', '%f', '%s', '%u', '{}']
            for ph in placeholders:
                if ph in template:
                    return template.replace(ph, url)
            return f"{template} {url}"

    def is_valid_media_url(self, url: str) -> bool:
        """Validate if a string is a streamable media URL and not an API endpoint or webpage."""
        if not url or not isinstance(url, str):
            return False
        url = url.strip()
        if any(ch.isspace() for ch in url):
            return False
        if not (url.startswith('http://') or url.startswith('https://') or url.startswith('rtsp://') or url.startswith('mms://')):
            return False
        # Reject API endpoints
        if '/api/' in url or '/api/v' in url or url.startswith('https://twit.tv/api') or url.startswith('http://twit.tv/api'):
            return False
        # Reject standard webpage links on twit.tv (e.g. /shows/..., /episodes/...)
        if re.search(r'https?://(?:www\.)?twit\.tv/(?:shows/|episodes/|node/|credits/|people/)[^?#]*$', url, re.IGNORECASE):
            # Unless it has an explicit media file extension
            if not re.search(r'\.(?:mp4|mp3|m4a|webm|ogg|m4v|mov|flv|m3u8|aac)(?:[?#]|$)', url, re.IGNORECASE):
                return False
        return True

    def extract_media_url(self, episode_dict: dict, audio_only: bool = None) -> str | None:
        """Extract the best available media/stream URL directly from an episode dict."""
        if not isinstance(episode_dict, dict):
            return None

        if audio_only is None:
            audio_only = self.is_audio_only()

        # Determine priority field order based on audio_only setting
        if audio_only:
            media_fields = ['video_audio', 'audio', 'video_hd', 'video_large', 'video_small', 'video_youtube']
            direct_fields = ['audioUrl', 'audio_url', 'mediaUrl', 'media_url', 'downloadUrl', 'streamUrl', 'fileUrl', 'enclosure_url', 'videoUrl', 'video_url', 'url']
        else:
            media_fields = ['video_hd', 'video_large', 'video_small', 'video_audio', 'video_youtube']
            direct_fields = ['mediaUrl', 'media_url', 'videoUrl', 'video_url', 'audioUrl', 'audio_url', 'downloadUrl', 'streamUrl', 'fileUrl', 'enclosure_url', 'url']

        # 1. Check media objects matching requested format
        for field in media_fields:
            val = episode_dict.get(field)
            if isinstance(val, dict):
                for subfield in ['mediaUrl', 'media_url', 'guid', 'url', 'href', 'streamUrl', 'downloadUrl']:
                    url = val.get(subfield)
                    if url and self.is_valid_media_url(str(url)):
                        cand = str(url).strip()
                        if audio_only:
                            if self.is_audio_url(cand):
                                return cand
                        else:
                            if self.is_video_url(cand):
                                return cand
            elif isinstance(val, str) and self.is_valid_media_url(val):
                cand = val.strip()
                if audio_only:
                    if self.is_audio_url(cand):
                        return cand
                else:
                    if self.is_video_url(cand):
                        return cand

        # 2. Check direct URL fields
        for field in direct_fields:
            val = episode_dict.get(field)
            if isinstance(val, str) and self.is_valid_media_url(val):
                cand = val.strip()
                if audio_only and self.is_audio_url(cand):
                    return cand
                elif not audio_only and self.is_video_url(cand):
                    return cand

        # 3. Check files list or dict
        files = episode_dict.get('files')
        if isinstance(files, list):
            for f in files:
                if isinstance(f, dict):
                    for subfield in ['mediaUrl', 'media_url', 'url', 'downloadUrl', 'fileUrl']:
                        url = f.get(subfield)
                        if url and self.is_valid_media_url(str(url)):
                            cand = str(url).strip()
                            if audio_only and self.is_audio_url(cand):
                                return cand
                            elif not audio_only and self.is_video_url(cand):
                                return cand
                elif isinstance(f, str) and self.is_valid_media_url(f):
                    cand = f.strip()
                    if audio_only and self.is_audio_url(cand):
                        return cand
                    elif not audio_only and self.is_video_url(cand):
                        return cand
        elif isinstance(files, dict):
            for subfield in ['mediaUrl', 'media_url', 'url', 'downloadUrl', 'fileUrl']:
                url = files.get(subfield)
                if url and self.is_valid_media_url(str(url)):
                    cand = str(url).strip()
                    if audio_only and self.is_audio_url(cand):
                        return cand
                    elif not audio_only and self.is_video_url(cand):
                        return cand

        # 4. Check _links
        links = episode_dict.get('_links')
        if isinstance(links, dict):
            link_keys = ['audio', 'enclosure', 'media', 'download', 'stream'] if audio_only else ['video', 'enclosure', 'media', 'download', 'stream']
            for link_key in link_keys:
                link_obj = links.get(link_key)
                if isinstance(link_obj, dict):
                    url = link_obj.get('href') or link_obj.get('url')
                    if url and self.is_valid_media_url(str(url)):
                        cand = str(url).strip()
                        if audio_only and self.is_audio_url(cand):
                            return cand
                        elif not audio_only and self.is_video_url(cand):
                            return cand

        # Fallback to any valid media URL if preferred format not found
        for field in ['video_hd', 'video_large', 'video_small', 'video_audio', 'video_youtube']:
            val = episode_dict.get(field)
            if isinstance(val, dict):
                for subfield in ['mediaUrl', 'media_url', 'guid', 'url', 'href', 'streamUrl', 'downloadUrl']:
                    url = val.get(subfield)
                    if url and self.is_valid_media_url(str(url)):
                        return str(url).strip()
            elif isinstance(val, str) and self.is_valid_media_url(val):
                return val.strip()

        for field in ['mediaUrl', 'media_url', 'videoUrl', 'video_url', 'audioUrl', 'audio_url', 'downloadUrl', 'streamUrl', 'fileUrl', 'enclosure_url', 'url']:
            val = episode_dict.get(field)
            if isinstance(val, str) and self.is_valid_media_url(val):
                return val.strip()

        return None

    def _match_rss_item(self, item: dict, clean_path: str, ep_id: str, ep_num: str, ep_title: str, show: str) -> bool:
        """Helper to match an RSS item against episode identifiers."""
        enc_url = item.get('enclosure_url', '')
        if not enc_url or not self.is_valid_media_url(enc_url):
            return False

        item_link = item.get('link', '')
        item_title = item.get('title', '')

        # 1. Clean path matching
        if clean_path and item_link and clean_path in item_link:
            return True

        # 2. Episode ID in media URL
        if ep_id and (f"_{ep_id}-" in enc_url or f"_{ep_id}." in enc_url or f"_{ep_id}_" in enc_url or f"/{ep_id}/" in enc_url):
            return True

        # 3. Episode number matching (e.g. beta002, 1001, etc.)
        if ep_num:
            if re.search(r'\b' + re.escape(ep_num) + r'\b', item_title, re.IGNORECASE):
                if not show or show.lower() in item_title.lower() or any(w.lower() in item_title.lower() for w in show.split() if len(w) > 2):
                    return True
            if (f"_{ep_num.lower()}_" in enc_url.lower() or f"_{ep_num.lower()}-" in enc_url.lower() or f"_{ep_num.lower()}." in enc_url.lower()):
                return True

        # 4. Episode title matching
        if ep_title:
            clean_title = re.sub(r'^(?:AI Inside|TWiT\+?|Hands-On AI|[^:]+):\s*', '', ep_title, flags=re.I).strip()
            if len(clean_title) >= 4 and clean_title.lower() in item_title.lower():
                return True
            if len(ep_title) >= 4 and ep_title.lower() in item_title.lower():
                return True

        return False

    def resolve_media_url(self, episode_dict: dict, show_name: str = None, audio_only: bool = None) -> str | None:
        """Resolve a streamable media URL for an episode through all available sources."""
        if not isinstance(episode_dict, dict):
            return None

        if audio_only is None:
            audio_only = self.is_audio_only()

        fallback_candidate = None

        # 1. Direct fields in episode dict
        url = self.extract_media_url(episode_dict, audio_only=audio_only)
        if url and self.is_valid_media_url(url):
            if (audio_only and self.is_audio_url(url)) or (not audio_only and self.is_video_url(url)):
                return url
            fallback_candidate = url

        # Extract identifiers from episode dict
        clean_path = str(episode_dict.get('cleanPath') or episode_dict.get('link') or '').strip()
        ep_num = str(episode_dict.get('number') or episode_dict.get('episodeNumber') or '').strip()
        ep_title = str(episode_dict.get('title') or episode_dict.get('label') or '').strip()
        ep_id = str(episode_dict.get('id') or '').strip()
        show = show_name or (self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo else '')

        # 2. Match in Club TWiT RSS feeds (show-specific feeds, network feeds, host feeds)
        club_items = self.fetch_club_twit_rss_items(show, audio_only=audio_only)
        if club_items:
            for item in club_items:
                if self._match_rss_item(item, clean_path, ep_id, ep_num, ep_title, show):
                    enc = item.get('enclosure_url')
                    if enc and self.is_valid_media_url(enc):
                        if (audio_only and self.is_audio_url(enc)) or (not audio_only and self.is_video_url(enc)):
                            return enc
                        if not fallback_candidate:
                            fallback_candidate = enc

        # 3. Match in Show's public RSS feed on feeds.twit.tv
        if show:
            show_items = self.fetch_show_rss_items(show, audio_only=audio_only)
            if show_items:
                for item in show_items:
                    if self._match_rss_item(item, clean_path, ep_id, ep_num, ep_title, show):
                        enc = item.get('enclosure_url')
                        if enc and self.is_valid_media_url(enc):
                            if (audio_only and self.is_audio_url(enc)) or (not audio_only and self.is_video_url(enc)):
                                return enc
                            if not fallback_candidate:
                                fallback_candidate = enc

        # 4. Fetch Episode Webpage and extract media stream URL
        if clean_path:
            web_url = self.fetch_media_from_webpage(clean_path, audio_only=audio_only)
            if web_url and self.is_valid_media_url(web_url):
                if (audio_only and self.is_audio_url(web_url)) or (not audio_only and self.is_video_url(web_url)):
                    return web_url
                if not fallback_candidate:
                    fallback_candidate = web_url
        elif show and ep_num:
            show_slug = re.sub(r'[^a-zA-Z0-9]+', '-', show.lower()).strip('-')
            candidate_path = f"/shows/{show_slug}/episodes/{ep_num}"
            web_url = self.fetch_media_from_webpage(candidate_path, audio_only=audio_only)
            if web_url and self.is_valid_media_url(web_url):
                if (audio_only and self.is_audio_url(web_url)) or (not audio_only and self.is_video_url(web_url)):
                    return web_url
                if not fallback_candidate:
                    fallback_candidate = web_url

        # 5. Fetch Episode Detail endpoint from REST API
        if ep_id:
            detail = self.fetch_episode_detail(ep_id)
            if detail:
                detail_url = self.extract_media_url(detail, audio_only=audio_only)
                if detail_url and self.is_valid_media_url(detail_url):
                    if (audio_only and self.is_audio_url(detail_url)) or (not audio_only and self.is_video_url(detail_url)):
                        return detail_url
                    if not fallback_candidate:
                        fallback_candidate = detail_url
                detail_clean_path = detail.get('cleanPath')
                if detail_clean_path:
                    web_url = self.fetch_media_from_webpage(detail_clean_path, audio_only=audio_only)
                    if web_url and self.is_valid_media_url(web_url):
                        if (audio_only and self.is_audio_url(web_url)) or (not audio_only and self.is_video_url(web_url)):
                            return web_url
                        if not fallback_candidate:
                            fallback_candidate = web_url

        # 6. Deep search across all Memberful host/network feeds
        host_feeds = list(MEMBERFUL_HOST_FEEDS)
        if audio_only:
            host_feeds.reverse()
        for host_fid in host_feeds:
            host_items = self.fetch_memberful_feed_items(host_fid)
            for item in host_items:
                if self._match_rss_item(item, clean_path, ep_id, ep_num, ep_title, show):
                    enc = item.get('enclosure_url')
                    if enc and self.is_valid_media_url(enc):
                        if (audio_only and self.is_audio_url(enc)) or (not audio_only and self.is_video_url(enc)):
                            return enc
                        if not fallback_candidate:
                            fallback_candidate = enc

        return fallback_candidate

    def get_available_resolutions(self, target, show_name: str = None, audio_only: bool = None) -> list[dict]:
        """Extract all available resolution and format choices for a given episode target."""
        if target is None:
            return []

        if audio_only is None:
            audio_only = self.is_audio_only()

        resolutions = []
        seen_urls = set()

        ep_dict = {}
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            ep_dict.update(target.episode_data)
        elif isinstance(target, dict):
            ep_dict.update(target)
        elif hasattr(target, '__dict__'):
            for k, v in target.__dict__.items():
                if not k.startswith('_'):
                    ep_dict[k] = v

        target_num = getattr(target, 'episode', str(target[0] if isinstance(target, (tuple, list)) and len(target) > 0 else ''))
        target_title = getattr(target, 'title', str(target[1] if isinstance(target, (tuple, list)) and len(target) > 1 else ''))

        if hasattr(self, 'current_episodes') and self.current_episodes:
            for ep in self.current_episodes:
                if (target_num and str(ep.get('number', '')) == str(target_num)) or (target_title and ep.get('title') == target_title):
                    if isinstance(ep, dict):
                        ep_dict = {**ep, **ep_dict}
                    break

        if not show_name:
            show_name = self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo else ''

        def _add_cand(res_id: str, name: str, res_type: str, url: str | None, size_val: Any = None):
            if not url or not isinstance(url, str):
                return
            cand_url = url.strip()
            if not (self.is_valid_media_url(cand_url) or self.is_youtube_url(cand_url)):
                return
            if cand_url in seen_urls:
                return

            if audio_only:
                if res_type != 'audio' and not self.is_audio_url(cand_url):
                    return

            seen_urls.add(cand_url)

            size_bytes = 0
            if size_val is not None:
                try:
                    size_bytes = int(size_val)
                except Exception:
                    size_bytes = 0

            size_formatted = self.format_file_size(size_bytes) if size_bytes > 0 else ""
            label = f"{name} ({size_formatted})" if size_formatted else name

            resolutions.append({
                'id': res_id,
                'name': name,
                'label': label,
                'type': res_type,
                'url': cand_url,
                'size': size_bytes,
                'size_formatted': size_formatted
            })

        # 1. Standard TWiT API format fields
        format_specs = [
            ('video_hd', 'HD Video (1080p/720p)', 'video'),
            ('video_large', 'Large Video (540p/480p)', 'video'),
            ('video_small', 'Small / Mobile Video (360p)', 'video'),
            ('video_audio', 'Audio Only (MP3/M4A)', 'audio'),
            ('audio', 'Audio (MP3/M4A)', 'audio'),
            ('video_youtube', 'YouTube Stream', 'video'),
        ]

        for fid, name, ftype in format_specs:
            val = ep_dict.get(fid)
            if isinstance(val, dict):
                u = next((val[k] for k in ['mediaUrl', 'media_url', 'downloadUrl', 'streamUrl', 'url', 'href', 'guid', 'videoId', 'video_id', 'id'] if val.get(k)), None)
                s = next((val[k] for k in ['fileSize', 'file_size', 'size', 'bytes', 'length'] if val.get(k)), None)
                if u:
                    u_str = str(u).strip()
                    if not (u_str.startswith('http://') or u_str.startswith('https://')) and (fid == 'video_youtube' or 'youtube' in fid):
                        u_str = f"https://www.youtube.com/watch?v={u_str}"
                    _add_cand(fid, name, ftype, u_str, s)
            elif isinstance(val, str) and val.strip():
                val_str = val.strip()
                if not (val_str.startswith('http://') or val_str.startswith('https://')) and (fid == 'video_youtube' or 'youtube' in fid):
                    val_str = f"https://www.youtube.com/watch?v={val_str}"
                _add_cand(fid, name, ftype, val_str)

        # 2. Check files list/dict
        files = ep_dict.get('files')
        if isinstance(files, list):
            for idx, f in enumerate(files):
                if isinstance(f, dict):
                    u = next((f[k] for k in ['mediaUrl', 'media_url', 'downloadUrl', 'url', 'fileUrl'] if f.get(k)), None)
                    s = next((f[k] for k in ['fileSize', 'file_size', 'size', 'bytes', 'length'] if f.get(k)), None)
                    fmt = str(f.get('format') or f.get('quality') or f.get('label') or '').lower()
                    if u:
                        if 'hd' in fmt or '1080' in fmt or '720' in fmt:
                            _add_cand('video_hd', 'HD Video (1080p/720p)', 'video', str(u), s)
                        elif 'large' in fmt or '540' in fmt or '480' in fmt or 'sdl' in fmt:
                            _add_cand('video_large', 'Large Video (540p/480p)', 'video', str(u), s)
                        elif 'small' in fmt or '360' in fmt or 'sds' in fmt or 'low' in fmt:
                            _add_cand('video_small', 'Small / Mobile Video (360p)', 'video', str(u), s)
                        elif 'audio' in fmt or 'mp3' in fmt or 'm4a' in fmt:
                            _add_cand(f'audio_{idx}' if idx > 0 else 'video_audio', f.get('label') or 'Audio Only (MP3/M4A)', 'audio', str(u), s)
                        else:
                            is_aud = self.is_audio_url(str(u))
                            _add_cand(f'file_{idx}', f.get('label') or ('Audio' if is_aud else 'Video'), 'audio' if is_aud else 'video', str(u), s)
        elif isinstance(files, dict):
            for k, f in files.items():
                if isinstance(f, dict):
                    u = next((f[sf] for sf in ['mediaUrl', 'media_url', 'downloadUrl', 'url', 'fileUrl'] if f.get(sf)), None)
                    s = next((f[sf] for sf in ['fileSize', 'file_size', 'size', 'bytes', 'length'] if f.get(sf)), None)
                    if u:
                        k_low = str(k).lower()
                        if 'hd' in k_low:
                            _add_cand('video_hd', 'HD Video (1080p/720p)', 'video', str(u), s)
                        elif 'large' in k_low:
                            _add_cand('video_large', 'Large Video (540p/480p)', 'video', str(u), s)
                        elif 'small' in k_low:
                            _add_cand('video_small', 'Small / Mobile Video (360p)', 'video', str(u), s)
                        elif 'audio' in k_low:
                            _add_cand('video_audio', 'Audio Only (MP3/M4A)', 'audio', str(u), s)
                        else:
                            is_aud = self.is_audio_url(str(u))
                            _add_cand(str(k), str(k), 'audio' if is_aud else 'video', str(u), s)

        # 3. Check RSS feeds for this show
        if show_name and hasattr(self, '_show_rss_cache'):
            show_key = show_name.strip().lower()
            clean_path = ep_dict.get('cleanPath') or getattr(target, 'clean_path', '')
            ep_id = str(ep_dict.get('id') or getattr(target, 'id', ''))

            # Check cached RSS feeds for matching episode
            for feed_file in KNOWN_SHOW_FEEDS.get(show_key, []):
                cache_key = f"rss_{feed_file}"
                items = self._show_rss_cache.get(cache_key, [])
                for item in items:
                    if self._match_rss_item(item, clean_path, ep_id, target_num, target_title, show_name):
                        enc = item.get('enclosure_url')
                        s = item.get('enclosure_length')
                        if enc and self.is_valid_media_url(enc):
                            if 'video_hd' in feed_file or '_hd' in feed_file:
                                _add_cand('video_hd', 'HD Video (1080p/720p)', 'video', enc, s)
                            elif 'video_large' in feed_file or '_large' in feed_file:
                                _add_cand('video_large', 'Large Video (540p/480p)', 'video', enc, s)
                            elif 'video_small' in feed_file or '_small' in feed_file:
                                _add_cand('video_small', 'Small / Mobile Video (360p)', 'video', enc, s)
                            else:
                                is_aud = self.is_audio_url(enc)
                                _add_cand('rss_feed', 'Audio (MP3/M4A)' if is_aud else 'Standard Video', 'audio' if is_aud else 'video', enc, s)

        # 4. Check direct media_url or resolved candidate
        for k in ['audio_url', 'audioUrl', 'media_url', 'mediaUrl', 'downloadUrl', 'streamUrl', 'fileUrl', 'enclosure_url']:
            direct_url = ep_dict.get(k) or (getattr(target, k, None) if hasattr(target, k) else None)
            if direct_url and self.is_valid_media_url(direct_url) and direct_url not in seen_urls:
                is_aud = self.is_audio_url(direct_url) or 'audio' in k.lower()
                _add_cand('direct', 'Audio' if is_aud else 'Video', 'audio' if is_aud else 'video', direct_url)

        if not resolutions and audio_only:
            resolved_url = self.resolve_target_media_url(target, audio_only=True)
            if resolved_url and self.is_valid_media_url(resolved_url) and resolved_url not in seen_urls:
                is_aud = self.is_audio_url(resolved_url)
                if is_aud:
                    _add_cand('audio', 'Audio Only (MP3/M4A)', 'audio', resolved_url)

        return resolutions

    async def prompt_resolution_choice(self, title: str, message: str, resolutions: list[dict]) -> dict | None:
        """Prompt the user to select their preferred resolution from available choices."""
        if not resolutions:
            return None
        if len(resolutions) == 1:
            return resolutions[0]

        # 1. Try backend ChoiceDialog first (e.g. Textual)
        try:
            from toga_textual_backend import ChoiceDialog
            res = await self.main_window.dialog(ChoiceDialog(title, message, resolutions))
            if res is not None:
                return res
            # User cancelled or dismissed
            return None
        except Exception:
            pass

        # 2. Universal GUI Modal Window Fallback (for GTK / Cocoa / WinForms / etc.)
        try:
            choice_future = asyncio.get_running_loop().create_future()
            modal_win = toga.Window(title=title, size=(520, 340))

            box = toga.Box(style=Pack(direction=COLUMN, margin=15))
            title_lbl = toga.Label(title, style=Pack(margin=(0, 0, 10, 0), font_weight='bold'), tooltip='Resolution selection dialog title')
            msg_lbl = toga.Label(message, style=Pack(margin=(0, 0, 15, 0)), tooltip='Available stream formats for this episode')
            box.add(title_lbl)
            box.add(msg_lbl)

            options_box = toga.Box(style=Pack(direction=COLUMN, margin=(0, 0, 15, 0)))
            for opt in resolutions:
                lbl = opt.get('label') or opt.get('name') or str(opt)
                def _make_handler(option_dict=opt):
                    def _on_click(btn):
                        if not choice_future.done():
                            choice_future.set_result(option_dict)
                        try:
                            modal_win.close()
                        except Exception:
                            pass
                    return _on_click
                btn = toga.Button(lbl, on_press=_make_handler(opt), style=Pack(margin=(3, 0)), tooltip=f'Stream with resolution: {lbl}')
                options_box.add(btn)
            box.add(options_box)

            def _on_cancel(btn):
                if not choice_future.done():
                    choice_future.set_result(None)
                try:
                    modal_win.close()
                except Exception:
                    pass

            cancel_btn = toga.Button('Cancel', on_press=_on_cancel, style=Pack(margin=(10, 0)), tooltip='Cancel stream resolution selection')
            box.add(cancel_btn)

            def _on_win_close(win):
                if not choice_future.done():
                    choice_future.set_result(None)
                return True

            modal_win.on_close = _on_win_close
            modal_win.content = box
            modal_win.show()

            return await choice_future
        except Exception as e:
            print(f"Error presenting resolution choice dialog: {e}")
            return resolutions[0]

    async def on_stream_press(self, widget=None) -> None:
        """Process selected episode for streaming with resolution prompt if multiple are available."""
        try:
            self._cancel_hover_timer()
            selected = self.episodes_list.selection
            if not selected:
                print("No episode selected for streaming")
                return

            target = selected[0] if isinstance(selected, list) else selected
            is_audio = self.is_audio_only()

            resolutions = self.get_available_resolutions(target, audio_only=is_audio)
            target_title = getattr(target, 'title', str(target[1] if isinstance(target, (tuple, list)) and len(target) > 1 else 'Episode'))

            if len(resolutions) > 1:
                chosen_res = await self.prompt_resolution_choice(
                    title="Select Audio Stream" if is_audio else "Select Stream Resolution",
                    message=f"Multiple audio options available for '{target_title}'. Which format do you prefer to stream?" if is_audio else f"Multiple resolutions available for '{target_title}'. Which resolution do you prefer to stream?",
                    resolutions=resolutions
                )
                if not chosen_res:
                    print("Stream cancelled by user.")
                    return
                media_url = chosen_res.get('url')
            elif len(resolutions) == 1:
                media_url = resolutions[0].get('url')
            else:
                media_url = self.resolve_target_media_url(target, audio_only=is_audio)

            if not media_url:
                print("No media URL found for the selected episode")
                return

            resolved_media_url = resolve_stream_url(media_url)
            streamer_template = self.streamer_input.value if getattr(self, 'streamer_input', None) and self.streamer_input.value else 'env LC_ALL=C vlc %f'
            sanitized_log_url = re.sub(r'([?&]auth=)[^&]+', r'\1[REDACTED]', resolved_media_url)
            print(f"Launching stream player for: {sanitized_log_url}")
            launch_stream_safe(streamer_template, resolved_media_url)
        except Exception as e:
            print(f"Error launching stream: {e}")

    def on_cancel_press(self, widget) -> None:
        self._cancel_hover_timer()
        if getattr(self, '_metadata_window', None) is not None:
            try:
                self._metadata_window.close()
            except Exception:
                pass
            self._metadata_window = None
        if getattr(self, '_is_downloading', False):
            print("Cancelling active download...")
            self._cancel_download = True
            self.reset_progress()
        else:
            self.exit()

    def on_close_press(self, widget) -> None:
        self._cancel_hover_timer()
        if getattr(self, '_metadata_window', None) is not None:
            try:
                self._metadata_window.close()
            except Exception:
                pass
            self._metadata_window = None
        self.exit()

    async def on_browse_press(self, widget) -> None:
        """Handle folder selection for download destination."""
        try:
            initial_dir = self.dest_input.value if self.dest_input.value and os.path.isdir(self.dest_input.value) else None
            selected_folder = await self.main_window.dialog(
                toga.SelectFolderDialog(
                    title="Select Download Destination",
                    initial_directory=initial_dir
                )
            )
            if selected_folder is not None:
                self.dest_input.value = str(selected_folder)
        except Exception as e:
            print(f"Error selecting folder: {e}")

    def show_api_test_dialog(self, success: bool, message: str) -> None:
        """Display a modal dialog indicating whether the TWiT API credentials test passed or failed."""
        title = "TWiT API Test: Passed" if success else "TWiT API Test: Failed"

        def _show():
            try:
                if hasattr(self, 'main_window') and self.main_window:
                    if success:
                        self.main_window.info_dialog(title, message)
                    else:
                        self.main_window.error_dialog(title, message)
            except Exception as e:
                print(f"Error displaying API test dialog: {e}")

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(_show)
            except Exception:
                _show()
        else:
            _show()

    def test_api_credentials(self, app_id: str, app_key: str) -> tuple[bool, str]:
        """Validate TWiT API Application ID and Key against TWiT REST API."""
        app_id = (app_id or '').strip()
        app_key = (app_key or '').strip()

        if not app_id or not app_key:
            return False, "Failed: Missing API Application ID or Application Key.\nPlease enter both credentials before testing."

        headers = {
            'Accept': 'application/json',
            'app-id': app_id,
            'app-key': app_key,
            'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'
        }

        try:
            resp = requests.get('https://twit.tv/api/v1.0/shows', headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                show_count = len(data.get('shows', [])) if isinstance(data, dict) and 'shows' in data else 0
                return True, f"Passed: TWiT API credentials verified successfully!\nRetrieved {show_count} shows from the TWiT API."
            elif resp.status_code in (401, 403):
                return False, f"Failed: TWiT API authentication rejected (HTTP {resp.status_code}).\nPlease check that your Application ID and Key are correct."
            else:
                return False, f"Failed: TWiT API returned HTTP status {resp.status_code} ({resp.reason})."
        except requests.exceptions.Timeout:
            return False, "Failed: Connection to TWiT API timed out."
        except requests.exceptions.RequestException as e:
            return False, f"Failed: Network error communicating with TWiT API: {e}"
        except Exception as e:
            return False, f"Failed: Error testing TWiT API credentials: {e}"

    def on_test_api_press(self, widget=None) -> None:
        """Handler for Test API button press."""
        app_id = self.get_api_app_id()
        app_key = self.get_api_app_key()

        def _worker():
            success, msg = self.test_api_credentials(app_id, app_key)
            self.show_api_test_dialog(success, msg)

        threading.Thread(target=_worker, daemon=True).start()

    def fetch_episode_detail(self, episode_id):
        """Fetch full details for a single episode ID."""
        try:
            load_twittui_dotenv()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()
            if not app_id or not app_key:
                return None
            headers = {
                'Accept': 'application/json',
                'app-id': app_id,
                'app-key': app_key
            }
            url = f'https://twit.tv/api/v1.0/episodes/{episode_id}'
            response = requests.get(url, headers=headers, timeout=8)
            if response.status_code == 200:
                data = response.json()
                if 'episodes' in data and isinstance(data['episodes'], list) and data['episodes']:
                    return data['episodes'][0]
                elif 'episode' in data and isinstance(data['episode'], dict):
                    return data['episode']
                elif isinstance(data, dict):
                    return data
            return None
        except Exception as e:
            print(f"Error fetching episode details: {e}")
            return None

    def fetch_episodes(self, show_id, page=1, sort=None):
        """Fetch episodes for a specific show ID, with fallback to Show and Club RSS feeds."""
        selected_show = self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo and self.show_combo.value else ''
        if not selected_show and hasattr(self, 'show_ids'):
            for name, sid in self.show_ids.items():
                if str(sid) == str(show_id):
                    selected_show = name
                    break
        try:
            load_twittui_dotenv()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()

            if app_id and app_key:
                headers = {
                    'Accept': 'application/json',
                    'app-id': app_id,
                    'app-key': app_key
                }

                if sort is None:
                    sort = self.get_current_sort_param()

                url = f'https://twit.tv/api/v1.0/episodes?filter[shows]={show_id}'
                if sort:
                    url += f'&sort={sort}'
                if page and int(page) > 1:
                    url += f'&page={int(page)}'
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    episodes = []
                    if 'episodes' in data and isinstance(data['episodes'], list):
                        for episode in data['episodes']:
                            episode_info = dict(episode)
                            title = episode.get('label') or episode.get('title')
                            if title:
                                episode_info['title'] = title
                            date = episode.get('airingDate') or episode.get('publishDate')
                            if date:
                                episode_info['date'] = date
                            number = episode.get('episodeNumber') or episode.get('number')
                            if number is not None:
                                episode_info['number'] = number

                            length = self.extract_duration(episode)
                            if length:
                                episode_info['length'] = length
                                episode_info['duration'] = length

                            size_val = self.extract_size(episode)
                            if size_val:
                                episode_info['size'] = size_val
                                episode_info['file_size'] = size_val
                                episode_info['enclosure_length'] = size_val

                            media_url = self.extract_media_url(episode)
                            if media_url:
                                episode_info['media_url'] = media_url

                            transcript_url = episode.get('transcript_url') or episode.get('transcript') or ''
                            if transcript_url:
                                episode_info['transcript_url'] = transcript_url

                            episodes.append(episode_info)

                    if episodes:
                        return episodes
        except Exception as e:
            print(f"Error fetching episodes from API: {e}")

        # Fallback 1: Fetch episodes from Show's public RSS feed on feeds.twit.tv
        if selected_show:
            rss_items = self.fetch_show_rss_items(selected_show, audio_only=self.is_audio_only())
            if rss_items:
                is_asc = self.is_sort_ascending()
                if is_asc:
                    rss_items = list(reversed(rss_items))

                page_size = 25
                if page and int(page) >= 1:
                    start_idx = (int(page) - 1) * page_size
                    end_idx = start_idx + page_size
                    page_items = rss_items[start_idx:end_idx]
                else:
                    page_items = rss_items

                episodes = []
                for item in page_items:
                    episodes.append({
                        'title': item.get('title', ''),
                        'number': item.get('number', ''),
                        'date': item.get('date', ''),
                        'length': item.get('length') or item.get('duration', ''),
                        'duration': item.get('duration') or item.get('length', ''),
                        'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                        'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                        'enclosure_length': item.get('enclosure_length', ''),
                        'media_url': item.get('enclosure_url', ''),
                        'cleanPath': item.get('link', ''),
                        'transcript_url': item.get('transcript_url', ''),
                        'description': item.get('description', ''),
                        'summary': item.get('summary', ''),
                        'guid': item.get('guid', ''),
                        'pubDate': item.get('pubDate', '')
                    })
                if episodes:
                    return episodes

        # Fallback 2: Fetch episodes from Club TWiT RSS feed
        club_items = self.fetch_club_twit_rss_items(selected_show, audio_only=self.is_audio_only())
        if club_items:
            matching_items = []
            for item in club_items:
                title = item.get('title', '')
                if not selected_show or selected_show.lower() in title.lower() or any(w.lower() in title.lower() for w in selected_show.split() if len(w) > 3):
                    matching_items.append(item)

            is_asc = self.is_sort_ascending()
            if is_asc:
                matching_items = list(reversed(matching_items))

            page_size = 25
            if page and int(page) >= 1:
                start_idx = (int(page) - 1) * page_size
                end_idx = start_idx + page_size
                page_items = matching_items[start_idx:end_idx]
            else:
                page_items = matching_items

            episodes = []
            for item in page_items:
                episodes.append({
                    'title': item.get('title', ''),
                    'number': item.get('number', ''),
                    'date': item.get('date', ''),
                    'length': item.get('length') or item.get('duration', ''),
                    'duration': item.get('duration') or item.get('length', ''),
                    'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                    'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                    'enclosure_length': item.get('enclosure_length', ''),
                    'media_url': item.get('enclosure_url', ''),
                    'cleanPath': item.get('link', ''),
                    'transcript_url': item.get('transcript_url', ''),
                    'description': item.get('description', ''),
                    'summary': item.get('summary', ''),
                    'guid': item.get('guid', ''),
                    'pubDate': item.get('pubDate', '')
                })
            if episodes:
                return episodes

        return []

    def search_episodes(self, query: str, show_id: str = None, show_name: str = None) -> list:
        """Search for episodes matching keywords within the selected show across API and fallback RSS feeds."""
        if not query or not query.strip():
            return []

        query_str = query.strip()
        query_lower = query_str.lower()
        query_words = [w for w in re.split(r'\s+', query_lower) if w]

        selected_show = show_name or (self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo and self.show_combo.value else '')
        if not selected_show and hasattr(self, 'show_ids') and show_id:
            for name, sid in self.show_ids.items():
                if str(sid) == str(show_id):
                    selected_show = name
                    break

        is_all_shows = not selected_show or selected_show.lower().strip() == 'all twit.tv shows'
        results = []
        seen_keys = set()

        def add_result(ep):
            if not ep:
                return
            ep_id = ep.get('id')
            clean_path = ep.get('cleanPath')
            num = ep.get('number')
            title = ep.get('title')
            key = None
            if ep_id:
                key = f"id:{ep_id}"
            elif clean_path:
                key = f"path:{clean_path}"
            elif num or title:
                key = f"nt:{num}:{title}"

            if key and key in seen_keys:
                return
            if key:
                seen_keys.add(key)
            results.append(ep)

        # Show slug helpers for checking cleanPath or body
        slug_candidates = set()
        if selected_show:
            show_clean = selected_show.lower().strip()
            slug_candidates.add(re.sub(r'[^a-z0-9]+', '-', show_clean).strip('-'))
            slug_candidates.add(re.sub(r'[^a-z0-9]+', '', show_clean))
            # Known abbreviations and aliases
            abbrevs = {
                'this week in tech': ['twit', 'this-week-in-tech'],
                'security now': ['sn', 'security-now'],
                'macbreak weekly': ['mbw', 'macbreak-weekly'],
                'windows weekly': ['ww', 'windows-weekly'],
                'tech news weekly': ['tnw', 'tech-news-weekly'],
                'hands-on tech': ['hot', 'hands-on-tech'],
                'hands-on ai': ['hoa', 'hands-on-ai'],
                'hands-on mac': ['hom', 'hands-on-mac'],
                'hands-on windows': ['how', 'hands-on-windows'],
                'this week in space': ['twis', 'this-week-in-space'],
                'untitled linux show': ['uls', 'untitled-linux-show'],
                'ios today': ['iost', 'ios-today'],
                'intelligent machines': ['im', 'intelligent-machines'],
                'ask the tech guys': ['attg', 'ask-the-tech-guys', 'ask-the-tech-guy'],
                'ask the tech guy': ['attg', 'ask-the-tech-guys', 'ask-the-tech-guy'],
                'the tech guy': ['ttg', 'the-tech-guy'],
                'home theater geeks': ['htg', 'home-theater-geeks'],
                'all about android': ['aaa', 'all-about-android'],
                'twit+ news': ['twit-news', 'twit-plus-news', 'twit_news'],
                'twit news': ['twit-news'],
                'twit+ clips': ['twit-clips'],
                'twit+ club shows': ['twit-club-shows'],
                'ai inside': ['ai-inside'],
                'total leo': ['total-leo'],
                'total mikah': ['total-mikah'],
                'total jason': ['total-jason'],
                'total ant': ['total-ant']
            }
            if show_clean in abbrevs:
                slug_candidates.update(abbrevs[show_clean])

        def show_matches_cleanpath(cp: str, body: str = '') -> bool:
            if is_all_shows:
                return True
            if not cp and not body:
                return True
            cp_lower = (cp or '').lower()
            for cand in slug_candidates:
                if f"/shows/{cand}/" in cp_lower or f"/shows/{cand}" in cp_lower or f"/{cand}/" in cp_lower:
                    return True
            if selected_show and selected_show.lower() in (body or '').lower():
                return True
            return False

        # Load show RSS items to help enrich and match
        rss_items_map = {}
        show_rss_list = []
        if selected_show:
            try:
                show_rss_list = self.fetch_show_rss_items(selected_show, audio_only=self.is_audio_only())
                for r_item in (show_rss_list or []):
                    r_num = str(r_item.get('number', '')).strip()
                    if r_num:
                        rss_items_map[r_num] = r_item
                    r_title = r_item.get('title', '').strip().lower()
                    if r_title:
                        rss_items_map[r_title] = r_item
            except Exception:
                pass

        # Tier 1: TWiT REST API Search Endpoint
        try:
            load_twittui_dotenv()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()

            if app_id and app_key:
                headers = {
                    'Accept': 'application/json',
                    'app-id': app_id,
                    'app-key': app_key
                }
                encoded_query = urllib.parse.quote(query_str)
                url = f'https://twit.tv/api/v1.0/search/{encoded_query}?range=100'
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    search_items = data.get('search', [])
                    if isinstance(search_items, list):
                        for item in search_items:
                            item_type = item.get('type')
                            if item_type and item_type != 'episode':
                                continue
                            clean_path = item.get('cleanPath', '')
                            body = item.get('body', '')
                            if not show_matches_cleanpath(clean_path, body):
                                continue

                            ep_id = item.get('id')
                            title = item.get('label') or item.get('title') or ''
                            ep_num = ''
                            if clean_path:
                                num_match = re.search(r'/episodes/(\d+)', clean_path)
                                if num_match:
                                    ep_num = num_match.group(1)
                            if not ep_num and title:
                                num_match = re.search(r'\b(\d+)\b', title)
                                if num_match:
                                    ep_num = num_match.group(1)

                            matched_rss = rss_items_map.get(str(ep_num).strip()) or rss_items_map.get(title.strip().lower())
                            date_val = matched_rss.get('date', '') if matched_rss else ''
                            dur_val = (matched_rss.get('length') or matched_rss.get('duration', '')) if matched_rss else ''
                            size_val = (matched_rss.get('size') or matched_rss.get('file_size') or matched_rss.get('enclosure_length', '')) if matched_rss else ''
                            media_url_val = matched_rss.get('enclosure_url', '') if matched_rss else ''

                            ep_info = {
                                'id': str(ep_id) if ep_id is not None else '',
                                'title': title,
                                'number': ep_num,
                                'cleanPath': clean_path,
                                'description': body,
                                'summary': body,
                                'date': date_val,
                                'length': dur_val,
                                'duration': dur_val,
                                'size': size_val,
                                'file_size': size_val,
                                'enclosure_length': size_val,
                                'media_url': media_url_val
                            }
                            add_result(ep_info)
        except Exception as e:
            print(f"Error searching API: {e}")

        # Tier 2: Public Show RSS Feeds (feeds.twit.tv)
        if show_rss_list:
            try:
                for item in show_rss_list:
                    t = item.get('title', '')
                    d = item.get('description', '')
                    s = item.get('summary', '')
                    num = str(item.get('number', ''))
                    combined = f"{t} {d} {s} {num}".lower()
                    if all(word in combined for word in query_words):
                        ep = {
                            'title': t,
                            'number': num,
                            'date': item.get('date', ''),
                            'length': item.get('length') or item.get('duration', ''),
                            'duration': item.get('duration') or item.get('length', ''),
                            'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                            'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                            'enclosure_length': item.get('enclosure_length', ''),
                            'media_url': item.get('enclosure_url', ''),
                            'cleanPath': item.get('link', ''),
                            'description': d,
                            'summary': s,
                            'guid': item.get('guid', ''),
                            'pubDate': item.get('pubDate', '')
                        }
                        add_result(ep)
            except Exception as e:
                print(f"Error searching show RSS: {e}")

        # Tier 3: Club TWiT RSS Feed
        try:
            club_items = self.fetch_club_twit_rss_items(selected_show, audio_only=self.is_audio_only())
            if club_items:
                for item in club_items:
                    t = item.get('title', '')
                    d = item.get('description', '')
                    s = item.get('summary', '')
                    num = str(item.get('number', ''))
                    if not is_all_shows and selected_show:
                        if selected_show.lower() not in t.lower() and not any(w.lower() in t.lower() for w in selected_show.split() if len(w) > 3):
                            continue
                    combined = f"{t} {d} {s} {num}".lower()
                    if all(word in combined for word in query_words):
                        ep = {
                            'title': t,
                            'number': num,
                            'date': item.get('date', ''),
                            'length': item.get('length') or item.get('duration', ''),
                            'duration': item.get('duration') or item.get('length', ''),
                            'size': item.get('size') or item.get('file_size') or item.get('enclosure_length', ''),
                            'file_size': item.get('file_size') or item.get('size') or item.get('enclosure_length', ''),
                            'enclosure_length': item.get('enclosure_length', ''),
                            'media_url': item.get('enclosure_url', ''),
                            'cleanPath': item.get('link', ''),
                            'description': d,
                            'summary': s,
                            'guid': item.get('guid', ''),
                            'pubDate': item.get('pubDate', '')
                        }
                        add_result(ep)
        except Exception as e:
            print(f"Error searching Club TWiT RSS: {e}")

        # Tier 4: Search across currently loaded episodes if any
        if hasattr(self, 'current_episodes') and self.current_episodes:
            for ep in self.current_episodes:
                t = str(ep.get('title', ''))
                d = str(ep.get('description', ''))
                s = str(ep.get('summary', ''))
                num = str(ep.get('number', ''))
                combined = f"{t} {d} {s} {num}".lower()
                if all(word in combined for word in query_words):
                    add_result(ep)

        return results

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
                try:
                    native.set_policy(1, 1)  # 1 corresponds to PolicyType.AUTOMATIC in GTK3/4
                except Exception:
                    pass

        # Cocoa / macOS backend
        if hasattr(impl, 'native') and hasattr(impl.native, 'setHasHorizontalScroller_'):
            try:
                impl.native.setHasHorizontalScroller_(True)
                if hasattr(impl.native, 'setAutohidesScrollers_'):
                    impl.native.setAutohidesScrollers_(True)
            except Exception:
                pass

    @staticmethod
    def clean_html_text(text: str) -> str:
        """Strip HTML tags and unescape HTML entities into clean plain text."""
        if not text:
            return ''
        s = str(text)
        s = re.sub(r'<\s*br\s*/?>', '\n', s, flags=re.I)
        s = re.sub(r'</\s*p\s*>', '\n\n', s, flags=re.I)
        s = re.sub(r'</\s*li\s*>', '\n', s, flags=re.I)
        s = re.sub(r'<[^>]+>', '', s)
        s = html.unescape(s)
        s = re.sub(r'\n{3,}', '\n\n', s)
        return s.strip()

    def open_url_in_browser(self, url: str) -> None:
        """Open the specified URL in the system default web browser."""
        if not url:
            return
        target_url = str(url).strip()
        if not target_url.startswith('http://') and not target_url.startswith('https://'):
            target_url = f"https://{target_url}"
        try:
            webbrowser.open(target_url)
        except Exception as e:
            err_msg = f"Failed to open URL in browser: {e}"
            print(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                try:
                    self.main_window.error_dialog("Browser Error", err_msg)
                except Exception:
                    pass

    def generate_transcript_slug_candidates(self, show_name: str, ep_num: str) -> list:
        """Generate candidate transcript URL slugs for a show and episode number."""
        if not show_name or not ep_num:
            return []
        s = str(show_name).lower().strip()
        s_clean = re.sub(r'[^a-z0-9\s-]', '', s)
        ep_clean = str(ep_num).strip().lstrip('#')

        show_variants = [
            s_clean.replace(' ', '-'),
        ]
        if s_clean.startswith('this week in '):
            show_variants.append(s_clean.replace('this week in ', 'week-').replace(' ', '-'))
        if s_clean.startswith('the '):
            show_variants.append(s_clean[4:].replace(' ', '-'))

        short_map = {
            'this week in tech': ['twit', 'week-tech', 'this-week-in-tech'],
            'this week in space': ['week-space', 'twis', 'this-week-in-space'],
            'this week in google': ['week-google', 'twig', 'this-week-in-google'],
            'this week in enterprise tech': ['week-enterprise-tech', 'twiet'],
            'tech news weekly': ['tech-news-weekly', 'tnw'],
            'security now': ['security-now', 'sn'],
            'macbreak weekly': ['macbreak-weekly', 'mbw'],
            'windows weekly': ['windows-weekly', 'ww'],
            'untitled linux show': ['untitled-linux-show', 'uls'],
            'ios today': ['ios-today', 'iost'],
            'ask the tech guys': ['ask-tech-guys', 'tech-guy', 'atg'],
            'floss weekly': ['floss-weekly', 'floss'],
            'know how': ['know-how', 'kh'],
            'hands-on mac': ['hands-on-mac', 'hom'],
            'hands-on windows': ['hands-on-windows', 'how'],
            'hands-on tech': ['hands-on-tech', 'hot']
        }
        for k, v in short_map.items():
            if k in s_clean:
                show_variants = v + show_variants

        seen = set()
        unique_variants = []
        for var in show_variants:
            if var and var not in seen:
                seen.add(var)
                unique_variants.append(var)

        candidates = []
        for var in unique_variants:
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-{ep_clean}-transcript")
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-episode-{ep_clean}-transcript")
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-{ep_clean}")
            candidates.append(f"https://twit.tv/posts/transcripts/{var}-episode-{ep_clean}")
        return candidates

    def resolve_transcript_url(self, target, show_name: str = '') -> str:
        """Resolve or extract the transcript URL for an episode target."""
        if not target:
            return ''
        ep_data = {}
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            ep_data.update(target.episode_data)
        elif isinstance(target, dict):
            if 'episode_data' in target and isinstance(target['episode_data'], dict):
                ep_data.update(target['episode_data'])
            else:
                ep_data.update(target)

        # Collect show and episode identifiers
        show = show_name or getattr(target, 'show', '') or ep_data.get('show_name') or ep_data.get('show') or ''
        if not show and hasattr(self, 'show_combo') and self.show_combo and self.show_combo.value:
            show = self.show_combo.value or ''
        if isinstance(show, dict):
            show = show.get('label') or show.get('title') or ''
        show_str = str(show).strip()
        ep_title = getattr(target, 'title', '') or ep_data.get('title') or ep_data.get('label') or ''
        ep_num = getattr(target, 'episode', '') or getattr(target, 'number', '') or ep_data.get('episode') or ep_data.get('number') or ep_data.get('episodeNumber') or ep_data.get('episode_number') or ''
        if not ep_num and ep_title:
            m_num = re.search(r'\b(?:episode|ep|twis|twit|twig|tnw|mbw|sn|ww|uls|iost)?\s*#?\s*(\d{1,5})\b', ep_title, re.IGNORECASE)
            if m_num:
                ep_num = m_num.group(1)
        if not ep_num and (ep_data.get('link') or ep_data.get('cleanPath')):
            m_link = re.search(r'/episodes/(\d+)', str(ep_data.get('link') or ep_data.get('cleanPath')))
            if m_link:
                ep_num = m_link.group(1)

        # 1. Direct field on target or ep_data (with sanity check against show name)
        t_url = (getattr(target, 'transcript_url', None) or getattr(target, 'transcript', None)
                 or ep_data.get('transcript_url') or ep_data.get('transcript')
                 or ep_data.get('podcast_transcript') or ep_data.get('transcriptUrl')
                 or ep_data.get('transcript_link') or '')
        if t_url:
            t_url = str(t_url).strip()
            if t_url:
                if not t_url.startswith('http://') and not t_url.startswith('https://'):
                    t_url = f"https://twit.tv/{t_url.lstrip('/')}"
                is_mismatch = False
                if show_str and ep_num:
                    s_lower = show_str.lower()
                    u_lower = t_url.lower()
                    if 'space' in s_lower and 'space' not in u_lower and ('tech-news' in u_lower or 'google' in u_lower or 'windows' in u_lower or 'twit' in u_lower):
                        is_mismatch = True
                    elif 'google' in s_lower and 'google' not in u_lower and ('space' in u_lower or 'tech-news' in u_lower):
                        is_mismatch = True
                    elif 'tech news weekly' in s_lower and 'tech-news' not in u_lower and ('space' in u_lower or 'google' in u_lower):
                        is_mismatch = True
                if not is_mismatch:
                    return t_url

        # 2. Check matched cached RSS items for THIS specific show
        show_key = show_str.lower().strip() if show_str else ''
        if show_key:
            matching_caches = []
            for k, v in getattr(self, '_show_rss_cache', {}).items():
                if show_key in k.lower() or k.lower().startswith(show_key):
                    matching_caches.append(v)
            for cache_items in matching_caches:
                for it in (cache_items or []):
                    match_num = ep_num and str(it.get('number', '')).strip() == str(ep_num).strip()
                    match_title = ep_title and str(it.get('title', '')).strip().lower() == str(ep_title).strip().lower()
                    if (match_num or match_title) and it.get('transcript_url'):
                        t_url = str(it['transcript_url']).strip()
                        if t_url:
                            if not t_url.startswith('http://') and not t_url.startswith('https://'):
                                t_url = f"https://twit.tv/{t_url.lstrip('/')}"
                            return t_url

        # Check general caches only when title matches or show name is in link/title
        for cache_items in [getattr(self, '_club_rss_cache', [])] + list(getattr(self, '_memberful_feeds_cache', {}).values()):
            for it in (cache_items or []):
                it_title = str(it.get('title', '')).strip().lower()
                it_link = str(it.get('link', '')).strip().lower()
                match_title = ep_title and ep_title.strip().lower() == it_title
                match_num = ep_num and str(it.get('number', '')).strip() == str(ep_num).strip()
                match_show = show_key and (show_key in it_title or show_key in it_link or (show_key.replace(' ', '-') in it_link))
                if ((match_title and (not show_key or match_show)) or (match_num and match_show)) and it.get('transcript_url'):
                    t_url = str(it['transcript_url']).strip()
                    if t_url:
                        if not t_url.startswith('http://') and not t_url.startswith('https://'):
                            t_url = f"https://twit.tv/{t_url.lstrip('/')}"
                        return t_url

        # 3. Direct candidate transcript URLs on twit.tv verified via fast HEAD request
        if show_str and ep_num:
            candidates = self.generate_transcript_slug_candidates(show_str, str(ep_num).strip())
            for cand in candidates:
                try:
                    r = requests.head(cand, headers={'User-Agent': 'TwitTUI/1.0'}, timeout=2.5)
                    if r.status_code == 200:
                        ep_data['transcript_url'] = cand
                        return cand
                except Exception:
                    pass

        # 4. Query TWiT API posts endpoint if episode ID exists
        ep_id = ep_data.get('id') or ep_data.get('guid') or ep_data.get('node_id') or ''
        if ep_id and str(ep_id).isdigit():
            try:
                load_twittui_dotenv()
                app_id = self.get_api_app_id()
                app_key = self.get_api_app_key()
                if app_id and app_key:
                    headers = {
                        'Accept': 'application/json',
                        'app-id': app_id,
                        'app-key': app_key
                    }
                    resp = requests.get(f'https://twit.tv/api/v1.0/posts?filter[episodes]={ep_id}&posts_type=transcripts', headers=headers, timeout=4)
                    if resp.status_code != 200 or not resp.json().get('posts'):
                        resp = requests.get(f'https://twit.tv/api/v1.0/posts?filter[episodes]={ep_id}', headers=headers, timeout=4)
                    if resp.status_code == 200:
                        posts = resp.json().get('posts', [])
                        for p in posts:
                            cp = p.get('cleanPath')
                            if cp:
                                t_url = f"https://twit.tv/{str(cp).lstrip('/')}"
                                ep_data['transcript_url'] = t_url
                                return t_url
            except Exception as e:
                print(f"Error querying transcript posts: {e}")

        # 5. Scrape cleanPath or web link for transcript href if available
        ep_link = ep_data.get('cleanPath') or ep_data.get('link') or ep_data.get('url') or ''
        if ep_link:
            if not str(ep_link).startswith('http://') and not str(ep_link).startswith('https://'):
                ep_link = f"https://twit.tv/{str(ep_link).lstrip('/')}"
            try:
                resp = requests.get(ep_link, headers={'User-Agent': 'TwitTUI/1.0'}, timeout=4)
                if resp.status_code == 200:
                    m = re.search(r'href=[\"\'](/posts/transcripts/[^\"\']+)[\"\']', resp.text, re.IGNORECASE)
                    if m:
                        t_url = f"https://twit.tv/{m.group(1).lstrip('/')}"
                        ep_data['transcript_url'] = t_url
                        return t_url
            except Exception as e:
                print(f"Error scraping transcript from webpage: {e}")

        return ''

    def extract_episode_metadata_fields(self, target, show_name: str = '') -> dict:
        """Extract all structured metadata fields for an episode."""
        ep_data = {}
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            ep_data.update(target.episode_data)
        elif isinstance(target, dict):
            if 'episode_data' in target and isinstance(target['episode_data'], dict):
                ep_data.update(target['episode_data'])
            else:
                ep_data.update(target)

        # Collect show name
        show = show_name or getattr(target, 'show', '') or ep_data.get('show_name') or ep_data.get('show')
        if not show and hasattr(self, 'show_combo') and self.show_combo:
            show = self.show_combo.value or ''
        if isinstance(show, dict):
            show = show.get('label') or show.get('title') or ''

        # Collect episode number
        ep_num = getattr(target, 'episode', '') or getattr(target, 'number', '') or ep_data.get('episode') or ep_data.get('number') or ep_data.get('episodeNumber') or ep_data.get('episode_number') or ''
        if not ep_num and ep_title:
            m_num = re.search(r'\b(?:episode|ep|twis|twit|twig|tnw|mbw|sn|ww|uls|iost)?\s*#?\s*(\d{1,5})\b', ep_title, re.IGNORECASE)
            if m_num:
                ep_num = m_num.group(1)
        if not ep_num and (ep_data.get('link') or ep_data.get('cleanPath')):
            m_link = re.search(r'/episodes/(\d+)', str(ep_data.get('link') or ep_data.get('cleanPath')))
            if m_link:
                ep_num = m_link.group(1)

        # Collect episode title
        ep_title = getattr(target, 'title', '') or ep_data.get('title') or ep_data.get('label') or ''

        # Collect date
        ep_date = getattr(target, 'date', '') or ep_data.get('date') or ep_data.get('airingDate') or ep_data.get('publishDate') or ep_data.get('pubDate') or ''

        # Collect duration / length
        ep_dur = getattr(target, 'length', '') or getattr(target, 'duration', '') or ep_data.get('length') or ep_data.get('duration') or ep_data.get('runningTime') or ''
        if ep_dur:
            ep_dur = self.format_duration(ep_dur)

        # Collect file size
        ep_size = getattr(target, 'size', '') or getattr(target, 'file_size', '') or ep_data.get('size') or ep_data.get('file_size') or ep_data.get('enclosure_length') or ''
        if not ep_size:
            ep_size = self.extract_size(ep_data) or ''
        ep_size_formatted = self.format_file_size(ep_size) if ep_size else ''

        # Collect ID / GUID / Node ID
        ep_id = ep_data.get('id') or ep_data.get('guid') or ep_data.get('node_id') or ''

        # Collect Web Link / CleanPath
        ep_link = ep_data.get('cleanPath') or ep_data.get('link') or ep_data.get('url') or ''
        if ep_link and not str(ep_link).startswith('http'):
            ep_link = f"https://twit.tv/{str(ep_link).lstrip('/')}"

        # Collect Transcript Link / URL
        transcript_url = self.resolve_transcript_url(target, show_name=show) or ''

        # Collect Media URL
        media_url = getattr(target, 'media_url', '') or ep_data.get('media_url') or ep_data.get('enclosure_url') or ''
        if not media_url:
            try:
                media_url = self.resolve_target_media_url(target) or ''
            except Exception:
                media_url = ''

        # Available formats
        formats = []
        for fmt_key, fmt_label in [
            ('video_hd', 'HD Video (1080p/720p)'),
            ('video_large', 'Large Video'),
            ('video_small', 'Small/Mobile Video'),
            ('video_audio', 'Audio (MP3/M4A)'),
            ('audio', 'Audio'),
            ('video_youtube', 'YouTube Stream')
        ]:
            if fmt_key in ep_data and ep_data[fmt_key]:
                formats.append(fmt_label)

        # Hosts / Guests / People
        people_list = []
        for p_key in ['hosts', 'guests', 'people', 'staff']:
            val = ep_data.get(p_key)
            if isinstance(val, list):
                for p in val:
                    if isinstance(p, dict):
                        name = p.get('label') or p.get('name') or p.get('title')
                        if name:
                            people_list.append(str(name))
                    elif isinstance(p, str) and p.strip():
                        people_list.append(p.strip())
            elif isinstance(val, str) and val.strip():
                people_list.append(val.strip())

        # Topics / Categories / Tags
        topics_list = []
        for t_key in ['topics', 'tags', 'categories']:
            val = ep_data.get(t_key)
            if isinstance(val, list):
                for t in val:
                    if isinstance(t, dict):
                        name = t.get('label') or t.get('name') or t.get('title')
                        if name:
                            topics_list.append(str(name))
                    elif isinstance(t, str) and t.strip():
                        topics_list.append(t.strip())
            elif isinstance(val, str) and val.strip():
                topics_list.append(val.strip())

        # Description / Show notes
        desc_raw = ep_data.get('description') or ep_data.get('summary') or ep_data.get('body') or ep_data.get('teaser') or ep_data.get('snippet') or ''
        desc_clean = self.clean_html_text(desc_raw)

        header_title = f"Episode Details: {ep_title}" if ep_title else "Episode Details"
        if len(header_title) > 60:
            header_title = header_title[:57] + "..."

        return {
            'header_title': header_title,
            'show': show,
            'episode': ep_num,
            'title': ep_title,
            'date': ep_date,
            'duration': ep_dur,
            'size': ep_size_formatted,
            'file_size': ep_size_formatted,
            'id': ep_id,
            'link': ep_link,
            'transcript_url': transcript_url,
            'transcript': transcript_url,
            'media_url': media_url,
            'formats': formats,
            'people': people_list,
            'topics': topics_list,
            'description': desc_clean,
            'raw_data': ep_data
        }

    def format_episode_metadata(self, target, show_name: str = '') -> tuple[str, str]:
        """Format all available metadata for an episode into a human-readable title and description."""
        meta = self.extract_episode_metadata_fields(target, show_name=show_name)
        show = meta['show']
        ep_num = meta['episode']
        ep_title = meta['title']
        ep_date = meta['date']
        ep_dur = meta['duration']
        ep_size = meta.get('size')
        ep_id = meta['id']
        ep_link = meta['link']
        transcript_url = meta.get('transcript_url') or meta.get('transcript') or ''
        media_url = meta['media_url']
        formats = meta['formats']
        people_list = meta['people']
        topics_list = meta['topics']
        desc_clean = meta['description']

        lines = []
        if show:
            lines.append(f"Show: {show}")
        if ep_num and str(ep_num) != 'Unknown Number':
            lines.append(f"Episode: {ep_num}")
        if ep_title and str(ep_title) != 'Unknown Title':
            lines.append(f"Title: {ep_title}")
        if ep_date and str(ep_date) != 'Unknown Date':
            lines.append(f"Date: {ep_date}")
        if ep_dur:
            lines.append(f"Duration: {ep_dur}")
        if ep_size:
            lines.append(f"Size: {ep_size}")
        if ep_id:
            lines.append(f"ID / GUID: {ep_id}")
        if ep_link:
            lines.append(f"Web Link: {ep_link}")
        if transcript_url:
            lines.append(f"Transcript: {transcript_url}")
        if media_url:
            lines.append(f"Media URL: {media_url}")
        if formats:
            lines.append(f"Available Formats: {', '.join(formats)}")
        if people_list:
            lines.append(f"Hosts / Guests: {', '.join(people_list)}")
        if topics_list:
            lines.append(f"Topics: {', '.join(topics_list)}")

        if desc_clean:
            lines.append("")
            lines.append("Description / Show Notes:")
            lines.append(desc_clean)

        return meta['header_title'], "\n".join(lines)

    def show_episode_metadata_dialog(self, target) -> None:
        """Display a popup dialog/window with all metadata for the specified episode, featuring clickable Web and Media URLs."""
        if not target:
            return

        meta = self.extract_episode_metadata_fields(target)
        title, message = self.format_episode_metadata(target)
        if not message:
            message = "No metadata available for this episode."

        def _on_closed(window=None, result=None):
            self._dialog_open = False
            self._hover_row_index = None
            self._metadata_window = None
            return True

        def _close_meta_window(widget=None):
            try:
                if getattr(self, '_metadata_window', None) is not None:
                    self._metadata_window.close()
            except Exception:
                pass
            _on_closed()

        def _show():
            try:
                self._dialog_open = True
                self._cancel_hover_timer()

                # If an existing metadata window is open, close it first
                if getattr(self, '_metadata_window', None) is not None:
                    try:
                        self._metadata_window.close()
                    except Exception:
                        pass
                    self._metadata_window = None

                # Build rich custom dialog window with clickable URLs
                win_title = meta.get('header_title') or title or "Episode Details"
                win = toga.Window(title=win_title, size=(750, 650), on_close=_on_closed)
                self._metadata_window = win

                content_box = toga.Box(style=Pack(direction=COLUMN, margin=10))

                # Title
                ep_title = meta.get('title') or ''
                if ep_title:
                    content_box.add(toga.Label(ep_title, style=Pack(font_size=13, font_weight='bold', margin_bottom=6), tooltip='Episode title'))

                # Metadata Key-Values
                meta_rows = []
                if meta.get('show'):
                    meta_rows.append(f"Show: {meta['show']}")
                if meta.get('episode') and str(meta['episode']) != 'Unknown Number':
                    meta_rows.append(f"Episode: {meta['episode']}")
                if meta.get('date') and str(meta['date']) != 'Unknown Date':
                    meta_rows.append(f"Date: {meta['date']}")
                if meta.get('duration'):
                    meta_rows.append(f"Duration: {meta['duration']}")
                if meta.get('size'):
                    meta_rows.append(f"Size: {meta['size']}")
                if meta.get('id'):
                    meta_rows.append(f"ID / GUID: {meta['id']}")

                for row_text in meta_rows:
                    content_box.add(toga.Label(row_text, style=Pack(margin_bottom=3), tooltip=f'Metadata: {row_text}'))

                # Web Link (Clickable)
                ep_link = meta.get('link') or ''
                if ep_link:
                    link_box = toga.Box(style=Pack(direction=ROW, margin_top=4, margin_bottom=4, align_items='center'))
                    link_box.add(toga.Label("Web Link:", style=Pack(width=90, font_weight='bold', margin_right=4), tooltip='Episode webpage link'))
                    link_btn = toga.Button(
                        ep_link,
                        on_press=lambda w, u=ep_link: self.open_url_in_browser(u),
                        style=Pack(flex=1),
                        tooltip=f'Open episode webpage in browser: {ep_link}'
                    )
                    link_box.add(link_btn)
                    content_box.add(link_box)

                # Transcript Link (Clickable)
                transcript_url = meta.get('transcript_url') or meta.get('transcript') or ''
                if transcript_url:
                    transcript_box = toga.Box(style=Pack(direction=ROW, margin_top=4, margin_bottom=4, align_items='center'))
                    transcript_box.add(toga.Label("Transcript:", style=Pack(width=90, font_weight='bold', margin_right=4), tooltip='Episode transcript link'))
                    transcript_btn = toga.Button(
                        transcript_url,
                        on_press=lambda w, u=transcript_url: self.open_url_in_browser(u),
                        style=Pack(flex=1),
                        tooltip=f'Open transcript in browser: {transcript_url}'
                    )
                    transcript_box.add(transcript_btn)
                    content_box.add(transcript_box)

                # Media URL (Clickable)
                media_url = meta.get('media_url') or ''
                if media_url:
                    media_box = toga.Box(style=Pack(direction=ROW, margin_top=4, margin_bottom=4, align_items='center'))
                    media_box.add(toga.Label("Media URL:", style=Pack(width=90, font_weight='bold', margin_right=4), tooltip='Direct media stream link'))
                    media_btn = toga.Button(
                        media_url,
                        on_press=lambda w, u=media_url: self.open_url_in_browser(u),
                        style=Pack(flex=1),
                        tooltip=f'Open media stream in browser: {media_url}'
                    )
                    media_box.add(media_btn)
                    content_box.add(media_box)

                # Available Formats
                if meta.get('formats'):
                    content_box.add(toga.Label(f"Available Formats: {', '.join(meta['formats'])}", style=Pack(margin_top=3, margin_bottom=3), tooltip='Available media formats for this episode'))

                # Hosts / Guests
                if meta.get('people'):
                    content_box.add(toga.Label(f"Hosts / Guests: {', '.join(meta['people'])}", style=Pack(margin_top=3, margin_bottom=3), tooltip='Hosts and guests appearing in this episode'))

                # Topics
                if meta.get('topics'):
                    content_box.add(toga.Label(f"Topics: {', '.join(meta['topics'])}", style=Pack(margin_top=3, margin_bottom=3), tooltip='Topics discussed in this episode'))

                # Description / Show notes
                desc_text = meta.get('description') or ''
                if desc_text:
                    content_box.add(toga.Label("Description / Show Notes:", style=Pack(font_weight='bold', margin_top=6, margin_bottom=4), tooltip='Episode description and show notes'))
                    desc_input = toga.MultilineTextInput(
                        value=desc_text,
                        readonly=True,
                        style=Pack(flex=1, height=220, margin_bottom=6),
                        tooltip='Episode description and show notes'
                    )
                    content_box.add(desc_input)

                # Bottom Action Bar
                btn_box = toga.Box(style=Pack(direction=ROW, margin_top=6, align_items='center'))
                btn_box.add(toga.Box(style=Pack(flex=1)))
                close_btn = toga.Button('Close', on_press=_close_meta_window, style=Pack(width=100), tooltip='Close episode details window')
                btn_box.add(close_btn)
                content_box.add(btn_box)

                # Top-level window layout container
                win.content = content_box
                win.show()

            except Exception as e:
                print(f"Error displaying custom episode metadata window ({e}), falling back to info_dialog.")
                try:
                    if hasattr(self, 'main_window') and self.main_window:
                        self.main_window.info_dialog(title, message, on_result=_on_closed)
                except Exception as inner_e:
                    print(f"Error displaying fallback info_dialog: {inner_e}")
                    _on_closed()

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(_show)
            except Exception:
                _show()
        else:
            _show()

    def _cancel_hover_timer_locked(self) -> None:
        """Cancel active hover timer while holding lock."""
        if getattr(self, '_hover_timer', None) is not None:
            try:
                self._hover_timer.cancel()
            except Exception:
                pass
            self._hover_timer = None

    def _cancel_hover_timer(self) -> None:
        """Cancel active hover timer and clear hovered row index."""
        if not hasattr(self, '_hover_lock'):
            self._hover_lock = threading.Lock()
        with self._hover_lock:
            self._cancel_hover_timer_locked()
            self._hover_row_index = None

    def _trigger_hover_metadata(self, row_idx: int) -> None:
        """Triggered after 3 seconds of continuous hover over an episode row."""
        with self._hover_lock:
            if getattr(self, '_dialog_open', False):
                return
            if self._hover_row_index != row_idx:
                return
            self._hover_timer = None

        def _show():
            try:
                if not hasattr(self, 'episodes_list') or not self.episodes_list or not self.episodes_list.data:
                    return
                if row_idx < 0 or row_idx >= len(self.episodes_list.data):
                    return
                row_item = self.episodes_list.data[row_idx]
                self.show_episode_metadata_dialog(row_item)
            except Exception as e:
                print(f"Error displaying episode metadata dialog: {e}")

        if hasattr(self, 'loop') and self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(_show)
            except Exception:
                _show()
        else:
            _show()

    def _on_table_motion_notify(self, widget, event) -> bool:
        """Handle mouse motion over episodes table and track 3-second hover dwell time."""
        if getattr(self, '_dialog_open', False):
            self._cancel_hover_timer()
            return False

        try:
            x, y = int(event.x), int(event.y)
            path_info = widget.get_path_at_pos(x, y)
            if path_info:
                path = path_info[0]
                indices = path.get_indices()
                if indices and len(indices) > 0:
                    row_idx = indices[0]
                    with self._hover_lock:
                        if self._hover_row_index != row_idx:
                            self._cancel_hover_timer_locked()
                            self._hover_row_index = row_idx
                            self._hover_timer = threading.Timer(3.0, self._trigger_hover_metadata, args=(row_idx,))
                            self._hover_timer.daemon = True
                            self._hover_timer.start()
                    return False
        except Exception:
            pass

        self._cancel_hover_timer()
        return False

    def _on_table_leave_notify(self, widget, event) -> bool:
        """Cancel hover timer when mouse pointer leaves the episodes table."""
        self._cancel_hover_timer()
        return False

    def _setup_table_hover_events(self) -> None:
        """Set up hover tracking on the episodes table to show metadata dialog after 3 seconds."""
        if not hasattr(self, 'episodes_list') or not self.episodes_list:
            return

        impl = getattr(self.episodes_list, '_impl', None)
        if not impl:
            return

        native_table = getattr(impl, 'native_table', None)
        if native_table and hasattr(native_table, 'connect'):
            if getattr(self, '_table_hover_connected', False):
                return
            try:
                from gi.repository import Gdk
                native_table.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
                native_table.connect('motion-notify-event', self._on_table_motion_notify)
                native_table.connect('leave-notify-event', self._on_table_leave_notify)
                self._table_hover_connected = True
            except Exception:
                try:
                    native_table.connect('motion-notify-event', self._on_table_motion_notify)
                    native_table.connect('leave-notify-event', self._on_table_leave_notify)
                    self._table_hover_connected = True
                except Exception:
                    pass

    def update_episodes_display(self) -> None:
        """Format and display current episodes based on selected sort order."""
        if not hasattr(self, 'episodes_list') or self.episodes_list is None:
            return

        self._cancel_hover_timer()

        if not self.current_episodes:
            self.episodes_list.data = []
            self._enable_table_horizontal_scroll()
            self._setup_table_hover_events()
            return

        episodes = list(self.current_episodes)
        sort_by = 'date'
        if hasattr(self, 'episode_radio') and self.episode_radio and '☑' in self.episode_radio.text:
            sort_by = 'number'
        elif hasattr(self, 'title_radio') and self.title_radio and '☑' in self.title_radio.text:
            sort_by = 'title'

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
            table_data.append({
                'episode': str(number),
                'title': str(title),
                'date': str(date),
                'length': str(formatted_length),
                'duration': str(formatted_length),
                'size': str(formatted_size),
                'file_size': str(formatted_size),
                'media_url': media_url,
                'episode_data': episode
            })

        self.episodes_list.data = table_data
        self._enable_table_horizontal_scroll()
        self._setup_table_hover_events()

    def on_search_press(self, widget=None) -> None:
        """Execute search query against selected show episodes and populate table with matches."""
        self._cancel_hover_timer()
        query = self.search_input.value.strip() if hasattr(self, 'search_input') and self.search_input and self.search_input.value else ''
        if not query:
            self.load_episodes_for_selected_show()
            return

        selected_show = self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo else ''
        show_id = self.show_ids.get(selected_show) if hasattr(self, 'show_ids') and selected_show in self.show_ids else None

        results = self.search_episodes(query, show_id=show_id, show_name=selected_show)
        self.current_episodes = results
        self.update_episodes_display()

    def on_clear_search_press(self, widget=None) -> None:
        """Clear search input text and restore full episode catalog for selected show."""
        self._cancel_hover_timer()
        if hasattr(self, 'search_input') and self.search_input:
            self.search_input.value = ''
        self.load_episodes_for_selected_show()

    def load_episodes_for_selected_show(self) -> None:
        """Fetch and display episodes for currently selected show in the combo box."""
        self._cancel_hover_timer()
        self.current_page = 1
        selected_show = self.show_combo.value
        if selected_show and hasattr(self, 'show_ids') and selected_show in self.show_ids:
            show_id = self.show_ids[selected_show]
            self.current_episodes = self.fetch_episodes(show_id, page=1)
            self.update_episodes_display()
        else:
            self.current_episodes = []
            self.update_episodes_display()

    def on_show_select(self, widget) -> None:
        """Handle show selection change."""
        self.current_page = 1
        if hasattr(self, 'search_input') and self.search_input and self.search_input.value and self.search_input.value.strip():
            self.on_search_press()
        else:
            self.load_episodes_for_selected_show()

    def on_fetch_press(self, widget) -> None:
        """Fetch episodes for the selected show and refresh the show list."""
        self.current_page = 1
        shows = self.fetch_shows()
        if shows:
            current_selection = self.show_combo.value
            self.show_combo.items = shows
            if current_selection in shows:
                self.show_combo.value = current_selection

        if hasattr(self, 'search_input') and self.search_input and self.search_input.value and self.search_input.value.strip():
            self.on_search_press()
        else:
            self.load_episodes_for_selected_show()

    def on_next_press(self, widget) -> None:
        """Fetch the next page of episodes for the currently selected show."""
        selected_show = self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo else ''
        if not selected_show or not hasattr(self, 'show_ids') or selected_show not in self.show_ids:
            return

        show_id = self.show_ids[selected_show]
        next_page = getattr(self, 'current_page', 1) + 1
        new_episodes = self.fetch_episodes(show_id, page=next_page)

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
        self.date_radio.text = self.date_radio.text.replace('☑', '☐')
        self.episode_radio.text = self.episode_radio.text.replace('☑', '☐')
        self.title_radio.text = self.title_radio.text.replace('☑', '☐')

        if widget == self.date_radio:
            self.date_radio.text = self.date_radio.text.replace('☐', '☑')
        elif widget == self.episode_radio:
            self.episode_radio.text = self.episode_radio.text.replace('☐', '☑')
        elif widget == self.title_radio:
            self.title_radio.text = self.title_radio.text.replace('☐', '☑')

        if hasattr(self, 'date_radio') and self.date_radio:
            self.date_radio.tooltip = "Sort episodes by release date" + (" (active)" if widget == self.date_radio else "")
        if hasattr(self, 'episode_radio') and self.episode_radio:
            self.episode_radio.tooltip = "Sort episodes by episode number" + (" (active)" if widget == self.episode_radio else "")
        if hasattr(self, 'title_radio') and self.title_radio:
            self.title_radio.tooltip = "Sort episodes alphabetically by title" + (" (active)" if widget == self.title_radio else "")

        self.load_episodes_for_selected_show()

def main():
    return TwitTUIForm('TWIT.tv TUI', 'org.beeware.twittui')

if __name__ == '__main__':
    from main import resolve_toga_backend
    resolve_toga_backend()
    load_twittui_dotenv()
    app = main()
    app.main_loop()
