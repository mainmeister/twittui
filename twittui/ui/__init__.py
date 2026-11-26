"""TwitTUI user-interface controllers, windows, and backend extensions."""

from twittui.ui.form import (
    TwitTUIForm,
    apply_tooltip_to_impl,
    get_widget_tooltip,
    main,
    patch_toga_gtk_app,
    patch_toga_icons,
    patch_toga_tooltips,
    resolve_app_icon,
    set_widget_tooltip,
)
from twittui.ui.metadata import MetadataMixin
from twittui.ui.preferences import PreferencesMixin

__all__ = [
    "MetadataMixin",
    "PreferencesMixin",
    "TwitTUIForm",
    "apply_tooltip_to_impl",
    "get_widget_tooltip",
    "main",
    "patch_toga_gtk_app",
    "patch_toga_icons",
    "patch_toga_tooltips",
    "resolve_app_icon",
    "set_widget_tooltip",
]
