"""Structured logging configuration for TwitTUI.

By default TwitTUI attaches only a ``NullHandler`` and sets ``propagate = False``
on the ``twittui`` logger so terminal UI output is never corrupted.  Diagnostic
logging can be enabled via ``--log-file <path>`` or the ``TWITTUI_LOG_FILE``
environment variable (with optional ``--log-level`` / ``TWITTUI_LOG_LEVEL``).
"""

from __future__ import annotations

import logging
import os
import urllib.parse

LOGGER_NAME = "twittui"
_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def safe_url_for_log(url: str) -> str:
    """Return only a URL's scheme and host, excluding paths and credentials."""
    try:
        parsed = urllib.parse.urlsplit(str(url))
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        if scheme not in {"http", "https"} or not hostname:
            return "<redacted-url>"
        host = f"[{hostname}]" if ":" in hostname else hostname
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return f"{scheme}://{host}"
    except (TypeError, ValueError):
        return "<redacted-url>"


def _ensure_base_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the root TwitTUI logger or a child logger under ``twittui.*``."""
    base = _ensure_base_logger()
    if not name or name == LOGGER_NAME:
        return base
    if name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def _parse_log_level(level: int | str | None) -> int:
    if isinstance(level, int):
        return level
    raw = (level or os.environ.get("TWITTUI_LOG_LEVEL") or "DEBUG").strip().upper()
    return getattr(logging, raw, logging.DEBUG)


def _create_restricted_log_file(log_path: str) -> None:
    """Ensure the diagnostic log file exists with owner-only (0o600) permissions."""
    parent = os.path.dirname(os.path.abspath(log_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(log_path, flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(log_path, 0o600)
    except OSError:
        try:
            os.chmod(log_path, 0o600)
        except OSError:
            pass
    finally:
        os.close(fd)


def _remove_managed_file_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "_twittui_managed_file_handler", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except OSError:
                pass


def configure_logging(
    log_file: str | None = None,
    level: int | str | None = None,
) -> logging.Logger:
    """Configure structured file logging when a log path is requested.

    Args:
        log_file: Optional file path. Falls back to ``TWITTUI_LOG_FILE`` env var.
        level: Optional logging level name or int (defaults to ``TWITTUI_LOG_LEVEL`` or DEBUG).

    Returns:
        The configured ``twittui`` logger.
    """
    logger = _ensure_base_logger()
    _remove_managed_file_handlers(logger)

    target = (log_file if log_file is not None else os.environ.get("TWITTUI_LOG_FILE", "")).strip()
    resolved_level = _parse_log_level(level)

    if target:
        try:
            _create_restricted_log_file(target)
            file_handler = logging.FileHandler(target, encoding="utf-8")
            file_handler.setLevel(resolved_level)
            file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
            setattr(file_handler, "_twittui_managed_file_handler", True)
            logger.addHandler(file_handler)
            logger.setLevel(resolved_level)
        except OSError:
            # Never crash application startup if a log path is unwritable.
            logger.setLevel(logging.NOTSET)
    else:
        logger.setLevel(logging.NOTSET)

    return logger


def reset_logging() -> None:
    """Detach and close any managed file handlers, restoring silent NullHandler mode."""
    logger = _ensure_base_logger()
    _remove_managed_file_handlers(logger)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.NOTSET)
    logger.propagate = False
