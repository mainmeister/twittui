"""Single-flight chunked HTTP and YouTube (yt-dlp) episode downloader mixin."""

from __future__ import annotations

import asyncio
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.parse

import requests

from twittui.logging_config import get_logger, safe_url_for_log

_logger = get_logger("downloader")


class DownloaderMixin:
    """Filename sanitization, deduplication, chunked HTTP, and yt-dlp download mixin."""

    def _terminate_active_download_proc(self) -> None:
        """Terminate any active child downloader subprocess (e.g. yt-dlp) cleanly without hanging."""
        proc = getattr(self, '_active_download_proc', None)
        self._active_download_proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        _logger.debug("Timed out waiting for killed download subprocess", exc_info=True)
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm._terminate_active_download_proc', exc_info=True)

    _WINDOWS_RESERVED_FS_NAMES = frozenset({
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
        'COM¹', 'COM²', 'COM³', 'LPT¹', 'LPT²', 'LPT³',
    })

    @staticmethod
    def _sanitize_fs_component(name: str, fallback: str = "TWiT", max_bytes: int = 255) -> str:
        """Sanitize a filename or folder component against control chars, dotfiles, traversal, reserved names, and NAME_MAX."""
        cleaned = re.sub(r'[\x00-\x1f\x7f]', '', str(name or ''))
        cleaned = re.sub(r'[/\\:*?"<>|]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip('. ')
        if not cleaned:
            cleaned = fallback
        def _is_reserved_device_name(component: str) -> bool:
            device_name = component.split('.', 1)[0].rstrip('. ').upper()
            return device_name in DownloaderMixin._WINDOWS_RESERVED_FS_NAMES

        if _is_reserved_device_name(cleaned):
            cleaned = f"_{cleaned}"
        if max_bytes > 0:
            encoded = cleaned.encode('utf-8')
            if len(encoded) > max_bytes:
                truncated = encoded[:max_bytes].decode('utf-8', errors='ignore').rstrip('. ')
                cleaned = truncated or fallback
            if _is_reserved_device_name(cleaned):
                encoded_remainder = cleaned.encode('utf-8')[:max(0, max_bytes - 1)]
                remainder = encoded_remainder.decode('utf-8', errors='ignore').rstrip('. ')
                cleaned = f"_{remainder}"
        return cleaned

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

        if not show:
            show = self._selected_show_name()

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

        # Sanitize folder name for filesystem safety (control chars, dotfiles, traversal, NAME_MAX)
        return self._sanitize_fs_component(show_str, fallback="TWiT", max_bytes=255)

    def get_target_destination_folder(self, target) -> str:
        """Get the destination directory for downloading the specified episode, accounting for Show Folders."""
        base_dest = self.get_destination_folder()
        if self.is_show_folders_enabled():
            show_folder = self.get_show_folder_name(target)
            if show_folder:
                return os.path.join(base_dest, show_folder)
        return base_dest

    def determine_download_filename(self, target, media_url: str) -> str:
        """Determine a clean, descriptive filename matching the actual episode name."""
        parsed = urllib.parse.urlparse(media_url)
        url_filename = os.path.basename(urllib.parse.unquote(parsed.path))

        # Check if URL filename has a known media extension
        _, ext = os.path.splitext(url_filename)
        valid_extensions = {'.mp4', '.mp3', '.m4a', '.webm', '.ogg', '.m4v', '.mov', '.flv', '.aac', '.m3u8'}
        file_ext = ext.lower() if ext and ext.lower() in valid_extensions else ('.mp3' if self.is_audio_only() else '.mp4')

        show = self._selected_show_name()
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

        # Sanitize filename for filesystem compatibility (control chars, dotfiles, traversal, NAME_MAX)
        ext_bytes = len(file_ext.encode('utf-8'))
        max_stem_bytes = max(16, 255 - ext_bytes)
        fallback_stem = os.path.splitext(url_filename)[0] if url_filename else "twit_episode"
        fallback_stem = self._sanitize_fs_component(fallback_stem, fallback="twit_episode", max_bytes=max_stem_bytes)
        clean_base = self._sanitize_fs_component(base_name, fallback=fallback_stem, max_bytes=max_stem_bytes)

        return f"{clean_base}{file_ext}"

    def is_existing_file_identical(self, dest_path: str, url: str, expected_size: int = None) -> bool:
        """Check whether an existing local file is confirmed to be identical to the remote media file."""
        if not dest_path or not os.path.exists(dest_path):
            return False

        if not self.is_valid_media_file(dest_path):
            return False

        try:
            local_size = os.path.getsize(dest_path)
        except OSError:
            _logger.debug("Could not stat local file %s", dest_path, exc_info=True)
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
                        _logger.warning(f"Error calculating MD5 checksum for {dest_path}: {e}")

                if remote_length and remote_length.isdigit() and int(remote_length) == local_size:
                    return True

            elif head_resp.status_code == 304:
                return True
        except Exception as e:
            _logger.warning(
                "Could not verify existing file headers via HEAD request for %s (%s)",
                safe_url_for_log(url), type(e).__name__,
            )
            if expected_size is not None and expected_size > 0 and local_size == expected_size:
                return True

        return False

    def download_youtube_video(self, url: str, dest_path: str, progress_callback=None) -> bool:
        """Extract and download a YouTube video or audio stream using yt-dlp or youtube-dl."""
        has_ffmpeg = bool(shutil.which('ffmpeg'))
        snap_audio = getattr(self, '_download_audio_only', None)
        audio_only = snap_audio if snap_audio is not None else self.is_audio_only()

        dest_dir = os.path.dirname(os.path.abspath(dest_path)) or '.'
        base_filename = os.path.basename(dest_path)
        base_stem, target_ext = os.path.splitext(base_filename)

        # Check existing file at dest_path or (when ffmpeg is absent) an aligned sibling container
        existing_candidates = [dest_path]
        if not has_ffmpeg:
            alt_exts = (
                ('.m4a', '.webm', '.opus', '.ogg', '.aac', '.mp3', '.flac')
                if audio_only
                else ('.mp4', '.webm', '.mkv', '.mov', '.m4v')
            )
            for ext in alt_exts:
                if ext != target_ext.lower():
                    existing_candidates.append(os.path.join(dest_dir, f"{base_stem}{ext}"))

        for existing_path in existing_candidates:
            if self.is_existing_file_identical(existing_path, url):
                local_size = os.path.getsize(existing_path)
                self._last_downloaded_path = existing_path
                _logger.info(f"Skipping download: '{existing_path}' already exists ({local_size} bytes).")
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
            _logger.warning(f"Error: {error_msg}")
            self._show_dialog_threadsafe("error", "YouTube Downloader Required", error_msg, prefer_main=True)
            return False

        os.makedirs(dest_dir, exist_ok=True)
        temp_prefix = os.path.join(dest_dir, f".twittui_yt_{base_stem}")
        escaped_temp_prefix = glob.escape(temp_prefix)
        escaped_dest_path = glob.escape(dest_path)
        escaped_stem_path = glob.escape(os.path.join(dest_dir, base_stem))
        # Escape literal '%' characters so yt-dlp does not treat episode titles like '100%' as template tokens
        outtmpl = f"{temp_prefix.replace('%', '%%')}.%(ext)s"

        def _cleanup_stale_parts() -> None:
            cleanup_patterns = [
                f"{escaped_temp_prefix}*",
                f"{escaped_dest_path}.part*",
                f"{escaped_dest_path}*.part*",
                f"{escaped_stem_path}.*.part*",
            ]
            for pattern in cleanup_patterns:
                for p in glob.glob(pattern):
                    try:
                        if os.path.isfile(p) or os.path.islink(p):
                            os.remove(p)
                        elif os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm.download_youtube_video._cleanup_stale_parts', exc_info=True)

        def _is_temp_fragment(path: str) -> bool:
            name_low = os.path.basename(path).lower()
            return (
                name_low.endswith('.part')
                or '.part.' in name_low
                or name_low.endswith('.ytdl')
                or name_low.endswith('.info.json')
                or name_low.endswith('.description')
            )

        def _find_and_promote_output(audio_mode: bool, ffmpeg_available: bool) -> str | None:
            candidates = glob.glob(f"{escaped_temp_prefix}.*")
            if not candidates:
                candidates = glob.glob(f"{escaped_temp_prefix}*")

            found_file = None
            if candidates:
                for c in sorted(
                    candidates,
                    key=lambda x: (not x.endswith('.mp4'), not x.endswith('.m4a'), not x.endswith('.mp3'), len(x)),
                ):
                    if _is_temp_fragment(c):
                        continue
                    if os.path.isfile(c) and os.path.getsize(c) > 1024:
                        found_file = c
                        break

            if not found_file or not os.path.exists(found_file):
                return None

            # Validate media payload BEFORE atomic replacement so corrupt/HTML downloads
            # can never overwrite an existing valid file at final_dest.
            if not self.is_valid_media_file(found_file):
                return None

            final_dest = dest_path
            # When ffmpeg is unavailable, keep the actual container extension instead of
            # misnaming downloaded audio (.m4a/.opus/.webm) or video (.webm/.mkv) containers.
            if not ffmpeg_available:
                actual_ext = os.path.splitext(found_file)[1].lower()
                allowed_exts = (
                    {'.m4a', '.webm', '.opus', '.ogg', '.aac', '.mp3', '.flac'}
                    if audio_mode
                    else {'.mp4', '.webm', '.mkv', '.mov', '.m4v'}
                )
                if actual_ext in allowed_exts and actual_ext != target_ext.lower():
                    final_dest = os.path.join(dest_dir, f"{base_stem}{actual_ext}")

            os.replace(found_file, final_dest)
            return final_dest

        # Clean up any leftover partial pieces before starting
        _cleanup_stale_parts()

        if progress_callback is None:
            self.reset_progress()

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

            proc = None
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
                self._active_download_proc = proc
                pct_regex = re.compile(r'\[download\]\s+([\d\.]+)%')
                merger_regex = re.compile(r'\[(?:Merger|ffmpeg|ExtractAudio)\]')
                while True:
                    if getattr(self, '_cancel_download', False):
                        self._terminate_active_download_proc()
                        _cleanup_stale_parts()
                        return False

                    line = proc.stdout.readline() if proc.stdout is not None else ''
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
                if getattr(self, '_cancel_download', False):
                    _cleanup_stale_parts()
                    return False
                if retcode != 0:
                    _logger.warning(f"yt-dlp returned error code {retcode}")
                    _cleanup_stale_parts()
                    return False

                # Locate finalized output file safely (handling [ ] brackets), validate, and promote atomically
                final_dest_path = _find_and_promote_output(audio_only, has_ffmpeg)
                _cleanup_stale_parts()

                if final_dest_path and os.path.exists(final_dest_path) and self.is_valid_media_file(final_dest_path):
                    self._last_downloaded_path = final_dest_path
                    if progress_callback:
                        progress_callback(100.0, 100.0)
                    else:
                        self.update_progress(100.0, 100.0)
                    _logger.info(f"Finished downloading YouTube video: {final_dest_path}")
                    return True
                return False
            except Exception as e:
                _logger.warning("Error executing yt-dlp for %s (%s)", safe_url_for_log(url), type(e).__name__)
                _cleanup_stale_parts()
                return False
            finally:
                if getattr(self, '_active_download_proc', None) is proc:
                    self._active_download_proc = None
                if proc is not None and getattr(proc, 'stdout', None) is not None:
                    try:
                        proc.stdout.close()
                    except OSError:
                        _logger.debug("Ignored error closing yt-dlp stdout pipe", exc_info=True)
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
                    'no_warnings': True,
                    'noprogress': True,
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

                final_dest_path = _find_and_promote_output(audio_only, has_ffmpeg)
                _cleanup_stale_parts()

                if final_dest_path and os.path.exists(final_dest_path) and self.is_valid_media_file(final_dest_path):
                    self._last_downloaded_path = final_dest_path
                    if progress_callback:
                        progress_callback(100.0, 100.0)
                    else:
                        self.update_progress(100.0, 100.0)
                    _logger.info(f"Finished downloading YouTube video: {final_dest_path}")
                    return True
                return False
            except Exception as e:
                _logger.warning(
                    "Error downloading YouTube video with yt_dlp module for %s (%s)",
                    safe_url_for_log(url), type(e).__name__,
                )
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
            _logger.info(f"Skipping download: '{dest_path}' already exists and is confirmed identical ({local_size} bytes).")
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
                    snap_audio = getattr(self, '_download_audio_only', None)
                    dl_audio_only = snap_audio if snap_audio is not None else self.is_audio_only()
                    for cand in media_matches:
                        if self.is_valid_media_url(cand) and (not dl_audio_only or self.is_audio_url(cand)):
                            return self.download_episode_file(cand, dest_path, block_size, progress_callback=progress_callback, expected_size=expected_size)

                    _logger.warning(
                        "URL '%s' returned an HTML document instead of a playable media stream.",
                        safe_url_for_log(url),
                    )
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
                                    _logger.info(f"Skipping download: '{dest_path}' already exists and matches MD5 checksum ({etag}).")
                                    if progress_callback:
                                        progress_callback(total_bytes, total_bytes)
                                    else:
                                        self.update_progress(total_bytes, total_bytes)
                                    return True
                            except Exception:
                                _logger.debug("Ignored exception in %s", 'TwitTUIForm.download_episode_file', exc_info=True)
                        else:
                            _logger.info(f"Skipping download: '{dest_path}' already exists with matching size ({local_size} bytes).")
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
                            _logger.info("Download cancelled by user")
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
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm.download_episode_file', exc_info=True)
                if progress_callback is None:
                    self.reset_progress()
                return False

            if not self.is_valid_media_file(temp_path):
                _logger.warning(
                    "Downloaded content from '%s' contains text/HTML rather than valid media.",
                    safe_url_for_log(url),
                )
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm.download_episode_file', exc_info=True)
                if progress_callback is None:
                    self.reset_progress()
                return False

            os.replace(temp_path, dest_path)
            self._last_downloaded_path = dest_path
            if progress_callback:
                progress_callback(total_bytes if total_bytes > 0 else downloaded_bytes, total_bytes)
            else:
                if total_bytes > 0:
                    self.update_progress(total_bytes, total_bytes)
            _logger.info(f"Finished downloading: {dest_path} ({downloaded_bytes} bytes)")
            return True
        except Exception as e:
            _logger.warning("Error downloading %s (%s)", safe_url_for_log(url), type(e).__name__)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm.download_episode_file', exc_info=True)
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

        show_name = self._selected_show_name()

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
        self._show_dialog_threadsafe("info", title, message, prefer_main=True)

    @staticmethod
    def _parse_expected_byte_size(val: Any) -> int | None:
        """Parse a positive byte-size value (> 1000 bytes), rejecting booleans and duration strings."""
        if val is None or isinstance(val, bool):
            return None
        if isinstance(val, int):
            return val if val > 1000 else None
        s = str(val).strip().replace(',', '')
        if s.isdigit():
            num = int(s)
            return num if num > 1000 else None
        return None

    def _extract_expected_byte_size(
        self,
        target: Any,
        media_url: str = '',
        matched_resolution: dict | None = None,
    ) -> int | None:
        """Extract expected byte size for a target download without confusing top-level duration ('length')."""
        if isinstance(matched_resolution, dict):
            res_size = self._parse_expected_byte_size(matched_resolution.get('size'))
            if res_size is not None:
                return res_size

        selected_size = self._parse_expected_byte_size(getattr(target, 'selected_media_size', None))
        if selected_size is not None:
            return selected_size

        ep_source = None
        if hasattr(target, 'episode_data') and isinstance(target.episode_data, dict):
            ep_source = target.episode_data
        elif isinstance(target, dict):
            ep_source = target
        if not isinstance(ep_source, dict):
            return None

        url_norm = str(media_url or '').strip()

        # 1. Prefer the exact format sub-dictionary matching the chosen media_url
        if url_norm:
            for fmt_key in ('video_hd', 'video_large', 'video_small', 'video_audio', 'audio'):
                fmt_val = ep_source.get(fmt_key)
                if isinstance(fmt_val, dict):
                    fmt_url = next(
                        (
                            str(fmt_val[u_key]).strip()
                            for u_key in ('mediaUrl', 'media_url', 'downloadUrl', 'streamUrl', 'url', 'href')
                            if fmt_val.get(u_key)
                        ),
                        '',
                    )
                    if fmt_url and fmt_url == url_norm:
                        for s_key in ('file_size', 'fileSize', 'size', 'bytes', 'content_length'):
                            parsed = self._parse_expected_byte_size(fmt_val.get(s_key))
                            if parsed is not None:
                                return parsed
                        # Matched this specific format without a known byte size; do not borrow
                        # another format's top-level size (e.g. HD video size for an MP3 download).
                        return None

        # 2. Explicit top-level byte-size keys (deliberately excluding top-level 'length', which is duration)
        for k in ('file_size', 'fileSize', 'enclosure_length', 'size', 'bytes', 'content_length'):
            parsed = self._parse_expected_byte_size(ep_source.get(k))
            if parsed is not None:
                return parsed

        # 3. Explicit RSS enclosure sub-dictionaries (where 'length' is defined by RSS 2.0 as byte count)
        enc_obj = ep_source.get('enclosure')
        if isinstance(enc_obj, dict):
            for k in ('length', 'size', 'bytes'):
                parsed = self._parse_expected_byte_size(enc_obj.get(k))
                if parsed is not None:
                    return parsed

        enc_list = ep_source.get('enclosures')
        if isinstance(enc_list, list):
            ordered_encs = [e for e in enc_list if isinstance(e, dict)]
            if url_norm:
                ordered_encs.sort(
                    key=lambda e: str(e.get('url') or e.get('href') or '').strip() != url_norm
                )
            for e in ordered_encs:
                for k in ('length', 'size', 'bytes'):
                    parsed = self._parse_expected_byte_size(e.get(k))
                    if parsed is not None:
                        return parsed

        return None

    def download_episodes_batch(
        self,
        targets: list,
        preferred_resolution: str = None,
        *,
        download_snapshot: dict | None = None,
    ) -> None:
        """Background worker to download multiple selected episodes."""
        download_lock = getattr(self, '_download_lock', None)
        lock_acquired = False
        if download_lock is not None:
            lock_acquired = download_lock.acquire(blocking=False)
            if not lock_acquired:
                _logger.info("Batch download already in progress; ignoring concurrent request.")
                return

        self._is_downloading = True
        self._cancel_download = False
        self.reset_progress()

        # Use UI-thread snapshot values when provided so worker threads never read live GUI widgets.
        snap = download_snapshot or {}
        worker = snap.get('worker') or self
        base_dest_dir = snap['base_dest_dir'] if 'base_dest_dir' in snap else self.get_destination_folder()
        block_size = snap['block_size'] if 'block_size' in snap else self.get_block_size()
        show_folders_enabled = snap['show_folders'] if 'show_folders' in snap else self.is_show_folders_enabled()
        audio_only = snap['audio_only'] if 'audio_only' in snap else self.is_audio_only()
        self._download_audio_only = audio_only

        downloaded_files = []
        total_targets = len(targets) if targets else 1

        _logger.info(f"Starting batch download for {len(targets)} episode(s) to '{base_dest_dir}' (block size: {block_size})...")
        try:
            try:
                os.makedirs(base_dest_dir, exist_ok=True)
            except Exception as e:
                _logger.warning(f"Error creating destination directory '{base_dest_dir}': {e}")
                self.reset_progress()
                return

            for idx_0, target in enumerate(targets):
                if getattr(self, '_cancel_download', False):
                    _logger.info("Batch download cancelled.")
                    break
                target_title = getattr(target, 'title', str(target))
                target_num = getattr(target, 'episode', '')

                matched_res_dict = None
                if hasattr(target, 'selected_media_url') and target.selected_media_url:
                    media_url = target.selected_media_url
                elif preferred_resolution:
                    cand_res = worker.get_available_resolutions(target, audio_only=audio_only)
                    matched_res_dict = next(
                        (r for r in cand_res if r.get('id') == preferred_resolution or r.get('type') == preferred_resolution),
                        None,
                    )
                    media_url = (matched_res_dict['url'] if matched_res_dict else None) or worker.resolve_target_media_url(target, audio_only=audio_only)
                else:
                    media_url = worker.resolve_target_media_url(target, audio_only=audio_only)

                if not media_url:
                    _logger.warning(f"[{idx_0 + 1}/{total_targets}] No media URL found for episode: {target_num} {target_title}")
                    batch_pct = ((idx_0 + 1) / total_targets) * 100.0
                    self.update_progress(batch_pct, 100.0)
                    continue

                show_folder = worker.get_show_folder_name(target) if show_folders_enabled else ''
                item_dest_dir = os.path.join(base_dest_dir, show_folder) if (show_folders_enabled and show_folder) else base_dest_dir
                try:
                    os.makedirs(item_dest_dir, exist_ok=True)
                except Exception as e:
                    _logger.warning(f"Error creating destination directory '{item_dest_dir}': {e}")
                    item_dest_dir = base_dest_dir

                filename = worker.determine_download_filename(target, media_url)
                dest_filepath = os.path.join(item_dest_dir, filename)

                # Attempt to extract known expected enclosure byte size (excluding top-level 'length',
                # which holds episode duration rather than file size).
                expected_size = self._extract_expected_byte_size(
                    target, media_url=media_url, matched_resolution=matched_res_dict
                )

                sanitized_log_url = safe_url_for_log(media_url)
                _logger.info(f"[{idx_0 + 1}/{total_targets}] Downloading '{target_title}' -> {dest_filepath} from {sanitized_log_url}")

                def _item_progress(downloaded_bytes: int, total_bytes: int, item_idx=idx_0):
                    if total_bytes > 0:
                        item_frac = min(1.0, max(0.0, downloaded_bytes / total_bytes))
                    else:
                        item_frac = 0.0
                    batch_pct = ((item_idx + item_frac) / total_targets) * 100.0
                    self.update_progress(batch_pct, 100.0)

                self._last_downloaded_path = None
                success = self.download_episode_file(media_url, dest_filepath, block_size, progress_callback=_item_progress, expected_size=expected_size)
                if success:
                    actual_filename = os.path.basename(self._last_downloaded_path) if self._last_downloaded_path else filename
                    if show_folders_enabled:
                        rel_path = os.path.join(show_folder, actual_filename) if show_folder else actual_filename
                        downloaded_files.append(rel_path)
                    else:
                        downloaded_files.append(actual_filename)

                batch_pct = ((idx_0 + 1) / total_targets) * 100.0
                self.update_progress(batch_pct, 100.0)
        finally:
            if worker is not self:
                cache_lock = getattr(self, '_cache_lock', None)
                def _merge_worker_caches() -> None:
                    for cache_attr in (
                        '_memberful_feeds_cache',
                        '_show_rss_cache',
                        '_media_webpage_cache',
                        '_episode_detail_cache',
                    ):
                        w_cache = getattr(worker, cache_attr, None)
                        s_cache = getattr(self, cache_attr, None)
                        if isinstance(w_cache, dict) and isinstance(s_cache, dict):
                            s_cache.update(w_cache)
                if cache_lock is not None:
                    with cache_lock:
                        _merge_worker_caches()
                else:
                    _merge_worker_caches()
            self._download_audio_only = None
            self._is_downloading = False
            if lock_acquired and download_lock is not None:
                download_lock.release()
            if getattr(self, '_cancel_download', False):
                self.reset_progress()
            if downloaded_files:
                self.show_download_complete_dialog(base_dest_dir, downloaded_files)

    async def on_download_press(self, widget=None) -> None:
        """Process selected episodes for batch download with resolution prompt if multiple are available."""
        download_starting_acquired = False
        try:
            self._cancel_hover_timer()
            if getattr(self, '_is_downloading', False) or getattr(self, '_download_starting', False):
                self._show_dialog_threadsafe(
                    "info",
                    "Download In Progress",
                    "A download is already in progress. Please wait for it to finish or press Cancel first.",
                )
                return
            self._download_starting = True
            download_starting_acquired = True
            selected = self.episodes_list.selection
            if not selected:
                _logger.info("No episode selected for download")
                return

            if isinstance(selected, (list, tuple, set)):
                targets = [t for t in selected if t is not None]
            else:
                targets = [selected] if selected is not None else []

            if not targets:
                _logger.info("No episode selected for download")
                return

            targets = [self._snapshot_episode(t) for t in targets]
            worker = self._network_snapshot()
            token = getattr(self, '_episode_request', 0)
            is_audio = self.is_audio_only()
            all_resolutions = await asyncio.to_thread(
                lambda: [worker.get_available_resolutions(t, audio_only=is_audio) for t in targets])
            if token != getattr(self, '_episode_request', 0):
                return
            preferred_resolution = None

            if len(targets) == 1:
                target = targets[0]
                is_audio = self.is_audio_only()
                resolutions = all_resolutions[0]
                target_title = getattr(target, 'title', str(target[1] if isinstance(target, (tuple, list)) and len(target) > 1 else 'Episode'))
                if len(resolutions) > 1:
                    chosen_res = await self.prompt_resolution_choice(
                        title="Select Download Format" if is_audio else "Select Download Resolution",
                        message=f"Multiple audio options available for '{target_title}'. Which format do you prefer to download?" if is_audio else f"Multiple resolutions available for '{target_title}'. Which resolution do you prefer to download?",
                        resolutions=resolutions
                    )
                    if not chosen_res:
                        _logger.info("Download cancelled by user.")
                        return
                    target.selected_media_url = chosen_res.get('url')
                    target.selected_resolution = chosen_res.get('id')
                elif len(resolutions) == 1:
                    target.selected_media_url = resolutions[0].get('url')
                    target.selected_resolution = resolutions[0].get('id')
            else:
                is_audio = self.is_audio_only()
                # Check if multiple resolutions exist across batch
                has_multi = any(len(resolutions) > 1 for resolutions in all_resolutions)
                if has_multi:
                    if is_audio:
                        seen_ids = set()
                        batch_options = []
                        for resolutions in all_resolutions:
                            for r in resolutions:
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
                            _logger.info("Batch download cancelled by user.")
                            return
                        preferred_resolution = chosen_batch.get('id')
                    elif len(batch_options) == 1:
                        preferred_resolution = batch_options[0].get('id')

            if getattr(self, '_is_downloading', False):
                self._show_dialog_threadsafe(
                    "info",
                    "Download In Progress",
                    "A download is already in progress. Please wait for it to finish or press Cancel first.",
                )
                return

            # Merge resolution discovery caches safely under _cache_lock before snapshotting
            cache_lock = getattr(self, '_cache_lock', None)
            def _merge_res_caches() -> None:
                for cache_attr in (
                    '_memberful_feeds_cache',
                    '_show_rss_cache',
                    '_media_webpage_cache',
                    '_episode_detail_cache',
                ):
                    w_cache = getattr(worker, cache_attr, None)
                    s_cache = getattr(self, cache_attr, None)
                    if isinstance(w_cache, dict) and isinstance(s_cache, dict):
                        s_cache.update(w_cache)
            if cache_lock is not None:
                with cache_lock:
                    _merge_res_caches()
            else:
                _merge_res_caches()

            # Snapshot UI widget settings on the UI thread before spawning background worker
            download_snapshot = {
                'base_dest_dir': self.get_destination_folder(),
                'block_size': self.get_block_size(),
                'show_folders': self.is_show_folders_enabled(),
                'audio_only': self.is_audio_only(),
                'worker': self._network_snapshot(),
            }

            # Start download in background thread so GUI remains responsive
            thread = threading.Thread(
                target=self.download_episodes_batch,
                args=(targets, preferred_resolution),
                kwargs={'download_snapshot': download_snapshot},
                daemon=True,
            )
            thread.start()
        except Exception as e:
            _logger.warning(f"Error initiating download: {e}")
        finally:
            if download_starting_acquired:
                self._download_starting = False
