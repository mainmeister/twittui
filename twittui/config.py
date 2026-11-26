"""Configuration, URL constants, and secure file-persistence helpers for TwitTUI."""

from __future__ import annotations

import os
from dotenv import find_dotenv, load_dotenv

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
    except Exception:
        if fd_owned:
            try:
                os.close(fd)
            except OSError:
                pass
        raise
