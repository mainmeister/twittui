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

from twittui.logging_config import get_logger

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
    if re.search(r"(?:youtube\.com/|youtu\.be/)", clean_url, re.IGNORECASE):
        return clean_url

    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; TwitTUI/1.0)"}
        head_resp = requests.head(clean_url, headers=headers, allow_redirects=True, timeout=timeout)
        if head_resp.status_code < 400 and head_resp.url:
            return head_resp.url
        with requests.get(
            clean_url, headers=headers, stream=True, allow_redirects=True, timeout=timeout
        ) as get_resp:
            if get_resp.status_code < 400 and get_resp.url:
                return get_resp.url
    except Exception as exc:
        _logger.debug("Could not resolve redirects for stream URL %s: %s", clean_url, exc)

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
        _logger.debug("Regex error while unwrapping tracking URL %s", clean_url, exc_info=True)

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
