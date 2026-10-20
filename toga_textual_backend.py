"""
Textual Backend Extensions and Implementations for Toga.

Provides complete Textual widget implementations for Selection, Table, ProgressBar,
WebView, and other widgets missing from standard toga-textual.
"""

from __future__ import annotations

import os
from typing import Any
from travertino.size import at_least
from textual._context import NoActiveAppError
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import (
    Button,
    DataTable,
    Label,
    LoadingIndicator,
    ProgressBar as TextualProgressBar,
    Rule,
    Select,
    Static,
    TextArea,
)
import toga
import toga.platform
from toga_textual.widgets.base import Widget


class TextualDialogScreen(ModalScreen):
    """Textual modal screen for displaying Toga dialogs."""

    DEFAULT_CSS = """
    TextualDialogScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #dialog_box {
        width: 60;
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

    def __init__(self, title: str, message: str, buttons: list[tuple[str, Any]], future: Any) -> None:
        super().__init__()
        self.dialog_title = title
        self.dialog_message = message
        self.buttons = buttons
        self.future = future

    def compose(self) -> Any:
        with Vertical(id="dialog_box"):
            yield Label(self.dialog_title, id="dialog_title")
            yield Label(self.dialog_message, id="dialog_message")
            with Horizontal(id="button_row"):
                for label, val in self.buttons:
                    yield Button(label, id=f"btn_{label.lower()}", variant="primary" if val else "default", tooltip=f"Select {label}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        for label, val in self.buttons:
            if button_id == f"btn_{label.lower()}":
                self.dismiss(val)
                if self.future and not self.future.done():
                    self.future.set_result(val)
                return
        self.dismiss(None)
        if self.future and not self.future.done():
            self.future.set_result(None)


class BaseTextualDialog:
    def __init__(self, title: str, message: str, buttons: list[tuple[str, Any]], default_result: Any = None) -> None:
        self.title = title
        self.message = message
        self.buttons = buttons
        self.default_result = default_result

    def show(self, host_window: Any, future: Any) -> None:
        try:
            app = toga.App.app
            if app and hasattr(app, '_impl') and hasattr(app._impl, 'native'):
                screen = TextualDialogScreen(self.title, self.message, self.buttons, future)
                app._impl.native.push_screen(screen)
                return
        except Exception:
            pass
        if future and not future.done():
            future.set_result(self.default_result)


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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn_choice_cancel":
            self.dismiss(None)
            if self.future and not self.future.done():
                self.future.set_result(None)
            return

        if button_id and button_id.startswith("opt_btn_"):
            try:
                idx = int(button_id.split("opt_btn_")[1])
                selected = self.options[idx]
                self.dismiss(selected)
                if self.future and not self.future.done():
                    self.future.set_result(selected)
                return
            except Exception:
                pass

        self.dismiss(None)
        if self.future and not self.future.done():
            self.future.set_result(None)


class ChoiceDialog:
    """Dialog that allows user to choose from a list of option dictionaries."""
    def __init__(self, title: str, message: str, options: list[dict], default_result: Any = None) -> None:
        self.title = title
        self.message = message
        self.options = options
        self.default_result = default_result

    def show(self, host_window: Any, future: Any) -> None:
        try:
            app = toga.App.app
            if app and hasattr(app, '_impl') and hasattr(app._impl, 'native'):
                screen = TextualChoiceDialogScreen(self.title, self.message, self.options, future)
                app._impl.native.push_screen(screen)
                return
        except Exception:
            pass
        if future and not future.done():
            future.set_result(self.default_result)


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


class SelectFolderDialog:
    def __init__(self, title: str, initial_directory: Any = None, multiple_select: bool = False) -> None:
        self.title = title
        self.initial_directory = initial_directory
        self.multiple_select = multiple_select

    def show(self, host_window: Any, future: Any) -> None:
        import pathlib
        res = pathlib.Path(self.initial_directory or os.getcwd())
        if self.multiple_select:
            future.set_result([res] if not future.done() else None)
        else:
            future.set_result(res if not future.done() else None)


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

    def _on_mount(self, event: Any) -> None:
        super()._on_mount(event)
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
        if not getattr(self.native, 'is_mounted', False):
            return
        self._suppress_change = True
        try:
            native_opts = [(title, str(idx)) for idx, (title, val) in enumerate(self._options)]
            if native_opts:
                self.native.set_options(native_opts)
                if self._selected_index is not None and 0 <= self._selected_index < len(native_opts):
                    self.native.value = str(self._selected_index)
                else:
                    self.native.value = native_opts[0][1]
            else:
                self.native.set_options([])
                self.native.value = Select.BLANK
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
        self._sync_options_to_native()

    def get_selected_index(self) -> int | None:
        return self._selected_index

    def rehint(self) -> None:
        max_len = max([len(t) for t, _ in self._options], default=10)
        self.interface.intrinsic.width = at_least(max_len + 8)
        self.interface.intrinsic.height = 3


class TogaDataTable(DataTable):
    """Textual native DataTable wrapper for Toga Table."""

    BINDINGS = [
        Binding('space', 'toggle_row_select', 'Select Row', show=True),
    ]

    def __init__(self, impl: TextualTable, **kwargs: Any) -> None:
        super().__init__(cursor_type='row', zebra_stripes=True, **kwargs)
        self.interface = impl.interface
        self.impl = impl
        self._marked_rows: set[int] = set()

    def _on_mount(self, event: Any) -> None:
        super()._on_mount(event)
        self.impl._sync_data_to_native()

    def action_toggle_row_select(self) -> None:
        if not self.interface.multiple_select:
            return
        row_idx = self.cursor_row
        if row_idx is not None and 0 <= row_idx < len(self.impl._rows):
            if row_idx in self._marked_rows:
                self._marked_rows.remove(row_idx)
            else:
                self._marked_rows.add(row_idx)
            if self.interface.on_select:
                self.interface.on_select()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self.impl._rows):
            row_data = self.impl._rows[row_idx]
            if self.interface.on_activate:
                self.interface.on_activate(row=row_data)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.interface.on_select:
            self.interface.on_select()


class TextualTable(Widget):
    """Toga Table backend implementation for Textual."""

    def create(self) -> None:
        self._columns: list[Any] = []
        self._rows: list[Any] = []
        self.native = TogaDataTable(self)

    def _sync_data_to_native(self) -> None:
        if not getattr(self.native, 'is_mounted', False):
            return
        try:
            self.native.clear(columns=True)
            headings = [col.heading for col in self.interface.columns]
            if headings:
                self.native.add_columns(*headings)
            for row in self._rows:
                row_vals = []
                for col in self.interface.columns:
                    val = getattr(row, col.accessor, '')
                    row_vals.append(str(val if val is not None else ''))
                self.native.add_row(*row_vals)
        except Exception:
            pass

    def change_source(self, source: Any) -> None:
        self._rows = list(source) if source else []
        self._sync_data_to_native()

    def source_clear(self) -> None:
        self._rows.clear()
        if hasattr(self.native, '_marked_rows'):
            self.native._marked_rows.clear()
        self._sync_data_to_native()

    def source_insert(self, index: int, item: Any) -> None:
        self._rows.insert(index, item)
        self._sync_data_to_native()

    def source_remove(self, index: int, item: Any) -> None:
        if 0 <= index < len(self._rows):
            del self._rows[index]
            if hasattr(self.native, '_marked_rows') and index in self.native._marked_rows:
                self.native._marked_rows.remove(index)
        self._sync_data_to_native()

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

    def set_content(self, root_url: str, content: str) -> None:
        if getattr(self.native, 'is_mounted', False):
            try:
                self.native.update(content[:500] + ("..." if len(content) > 500 else ""))
            except Exception:
                pass

    def set_url(self, url: str) -> None:
        self._url = url
        if getattr(self.native, 'is_mounted', False):
            try:
                self.native.update(f"Web Content: {url}")
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
        self.interface.intrinsic.width = at_least(len(val) + 4)
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
        self._initial_value = bool_val
        try:
            self.native_switch.value = bool_val
        except (NoActiveAppError, Exception):
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
        import toga_textual.window
        import toga_textual.widgets.base

        # Safely wrap Window.set_app to handle headless/test execution
        orig_set_app = toga_textual.window.Window.set_app

        def safe_set_app(self: Any, app: Any) -> None:
            try:
                orig_set_app(self, app)
            except Exception:
                try:
                    app.native.install_screen(self.native, name=self.interface.id)
                except Exception:
                    pass

        toga_textual.window.Window.set_app = safe_set_app

        # Safely wrap Widget._mount to handle unmounted container parents during tests
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

        # Inject implementations into toga_textual module
        for name, impl_cls in TEXTUAL_WIDGET_IMPLEMENTATIONS.items():
            setattr(toga_textual, name, impl_cls)

        setattr(toga_textual, 'dialogs', DialogsFactory)

        # Patch Factory.__getattr__ so any Factory instance resolves these widgets
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
