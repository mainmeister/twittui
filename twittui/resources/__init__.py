"""Packaged runtime assets (README, API Blueprint, RSS styles, icons) loaded via importlib.resources."""

from __future__ import annotations

import atexit
from importlib import resources as importlib_resources
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from twittui.logging_config import get_logger

_logger = get_logger("resources")
_resource_lock = threading.Lock()
_materialized_resource_dir = None
_materialized_resource_paths: dict[str, str] = {}


def _cleanup_materialized_resources() -> None:
    global _materialized_resource_dir
    with _resource_lock:
        resource_dir = _materialized_resource_dir
        _materialized_resource_dir = None
        _materialized_resource_paths.clear()
    if resource_dir is not None:
        resource_dir.cleanup()


atexit.register(_cleanup_materialized_resources)


def get_resource_traversable(filename: str) -> Any | None:
    """Return an ``importlib.resources`` Traversable for ``filename`` if present."""
    if not filename:
        return None
    try:
        candidate = importlib_resources.files(__name__).joinpath(filename)
        if candidate.is_file():
            return candidate
    except (FileNotFoundError, ModuleNotFoundError, OSError, TypeError):
        _logger.debug("Could not inspect package resource %s", filename, exc_info=True)
    return None


def locate_resource_file(filename: str, *, keep_alive: bool = False) -> str | None:
    """Return a real resource path, optionally materializing it for the process lifetime."""
    candidate = get_resource_traversable(filename)
    if candidate is None:
        return None
    if isinstance(candidate, Path):
        resolved = str(candidate)
        return resolved if os.path.isfile(resolved) else None
    if not keep_alive:
        return None
    try:
        with _resource_lock:
            cached = _materialized_resource_paths.get(filename)
            if cached and os.path.isfile(cached):
                return cached

            global _materialized_resource_dir
            if _materialized_resource_dir is None:
                _materialized_resource_dir = tempfile.TemporaryDirectory(prefix="twittui-resources-")
            resolved = os.path.join(_materialized_resource_dir.name, os.path.basename(filename))
            with open(resolved, "wb") as resource_file:
                resource_file.write(candidate.read_bytes())
            if os.path.isfile(resolved):
                _materialized_resource_paths[filename] = resolved
                return resolved
    except (FileNotFoundError, OSError, TypeError):
        _logger.debug("Could not materialize path for resource %s", filename, exc_info=True)
    return None


def read_resource_text(filename: str, encoding: str = "utf-8", errors: str = "replace") -> str | None:
    """Read a UTF-8 text asset from ``twittui.resources`` via ``importlib.resources``."""
    candidate = get_resource_traversable(filename)
    if candidate is None:
        return None
    try:
        return candidate.read_text(encoding=encoding, errors=errors)
    except (FileNotFoundError, OSError, UnicodeError):
        _logger.debug("Could not read text resource %s", filename, exc_info=True)
        return None


def read_resource_bytes(filename: str) -> bytes | None:
    """Read raw bytes of an asset from ``twittui.resources`` via ``importlib.resources``."""
    candidate = get_resource_traversable(filename)
    if candidate is None:
        return None
    try:
        return candidate.read_bytes()
    except (FileNotFoundError, OSError):
        _logger.debug("Could not read binary resource %s", filename, exc_info=True)
        return None


def resolve_icon_base() -> str | None:
    """Locate the packaged application icon base path via ``importlib.resources``."""
    for fname in ("twittui.png", "twittui.ico"):
        path_str = locate_resource_file(fname, keep_alive=True)
        if path_str:
            return os.path.join(os.path.dirname(path_str), "twittui")
    return None


__all__ = [
    "get_resource_traversable",
    "locate_resource_file",
    "read_resource_text",
    "read_resource_bytes",
    "resolve_icon_base",
]
