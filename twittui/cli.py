"""CLI bootstrap and backend resolution facade for the ``twittui`` package."""

from main import (
    StderrRedirector,
    _NullTextIO,
    _configure_textual_warnings,
    configure_gtk_environment,
    get_installed_toga_backends,
    is_graphical_display_available,
    main,
    parse_backend_args,
    resolve_toga_backend,
    sanitize_gtk_module_env,
    show_terminal_splash,
)

__all__ = [
    "StderrRedirector",
    "_NullTextIO",
    "_configure_textual_warnings",
    "configure_gtk_environment",
    "get_installed_toga_backends",
    "is_graphical_display_available",
    "main",
    "parse_backend_args",
    "resolve_toga_backend",
    "sanitize_gtk_module_env",
    "show_terminal_splash",
]
