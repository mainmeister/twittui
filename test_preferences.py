"""Tests for the Preferences window and its main-window integration."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

import toga
from toga_textual_backend import patch_toga_textual
from twittui_form import TwitTUIForm


class TestPreferences(unittest.TestCase):
    def setUp(self) -> None:
        patch_toga_textual()
        os.environ['TWITAUDIOONLY'] = '0'
        os.environ['TWITCLUBSHOWFOLDERS'] = '0'
        self.form = TwitTUIForm(formal_name='TwitTUI', app_id='org.twit.preferences-test')
        with patch.object(self.form, '_refresh_catalog'):
            self.form.startup()

    def tearDown(self) -> None:
        loop = getattr(self.form, 'loop', None)
        if loop and not loop.is_running() and not loop.is_closed():
            loop.close()

    def test_settings_are_in_preferences_not_main_window(self) -> None:
        main_children = self.form.main_window.content.children

        self.assertNotIn(self.form.settings_box, main_children)
        self.assertIn(self.form.progress_bar, main_children)

    def test_preferences_command_is_in_app_menu(self) -> None:
        self.assertIsNotNone(self.form.preferences_cmd)
        self.assertEqual(self.form.preferences_cmd.text, 'Preferences')
        self.assertEqual(self.form.preferences_cmd.group, toga.Group.APP)

    def test_preferences_window_is_created_once_and_uses_settings_box(self) -> None:
        self.form.show_preferences_window()
        preferences_window = self.form._preferences_window

        self.assertIsNotNone(preferences_window)
        self.assertEqual(preferences_window.title, 'Preferences')
        self.assertIs(preferences_window.content, self.form.settings_box)

        self.form.show_preferences_window()

        self.assertIs(self.form._preferences_window, preferences_window)

    def test_preferences_window_close_hides_instead_of_destroying(self) -> None:
        self.form.show_preferences_window()
        preferences_window = self.form._preferences_window

        self.assertTrue(self.form.on_preferences_window_close(preferences_window, preferences_window))
        self.assertIs(self.form._preferences_window, preferences_window)

        self.form.show_preferences_window()

        self.assertIs(self.form._preferences_window, preferences_window)

    def test_preferences_close_button_has_tooltip(self) -> None:
        self.assertTrue(self.form.preferences_close_button.tooltip)

    def test_search_options_switches_in_preferences(self) -> None:
        self.assertIsNotNone(self.form.fuzzy_search_checkbox)
        self.assertIsNotNone(self.form.phonetic_search_checkbox)
        self.assertTrue(self.form.fuzzy_search_checkbox.tooltip)
        self.assertTrue(self.form.phonetic_search_checkbox.tooltip)


if __name__ == '__main__':
    unittest.main()
