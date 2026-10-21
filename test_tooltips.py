"""Unit tests verifying tooltips across all UI elements in TwitTUI."""

import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

import toga
from textual.app import App
from twittui_form import (
    TwitTUIForm,
    apply_tooltip_to_impl,
    get_widget_tooltip,
    set_widget_tooltip,
    patch_toga_tooltips,
)
from toga_textual_backend import (
    TextualDialogScreen,
    TextualChoiceDialogScreen,
    patch_toga_textual,
)


class TestWidgetTooltipInfrastructure(unittest.TestCase):
    """Test core tooltip attachment, getter/setter, and native propagation."""

    def setUp(self) -> None:
        patch_toga_textual()
        patch_toga_tooltips()

    def test_button_constructor_and_property(self) -> None:
        """Verify Button accepts tooltip keyword in constructor and exposes property."""
        btn = toga.Button("Test", tooltip="Click to run test")
        self.assertEqual(btn.tooltip, "Click to run test")
        self.assertEqual(get_widget_tooltip(btn), "Click to run test")
        if hasattr(btn, '_impl') and btn._impl and hasattr(btn._impl, 'native') and btn._impl.native:
            self.assertEqual(getattr(btn._impl.native, 'tooltip', None), "Click to run test")

        btn.tooltip = "Updated description"
        self.assertEqual(btn.tooltip, "Updated description")
        if hasattr(btn, '_impl') and btn._impl and hasattr(btn._impl, 'native') and btn._impl.native:
            self.assertEqual(getattr(btn._impl.native, 'tooltip', None), "Updated description")

        btn.tooltip = None
        self.assertIsNone(btn.tooltip)
        if hasattr(btn, '_impl') and btn._impl and hasattr(btn._impl, 'native') and btn._impl.native:
            self.assertIsNone(getattr(btn._impl.native, 'tooltip', None))

    def test_all_widget_types_tooltip_support(self) -> None:
        """Verify tooltip keyword and property on all primary Toga widget classes."""
        label = toga.Label("Label", tooltip="Label tooltip")
        self.assertEqual(label.tooltip, "Label tooltip")

        text_input = toga.TextInput(tooltip="Input tooltip")
        self.assertEqual(text_input.tooltip, "Input tooltip")

        pwd_input = toga.PasswordInput(tooltip="Password tooltip")
        self.assertEqual(pwd_input.tooltip, "Password tooltip")

        selection = toga.Selection(items=["Option 1", "Option 2"], tooltip="Selection tooltip")
        self.assertEqual(selection.tooltip, "Selection tooltip")

        switch = toga.Switch("Toggle", tooltip="Switch tooltip")
        self.assertEqual(switch.tooltip, "Switch tooltip")
        if hasattr(switch._impl, 'native_switch'):
            self.assertEqual(getattr(switch._impl.native_switch, 'tooltip', None), "Switch tooltip")
        if hasattr(switch._impl, 'native_label'):
            self.assertEqual(getattr(switch._impl.native_label, 'tooltip', None), "Switch tooltip")

        table = toga.Table(columns=["A", "B"], tooltip="Table tooltip")
        self.assertEqual(table.tooltip, "Table tooltip")

        prog = toga.ProgressBar(tooltip="Progress tooltip")
        self.assertEqual(prog.tooltip, "Progress tooltip")

    def test_apply_tooltip_to_impl_mocked_gtk(self) -> None:
        """Verify apply_tooltip_to_impl correctly invokes set_tooltip_text on GTK targets."""
        mock_native = MagicMock()
        mock_sub = MagicMock()
        mock_impl = MagicMock()
        mock_impl.native = mock_native
        mock_impl.native_table = mock_sub

        apply_tooltip_to_impl(mock_impl, "GTK Tooltip Text")
        mock_native.set_tooltip_text.assert_called_once_with("GTK Tooltip Text")
        mock_sub.set_tooltip_text.assert_called_once_with("GTK Tooltip Text")

        apply_tooltip_to_impl(mock_impl, None)
        mock_native.set_tooltip_text.assert_called_with(None)
        mock_sub.set_tooltip_text.assert_called_with(None)


class TestMainFormUITooltips(unittest.TestCase):
    """Verify that all UI controls on the main TwitTUIForm window have descriptive tooltips."""

    def setUp(self) -> None:
        os.environ['TWITAUDIOONLY'] = '0'
        os.environ['TWITCLUBSHOWFOLDERS'] = '0'
        self.form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.tooltiptest")
        with patch.object(self.form, 'fetch_shows', return_value=['This Week in Tech']):
            with patch.object(self.form, 'fetch_episodes', return_value=[]):
                self.form.startup()

    def test_all_startup_elements_have_tooltips(self) -> None:
        """Ensure every single UI component instantiated in startup has a non-empty tooltip."""
        expected_widgets = {
            'show_label': self.form.show_label,
            'show_combo': self.form.show_combo,
            'fetch_button': self.form.fetch_button,
            'next_button': self.form.next_button,
            'search_label': self.form.search_label,
            'search_input': self.form.search_input,
            'search_button': self.form.search_button,
            'clear_button': self.form.clear_button,
            'sort_label': self.form.sort_label,
            'date_radio': self.form.date_radio,
            'episode_radio': self.form.episode_radio,
            'title_radio': self.form.title_radio,
            'sort_order_button': self.form.sort_order_button,
            'audio_only_checkbox': self.form.audio_only_checkbox,
            'episodes_label': self.form.episodes_label,
            'episodes_list': self.form.episodes_list,
            'download_button': self.form.download_button,
            'stream_button': self.form.stream_button,
            'cancel_button': self.form.cancel_button,
            'close_button': self.form.close_button,
            'app_id_label': self.form.app_id_label,
            'app_id_input': self.form.app_id_input,
            'app_key_label': self.form.app_key_label,
            'app_key_input': self.form.app_key_input,
            'test_api_button': self.form.test_api_button,
            'url_label': self.form.url_label,
            'url_prefix': self.form.url_prefix,
            'url_input': self.form.url_input,
            'show_url_button': self.form.show_url_button,
            'dest_label': self.form.dest_label,
            'dest_input': self.form.dest_input,
            'dest_button': self.form.dest_button,
            'dest_open_button': self.form.dest_open_button,
            'show_folders_checkbox': self.form.show_folders_checkbox,
            'block_label': self.form.block_label,
            'block_input': self.form.block_input,
            'streamer_label': self.form.streamer_label,
            'streamer_input': self.form.streamer_input,
            'progress_bar': self.form.progress_bar,
            'readme_cmd': self.form.readme_cmd,
            'apib_cmd': self.form.apib_cmd,
            'api_key_cmd': self.form.api_key_cmd,
        }

        for name, widget in expected_widgets.items():
            self.assertIsNotNone(widget, f"Widget '{name}' was not found or initialized on form.")
            tooltip = getattr(widget, 'tooltip', None) or self.form.get_tooltip(widget)
            self.assertIsNotNone(tooltip, f"Widget '{name}' has no tooltip.")
            self.assertIsInstance(tooltip, str, f"Widget '{name}' tooltip is not a string.")
            self.assertTrue(len(tooltip.strip()) > 5, f"Widget '{name}' has too short or empty tooltip: '{tooltip}'")

    def test_native_widgets_receive_tooltips(self) -> None:
        """Verify native Textual widgets match Toga tooltips."""
        widgets_to_check = [
            self.form.show_combo,
            self.form.fetch_button,
            self.form.next_button,
            self.form.search_input,
            self.form.search_button,
            self.form.clear_button,
            self.form.date_radio,
            self.form.download_button,
            self.form.stream_button,
            self.form.app_id_input,
            self.form.app_key_input,
            self.form.dest_input,
            self.form.dest_button,
            self.form.progress_bar,
        ]
        for w in widgets_to_check:
            native = getattr(w._impl, 'native', None)
            if native and hasattr(native, 'tooltip'):
                self.assertEqual(native.tooltip, w.tooltip, f"Native widget tooltip mismatch for {w}")

    def test_dynamic_sort_order_tooltip(self) -> None:
        """Verify sort order button tooltip updates on toggle."""
        # Initial is descending
        self.assertIn("descending", self.form.sort_order_button.tooltip.lower())

        with patch.object(self.form, 'load_episodes_for_selected_show'):
            self.form.on_sort_order_toggle()
            self.assertIn("ascending", self.form.sort_order_button.tooltip.lower())

            self.form.on_sort_order_toggle()
            self.assertIn("descending", self.form.sort_order_button.tooltip.lower())

    def test_dynamic_audio_only_tooltip(self) -> None:
        """Verify Audio Only toggle updates tooltip state."""
        self.assertIn("switch to audio-only", self.form.audio_only_checkbox.tooltip.lower())

        with patch.object(self.form, 'update_episodes_display'):
            self.form.on_audio_only_toggle()
            self.assertIn("currently showing audio-only", self.form.audio_only_checkbox.tooltip.lower())

            self.form.on_audio_only_toggle()
            self.assertIn("switch to audio-only", self.form.audio_only_checkbox.tooltip.lower())

    def test_dynamic_sort_radio_tooltips(self) -> None:
        """Verify sort criteria buttons reflect active state in tooltip."""
        with patch.object(self.form, 'load_episodes_for_selected_show'):
            self.form.on_sort_button_press(self.form.episode_radio)
            self.assertIn("(active)", self.form.episode_radio.tooltip)
            self.assertNotIn("(active)", self.form.date_radio.tooltip)

            self.form.on_sort_button_press(self.form.title_radio)
            self.assertIn("(active)", self.form.title_radio.tooltip)
            self.assertNotIn("(active)", self.form.episode_radio.tooltip)

            self.form.on_sort_button_press(self.form.date_radio)
            self.assertIn("(active)", self.form.date_radio.tooltip)
            self.assertNotIn("(active)", self.form.title_radio.tooltip)

    def test_form_set_and_get_tooltip_helpers(self) -> None:
        """Verify set_tooltip and get_tooltip form helper methods."""
        dummy_btn = toga.Button("Dummy")
        self.form.set_tooltip(dummy_btn, "Custom Helper Tooltip")
        self.assertEqual(self.form.get_tooltip(dummy_btn), "Custom Helper Tooltip")
        self.assertEqual(dummy_btn.tooltip, "Custom Helper Tooltip")


class TestModalAndDialogTooltips(unittest.TestCase):
    """Verify tooltips on modal dialogs and viewers."""

    def test_textual_dialog_screen_buttons_have_tooltips(self) -> None:
        """Verify buttons in TextualDialogScreen have tooltips."""
        async def _run():
            app = App()
            async with app.run_test() as pilot:
                screen = TextualDialogScreen("Confirm Action", "Do you want to proceed?", [("Yes", True), ("No", False)], None)
                await pilot.app.push_screen(screen)
                buttons = list(screen.query("Button"))
                self.assertEqual(len(buttons), 2)
                for btn in buttons:
                    self.assertTrue(hasattr(btn, 'tooltip'))
                    self.assertIsNotNone(btn.tooltip)
                    self.assertIn("Select", btn.tooltip)

        asyncio.run(_run())

    def test_textual_choice_dialog_screen_buttons_have_tooltips(self) -> None:
        """Verify option and cancel buttons in TextualChoiceDialogScreen have tooltips."""
        async def _run():
            app = App()
            async with app.run_test() as pilot:
                options = [
                    {'label': '1080p HD', 'url': 'http://example.com/1080.mp4'},
                    {'label': '540p Large', 'url': 'http://example.com/540.mp4'},
                ]
                screen = TextualChoiceDialogScreen("Resolution", "Pick quality", options, None)
                await pilot.app.push_screen(screen)
                buttons = list(screen.query("Button"))
                self.assertEqual(len(buttons), 3)

                opt_buttons = [b for b in buttons if b.id != "btn_choice_cancel"]
                cancel_button = next(b for b in buttons if b.id == "btn_choice_cancel")

                for idx, btn in enumerate(opt_buttons):
                    self.assertTrue(hasattr(btn, 'tooltip'))
                    self.assertIn("resolution", btn.tooltip.lower())
                    self.assertIn(options[idx]['label'], btn.tooltip)

                self.assertTrue(hasattr(cancel_button, 'tooltip'))
                self.assertIn("cancel", cancel_button.tooltip.lower())

        asyncio.run(_run())


if __name__ == '__main__':
    unittest.main()
