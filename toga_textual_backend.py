"""
Textual Backend Extensions and Implementations for Toga.

Provides complete Textual widget implementations for Selection, Table, ProgressBar,
WebView, and other widgets missing from standard toga-textual.
"""

from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
from typing import Any
import warnings
from rich.text import Text
from travertino.size import at_least
from textual._context import NoActiveAppError
from textual.app import SystemCommand
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.containers import Vertical, Horizontal
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Input as TextualInputWidget,
    Label,
    LoadingIndicator,
    ProgressBar as TextualProgressBar,
    Rule,
    Select,
    Static,
    TextArea,
)
import toga
import toga.dialogs
import toga.platform
from toga_textual.widgets.base import Widget


class RateLimitScreen(ModalScreen):
    DEFAULT_CSS = """
    RateLimitScreen { align: center middle; background: rgba(0, 0, 0, 0.7); }
    RateLimitScreen Vertical { width: 60; height: auto; border: solid $accent; background: $surface; padding: 1 2; }
    RateLimitScreen LoadingIndicator { height: 3; color: red; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._close_requested = False

    def compose(self) -> Any:
        with Vertical():
            yield Label('Waiting for the TWiT API. Please wait.')
            yield LoadingIndicator()

    def _try_dismiss(self) -> None:
        if not self._close_requested:
            return
        try:
            app = getattr(self, 'app', None)
            if not app:
                return
            if getattr(app, 'screen', None) is self:
                self.dismiss()
            else:
                stack = getattr(app, '_screen_stack', None)
                if isinstance(stack, list) and self in stack and stack[-1] is not self:
                    stack.remove(self)
        except Exception:
            pass

    def close_wait(self) -> None:
        self._close_requested = True
        self._try_dismiss()

    def on_mount(self) -> None:
        if self._close_requested:
            self.call_later(self._try_dismiss)

    def on_screen_resume(self) -> None:
        if self._close_requested:
            self._try_dismiss()


class SplashScreen(ModalScreen):
    """Textual modal splash screen displayed while TwitTUI loads or closes."""

    DEFAULT_CSS = """
    SplashScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #splash_box {
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
        align: center middle;
    }
    #splash_title {
        text-style: bold;
        margin-bottom: 1;
        width: 100%;
        text-align: center;
    }
    #splash_message {
        margin-bottom: 1;
        width: 100%;
        text-align: center;
    }
    SplashScreen LoadingIndicator {
        height: 3;
        color: $accent;
    }
    """

    def __init__(self, title: str = "TWiT.tv TUI", message: str = "Loading TwitTUI. Please wait...") -> None:
        super().__init__()
        self.splash_title = title
        self.splash_message = message
        self._close_requested = False

    def compose(self) -> Any:
        with Vertical(id="splash_box"):
            yield Label(self.splash_title, id="splash_title")
            yield Label(self.splash_message, id="splash_message")
            yield LoadingIndicator()

    def update_message(self, message: str) -> None:
        self.splash_message = message
        try:
            msg_label = self.query_one("#splash_message", Label)
            if msg_label:
                msg_label.update(message)
        except Exception:
            pass

    def _try_dismiss(self) -> None:
        if not self._close_requested:
            return
        try:
            app = getattr(self, 'app', None)
            if not app:
                return
            if getattr(app, 'screen', None) is self:
                self.dismiss()
            else:
                stack = getattr(app, '_screen_stack', None)
                if isinstance(stack, list) and self in stack and stack[-1] is not self:
                    stack.remove(self)
        except Exception:
            pass

    def close_splash(self) -> None:
        self._close_requested = True
        self._try_dismiss()

    def on_mount(self) -> None:
        if self._close_requested:
            self.call_later(self._try_dismiss)

    def on_screen_resume(self) -> None:
        if self._close_requested:
            self._try_dismiss()


def _resolve_dialog_future(future: Any, value: Any) -> None:
    """Safely resolve either an asyncio.Future or a Toga Dialog (AsyncResult) wrapper."""
    if future is None:
        return
    try:
        inner = getattr(future, "future", None)
        if inner is not None and hasattr(inner, "done"):
            if not inner.done():
                future.set_result(value)
        elif hasattr(future, "done"):
            if not future.done():
                future.set_result(value)
        elif hasattr(future, "set_result"):
            future.set_result(value)
    except Exception:
        pass


class TextualDialogScreen(ModalScreen):
    """Textual modal screen for displaying Toga dialogs."""

    DEFAULT_CSS = """
    TextualDialogScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #dialog_box {
        width: 60;
        max-width: 90%;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    #dialog_title {
        text-style: bold;
        margin-bottom: 1;
        width: 100%;
        text-align: center;
    }
    #dialog_message {
        margin-bottom: 1;
        width: 100%;
    }
    #button_row {
        align: center middle;
        width: 100%;
        height: auto;
    }
    #button_row Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_dialog", "Close"),
        Binding("left", "focus_previous", "Previous", show=False),
        Binding("right", "focus_next", "Next", show=False),
    ]

    def __init__(self, title: str, message: str, buttons: list[tuple[str, Any]], future: Any, default_result: Any = None) -> None:
        super().__init__()
        self.dialog_title = title
        self.dialog_message = message
        self.buttons = buttons
        self.future = future
        self.default_result = default_result

    def compose(self) -> Any:
        with Vertical(id="dialog_box"):
            yield Label(self.dialog_title, id="dialog_title")
            yield Label(self.dialog_message, id="dialog_message")
            with Horizontal(id="button_row"):
                for label, val in self.buttons:
                    yield Button(label, id=f"btn_{label.lower()}", variant="primary" if val else "default", tooltip=f"Select {label}")

    def on_mount(self) -> None:
        try:
            buttons = list(self.query(Button))
            if buttons:
                buttons[0].focus()
        except Exception:
            pass

    def _finish(self, value: Any) -> None:
        _resolve_dialog_future(self.future, value)
        try:
            self.dismiss(value)
        except Exception:
            pass

    def action_cancel_dialog(self) -> None:
        self._finish(self.default_result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        for label, val in self.buttons:
            if button_id == f"btn_{label.lower()}":
                self._finish(val)
                return
        self._finish(self.default_result)


class BaseTextualDialog:
    def __init__(self, title: str, message: str, buttons: list[tuple[str, Any]], default_result: Any = None) -> None:
        self.title = title
        self.message = message
        self.buttons = buttons
        self.default_result = default_result

    def show(self, host_window: Any, future: Any) -> None:
        try:
            app = getattr(host_window, 'app', None) or toga.App.app
            native = getattr(getattr(app, '_impl', None), 'native', None) if app else None
            if native is not None and getattr(native, '_running', False) and hasattr(native, 'push_screen'):
                screen = TextualDialogScreen(
                    self.title,
                    self.message,
                    self.buttons,
                    future,
                    default_result=self.default_result,
                )
                native.push_screen(screen)
                return
        except Exception:
            pass
        _resolve_dialog_future(future, self.default_result)


class TextualChoiceDialogScreen(ModalScreen):
    """Textual modal screen for displaying multiple choice options (such as video resolutions)."""

    DEFAULT_CSS = """
    TextualChoiceDialogScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #choice_dialog_box {
        width: 72;
        max-width: 90%;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    #choice_dialog_title {
        text-style: bold;
        margin-bottom: 1;
        width: 100%;
        text-align: center;
    }
    #choice_dialog_message {
        margin-bottom: 1;
        width: 100%;
        text-align: center;
    }
    #choice_options_container {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }
    .choice_option_btn {
        width: 100%;
        margin-bottom: 1;
    }
    #choice_cancel_row {
        align: center middle;
        width: 100%;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "focus_previous", "Previous", show=False),
        Binding("down", "focus_next", "Next", show=False),
    ]

    def __init__(self, title: str, message: str, options: list[dict], future: Any) -> None:
        super().__init__()
        self.dialog_title = title
        self.dialog_message = message
        self.options = options
        self.future = future

    def compose(self) -> Any:
        with Vertical(id="choice_dialog_box"):
            yield Label(self.dialog_title, id="choice_dialog_title")
            if self.dialog_message:
                yield Label(self.dialog_message, id="choice_dialog_message")
            with Vertical(id="choice_options_container"):
                for idx, opt in enumerate(self.options):
                    lbl = opt.get('label') or opt.get('name') or str(opt)
                    yield Button(lbl, id=f"opt_btn_{idx}", classes="choice_option_btn", variant="primary" if idx == 0 else "default", tooltip=f"Choose resolution: {lbl}")
            with Horizontal(id="choice_cancel_row"):
                yield Button("Cancel", id="btn_choice_cancel", variant="error", tooltip="Cancel resolution selection")

    def on_mount(self) -> None:
        try:
            if self.options:
                self.query_one("#opt_btn_0", Button).focus()
            else:
                self.query_one("#btn_choice_cancel", Button).focus()
        except Exception:
            pass

    def _finish(self, result: Any) -> None:
        _resolve_dialog_future(self.future, result)
        try:
            self.dismiss(result)
        except Exception:
            pass

    def action_cancel(self) -> None:
        self._finish(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn_choice_cancel":
            self._finish(None)
            return

        if button_id and button_id.startswith("opt_btn_"):
            try:
                idx = int(button_id.split("opt_btn_")[1])
                selected = self.options[idx]
                self._finish(selected)
                return
            except Exception:
                pass

        self._finish(None)


class ChoiceDialog(toga.dialogs.Dialog):
    """Dialog that allows user to choose from a list of option dictionaries."""
    def __init__(self, title: str, message: str, options: list[dict], default_result: Any = None) -> None:
        self.title = title
        self.message = message
        self.options = options
        self.default_result = default_result
        self._impl = self

    def _show(self, window: Any) -> asyncio.Future:
        try:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
        except RuntimeError:
            future = asyncio.Future()
        self.show(window, future)
        return future

    def show(self, host_window: Any, future: Any) -> None:
        try:
            app = getattr(host_window, 'app', None) or toga.App.app
            native = getattr(getattr(app, '_impl', None), 'native', None) if app else None
            if native is not None and getattr(native, '_running', False) and hasattr(native, 'push_screen'):
                screen = TextualChoiceDialogScreen(self.title, self.message, self.options, future)
                native.push_screen(screen)
                return
        except Exception:
            pass
        _resolve_dialog_future(future, self.default_result)


class InfoDialog(BaseTextualDialog):
    def __init__(self, title: str, message: str) -> None:
        super().__init__(title, message, [("OK", None)], default_result=None)


class ErrorDialog(BaseTextualDialog):
    def __init__(self, title: str, message: str) -> None:
        super().__init__(title, message, [("OK", None)], default_result=None)


class QuestionDialog(BaseTextualDialog):
    def __init__(self, title: str, message: str) -> None:
        super().__init__(title, message, [("Yes", True), ("No", False)], default_result=False)


class ConfirmDialog(BaseTextualDialog):
    def __init__(self, title: str, message: str) -> None:
        super().__init__(title, message, [("OK", True), ("Cancel", False)], default_result=False)


class _FoldersOnlyDirectoryTree(DirectoryTree):
    """DirectoryTree filtered to display directories only for folder selection."""

    def filter_paths(self, paths: Any) -> list[Path]:
        filtered: list[Path] = []
        for p in paths:
            try:
                if p.is_dir() and not p.name.startswith("."):
                    filtered.append(p)
            except Exception:
                pass
        return sorted(filtered, key=lambda item: item.name.lower())


class TextualSelectFolderScreen(ModalScreen):
    """Interactive Textual modal screen for selecting a directory in TUI mode."""

    DEFAULT_CSS = """
    TextualSelectFolderScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #folder_dialog_box {
        width: 84;
        max-width: 94%;
        height: 24;
        max-height: 90%;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    #folder_dialog_title {
        text-style: bold;
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }
    #folder_path_row {
        width: 100%;
        height: 3;
        margin-bottom: 1;
    }
    #folder_path_input {
        width: 1fr;
    }
    #btn_folder_up {
        min-width: 8;
        margin-left: 1;
    }
    #folder_tree {
        width: 100%;
        height: 1fr;
        border: solid $panel;
        margin-bottom: 1;
    }
    #folder_button_row {
        align: center middle;
        width: 100%;
        height: auto;
    }
    #folder_button_row Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_folder", "Cancel"),
    ]

    def __init__(
        self,
        title: str,
        initial_directory: Any = None,
        multiple_select: bool = False,
        future: Any = None,
    ) -> None:
        super().__init__()
        self.dialog_title = title or "Select Folder"
        self.multiple_select = multiple_select
        self.future = future
        start_dir = Path(os.path.expanduser(str(initial_directory))) if initial_directory else Path(os.getcwd())
        try:
            if not start_dir.is_dir():
                start_dir = start_dir.parent if start_dir.parent.is_dir() else Path(os.getcwd())
            start_dir = start_dir.resolve()
        except Exception:
            start_dir = Path(os.getcwd())
        self.current_dir: Path = start_dir

    def compose(self) -> Any:
        with Vertical(id="folder_dialog_box"):
            yield Label(self.dialog_title, id="folder_dialog_title")
            with Horizontal(id="folder_path_row"):
                yield TextualInputWidget(
                    value=str(self.current_dir),
                    placeholder="Enter directory path...",
                    id="folder_path_input",
                    tooltip="Enter or edit destination directory path",
                )
                yield Button(
                    "Up",
                    id="btn_folder_up",
                    tooltip="Navigate to parent directory",
                )
            yield _FoldersOnlyDirectoryTree(self.current_dir, id="folder_tree")
            with Horizontal(id="folder_button_row"):
                yield Button(
                    "Select Folder",
                    id="btn_folder_select",
                    variant="primary",
                    tooltip="Confirm selected directory",
                )
                yield Button(
                    "Cancel",
                    id="btn_folder_cancel",
                    variant="error",
                    tooltip="Cancel folder selection",
                )

    def on_mount(self) -> None:
        try:
            self.query_one("#folder_tree", _FoldersOnlyDirectoryTree).focus()
        except Exception:
            pass

    def _finish(self, selected: Path | None) -> None:
        if selected is None:
            result: Any = None
        elif self.multiple_select:
            result = [selected]
        else:
            result = selected
        _resolve_dialog_future(self.future, result)
        try:
            self.dismiss(result)
        except Exception:
            pass

    def _navigate_to(self, target_dir: Path) -> None:
        try:
            resolved = target_dir.expanduser().resolve()
            if resolved.is_dir():
                self.current_dir = resolved
                self.query_one("#folder_path_input", TextualInputWidget).value = str(resolved)
                tree = self.query_one("#folder_tree", _FoldersOnlyDirectoryTree)
                tree.path = resolved
        except Exception:
            pass

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        try:
            selected_path = Path(event.path).resolve()
            self.current_dir = selected_path
            self.query_one("#folder_path_input", TextualInputWidget).value = str(selected_path)
        except Exception:
            pass

    def on_input_submitted(self, event: TextualInputWidget.Submitted) -> None:
        if event.input.id == "folder_path_input":
            raw = (event.value or "").strip()
            if raw:
                candidate = Path(os.path.expanduser(raw))
                if candidate.is_dir():
                    self._navigate_to(candidate)
                else:
                    self._finish(candidate)

    def action_cancel_folder(self) -> None:
        self._finish(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_folder_cancel":
            self._finish(None)
            return
        if btn_id == "btn_folder_up":
            parent = self.current_dir.parent
            if parent != self.current_dir:
                self._navigate_to(parent)
            return
        if btn_id == "btn_folder_select":
            try:
                raw = self.query_one("#folder_path_input", TextualInputWidget).value.strip()
                chosen = Path(os.path.expanduser(raw)) if raw else self.current_dir
            except Exception:
                chosen = self.current_dir
            self._finish(chosen)


class SelectFolderDialog:
    def __init__(self, title: str, initial_directory: Any = None, multiple_select: bool = False) -> None:
        self.title = title
        self.initial_directory = initial_directory
        self.multiple_select = multiple_select

    def show(self, host_window: Any, future: Any) -> None:
        try:
            app = getattr(host_window, 'app', None) or toga.App.app
            native = getattr(getattr(app, '_impl', None), 'native', None) if app else None
            if native is not None and getattr(native, '_running', False) and hasattr(native, 'push_screen'):
                screen = TextualSelectFolderScreen(
                    self.title,
                    initial_directory=self.initial_directory,
                    multiple_select=self.multiple_select,
                    future=future,
                )
                native.push_screen(screen)
                return
        except Exception:
            pass
        res = Path(self.initial_directory or os.getcwd())
        _resolve_dialog_future(future, [res] if self.multiple_select else res)


class OpenFileDialog:
    def __init__(self, title: str, initial_directory: Any = None, file_types: Any = None, multiple_select: bool = False) -> None:
        self.title = title
        self.initial_directory = initial_directory
        self.multiple_select = multiple_select

    def show(self, host_window: Any, future: Any) -> None:
        if not future.done():
            future.set_result(None)


class SaveFileDialog:
    def __init__(self, title: str, filename: str, initial_directory: Any = None, file_types: Any = None) -> None:
        self.title = title
        self.filename = filename
        self.initial_directory = initial_directory

    def show(self, host_window: Any, future: Any) -> None:
        if not future.done():
            future.set_result(None)


class DialogsFactory:
    """Factory container for Textual dialogs."""
    InfoDialog = InfoDialog
    ErrorDialog = ErrorDialog
    QuestionDialog = QuestionDialog
    ConfirmDialog = ConfirmDialog
    SelectFolderDialog = SelectFolderDialog
    OpenFileDialog = OpenFileDialog
    SaveFileDialog = SaveFileDialog
    ChoiceDialog = ChoiceDialog
    SelectResolutionDialog = ChoiceDialog


class TogaSelect(Select):
    """Textual native Select wrapper for Toga Selection."""

    def __init__(self, impl: TextualSelection, **kwargs: Any) -> None:
        super().__init__(options=[], allow_blank=True, **kwargs)
        self.interface = impl.interface
        self.impl = impl

    def on_mount(self, event: Any = None) -> None:
        self.impl._sync_options_to_native()

    def on_select_changed(self, event: Select.Changed) -> None:
        if self.impl._suppress_change:
            return
        if event.value != Select.BLANK:
            for idx, (title, val) in enumerate(self.impl._options):
                if str(idx) == str(event.value) or val == event.value:
                    self.impl._selected_index = idx
                    if self.interface.on_change:
                        self.interface.on_change()
                    break


class TextualSelection(Widget):
    """Toga Selection backend implementation for Textual."""

    def create(self) -> None:
        self._options: list[tuple[str, Any]] = []
        self._selected_index: int | None = None
        self._suppress_change = False
        self.native = TogaSelect(self)

    def _sync_options_to_native(self) -> None:
        from textual.widgets._select import SelectOverlay
        try:
            self.native.query_one(SelectOverlay)
        except Exception:
            return
        self._suppress_change = True
        try:
            native_opts = [(title, str(idx)) for idx, (title, val) in enumerate(self._options)]
            if native_opts:
                self.native._allow_blank = False
                self.native.set_options(native_opts)
                if self._selected_index is not None and 0 <= self._selected_index < len(native_opts):
                    self.native.value = str(self._selected_index)
                else:
                    self._selected_index = 0
                    self.native.value = native_opts[0][1]
            else:
                self.native._allow_blank = True
                self.native.set_options([])
                self.native.value = Select.BLANK
                self._selected_index = None
        except Exception:
            pass
        finally:
            self._suppress_change = False

    def source_clear(self) -> None:
        self._options.clear()
        self._selected_index = None
        self._sync_options_to_native()

    def source_insert(self, index: int, item: Any) -> None:
        title = self.interface._title_for_item(item)
        self._options.insert(index, (title, item))
        if self._selected_index is None and len(self._options) > 0:
            self._selected_index = 0
        self._sync_options_to_native()

    def source_remove(self, index: int, item: Any) -> None:
        if 0 <= index < len(self._options):
            del self._options[index]
            if self._selected_index == index:
                self._selected_index = 0 if self._options else None
            elif self._selected_index is not None and self._selected_index > index:
                self._selected_index -= 1
        self._sync_options_to_native()

    def source_change(self, item: Any) -> None:
        title = self.interface._title_for_item(item)
        for idx, (t, val) in enumerate(self._options):
            if val == item:
                self._options[idx] = (title, item)
                break
        self._sync_options_to_native()

    def select_item(self, index: int, item: Any) -> None:
        self._selected_index = index
        from textual.widgets._select import SelectOverlay
        try:
            self.native.query_one(SelectOverlay)
        except Exception:
            return
        self._suppress_change = True
        try:
            if 0 <= index < len(self._options):
                self.native.value = str(index)
            else:
                self.native.value = Select.BLANK
        except Exception:
            pass
        finally:
            self._suppress_change = False

    def get_selected_index(self) -> int | None:
        return self._selected_index

    def rehint(self) -> None:
        max_len = max([len(t) for t, _ in self._options], default=10)
        self.interface.intrinsic.width = at_least(max_len + 8)
        self.interface.intrinsic.height = 3


class TogaDataTable(DataTable):
    """Textual native DataTable wrapper for Toga Table."""

    MARKED_LABEL = "☑"
    UNMARKED_LABEL = "☐"

    COMPONENT_CLASSES = DataTable.COMPONENT_CLASSES | {
        "datatable--marked-row",
    }

    DEFAULT_CSS = """
    TogaDataTable > .datatable--marked-row {
        background: $success 28%;
        color: $foreground;
        text-style: bold;
    }
    TogaDataTable:dark > .datatable--marked-row {
        background: $success 28%;
        color: $foreground;
        text-style: bold;
    }
    TogaDataTable:ansi > .datatable--marked-row {
        background: ansi_green;
        color: ansi_default;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding('space', 'toggle_row_select', 'Toggle Select', show=True),
        Binding('shift+up', 'range_select_up', 'Select Up', show=False),
        Binding('shift+down', 'range_select_down', 'Select Down', show=False),
        Binding('ctrl+a', 'select_all_rows', 'Select All', show=True),
        Binding('escape', 'clear_row_selection', 'Clear Selection', show=True),
        Binding('u', 'clear_row_selection', 'Clear Selection', show=False),
    ]

    _MULTI_SELECT_ACTIONS = frozenset({
        'toggle_row_select',
        'range_select_up',
        'range_select_down',
        'select_all_rows',
        'clear_row_selection',
    })

    def __init__(self, impl: TextualTable, **kwargs: Any) -> None:
        super().__init__(cursor_type='row', zebra_stripes=True, **kwargs)
        self.interface = impl.interface
        self.impl = impl
        self._marked_rows: set[int] = set()
        self._shift_anchor: int | None = None
        self._shift_base_marks: set[int] | None = None
        self._shift_cursor_row: int | None = None
        self._last_anchor_row: int | None = None

    @classmethod
    def _row_mark_label(cls, marked: bool) -> Text:
        if marked:
            return Text(cls.MARKED_LABEL, style='bold bright_green')
        return Text(cls.UNMARKED_LABEL, style='dim')

    def _clear_marks_state(self) -> bool:
        had_marks = bool(self._marked_rows)
        self._marked_rows.clear()
        self._shift_anchor = None
        self._shift_base_marks = None
        self._shift_cursor_row = None
        self._last_anchor_row = None
        return had_marks

    def _refresh_marked_visuals(self, row_indices: Any = None) -> None:
        if not getattr(self, 'is_mounted', False):
            return
        try:
            if self.interface.multiple_select:
                indices = (
                    range(self.row_count)
                    if row_indices is None
                    else [idx for idx in row_indices if 0 <= idx < self.row_count]
                )
                for idx in indices:
                    row_key = self._row_locations.get_key(idx)
                    if row_key is not None and row_key in self.rows:
                        self.rows[row_key].label = self._row_mark_label(idx in self._marked_rows)
                self._update_count += 1
                if row_indices is None:
                    self.refresh()
                else:
                    for idx in indices:
                        self.refresh_row(idx)
            self.refresh_bindings()
        except Exception:
            pass

    def _notify_selection_changed(self) -> None:
        if self.interface.on_select:
            self.interface.on_select()

    def _toggle_row_mark(self, row_idx: int) -> None:
        if not (0 <= row_idx < len(self.impl._rows)):
            return
        if row_idx in self._marked_rows:
            self._marked_rows.remove(row_idx)
        else:
            self._marked_rows.add(row_idx)
        self._refresh_marked_visuals([row_idx])
        self._notify_selection_changed()

    def _mark_row_range(self, start_row: int, end_row: int) -> None:
        if not self.impl._rows:
            return
        max_idx = len(self.impl._rows) - 1
        lo = max(0, min(max_idx, min(start_row, end_row)))
        hi = max(0, min(max_idx, max(start_row, end_row)))
        added = set(range(lo, hi + 1)) - self._marked_rows
        self._marked_rows.update(range(lo, hi + 1))
        self._refresh_marked_visuals(added or range(lo, hi + 1))
        self._notify_selection_changed()

    def _extend_shift_selection(self, delta: int) -> None:
        if not self.interface.multiple_select or not self.impl._rows:
            return
        cur = self.cursor_row if self.cursor_row is not None else 0
        if not (0 <= cur < len(self.impl._rows)):
            return
        if self._shift_anchor is None:
            self._shift_anchor = cur
            self._shift_base_marks = set(self._marked_rows)
        target = max(0, min(len(self.impl._rows) - 1, cur + delta))
        lo, hi = min(self._shift_anchor, target), max(self._shift_anchor, target)
        base = self._shift_base_marks if self._shift_base_marks is not None else set()
        new_marks = base | set(range(lo, hi + 1))
        changed = self._marked_rows ^ new_marks
        self._marked_rows = new_marks
        self._last_anchor_row = self._shift_anchor
        self._shift_cursor_row = target
        self.move_cursor(row=target)
        self._refresh_marked_visuals(changed or [cur, target])
        if changed:
            self._notify_selection_changed()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in self._MULTI_SELECT_ACTIONS:
            if not self.interface.multiple_select:
                return False
            if action == 'clear_row_selection':
                return bool(self._marked_rows)
            if action == 'select_all_rows':
                return bool(self.impl._rows)
        return True

    def _get_row_style(self, row_index: int, base_style: Any) -> Any:
        if (
            row_index >= 0
            and self.interface.multiple_select
            and row_index in self._marked_rows
        ):
            return self.get_component_styles("datatable--marked-row").rich_style
        return super()._get_row_style(row_index, base_style)

    def _render_cell(
        self,
        row_index: int,
        column_index: int,
        base_style: Any,
        width: int,
        cursor: bool = False,
        hover: bool = False,
    ) -> Any:
        if (
            column_index == -1
            and row_index >= 0
            and self.interface.multiple_select
            and row_index in self._marked_rows
        ):
            base_style = self.get_component_styles("datatable--marked-row").rich_style
        return super()._render_cell(
            row_index,
            column_index,
            base_style,
            width,
            cursor=cursor,
            hover=hover,
        )

    def on_mount(self, event: Any = None) -> None:
        self.impl._sync_data_to_native(force=True)

    def action_toggle_row_select(self) -> None:
        if not self.interface.multiple_select:
            return
        row_idx = self.cursor_row
        if row_idx is not None and 0 <= row_idx < len(self.impl._rows):
            self._shift_anchor = None
            self._shift_base_marks = None
            self._shift_cursor_row = None
            self._last_anchor_row = row_idx
            self._toggle_row_mark(row_idx)

    def action_range_select_up(self) -> None:
        self._extend_shift_selection(-1)

    def action_range_select_down(self) -> None:
        self._extend_shift_selection(1)

    def action_select_all_rows(self) -> None:
        if not self.interface.multiple_select or not self.impl._rows:
            return
        all_indices = set(range(len(self.impl._rows)))
        changed = all_indices - self._marked_rows
        self._marked_rows = all_indices
        self._shift_anchor = None
        self._shift_base_marks = None
        self._shift_cursor_row = None
        self._refresh_marked_visuals(changed or all_indices)
        self._notify_selection_changed()

    def action_clear_row_selection(self) -> None:
        if not self.interface.multiple_select or not self._marked_rows:
            return
        cleared = set(self._marked_rows)
        self._clear_marks_state()
        self._refresh_marked_visuals(cleared)
        self._notify_selection_changed()

    async def _on_click(self, event: Any) -> None:
        if self.interface.multiple_select:
            meta = getattr(getattr(event, 'style', None), 'meta', None) or {}
            if 'row' in meta and 'column' in meta:
                row_index = meta['row']
                column_index = meta['column']
                if 0 <= row_index < len(self.impl._rows):
                    is_row_label_click = self.show_row_labels and column_index == -1
                    if getattr(event, 'shift', False):
                        self._set_hover_cursor(True)
                        anchor = self._last_anchor_row
                        if anchor is None:
                            anchor = self.cursor_row if self.cursor_row is not None else row_index
                        self._shift_anchor = None
                        self._shift_base_marks = None
                        self._shift_cursor_row = None
                        self._last_anchor_row = anchor
                        self._mark_row_range(anchor, row_index)
                        self.move_cursor(row=row_index)
                        event.stop()
                        return
                    if is_row_label_click or getattr(event, 'ctrl', False):
                        self._set_hover_cursor(True)
                        self._shift_anchor = None
                        self._shift_base_marks = None
                        self._shift_cursor_row = None
                        self._last_anchor_row = row_index
                        self._toggle_row_mark(row_index)
                        self.move_cursor(row=row_index)
                        event.stop()
                        return
        await super()._on_click(event)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self.impl._rows):
            row_data = self.impl._rows[row_idx]
            if self.interface.on_activate:
                self.interface.on_activate(row=row_data)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._shift_cursor_row is not None and event.cursor_row == self._shift_cursor_row:
            return
        self._shift_cursor_row = None
        self._shift_anchor = None
        self._shift_base_marks = None
        if self.interface.on_select:
            self.interface.on_select()

    def on_mouse_move(self, event: Any) -> None:
        try:
            row_idx = self.hover_row
            if row_idx is not None and 0 <= row_idx < len(self.impl._rows):
                if hasattr(self.interface, 'on_hover_row') and callable(self.interface.on_hover_row):
                    self.interface.on_hover_row(row_idx)
        except Exception:
            pass

    def on_leave(self, event: Any) -> None:
        try:
            if hasattr(self.interface, 'on_hover_leave') and callable(self.interface.on_hover_leave):
                self.interface.on_hover_leave()
        except Exception:
            pass


class TextualTable(Widget):
    """Toga Table backend implementation for Textual."""

    def create(self) -> None:
        self._columns: list[Any] = []
        self._rows: list[Any] = []
        self.native = TogaDataTable(self)

    def _sync_data_to_native(self, force: bool = False) -> None:
        if hasattr(self.native, '_marked_rows'):
            self.native._marked_rows = {
                idx for idx in self.native._marked_rows if 0 <= idx < len(self._rows)
            }
        if not force and not (
            getattr(self.native, 'is_mounted', False)
            or getattr(self.native, 'is_attached', False)
        ):
            return
        try:
            self.native.clear(columns=True)
            headings = [col.heading for col in self.interface.columns]
            if headings:
                self.native.add_columns(*headings)
            is_multi = bool(self.interface.multiple_select)
            marked = getattr(self.native, '_marked_rows', set())
            for idx, row in enumerate(self._rows):
                row_vals = []
                for col in self.interface.columns:
                    val = getattr(row, col.accessor, '')
                    row_vals.append(str(val if val is not None else ''))
                if is_multi:
                    self.native.add_row(
                        *row_vals,
                        label=self.native._row_mark_label(idx in marked),
                    )
                else:
                    self.native.add_row(*row_vals)
            self.native.refresh_bindings()
        except Exception:
            pass

    def change_source(self, source: Any) -> None:
        self._rows = list(source) if source else []
        had_marks = False
        if hasattr(self.native, '_clear_marks_state'):
            had_marks = self.native._clear_marks_state()
        elif hasattr(self.native, '_marked_rows'):
            had_marks = bool(self.native._marked_rows)
            self.native._marked_rows.clear()
        self._sync_data_to_native()
        if had_marks and self.interface.on_select:
            self.interface.on_select()

    def source_clear(self) -> None:
        self._rows.clear()
        had_marks = False
        if hasattr(self.native, '_clear_marks_state'):
            had_marks = self.native._clear_marks_state()
        elif hasattr(self.native, '_marked_rows'):
            had_marks = bool(self.native._marked_rows)
            self.native._marked_rows.clear()
        self._sync_data_to_native()
        if had_marks and self.interface.on_select:
            self.interface.on_select()

    def source_insert(self, index: int, item: Any) -> None:
        self._rows.insert(index, item)
        if hasattr(self.native, '_marked_rows') and self.native._marked_rows:
            self.native._marked_rows = {
                (r + 1 if r >= index else r) for r in self.native._marked_rows
            }
        self._sync_data_to_native()

    def source_remove(self, index: int, item: Any) -> None:
        removed_marked = False
        if 0 <= index < len(self._rows):
            del self._rows[index]
            if hasattr(self.native, '_marked_rows') and self.native._marked_rows:
                removed_marked = index in self.native._marked_rows
                self.native._marked_rows = {
                    (r - 1 if r > index else r)
                    for r in self.native._marked_rows
                    if r != index
                }
        self._sync_data_to_native()
        if removed_marked and self.interface.on_select:
            self.interface.on_select()

    def source_change(self, item: Any) -> None:
        self._sync_data_to_native()

    def get_selection(self) -> list[int] | int | None:
        if self.interface.multiple_select:
            if hasattr(self.native, '_marked_rows') and self.native._marked_rows:
                return sorted(list(self.native._marked_rows))
            if self.native.cursor_row is not None and 0 <= self.native.cursor_row < len(self._rows):
                return [self.native.cursor_row]
            return []
        else:
            if self.native.cursor_row is not None and 0 <= self.native.cursor_row < len(self._rows):
                return self.native.cursor_row
            return None

    def scroll_to_row(self, row_index: int) -> None:
        if getattr(self.native, 'is_mounted', False) and 0 <= row_index < len(self._rows):
            try:
                self.native.move_cursor(row=row_index)
            except Exception:
                pass

    def insert_column(self, index: int, column: Any) -> None:
        self._sync_data_to_native()

    def remove_column(self, index: int) -> None:
        self._sync_data_to_native()

    def rehint(self) -> None:
        self.interface.intrinsic.width = at_least(40)
        self.interface.intrinsic.height = at_least(10)


class TogaProgressBar(TextualProgressBar):
    """Textual native ProgressBar wrapper for Toga ProgressBar."""

    def __init__(self, impl: TextualProgressBarImpl, **kwargs: Any) -> None:
        super().__init__(total=100.0, show_eta=False, **kwargs)
        self.interface = impl.interface
        self.impl = impl


class TextualProgressBarImpl(Widget):
    """Toga ProgressBar backend implementation for Textual."""

    def create(self) -> None:
        self._max = 100.0
        self._value = 0.0
        self._running = False
        self.native = TogaProgressBar(self)

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def get_value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._value = value
        if getattr(self.native, 'is_mounted', False):
            try:
                self.native.update(progress=value)
            except Exception:
                pass

    def get_max(self) -> float:
        return self._max

    def set_max(self, value: float) -> None:
        self._max = value
        if getattr(self.native, 'is_mounted', False):
            try:
                self.native.update(total=value)
            except Exception:
                pass

    def rehint(self) -> None:
        self.interface.intrinsic.width = at_least(20)
        self.interface.intrinsic.height = 1


class TextualWebView(Widget):
    """Toga WebView fallback implementation for Textual."""

    def create(self) -> None:
        self.native = Static("WebView (Documentation / Web Content)")
        self._url = ""
        self._content = ""

    def set_content(self, root_url: str, content: str) -> None:
        import re as _re
        import html as _html
        self._url = root_url or ""
        text = content or ""
        if "<" in text and ">" in text:
            text = _re.sub(r"<style[^>]*>.*?</style>", "", text, flags=_re.S | _re.I)
            text = _re.sub(r"<script[^>]*>.*?</script>", "", text, flags=_re.S | _re.I)
            text = _re.sub(r"<\s*br\s*/?>", "\n", text, flags=_re.I)
            text = _re.sub(r"</\s*(?:p|div|h[1-6]|li|tr)\s*>", "\n", text, flags=_re.I)
            text = _re.sub(r"<[^>]+>", "", text)
            text = _html.unescape(text)
            text = _re.sub(r"\n{3,}", "\n\n", text).strip()
        self._content = text
        try:
            self.native.update(text if text else "WebView (Documentation / Web Content)")
        except Exception:
            pass

    def set_url(self, url: str) -> None:
        self._url = url or ""
        try:
            self.native.update(f"Web Content: {self._url}")
        except Exception:
            pass

    def get_url(self) -> str:
        return self._url

    def rehint(self) -> None:
        self.interface.intrinsic.width = at_least(20)
        self.interface.intrinsic.height = at_least(10)


class TextualDivider(Widget):
    """Toga Divider implementation for Textual."""

    def create(self) -> None:
        self.native = Rule()

    def rehint(self) -> None:
        self.interface.intrinsic.width = at_least(10)
        self.interface.intrinsic.height = 1


class TextualActivityIndicator(Widget):
    """Toga ActivityIndicator implementation for Textual."""

    def create(self) -> None:
        self._running = False
        self.native = LoadingIndicator()

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def rehint(self) -> None:
        self.interface.intrinsic.width = at_least(5)
        self.interface.intrinsic.height = 1


class TextualMultilineTextInput(Widget):
    """Toga MultilineTextInput implementation for Textual."""

    def create(self) -> None:
        self.native = TextArea()

    def get_value(self) -> str:
        return self.native.text if hasattr(self.native, 'text') else ""

    def set_value(self, value: str) -> None:
        if hasattr(self.native, 'load_text'):
            self.native.load_text(value or "")

    def get_placeholder(self) -> str:
        return ""

    def set_placeholder(self, value: str) -> None:
        pass

    def get_readonly(self) -> bool:
        return getattr(self.native, 'read_only', False)

    def set_readonly(self, value: bool) -> None:
        self.native.read_only = bool(value)

    def rehint(self) -> None:
        self.interface.intrinsic.width = at_least(20)
        self.interface.intrinsic.height = at_least(5)


class TextualPasswordInput(Widget):
    """Toga PasswordInput implementation for Textual."""

    def create(self) -> None:
        self._is_valid = True
        self._programmatic_change = None
        try:
            from toga_textual.widgets.textinput import TogaInput
            self.native = TogaInput(self, password=True)
        except Exception:
            from textual.widgets import Input as TextualInput
            self.native = TextualInput(password=True)

    def get_readonly(self) -> bool:
        return getattr(self.native, 'disabled', False)

    def set_readonly(self, value: bool) -> None:
        self.native.disabled = bool(value)

    def get_placeholder(self) -> str:
        return getattr(self.native, 'placeholder', '')

    def set_placeholder(self, value: str) -> None:
        self.native.placeholder = value or ''

    def get_value(self) -> str:
        return getattr(self.native, 'value', '')

    def set_value(self, value: str) -> None:
        old_value = getattr(self.native, 'value', '')
        self._programmatic_change = value
        try:
            self.native.value = value or ''
        except NoActiveAppError:
            pass

        if value != old_value:
            if hasattr(self, 'interface') and hasattr(self.interface, '_value_changed'):
                self.interface._value_changed()
        else:
            self._programmatic_change = None

    def set_error(self, error_message: str) -> None:
        self._is_valid = False

    def clear_error(self) -> None:
        self._is_valid = True

    def is_valid(self) -> bool:
        return self._is_valid

    @property
    def width_adjustment(self) -> int:
        return 2

    @property
    def height_adjustment(self) -> int:
        return 2

    def rehint(self) -> None:
        val = getattr(self.native, 'value', '') or ''
        self.interface.intrinsic.width = at_least(min(max(len(val) + 4, 12), 28))
        self.interface.intrinsic.height = 3


class TextualSwitch(Widget):
    """Textual implementation for Toga Switch / Checkbox widget."""

    def create(self) -> None:
        self._initial_value = False
        try:
            from toga_textual.widgets.switch import TogaSwitch
            self.native_switch = TogaSwitch(self)
        except Exception:
            from textual.widgets import Switch as BaseSwitch
            self.native_switch = BaseSwitch()

        self.native_label = Label()
        try:
            self.native_label.styles.padding = (1, 0, 0, 1)
        except Exception:
            pass
        self.native = Horizontal(self.native_switch, self.native_label)

    def get_text(self) -> str:
        return str(getattr(self.native_label, 'renderable', ''))

    def set_text(self, text: str) -> None:
        if hasattr(self.native_label, 'update'):
            self.native_label.update(text or '')
        try:
            self.refresh()
        except Exception:
            pass

    def get_value(self) -> bool:
        return bool(getattr(self.native_switch, 'value', self._initial_value))

    def set_value(self, value: bool) -> None:
        bool_val = bool(value)
        old_val = self.get_value()
        self._initial_value = bool_val
        notified_by_textual = False
        try:
            self.native_switch.value = bool_val
            notified_by_textual = bool(getattr(self.native_switch, 'is_mounted', False))
        except (NoActiveAppError, Exception):
            notified_by_textual = False
        if old_val != bool_val and not notified_by_textual:
            try:
                if hasattr(self, 'interface') and getattr(self.interface, 'on_change', None) is not None:
                    self.interface.on_change()
            except Exception:
                pass

    def set_enabled(self, value: bool) -> None:
        super().set_enabled(value)
        if hasattr(self.native_switch, 'disabled'):
            self.native_switch.disabled = not bool(value)

    def focus(self) -> None:
        try:
            if hasattr(self.native_switch, 'app') and hasattr(self.native_switch.app, 'set_focus'):
                self.native_switch.app.set_focus(self.native_switch)
        except Exception:
            pass

    def rehint(self) -> None:
        text_len = len(self.get_text())
        self.interface.intrinsic.width = at_least(text_len + 8)
        self.interface.intrinsic.height = 3


# Registry of widget implementations for toga_textual
TEXTUAL_WIDGET_IMPLEMENTATIONS: dict[str, type] = {
    'Selection': TextualSelection,
    'Table': TextualTable,
    'ProgressBar': TextualProgressBarImpl,
    'WebView': TextualWebView,
    'Divider': TextualDivider,
    'ActivityIndicator': TextualActivityIndicator,
    'MultilineTextInput': TextualMultilineTextInput,
    'PasswordInput': TextualPasswordInput,
    'Switch': TextualSwitch,
}


def patch_toga_textual() -> None:
    """Register missing Textual widget implementations with Toga's platform factory."""
    try:
        import toga_textual
        import toga_textual.app
        import toga_textual.window
        import toga_textual.widgets.base
        import toga_textual.widgets.textinput

        warnings.filterwarnings(
            "ignore",
            message=r".*\[toga_textual\] Not implemented:.*",
        )

        # Cap TextInput intrinsic min-width so long values scroll inside Input instead of pushing buttons off-screen
        if not getattr(toga_textual.widgets.textinput.TextInput, "_twittui_rehint_patched", False):
            def _capped_textinput_rehint(self: Any) -> None:
                val = getattr(self.native, "value", "") or ""
                self.interface.intrinsic.width = at_least(min(max(len(val) + 4, 12), 28))
                self.interface.intrinsic.height = 3

            toga_textual.widgets.textinput.TextInput.rehint = _capped_textinput_rehint
            toga_textual.widgets.textinput.TextInput._twittui_rehint_patched = True

        # Expose Toga App commands in Textual's Ctrl+P Command Palette & bind F2 / Ctrl+O to Preferences
        if not getattr(toga_textual.app.TogaApp, "_twittui_commands_patched", False):
            orig_get_system_commands = toga_textual.app.TogaApp.get_system_commands
            orig_toga_app_init = toga_textual.app.TogaApp.__init__
            existing_bindings = list(getattr(toga_textual.app.TogaApp, "BINDINGS", []))
            toga_textual.app.TogaApp.BINDINGS = existing_bindings + [
                Binding("f2", "open_preferences", "Preferences", show=True, priority=True),
                Binding("ctrl+o", "open_preferences", "Preferences", show=False, priority=True),
            ]
            if hasattr(toga_textual.app.TogaApp, "_bindings") and hasattr(toga_textual.app.TogaApp._bindings, "bind"):
                toga_textual.app.TogaApp._bindings.bind("f2", "open_preferences", "Preferences", show=True, priority=True)
                toga_textual.app.TogaApp._bindings.bind("ctrl+o", "open_preferences", "Preferences", show=False, priority=True)

            def _patched_toga_app_init(self: Any, impl: Any) -> None:
                orig_toga_app_init(self, impl)
                try:
                    self._bindings.bind("f2", "open_preferences", "Preferences", show=True, priority=True)
                    self._bindings.bind("ctrl+o", "open_preferences", "Preferences", show=False, priority=True)
                except Exception:
                    pass

            toga_textual.app.TogaApp.__init__ = _patched_toga_app_init

            def _invoke_toga_command(toga_app: Any, cmd: Any) -> None:
                try:
                    action = getattr(cmd, "action", None)
                    if callable(action):
                        action()
                except Exception:
                    pass

            def _get_system_commands_with_toga(self: Any, screen: Screen) -> Any:
                try:
                    toga_app = getattr(self, "interface", None)
                    commands = getattr(toga_app, "commands", None)
                    if commands is not None:
                        for cmd in commands:
                            if not getattr(cmd, "enabled", True):
                                continue
                            text = getattr(cmd, "text", None)
                            action = getattr(cmd, "action", None)
                            if text and callable(action):
                                help_text = getattr(cmd, "tooltip", None) or f"Run {text}"
                                yield SystemCommand(
                                    str(text),
                                    str(help_text),
                                    lambda c=cmd, a=toga_app: _invoke_toga_command(a, c),
                                )
                except Exception:
                    pass
                yield from orig_get_system_commands(self, screen)

            def _action_open_preferences(self: Any) -> None:
                toga_app = getattr(self, "interface", None)
                if toga_app is None:
                    return
                prefs_win = getattr(toga_app, "_preferences_window", None)
                if prefs_win is not None and getattr(prefs_win, "visible", False):
                    if getattr(self, "screen", None) is getattr(getattr(prefs_win, "_impl", None), "native", None):
                        prefs_win.hide()
                        return
                if hasattr(toga_app, "show_preferences_window"):
                    toga_app.show_preferences_window()
                    return
                prefs_cmd = getattr(toga_app, "preferences_cmd", None)
                if prefs_cmd is not None and getattr(prefs_cmd, "enabled", True):
                    _invoke_toga_command(toga_app, prefs_cmd)

            toga_textual.app.TogaApp.get_system_commands = _get_system_commands_with_toga
            toga_textual.app.TogaApp.action_open_preferences = _action_open_preferences
            toga_textual.app.TogaApp._twittui_commands_patched = True

        # Silence noisy unimplemented menu/toolbar warnings in toga_textual
        if not getattr(toga_textual.app.App, "_twittui_patched", False):
            toga_textual.app.App.create_menus = lambda self: None

            orig_set_current_window = toga_textual.app.App.set_current_window

            def safe_set_current_window(self: Any, window: Any) -> None:
                if window is not None and hasattr(window, "_impl"):
                    window._impl._is_visible = True
                orig_set_current_window(self, window)

            toga_textual.app.App.set_current_window = safe_set_current_window

            orig_create = toga_textual.app.App.create

            def safe_create(self: Any) -> None:
                self.interface._startup()
                main_win = getattr(self.interface, "main_window", None)
                if main_win in (None, toga.App.BACKGROUND):
                    return
                win_impl = getattr(main_win, "_impl", None)
                if win_impl is not None:
                    win_impl._is_visible = True
                win_native = getattr(win_impl, "native", None)
                stack = getattr(self.native, "_screen_stack", None)
                # If startup already pushed main_window and modal screens (e.g. SplashScreen / RateLimitScreen),
                # preserve the modal stack instead of overwriting the top screen with a duplicate TogaMainWindow.
                if isinstance(stack, list) and win_native in stack and isinstance(stack[-1], ModalScreen):
                    previous_current = self._current_window
                    self._current_window = win_impl
                    self.native.title = win_impl.get_title()
                    if previous_current != win_impl:
                        if previous_current is not None:
                            previous_current.interface.on_lose_focus()
                            previous_current.interface.on_hide()
                        main_win.on_gain_focus()
                        main_win.on_show()
                else:
                    self.set_current_window(main_win)

            toga_textual.app.App.create = safe_create

            orig_main_loop = toga_textual.app.App.main_loop

            def safe_main_loop(self: Any) -> None:
                if getattr(self, "headless", False):
                    orig_main_loop(self)
                    return
                sink = io.StringIO()
                with redirect_stdout(sink):
                    orig_main_loop(self)

            toga_textual.app.App.main_loop = safe_main_loop
            toga_textual.app.App._twittui_patched = True

        if not getattr(toga_textual.window.Window, "_twittui_toolbar_patched", False):
            toga_textual.window.Window.create_toolbar = lambda self: None
            toga_textual.window.Window._twittui_toolbar_patched = True

        # Full secondary Window lifecycle, TitleBar, Escape binding, scrolling, and deferred content mounting
        if not getattr(toga_textual.window.Window, "_twittui_lifecycle_patched", False):
            TitleBarCls = toga_textual.window.TitleBar
            TogaWindowCls = toga_textual.window.TogaWindow
            TogaMainWindowCls = toga_textual.window.TogaMainWindow

            existing_win_css = getattr(TogaWindowCls, "DEFAULT_CSS", "") or ""
            if "overflow-x: auto" not in existing_win_css:
                TogaWindowCls.DEFAULT_CSS = existing_win_css + "\nTogaWindow { overflow-y: auto; overflow-x: auto; }\n"

            existing_win_bindings = list(getattr(TogaWindowCls, "BINDINGS", []))
            TogaWindowCls.BINDINGS = existing_win_bindings + [
                Binding("escape", "close_secondary_window", "Close", show=False, priority=True),
            ]
            if hasattr(TogaWindowCls, "_bindings") and hasattr(TogaWindowCls._bindings, "bind"):
                TogaWindowCls._bindings.bind("escape", "close_secondary_window", "Close", show=False, priority=True)

            def _focus_first_content_control(screen_obj: Any) -> None:
                try:
                    content = getattr(getattr(screen_obj.impl, "container", None), "content", None)
                    content_native = getattr(content, "native", None)
                    if content_native is None or not getattr(content_native, "is_attached", False):
                        return
                    current_focused = getattr(screen_obj, "focused", None)
                    if current_focused is not None and current_focused in content_native.walk_children():
                        return
                    for candidate in content_native.query("Input, Select, DataTable, Switch, Button"):
                        if getattr(candidate, "can_focus", False) and not getattr(candidate, "disabled", False):
                            candidate.focus()
                            break
                except Exception:
                    pass

            def _refresh_and_focus_window(screen_obj: Any, focus_content: bool = False) -> None:
                try:
                    if screen_obj.interface.content is not None:
                        screen_obj.interface.content.refresh()
                except Exception:
                    pass
                if focus_content:
                    _focus_first_content_control(screen_obj)

            def _toga_window_on_mount(self: Any) -> None:
                is_main = isinstance(self, TogaMainWindowCls)
                if is_main:
                    if hasattr(self, "titlebar") and not getattr(self.titlebar, "is_attached", False):
                        self.mount(self.titlebar)
                else:
                    try:
                        self._bindings.bind("escape", "close_secondary_window", "Close", show=False, priority=True)
                    except Exception:
                        pass
                    if not hasattr(self, "titlebar") or self.titlebar is None:
                        self.titlebar = TitleBarCls(self.impl.get_title())
                    else:
                        self.titlebar.text = self.impl.get_title()
                    if not getattr(self.titlebar, "is_attached", False):
                        self.mount(self.titlebar)

                content = getattr(self.impl.container, "content", None)
                if content is not None and not getattr(content.native, "is_attached", False):
                    content.install(parent=self.impl)

                self.call_after_refresh(lambda: _refresh_and_focus_window(self, focus_content=not is_main))

            def _toga_window_on_screen_resume(self: Any) -> None:
                is_main = isinstance(self, TogaMainWindowCls)
                self.call_after_refresh(lambda: _refresh_and_focus_window(self, focus_content=not is_main))

            def _action_close_secondary_window(self: Any) -> None:
                if isinstance(self, TogaMainWindowCls):
                    return
                self.impl.textual_close()

            def _check_window_action(self: Any, action: str, parameters: tuple[object, ...]) -> bool | None:
                if action == "close_secondary_window" and isinstance(self, TogaMainWindowCls):
                    return False
                return True

            TogaWindowCls.on_mount = _toga_window_on_mount
            TogaWindowCls.on_screen_resume = _toga_window_on_screen_resume
            TogaWindowCls.action_close_secondary_window = _action_close_secondary_window
            TogaWindowCls.check_action = _check_window_action
            # TogaMainWindow inherits TogaWindow; align its on_mount so both titlebar and deferred content mount cleanly
            TogaMainWindowCls.on_mount = _toga_window_on_mount

            orig_win_init = toga_textual.window.Window.__init__

            def _patched_win_init(self: Any, interface: Any, title: str, position: Any, size: Any) -> None:
                self._is_visible = False
                orig_win_init(self, interface, title, position, size)

            orig_win_set_title = toga_textual.window.Window.set_title

            def _patched_win_set_title(self: Any, title: str) -> None:
                orig_win_set_title(self, title)
                titlebar = getattr(getattr(self, "native", None), "titlebar", None)
                if titlebar is not None:
                    titlebar.text = title

            def _patched_win_set_content(self: Any, widget: Any) -> None:
                if self.container.content:
                    if getattr(self.container.content.native, "is_attached", False):
                        self.native.remove_children([self.container.content.native])
                self.container.content = widget
                if getattr(self.native, "is_attached", False):
                    widget.install(parent=self)

            def _patched_win_get_visible(self: Any) -> bool:
                app = getattr(self.interface, "app", None)
                app_native = getattr(getattr(app, "_impl", None), "native", None) if app is not None else None
                if app_native is not None and getattr(app_native, "_running", False):
                    stack = getattr(app_native, "_screen_stack", None)
                    if isinstance(stack, list):
                        return self.native in stack
                return bool(getattr(self, "_is_visible", False))

            def _patched_win_show(self: Any) -> None:
                self._is_visible = True
                titlebar = getattr(self.native, "titlebar", None)
                if titlebar is not None:
                    titlebar.text = self.get_title()
                app = getattr(self.interface, "app", None)
                app_impl = getattr(app, "_impl", None) if app is not None else None
                app_native = getattr(app_impl, "native", None) if app_impl is not None else None
                if app_native is not None and getattr(app_native, "_running", False):
                    try:
                        installed = getattr(app_native, "_installed_screens", {})
                        if self.native not in installed.values():
                            app_native.install_screen(self.native, name=self.interface.id)
                    except Exception:
                        pass
                    stack = getattr(app_native, "_screen_stack", None)
                    if not isinstance(stack, list) or self.native not in stack:
                        previous_current = getattr(app_impl, "_current_window", None)
                        app_impl._current_window = self
                        app_native.push_screen(self.native)
                        app_native.title = self.get_title()
                        if previous_current is not None and previous_current is not self:
                            try:
                                previous_current.interface.on_lose_focus()
                            except Exception:
                                pass
                        try:
                            self.interface.on_gain_focus()
                            self.interface.on_show()
                        except Exception:
                            pass

            def _patched_win_hide(self: Any) -> None:
                self._is_visible = False
                app = getattr(self.interface, "app", None)
                app_impl = getattr(app, "_impl", None) if app is not None else None
                app_native = getattr(app_impl, "native", None) if app_impl is not None else None
                if app_native is not None and getattr(app_native, "_running", False):
                    stack = getattr(app_native, "_screen_stack", None)
                    if isinstance(stack, list) and self.native in stack and len(stack) > 1:
                        try:
                            while len(stack) > 1 and stack[-1] is not self.native:
                                app_native.pop_screen()
                            if len(stack) > 1 and stack[-1] is self.native:
                                app_native.pop_screen()
                        except Exception:
                            pass
                    main_win = getattr(app, "main_window", None)
                    main_impl = getattr(main_win, "_impl", None) if main_win is not None else None
                    if app_impl is not None and getattr(app_impl, "_current_window", None) is self:
                        app_impl._current_window = main_impl
                        if main_impl is not None:
                            app_native.title = main_impl.get_title()
                    try:
                        self.interface.on_lose_focus()
                        self.interface.on_hide()
                    except Exception:
                        pass
                    if main_win is not None:
                        try:
                            main_win.on_gain_focus()
                        except Exception:
                            pass

            def _patched_win_close(self: Any) -> None:
                self._is_visible = False
                app = getattr(self.interface, "app", None)
                app_impl = getattr(app, "_impl", None) if app is not None else None
                app_native = getattr(app_impl, "native", None) if app_impl is not None else None
                if app_native is not None and getattr(app_native, "_running", False):
                    stack = getattr(app_native, "_screen_stack", None)
                    if isinstance(stack, list) and self.native in stack and len(stack) > 1:
                        _patched_win_hide(self)
                        return
                try:
                    if getattr(self.native, "is_active", False):
                        self.native.dismiss(None)
                except Exception:
                    pass

            def _patched_textual_close(self: Any) -> None:
                app = getattr(self.interface, "app", None)
                if app is not None and self.interface is getattr(app, "main_window", None):
                    self.interface.on_close()
                    return
                was_visible = _patched_win_get_visible(self)
                raw_handler = getattr(getattr(self.interface, "on_close", None), "_raw", None)
                if callable(raw_handler):
                    should_close = raw_handler(self.interface)
                    # If the handler already hid the window (e.g. Preferences hide-instead-of-destroy),
                    # do not invoke Toga's destructive close().
                    if was_visible and not _patched_win_get_visible(self):
                        return
                    if should_close:
                        self.interface.close()
                else:
                    self.interface.close()

            toga_textual.window.Window.__init__ = _patched_win_init
            toga_textual.window.Window.set_title = _patched_win_set_title
            toga_textual.window.Window.set_content = _patched_win_set_content
            toga_textual.window.Window.get_visible = _patched_win_get_visible
            toga_textual.window.Window.show = _patched_win_show
            toga_textual.window.Window.hide = _patched_win_hide
            toga_textual.window.Window.close = _patched_win_close
            toga_textual.window.Window.textual_close = _patched_textual_close
            toga_textual.window.Window._twittui_lifecycle_patched = True

        # Safely wrap Window.set_app to handle headless/test execution
        if not getattr(toga_textual.window.Window, "_twittui_set_app_patched", False):
            orig_set_app = toga_textual.window.Window.set_app

            def safe_set_app(self: Any, app: Any) -> None:
                try:
                    if getattr(app.native, "_running", False):
                        app.native.install_screen(self.native, name=self.interface.id)
                    else:
                        orig_set_app(self, app)
                except Exception:
                    try:
                        app.native.install_screen(self.native, name=self.interface.id)
                    except Exception:
                        pass

            toga_textual.window.Window.set_app = safe_set_app
            toga_textual.window.Window._twittui_set_app_patched = True

        # Safely wrap Widget._mount to handle unmounted container parents during tests
        if not getattr(toga_textual.widgets.base.Widget, "_twittui_mount_patched", False):
            orig_mount = toga_textual.widgets.base.Widget._mount

            def safe_mount(self: Any, parent: Any, before: Any = None) -> None:
                try:
                    orig_mount(self, parent, before)
                except Exception:
                    for child in getattr(self.interface, 'children', []):
                        try:
                            child._impl.install(parent=self)
                        except Exception:
                            pass

            toga_textual.widgets.base.Widget._mount = safe_mount
            toga_textual.widgets.base.Widget._twittui_mount_patched = True

        # Inject implementations into toga_textual module
        for name, impl_cls in TEXTUAL_WIDGET_IMPLEMENTATIONS.items():
            setattr(toga_textual, name, impl_cls)

        setattr(toga_textual, 'dialogs', DialogsFactory)

        # Patch Factory.__getattr__ so any Factory instance resolves these widgets
        if not getattr(toga.platform.Factory, "_twittui_getattr_patched", False):
            orig_getattr = toga.platform.Factory.__getattr__

            def custom_getattr(self: Any, name: str) -> Any:
                try:
                    backend = self.backend
                except Exception:
                    backend = os.environ.get('TOGA_BACKEND', '')
                if backend in ('toga_textual', 'textual'):
                    if name in TEXTUAL_WIDGET_IMPLEMENTATIONS:
                        val = TEXTUAL_WIDGET_IMPLEMENTATIONS[name]
                        setattr(self, name, val)
                        return val
                    if name == 'dialogs':
                        setattr(self, 'dialogs', DialogsFactory)
                        return DialogsFactory
                    if hasattr(DialogsFactory, name):
                        val = getattr(DialogsFactory, name)
                        setattr(self, name, val)
                        return val
                return orig_getattr(self, name)

            toga.platform.Factory.__getattr__ = custom_getattr
            toga.platform.Factory._twittui_getattr_patched = True

        # Also set directly on cached factory instances if the active backend is Textual
        try:
            f = toga.platform.get_factory()
            backend = getattr(f, 'backend', '') or os.environ.get('TOGA_BACKEND', '')
            if backend in ('toga_textual', 'textual'):
                for name, impl_cls in TEXTUAL_WIDGET_IMPLEMENTATIONS.items():
                    setattr(f, name, impl_cls)
                setattr(f, 'dialogs', DialogsFactory)
                for dialog_name in ['InfoDialog', 'ErrorDialog', 'QuestionDialog', 'ConfirmDialog', 'SelectFolderDialog', 'OpenFileDialog', 'SaveFileDialog', 'ChoiceDialog', 'SelectResolutionDialog']:
                    setattr(f, dialog_name, getattr(DialogsFactory, dialog_name))
        except Exception:
            pass
    except Exception as e:
        pass
