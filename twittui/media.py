"""Safe XML parsing, URL validation, redirect resolution, and stream launching."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from typing import Any, Callable
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from twittui.logging_config import get_logger, safe_url_for_log
import asyncio
import toga
from toga.style import Pack
from toga.style.pack import COLUMN
from twittui.shows import KNOWN_SHOW_FEEDS, MEMBERFUL_HOST_FEEDS, MEMBERFUL_SHOW_FEEDS

try:
    import defusedxml.ElementTree as DefusedET
except ImportError:
    DefusedET = None

_logger = get_logger("media")


def safe_xml_fromstring(xml_data: bytes | str) -> ET.Element:
    """Parse XML string or bytes safely using ``defusedxml`` if available."""
    if isinstance(xml_data, str):
        data_bytes = xml_data.encode("utf-8", errors="replace")
    else:
        data_bytes = xml_data

    if DefusedET is not None:
        return DefusedET.fromstring(data_bytes)

    return ET.fromstring(data_bytes)


def is_safe_http_url(url: str) -> bool:
    """Return True if ``url`` uses an ``http://`` or ``https://`` scheme."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return u.startswith("http://") or u.startswith("https://")


def resolve_stream_url(media_url: str, timeout: float = 10.0) -> str:
    """Resolve redirect chains (e.g. podcast tracking URLs) to the final playable media URL."""
    if not media_url or not isinstance(media_url, str):
        return media_url

    clean_url: str = media_url.strip()
    parsed: urllib.parse.SplitResult = urllib.parse.urlsplit(clean_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return clean_url

    # Do not follow redirects for YouTube stream URLs
    if re.search(r"(?:youtube\.com/|youtube-nocookie\.com/|youtu\.be/|yt\.be/)", clean_url, re.IGNORECASE):
        return clean_url

    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; TwitTUI/1.0)"}
        head_resp = requests.head(clean_url, headers=headers, allow_redirects=True, timeout=timeout)
        try:
            if head_resp.status_code < 400 and head_resp.url:
                return head_resp.url
        finally:
            if callable(getattr(head_resp, "close", None)):
                head_resp.close()
        with requests.get(
            clean_url, headers=headers, stream=True, allow_redirects=True, timeout=timeout
        ) as get_resp:
            if get_resp.status_code < 400 and get_resp.url:
                return get_resp.url
    except Exception as exc:
        _logger.debug(
            "Could not resolve redirects for stream URL %s (%s)",
            safe_url_for_log(clean_url), type(exc).__name__,
        )

    # Fallback: unwrap known podcast tracking / redirect prefixes when unreachable
    try:
        match = re.search(
            r"(https?://(?:cdn\.twit\.tv|twit\.cachefly\.net|episodes\.captivate\.fm|podcasts\.captivate\.fm)/.+)$",
            clean_url,
        )
        if match:
            return match.group(1)
        if re.search(
            r"/(?:pdst\.fm|pscrb\.fm|mgln\.ai|dts\.podtrac\.com|chrt\.fm|traffic\.megaphone\.fm)/",
            clean_url,
        ):
            match = re.search(r"(https?://[^/]+/(?:cap|video|members)/.+)$", clean_url)
            if match:
                return match.group(1)
            match = re.search(r"/(cdn\.twit\.tv/.+)$", clean_url)
            if match:
                return f"https://{match.group(1)}"
    except re.error:
        _logger.debug("Regex error while unwrapping tracking URL %s", safe_url_for_log(clean_url), exc_info=True)

    return clean_url


def build_stream_args(streamer_template: str, media_url: str) -> list[str]:
    """Build a safe argument vector for ``subprocess.Popen(..., shell=False)``."""
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
    except ValueError:
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
        matched_ph: str | None = next((ph for ph in placeholders if ph in token), None)
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
    *,
    resolve: bool = True,
    resolver: Callable[[str], str] | None = None,
    is_tui_running: Callable[[], bool] | None = None,
    popen_fn: Callable[..., subprocess.Popen] | None = None,
) -> subprocess.Popen:
    """Spawn the external media player safely with ``shell=False``."""
    resolve_fn = resolver or resolve_stream_url
    resolved_url: str = resolve_fn(media_url) if resolve else media_url
    args: list[str] = build_stream_args(streamer_template, resolved_url)
    spawn = popen_fn or subprocess.Popen

    if is_tui_running is not None and is_tui_running():
        if (
            sys.platform != "win32"
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")
        ):
            for idx, tok in enumerate(args):
                base_tok = os.path.basename(tok).lower()
                if base_tok == "vlc" and "-I" not in args and "--intf" not in args:
                    args = args[: idx + 1] + ["-I", "dummy"] + args[idx + 1 :]
                    break

        popen_kwargs: dict[str, Any] = {
            "shell": False,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            detached_flag = getattr(subprocess, "DETACHED_PROCESS", 0)
            if detached_flag:
                popen_kwargs["creationflags"] = detached_flag
        else:
            popen_kwargs["start_new_session"] = True
        return spawn(args, **popen_kwargs)

    return spawn(args, shell=False)


class MediaMixin:
    """Media URL parsing, resolution discovery, duration/size formatting, and validation mixin."""

    @staticmethod
    def parse_duration_to_seconds(val) -> int:
        """Parse duration value (seconds int/float, formatted HH:MM:SS / MM:SS string, or dict) to total seconds."""
        if val is None or val == '':
            return -1
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, dict):
            for k in ['runningTime', 'duration', 'length', 'running_time']:
                if k in val and val[k]:
                    res = MediaMixin.parse_duration_to_seconds(val[k])
                    if res >= 0:
                        return res
            if 'hours' in val or 'minutes' in val or 'seconds' in val:
                try:
                    h = int(val.get('hours') or 0)
                    m = int(val.get('minutes') or 0)
                    s = int(val.get('seconds') or 0)
                    return h * 3600 + m * 60 + s
                except Exception:
                    _logger.debug("Ignored exception in %s", 'MediaMixin.parse_duration_to_seconds', exc_info=True)
            return -1
        s_val = str(val).strip()
        if not s_val:
            return -1
        if s_val.isdigit():
            return int(s_val)
        if re.match(r'^\d+(\.\d+)?$', s_val):
            return int(float(s_val))
        if ':' in s_val:
            parts = s_val.split(':')
            try:
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
                elif len(parts) == 2:
                    return int(parts[0]) * 60 + int(float(parts[1]))
                elif len(parts) == 4:
                    return int(parts[0]) * 86400 + int(parts[1]) * 3600 + int(parts[2]) * 60 + int(float(parts[3]))
            except Exception:
                _logger.debug("Ignored exception in %s", 'MediaMixin.parse_duration_to_seconds', exc_info=True)
        return -1

    @staticmethod
    def parse_size_to_bytes(val) -> int:
        """Parse file size (bytes int/float, string in bytes, formatted string e.g. '500 MB', or dict) to total bytes."""
        if val is None or val == '':
            return -1
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, dict):
            for k in ['file_size', 'fileSize', 'size', 'length', 'enclosure_length', 'bytes', 'content_length']:
                if k in val and val[k]:
                    res = MediaMixin.parse_size_to_bytes(val[k])
                    if res >= 0:
                        return res
            return -1
        s_val = str(val).strip().replace(',', '')
        if not s_val:
            return -1
        if s_val.isdigit():
            return int(s_val)
        if re.match(r'^\d+(\.\d+)?$', s_val):
            return int(float(s_val))
        m = re.match(r'^([\d.]+)\s*([A-Za-z]+)$', s_val)
        if m:
            num = float(m.group(1))
            unit = m.group(2).upper()
            if unit in ('B', 'BYTE', 'BYTES'):
                return int(num)
            elif unit in ('KB', 'K', 'KIB'):
                return int(num * 1024)
            elif unit in ('MB', 'M', 'MIB'):
                return int(num * 1024 * 1024)
            elif unit in ('GB', 'G', 'GIB'):
                return int(num * 1024 * 1024 * 1024)
            elif unit in ('TB', 'T', 'TIB'):
                return int(num * 1024 * 1024 * 1024 * 1024)
        return -1

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
                return MediaMixin.format_duration(val['runningTime'])
            if 'duration' in val and val['duration']:
                return MediaMixin.format_duration(val['duration'])
            if 'hours' in val or 'minutes' in val or 'seconds' in val:
                try:
                    h = int(val.get('hours') or 0)
                    m = int(val.get('minutes') or 0)
                    s = int(val.get('seconds') or 0)
                    return f"{h:02d}:{m:02d}:{s:02d}"
                except Exception:
                    _logger.debug("Ignored exception in %s", 'MediaMixin.format_duration', exc_info=True)
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
            except (ValueError, TypeError):
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
                        res = MediaMixin.format_file_size(val[k])
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
        except (ValueError, TypeError):
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
        except OSError:
            _logger.debug("Could not inspect media file %s", file_path, exc_info=True)
            return False

    def format_stream_command(self, streamer_template: str, url: str) -> str:
        """Format the streamer command string with the episode media URL safely."""
        try:
            args = build_stream_args(streamer_template, url)
            return shlex.join(args)
        except (ValueError, TypeError):
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

    def resolve_media_url(self, episode_dict: dict, show_name: str = None, audio_only: bool = None) -> str | None:
        """Resolve a streamable media URL for an episode through all available sources."""
        if not isinstance(episode_dict, dict):
            return None

        if audio_only is None:
            audio_only = self.is_audio_only()

        fallback_candidate = None

        # Extract identifiers from episode dict
        clean_path = str(episode_dict.get('cleanPath') or episode_dict.get('link') or '').strip()
        ep_num = str(episode_dict.get('number') or episode_dict.get('episodeNumber') or '').strip()
        ep_title = str(episode_dict.get('title') or episode_dict.get('label') or '').strip()
        ep_id = str(episode_dict.get('id') or '').strip()
        show = show_name or self._selected_show_name()

        # 1. Match in Club TWiT RSS feeds (show-specific feeds, network feeds, host feeds) — highest priority when configured
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

        # 2. Direct fields in episode dict (public API data)
        url = self.extract_media_url(episode_dict, audio_only=audio_only)
        if url and self.is_valid_media_url(url):
            if (audio_only and self.is_audio_url(url)) or (not audio_only and self.is_video_url(url)):
                if not fallback_candidate:
                    return url
                # If we already have a Club TWiT match, prefer it over public API data
                if not self.is_valid_media_url(fallback_candidate):
                    return url
                return fallback_candidate
            if not fallback_candidate:
                fallback_candidate = url

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

        def _scalar_str(val: Any, allow_int: bool = False) -> str:
            if isinstance(val, str):
                return val.strip()
            if allow_int and isinstance(val, int) and not isinstance(val, bool):
                return str(val)
            return ''

        target_num = (
            _scalar_str(getattr(target, 'episode', None), allow_int=True)
            or _scalar_str(getattr(target, 'number', None), allow_int=True)
            or _scalar_str(ep_dict.get('episode'), allow_int=True)
            or _scalar_str(ep_dict.get('number'), allow_int=True)
            or _scalar_str(ep_dict.get('episodeNumber'), allow_int=True)
            or (_scalar_str(target[0], allow_int=True) if isinstance(target, (tuple, list)) and len(target) > 0 else '')
        )
        target_title = (
            _scalar_str(getattr(target, 'title', None))
            or _scalar_str(ep_dict.get('title'))
            or _scalar_str(ep_dict.get('label'))
            or (_scalar_str(target[1]) if isinstance(target, (tuple, list)) and len(target) > 1 else '')
        )

        if hasattr(self, 'current_episodes') and self.current_episodes:
            for ep in self.current_episodes:
                if (target_num and str(ep.get('number', '')) == target_num) or (target_title and ep.get('title') == target_title):
                    if isinstance(ep, dict):
                        ep_dict = {**ep, **ep_dict}
                    break

        if not show_name:
            selected = _scalar_str(self._selected_show_name())
            target_show = (
                _scalar_str(getattr(target, 'show', None))
                or _scalar_str(ep_dict.get('show_name'))
                or ep_dict.get('show')
                or ''
            )
            if isinstance(target_show, dict):
                target_show = _scalar_str(target_show.get('label')) or _scalar_str(target_show.get('title'))
            target_show_str = _scalar_str(target_show)
            if selected and selected.lower() not in ('all twit.tv shows', 'all shows'):
                show_name = selected
            else:
                show_name = target_show_str or selected
        if show_name:
            show_name = getattr(self, '_show_names_by_display', {}).get(show_name, show_name)

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
                except (ValueError, TypeError):
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

        # 2b. Check Club TWiT RSS feeds for this show (member-only, no commercials)
        if show_name:
            clean_path_club = _scalar_str(ep_dict.get('cleanPath')) or _scalar_str(getattr(target, 'clean_path', None))
            ep_id_club = _scalar_str(ep_dict.get('id'), allow_int=True) or _scalar_str(getattr(target, 'id', None), allow_int=True)
            club_items = self.fetch_club_twit_rss_items(show_name, audio_only=audio_only)
            if club_items:
                for item in club_items:
                    if self._match_rss_item(item, clean_path_club, ep_id_club, target_num, target_title, show_name):
                        enc = item.get('enclosure_url')
                        s = item.get('enclosure_length')
                        if enc and self.is_valid_media_url(enc):
                            is_aud = self.is_audio_url(enc)
                            if audio_only and is_aud:
                                _add_cand('club_twit_audio', 'Club TWiT Audio (No Commercials)', 'audio', enc, s)
                            elif not audio_only and not is_aud:
                                _add_cand('club_twit_video', 'Club TWiT Video (No Commercials)', 'video', enc, s)
                            elif not seen_urls:
                                # Add as fallback type if no other resolutions found yet
                                _add_cand('club_twit', 'Club TWiT (No Commercials)', 'audio' if is_aud else 'video', enc, s)

        # 3. Check cached RSS feeds for this show
        if show_name and hasattr(self, '_show_rss_cache') and isinstance(self._show_rss_cache, dict):
            show_key = show_name.strip().lower()
            clean_path = _scalar_str(ep_dict.get('cleanPath')) or _scalar_str(getattr(target, 'clean_path', None))
            ep_id = _scalar_str(ep_dict.get('id'), allow_int=True) or _scalar_str(getattr(target, 'id', None), allow_int=True)

            # Inspect the real keys written by fetch_show_rss_items() ('{show_key}_video', '{show_key}_audio')
            # in mode-preferred order, plus any legacy per-feed 'rss_{feed_file}' keys.
            suffix_order = ('audio', 'video') if audio_only else ('video', 'audio')
            rss_cache_sources: list[tuple[str, list]] = []

            def _collect_rss_sources() -> None:
                for suffix in suffix_order:
                    cached_items = self._show_rss_cache.get(f"{show_key}_{suffix}")
                    if cached_items:
                        rss_cache_sources.append(('', list(cached_items)))
                for feed_file in KNOWN_SHOW_FEEDS.get(show_key, []):
                    legacy_items = self._show_rss_cache.get(f"rss_{feed_file}")
                    if legacy_items:
                        rss_cache_sources.append((feed_file, list(legacy_items)))

            cache_lock = getattr(self, '_cache_lock', None)
            if cache_lock is not None:
                with cache_lock:
                    _collect_rss_sources()
            else:
                _collect_rss_sources()

            for default_feed_file, items in rss_cache_sources:
                for item in items:
                    if self._match_rss_item(item, clean_path, ep_id, target_num, target_title, show_name):
                        enc = item.get('enclosure_url')
                        s = item.get('enclosure_length')
                        if enc and self.is_valid_media_url(enc):
                            feed_hint = (item.get('feed_file') or default_feed_file or '').lower()
                            enc_low = enc.lower()
                            is_aud = self.is_audio_url(enc)
                            if is_aud:
                                _add_cand('rss_audio', 'Audio (MP3/M4A)', 'audio', enc, s)
                            elif 'video_hd' in feed_hint or '_hd' in feed_hint or '1280x720' in enc_low or '1920x1080' in enc_low:
                                _add_cand('video_hd', 'HD Video (1080p/720p)', 'video', enc, s)
                            elif 'video_large' in feed_hint or '_large' in feed_hint or '864x480' in enc_low or '640x368' in enc_low:
                                _add_cand('video_large', 'Large Video (540p/480p)', 'video', enc, s)
                            elif 'video_small' in feed_hint or '_small' in feed_hint or '480x270' in enc_low:
                                _add_cand('video_small', 'Small / Mobile Video (360p)', 'video', enc, s)
                            else:
                                _add_cand('rss_feed', 'Standard Video', 'video', enc, s)

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

        # 1. Use Textual ChoiceDialog when running on the Textual TUI backend
        if self._is_textual_app():
            try:
                from toga_textual_backend import ChoiceDialog
                dialog = ChoiceDialog(title, message, resolutions)
                if getattr(self, 'main_window', None) is not None:
                    return await self.main_window.dialog(dialog)
                return await dialog._show(None)
            except Exception as e:
                _logger.warning(f"Error presenting Textual resolution choice dialog: {e}")
                return resolutions[0]

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
                            _logger.debug("Ignored exception in %s", 'MediaMixin.prompt_resolution_choice._make_handler._on_click', exc_info=True)
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
                    _logger.debug("Ignored exception in %s", 'MediaMixin.prompt_resolution_choice._on_cancel', exc_info=True)

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
            _logger.warning(f"Error presenting resolution choice dialog: {e}")
            return resolutions[0]
