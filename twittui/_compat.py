"""Shared runtime compatibility helpers for decomposed ``twittui`` modules.

Preserves 100% compatibility with existing ``twittui_form`` monkeypatches and
imports while locating project-root runtime assets reliably from any subpackage.
"""

from __future__ import annotations

import builtins
import os
import subprocess
import sys
from typing import Any

import requests

from twittui.logging_config import get_logger
from twittui.rate_limiter import ApiRateLimiter as _BaseApiRateLimiter

_logger = get_logger()

# Root directory of the TwitTUI package / repository (parent of ``twittui/``)
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_ROOT: str = os.path.dirname(os.path.abspath(__file__))


def compat_attr(name: str, fallback: Any) -> Any:
    """Resolve ``name`` through ``twittui_form`` if imported, honoring test patches."""
    mod = sys.modules.get("twittui_form")
    return getattr(mod, name, fallback) if mod is not None else fallback


def _is_textual_environment(app: Any = None) -> bool:
    """Return True when the active or configured Toga backend is Textual TUI."""
    target_app = app
    if target_app is None:
        toga_mod = sys.modules.get("toga")
        if toga_mod is not None:
            try:
                target_app = toga_mod.App.app
            except AttributeError:
                target_app = None
    if target_app is not None:
        impl = getattr(target_app, "_impl", None)
        native = getattr(impl, "native", None)
        native_mod = (
            getattr(getattr(native, "__class__", None), "__module__", "")
            if native is not None
            else ""
        )
        if native_mod.startswith(("toga_textual", "textual")):
            return True
        if native_mod and not native_mod.startswith("unittest.mock"):
            return False
    return os.environ.get("TOGA_BACKEND", "").strip().lower() in ("toga_textual", "textual")


def _is_textual_tui_running(app: Any = None) -> bool:
    """Return True when a live Textual TUI application loop is currently running."""
    target_app = app
    if target_app is None:
        toga_mod = sys.modules.get("toga")
        if toga_mod is not None:
            try:
                target_app = toga_mod.App.app
            except AttributeError:
                target_app = None
    if target_app is None:
        return False
    impl = getattr(target_app, "_impl", None)
    native = getattr(impl, "native", None)
    if native is None:
        return False
    native_mod = getattr(getattr(native, "__class__", None), "__module__", "")
    return bool(
        native_mod.startswith(("toga_textual", "textual"))
        and getattr(native, "_running", False)
    )


def quiet_print(*args: Any, **kwargs: Any) -> None:
    """Route internal form/worker diagnostic prints to logger instead of corrupting TUI stdout."""
    if os.environ.get("TWITTUI_DEBUG_STDOUT") == "1" and not _is_textual_environment():
        builtins.print(*args, **kwargs)
        return
    sep = kwargs.get("sep", " ")
    if sep is None:
        sep = " "
    msg = sep.join(str(a) for a in args).strip()
    if msg:
        _logger.debug("%s", msg)


class ApiRateLimiter(_BaseApiRateLimiter):
    """TwitTUIForm-bound ApiRateLimiter that honors patches on ``twittui_form.requests``."""

    def _resolve_http_get(self):
        if callable(self._http_get_provider):
            return self._http_get_provider()
        return requests.get


api_rate_limiter = ApiRateLimiter()


def launch_stream_safe(
    streamer_template: str,
    media_url: str,
    *,
    resolve: bool = True,
) -> subprocess.Popen:
    """Spawn media player safely with ``shell=False``, honoring ``twittui_form`` monkeypatches."""
    from twittui.media import launch_stream_safe as _launch_stream_safe_impl
    from twittui.media import resolve_stream_url as _default_resolve_stream_url

    resolver = compat_attr("resolve_stream_url", _default_resolve_stream_url)
    tui_running_fn = compat_attr("_is_textual_tui_running", _is_textual_tui_running)
    return _launch_stream_safe_impl(
        streamer_template,
        media_url,
        resolve=resolve,
        resolver=resolver,
        is_tui_running=tui_running_fn,
        popen_fn=subprocess.Popen,
    )
