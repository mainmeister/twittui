import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW
import os
import re
import subprocess
import threading
import urllib.parse
import email.utils
import xml.etree.ElementTree as ET
import tempfile
import pathlib
import webbrowser
import html
import requests
import http.server
from dotenv import load_dotenv, set_key

# Ensure environment variables are loaded
load_dotenv()

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

class _LocalHTMLServer(http.server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.pages = {}
        self.lock = threading.Lock()

class _LocalHTMLHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path_key = parsed.path.lstrip('/') or 'index.html'

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
    def __init__(self, formal_name=None, app_id=None, **kwargs):
        self.show_ids = {}
        self.current_episodes = []
        self._club_rss_cache = None
        self._memberful_feeds_cache = {}
        self._show_rss_cache = {}
        self._local_server = None
        self.app_id_input = None
        self.app_key_input = None
        self.audio_only_checkbox = None
        self.progress_bar = None
        self._is_downloading = False
        self._cancel_download = False
        super().__init__(formal_name=formal_name, app_id=app_id, **kwargs)

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
        """Persist a configuration setting key-value pair to the .env file."""
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
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
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
        val_str = '1' if is_audio else '0'
        os.environ['TWITAUDIOONLY'] = val_str
        self.save_env_setting('TWITAUDIOONLY', val_str)

        self.update_episodes_display()

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
                root = ET.fromstring(resp.content)
                items = []
                for item in root.findall('.//item'):
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    guid_elem = item.find('guid')
                    enclosure_elem = item.find('enclosure')
                    pubdate_elem = item.find('pubDate')

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

                    item_data = {
                        'title': title_str,
                        'number': ep_num,
                        'date': date_str,
                        'link': link_elem.text.strip() if link_elem is not None and link_elem.text else '',
                        'guid': guid_elem.text.strip() if guid_elem is not None and guid_elem.text else '',
                        'pubDate': pub_str,
                        'enclosure_url': enc_url
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
                    root = ET.fromstring(resp.content)
                    for item in root.findall('.//item'):
                        title_elem = item.find('title')
                        link_elem = item.find('link')
                        enclosure_elem = item.find('enclosure')
                        pubdate_elem = item.find('pubDate')

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
                        if enc_url and self.is_valid_media_url(enc_url):
                            items.append({
                                'title': title_str,
                                'number': ep_num,
                                'date': date_str,
                                'link': link_elem.text.strip() if link_elem is not None and link_elem.text else '',
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
            load_dotenv()
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
        # Main box with vertical layout
        main_box = toga.Box(style=Pack(direction=COLUMN, margin=5))

        # Show selection section
        show_label = toga.Label('Show:', style=Pack(margin=(0, 5)))
        self.show_combo = toga.Selection(on_change=self.on_show_select, style=Pack(flex=1))
        fetch_button = toga.Button('Fetch', on_press=self.on_fetch_press, style=Pack(margin=5))
        show_box = toga.Box(style=Pack(direction=ROW, margin=5))
        show_box.add(show_label)
        show_box.add(self.show_combo)
        show_box.add(fetch_button)

        # Sort options section
        sort_label = toga.Label('Sort by:', style=Pack(margin=(0, 5)))
        self.date_radio = toga.Button('☑ Date', on_press=self.on_sort_button_press, style=Pack(margin=5))
        self.episode_radio = toga.Button('☐ Episode Number', on_press=self.on_sort_button_press, style=Pack(margin=5))
        self.title_radio = toga.Button('☐ Episode Title', on_press=self.on_sort_button_press, style=Pack(margin=5))

        env_audio = os.getenv('TWITAUDIOONLY') or os.getenv('twitaudioonly') or os.getenv('TWIT_AUDIO_ONLY') or ''
        initial_audio_only = env_audio.strip().lower() in ('1', 'true', 'yes', 'on')
        audio_symbol = '☑' if initial_audio_only else '☐'
        self.audio_only_checkbox = toga.Button(f'{audio_symbol} Audio Only', on_press=self.on_audio_only_toggle, style=Pack(margin=5))

        sort_box = toga.Box(style=Pack(direction=ROW, margin=5))
        sort_box.add(sort_label)
        sort_box.add(self.date_radio)
        sort_box.add(self.episode_radio)
        sort_box.add(self.title_radio)
        sort_box.add(self.audio_only_checkbox)

        # Episodes list section
        episodes_label = toga.Label('Episodes:', style=Pack(margin=(0, 5)))
        self.episodes_list = toga.Table(
            headings=['Episode', 'Title', 'Date'],
            multiple_select=True,
            on_activate=lambda widget, row: self.on_stream_press(widget),
            style=Pack(flex=1, margin=5, height=200)
        )

        # Populate the show combo with show names and load initial episodes
        shows = self.fetch_shows()
        if shows:
            self.show_combo.items = shows
            self.load_episodes_for_selected_show()
        else:
            self.episodes_list.data = []

        # Buttons section
        button_box = toga.Box(style=Pack(direction=ROW, margin=5))
        download_button = toga.Button('Download', on_press=self.on_download_press, style=Pack(margin=5))
        stream_button = toga.Button('Stream', on_press=self.on_stream_press, style=Pack(margin=5))
        cancel_button = toga.Button('Cancel', on_press=self.on_cancel_press, style=Pack(margin=5))
        close_button = toga.Button('Close', on_press=self.on_close_press, style=Pack(margin=5))

        button_box.add(download_button)
        button_box.add(stream_button)
        button_box.add(cancel_button)
        button_box.add(close_button)

        # Settings section
        settings_box = toga.Box(style=Pack(direction=COLUMN, margin=5))

        # TWIT API Application ID setting
        app_id_box = toga.Box(style=Pack(direction=ROW, margin=5))
        app_id_label = toga.Label('API Application ID:', style=Pack(margin=(0, 5)))
        initial_app_id = os.getenv('TWITAPI_APPLICATIONID') or os.getenv('twitapi_applicationid') or ''
        self.app_id_input = toga.TextInput(value=initial_app_id, style=Pack(flex=1))
        app_id_box.add(app_id_label)
        app_id_box.add(self.app_id_input)

        # TWIT API Application Key setting
        app_key_box = toga.Box(style=Pack(direction=ROW, margin=5))
        app_key_label = toga.Label('API Application Key:', style=Pack(margin=(0, 5)))
        initial_app_key = os.getenv('TWITAPI_APPLICATIONKEYS') or os.getenv('twitapi_applicationkeys') or ''
        self.app_key_input = toga.TextInput(value=initial_app_key, style=Pack(flex=1))
        test_api_button = toga.Button('Test API', on_press=self.on_test_api_press, style=Pack(margin=5))
        app_key_box.add(app_key_label)
        app_key_box.add(self.app_key_input)
        app_key_box.add(test_api_button)

        # TWIT Club URL setting
        url_box = toga.Box(style=Pack(direction=ROW, margin=5))
        url_label = toga.Label('TWIT Club URL:', style=Pack(margin=(0, 5)))
        url_prefix = toga.Label('https://twit.memberfulcontent.com/rss/9041?auth=', style=Pack(margin=(0, 5)))
        twit_club_url = os.getenv('twitcluburl') or os.getenv('TWITCLUBURL') or os.getenv('TWIT_CLUB_URL') or ''
        auth_prefix = 'https://twit.memberfulcontent.com/rss/9041?auth='
        if twit_club_url.startswith(auth_prefix):
            initial_url_key = twit_club_url[len(auth_prefix):]
        elif '?auth=' in twit_club_url:
            initial_url_key = twit_club_url.split('?auth=', 1)[1]
        else:
            initial_url_key = twit_club_url
        self.url_input = toga.TextInput(value=initial_url_key, style=Pack(flex=1))
        show_url_button = toga.Button('Show', on_press=self.on_show_club_url_press, style=Pack(margin=5))
        url_box.add(url_label)
        url_box.add(url_prefix)
        url_box.add(self.url_input)
        url_box.add(show_url_button)

        # Destination folder setting
        dest_box = toga.Box(style=Pack(direction=ROW, margin=5))
        dest_label = toga.Label('Download Destination:', style=Pack(margin=(0, 5)))
        initial_dest = os.getenv('twitclubdestination') or os.getenv('TWITCLUBDESTINATION') or os.getenv('TWIT_CLUB_DESTINATION') or ''
        self.dest_input = toga.TextInput(value=initial_dest, style=Pack(flex=1))
        dest_button = toga.Button('Browse', on_press=self.on_browse_press, style=Pack(margin=5))
        dest_box.add(dest_label)
        dest_box.add(self.dest_input)
        dest_box.add(dest_button)

        # Block size setting
        block_box = toga.Box(style=Pack(direction=ROW, margin=5))
        block_label = toga.Label('Block Size:', style=Pack(margin=(0, 5)))
        initial_block = os.getenv('twitclubblocksize') or os.getenv('TWITCLUBBLOCKSIZE') or '8192'
        self.block_input = toga.TextInput(value=initial_block, style=Pack(flex=1))
        block_box.add(block_label)
        block_box.add(self.block_input)

        # Streamer setting
        streamer_box = toga.Box(style=Pack(direction=ROW, margin=5))
        streamer_label = toga.Label('Streamer:', style=Pack(margin=(0, 5)))
        initial_streamer = os.getenv('twitclubstreamer') or os.getenv('TWITCLUBSTREAMER') or os.getenv('TWIT_CLUB_STREAMER') or 'vlc %f'
        self.streamer_input = toga.TextInput(value=initial_streamer, style=Pack(flex=1))
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
        self.progress_bar = toga.ProgressBar(max=100.0, value=0.0, style=Pack(flex=1, margin=5))

        # Add all components to main box
        main_box.add(show_box)
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
            group=toga.Group.HELP,
            section=0,
            order=1
        )
        apib_cmd = toga.Command(
            self.on_open_apib,
            text='View API Specification (twittv.apib)',
            group=toga.Group.HELP,
            section=0,
            order=2
        )
        api_key_cmd = toga.Command(
            self.on_open_api_key_url,
            text='Get TWiT API Key',
            group=toga.Group.HELP,
            section=0,
            order=3
        )
        self.commands.add(readme_cmd)
        self.commands.add(apib_cmd)
        self.commands.add(api_key_cmd)

        self.main_window.show()

    def sanitize_html(self, html_str: str) -> str:
        """Sanitize HTML content to prevent script injection and malicious payloads."""
        if not html_str:
            return ""

        # Attempt to use bleach if available
        try:
            import bleach
            return bleach.clean(
                html_str,
                tags=[
                    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
                    "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                    "blockquote", "strong", "em", "a", "hr", "br", "span", "div"
                ],
                attributes={"a": ["href", "title", "id", "name"], "th": ["align"], "td": ["align"], "*": ["class", "id"]},
                protocols=["http", "https", "mailto"]
            )
        except ImportError:
            pass

        # Attempt to use nh3 if available
        try:
            import nh3
            return nh3.clean(
                html_str,
                tags={
                    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
                    "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                    "blockquote", "strong", "em", "a", "hr", "br", "span", "div"
                },
                attributes={"a": {"href", "title", "id", "name"}, "th": {"align"}, "td": {"align"}, "*": {"class", "id"}},
                url_schemes={"http", "https", "mailto"}
            )
        except ImportError:
            pass

        # Defensive sanitization fallback
        dangerous_tags = [
            "script", "style", "iframe", "object", "embed", "applet",
            "form", "input", "button", "link", "meta", "svg", "base"
        ]
        sanitized = html_str
        for tag in dangerous_tags:
            sanitized = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", "", sanitized, flags=re.IGNORECASE | re.DOTALL)
            sanitized = re.sub(rf"<{tag}\b[^>]*/>", "", sanitized, flags=re.IGNORECASE)
            sanitized = re.sub(rf"<{tag}\b[^>]*>", "", sanitized, flags=re.IGNORECASE)

        # Strip all inline event handlers (e.g., onload, onclick, onerror)
        sanitized = re.sub(r"\s+on[a-zA-Z]+\s*=\s*(?:\"[^\"]*\"|\'[^\']*\'|[^\s>]+)", "", sanitized, flags=re.IGNORECASE)

        # Neutralize unsafe URI schemes in links or source attributes
        sanitized = re.sub(
            r'href\s*=\s*[\"\']?\s*(?:javascript|data|vbscript|file):[^\">\s]*[\"\']?',
            'href="#"',
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
            os.makedirs(cache_dir, mode=0o755, exist_ok=True)
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
            webbrowser.open(f"http://127.0.0.1:{port}/{page_name}")
            return

        # Fallback to local HTML file in cache directory if local HTTP server unavailable
        cache_dir = self.get_app_cache_dir()
        temp_file = tempfile.NamedTemporaryFile("w", dir=cache_dir, delete=False, suffix=".html", encoding="utf-8")
        temp_file.write(html_content)
        temp_file.close()
        try:
            os.chmod(temp_file.name, 0o644)
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

        # If lxml and feed-style.xsl are available, attempt XSLT transformation
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
                with open(xsl_path, "rb") as xf:
                    xslt_doc = etree.XML(xf.read())
                transform = etree.XSLT(xslt_doc)
                src_doc = etree.fromstring(xml_bytes)
                result_tree = transform(src_doc)
                html_out = str(result_tree)
                if css_content and '<style>' in html_out and '</style>' in html_out:
                    style_start = html_out.find('<style>') + 7
                    style_end = html_out.find('</style>')
                    html_out = html_out[:style_start] + "\n" + css_content + "\n" + html_out[style_end:]
                return html_out
            except Exception as xslt_err:
                print(f"XSLT rendering fallback ({xslt_err}), using Python RSS renderer.")

        # ElementTree parser fallback
        try:
            root = ET.fromstring(xml_bytes)
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

                title_html = f'<a href="{html.escape(link)}" target="_blank" rel="noopener noreferrer">{html.escape(title)}</a>' if link else html.escape(title)

                meta_parts = []
                if pub_date:
                    meta_parts.append(f'<span>Published: {html.escape(pub_date)}</span>')
                if duration:
                    meta_parts.append(f'<span>Duration: {html.escape(duration)}</span>')
                if episode_no:
                    meta_parts.append(f'<span>Episode #{html.escape(episode_no)}</span>')
                meta_html = f'<div class="episode-meta">{" ".join(meta_parts)}</div>' if meta_parts else ''

                media_html = ''
                if enc_url:
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

            image_html = f'<img class="channel-image" src="{html.escape(ch_image)}" alt="Podcast Cover Art" />' if ch_image else ''
            author_html = f'<span>Author: {html.escape(ch_author)}</span>' if ch_author else ''
            lang_html = f'<span>Language: {html.escape(ch_lang)}</span>' if ch_lang else ''
            link_html = f'<a href="{html.escape(ch_link)}" target="_blank" rel="noopener noreferrer">Visit Website</a>' if ch_link else ''

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

    def download_episode_file(self, url: str, dest_path: str, block_size: int = 8192, progress_callback=None) -> bool:
        """Stream and save a media file in chunks using the specified block size."""
        temp_path = dest_path + '.part'
        try:
            if progress_callback is None:
                self.reset_progress()
            os.makedirs(os.path.dirname(dest_path) or '.', exist_ok=True)
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'}
            with requests.get(url, stream=True, headers=headers, timeout=30) as r:
                r.raise_for_status()
                total_bytes = 0
                content_length = r.headers.get('content-length')
                if content_length and content_length.isdigit():
                    total_bytes = int(content_length)

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

    def download_episodes_batch(self, targets: list) -> None:
        """Background worker to download multiple selected episodes."""
        self._is_downloading = True
        self._cancel_download = False
        self.reset_progress()
        dest_dir = self.get_destination_folder()
        block_size = self.get_block_size()
        downloaded_files = []
        total_targets = len(targets) if targets else 1

        print(f"Starting batch download for {len(targets)} episode(s) to '{dest_dir}' (block size: {block_size})...")
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception as e:
            print(f"Error creating destination directory '{dest_dir}': {e}")
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
                media_url = self.resolve_target_media_url(target)
                if not media_url:
                    print(f"[{idx_0 + 1}/{total_targets}] No media URL found for episode: {target_num} {target_title}")
                    batch_pct = ((idx_0 + 1) / total_targets) * 100.0
                    self.update_progress(batch_pct, 100.0)
                    continue

                filename = self.determine_download_filename(target, media_url)
                dest_filepath = os.path.join(dest_dir, filename)

                print(f"[{idx_0 + 1}/{total_targets}] Downloading '{target_title}' -> {dest_filepath} from {media_url}")

                def _item_progress(downloaded_bytes: int, total_bytes: int, item_idx=idx_0):
                    if total_bytes > 0:
                        item_frac = min(1.0, max(0.0, downloaded_bytes / total_bytes))
                    else:
                        item_frac = 0.0
                    batch_pct = ((item_idx + item_frac) / total_targets) * 100.0
                    self.update_progress(batch_pct, 100.0)

                success = self.download_episode_file(media_url, dest_filepath, block_size, progress_callback=_item_progress)
                if success:
                    downloaded_files.append(filename)

                batch_pct = ((idx_0 + 1) / total_targets) * 100.0
                self.update_progress(batch_pct, 100.0)
        finally:
            self._is_downloading = False
            if getattr(self, '_cancel_download', False):
                self.reset_progress()
            if downloaded_files:
                self.show_download_complete_dialog(dest_dir, downloaded_files)

    def on_download_press(self, widget=None) -> None:
        """Process selected episodes for batch download."""
        try:
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

            # Start download in background thread so GUI remains responsive
            thread = threading.Thread(target=self.download_episodes_batch, args=(targets,), daemon=True)
            thread.start()
        except Exception as e:
            print(f"Error initiating download: {e}")

    def format_stream_command(self, streamer_template: str, url: str) -> str:
        """Format the streamer command string with the episode media URL."""
        template = (streamer_template or 'vlc %f').strip()
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

    def on_stream_press(self, widget=None) -> None:
        """Process selected episode for streaming."""
        try:
            selected = self.episodes_list.selection
            if not selected:
                print("No episode selected for streaming")
                return

            target = selected[0] if isinstance(selected, list) else selected

            media_url = self.resolve_target_media_url(target)

            if not media_url:
                print("No media URL found for the selected episode")
                return

            streamer_template = self.streamer_input.value if self.streamer_input and self.streamer_input.value else 'vlc %f'
            command = self.format_stream_command(streamer_template, media_url)
            print(f"Launching streamer: {command}")
            subprocess.Popen(command, shell=True)
        except Exception as e:
            print(f"Error launching stream: {e}")

    def on_cancel_press(self, widget) -> None:
        if getattr(self, '_is_downloading', False):
            print("Cancelling active download...")
            self._cancel_download = True
            self.reset_progress()
        else:
            self.exit()

    def on_close_press(self, widget) -> None:
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
            load_dotenv()
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

    def fetch_episodes(self, show_id):
        """Fetch episodes for a specific show ID, with fallback to Show and Club RSS feeds."""
        selected_show = self.show_combo.value if hasattr(self, 'show_combo') and self.show_combo and self.show_combo.value else ''
        if not selected_show and hasattr(self, 'show_ids'):
            for name, sid in self.show_ids.items():
                if str(sid) == str(show_id):
                    selected_show = name
                    break
        try:
            load_dotenv()
            app_id = self.get_api_app_id()
            app_key = self.get_api_app_key()

            if app_id and app_key:
                headers = {
                    'Accept': 'application/json',
                    'app-id': app_id,
                    'app-key': app_key
                }

                url = f'https://twit.tv/api/v1.0/episodes?filter[shows]={show_id}'
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

                            media_url = self.extract_media_url(episode)
                            if media_url:
                                episode_info['media_url'] = media_url

                            episodes.append(episode_info)

                    if episodes:
                        return episodes
        except Exception as e:
            print(f"Error fetching episodes from API: {e}")

        # Fallback 1: Fetch episodes from Show's public RSS feed on feeds.twit.tv
        if selected_show:
            rss_items = self.fetch_show_rss_items(selected_show, audio_only=self.is_audio_only())
            if rss_items:
                episodes = []
                for item in rss_items:
                    episodes.append({
                        'title': item.get('title', ''),
                        'number': item.get('number', ''),
                        'date': item.get('date', ''),
                        'media_url': item.get('enclosure_url', ''),
                        'cleanPath': item.get('link', '')
                    })
                if episodes:
                    return episodes

        # Fallback 2: Fetch episodes from Club TWiT RSS feed
        club_items = self.fetch_club_twit_rss_items(selected_show, audio_only=self.is_audio_only())
        if club_items:
            episodes = []
            for item in club_items:
                title = item.get('title', '')
                if not selected_show or selected_show.lower() in title.lower() or any(w.lower() in title.lower() for w in selected_show.split() if len(w) > 3):
                    episodes.append({
                        'title': title,
                        'number': item.get('number', ''),
                        'date': item.get('date', ''),
                        'media_url': item.get('enclosure_url', ''),
                        'cleanPath': item.get('link', '')
                    })
            if episodes:
                return episodes

        return []

    def update_episodes_display(self) -> None:
        """Format and display current episodes based on selected sort order."""
        if not hasattr(self, 'episodes_list') or self.episodes_list is None:
            return

        if not self.current_episodes:
            self.episodes_list.data = []
            return

        episodes = list(self.current_episodes)
        sort_by = 'date'
        if hasattr(self, 'episode_radio') and self.episode_radio and '☑' in self.episode_radio.text:
            sort_by = 'number'
        elif hasattr(self, 'title_radio') and self.title_radio and '☑' in self.title_radio.text:
            sort_by = 'title'

        if sort_by == 'date':
            episodes.sort(key=lambda x: str(x.get('date', '')), reverse=True)
        elif sort_by == 'number':
            def parse_num(val):
                num = val.get('number', 0)
                try:
                    return (0, int(num))
                except (ValueError, TypeError):
                    return (1, str(num))
            episodes.sort(key=parse_num, reverse=True)
        elif sort_by == 'title':
            episodes.sort(key=lambda x: str(x.get('title', '')))

        table_data = []
        for episode in episodes:
            title = episode.get('title', 'Unknown Title')
            date = episode.get('date', 'Unknown Date')
            number = episode.get('number', 'Unknown Number')
            media_url = self.extract_media_url(episode) or episode.get('media_url') or ''
            table_data.append({
                'episode': str(number),
                'title': str(title),
                'date': str(date),
                'media_url': media_url,
                'episode_data': episode
            })

        self.episodes_list.data = table_data

    def load_episodes_for_selected_show(self) -> None:
        """Fetch and display episodes for currently selected show in the combo box."""
        selected_show = self.show_combo.value
        if selected_show and hasattr(self, 'show_ids') and selected_show in self.show_ids:
            show_id = self.show_ids[selected_show]
            self.current_episodes = self.fetch_episodes(show_id)
            self.update_episodes_display()
        else:
            self.current_episodes = []
            self.update_episodes_display()

    def on_show_select(self, widget) -> None:
        """Handle show selection change."""
        self.load_episodes_for_selected_show()

    def on_fetch_press(self, widget) -> None:
        """Fetch episodes for the selected show and refresh the show list."""
        shows = self.fetch_shows()
        if shows:
            current_selection = self.show_combo.value
            self.show_combo.items = shows
            if current_selection in shows:
                self.show_combo.value = current_selection

        self.load_episodes_for_selected_show()

    def on_sort_button_press(self, widget) -> None:
        """Handle radio button behavior for checkbox-like buttons."""
        self.date_radio.text = self.date_radio.text.replace('☑', '☐')
        self.episode_radio.text = self.episode_radio.text.replace('☑', '☐')
        self.title_radio.text = self.title_radio.text.replace('☑', '☐')

        if widget == self.date_radio:
            self.date_radio.text = self.date_radio.text.replace('☐', '☑')
        elif widget == self.episode_radio:
            self.episode_radio.text = self.episode_radio.text.replace('☐', '☑')
        elif widget == self.title_radio:
            self.title_radio.text = self.title_radio.text.replace('☐', '☑')

        self.update_episodes_display()

def main():
    return TwitTUIForm('TWIT.tv TUI', 'org.beeware.twittui')

if __name__ == '__main__':
    load_dotenv()
    app = main()
    app.main_loop()
