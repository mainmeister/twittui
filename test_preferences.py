"""Tests for the Preferences window and its main-window and TUI integration."""

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

import toga
from toga_textual_backend import (
    TextualDialogScreen,
    TextualSelectFolderScreen,
    patch_toga_textual,
)
from twittui_form import TwitTUIForm, patch_toga_tooltips


class TestPreferences(unittest.TestCase):
    def setUp(self) -> None:
        patch_toga_textual()
        patch_toga_tooltips()
        os.environ['TWITAUDIOONLY'] = '0'
        os.environ['TWITCLUBSHOWFOLDERS'] = '0'
        self.form = TwitTUIForm(
            formal_name='TwitTUI',
            app_id='org.twit.preferences-test',
            cache_db_path=':memory:',
        )
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

    def test_tui_main_window_has_preferences_button_with_tooltip(self) -> None:
        self.assertIsNotNone(self.form.preferences_button)
        self.assertIn(self.form.preferences_button, self.form.button_box.children)
        self.assertTrue(self.form.preferences_button.tooltip)

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
        self.assertTrue(preferences_window.visible)

        self.form.show_preferences_window()

        self.assertIs(self.form._preferences_window, preferences_window)

    def test_preferences_window_close_hides_instead_of_destroying(self) -> None:
        self.form.show_preferences_window()
        preferences_window = self.form._preferences_window

        self.assertTrue(self.form.on_preferences_window_close(preferences_window, preferences_window))
        self.assertFalse(preferences_window.visible)
        self.assertFalse(preferences_window.closed)
        self.assertIs(self.form._preferences_window, preferences_window)

        self.form.show_preferences_window()

        self.assertTrue(preferences_window.visible)
        self.assertIs(self.form._preferences_window, preferences_window)

    def test_preferences_close_button_has_tooltip(self) -> None:
        self.assertTrue(self.form.preferences_close_button.tooltip)

    def test_search_options_switches_in_preferences(self) -> None:
        self.assertIsNotNone(self.form.fuzzy_search_checkbox)
        self.assertIsNotNone(self.form.phonetic_search_checkbox)
        self.assertTrue(self.form.fuzzy_search_checkbox.tooltip)
        self.assertTrue(self.form.phonetic_search_checkbox.tooltip)


class TestTUIPreferencesLive(unittest.TestCase):
    """End-to-end Textual pilot tests verifying Preferences navigation, editing, dialogs, and persistence in --tui."""

    def setUp(self) -> None:
        patch_toga_textual()
        patch_toga_tooltips()
        self._env_backup = dict(os.environ)
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.env_file = os.path.join(self._tmp_dir.name, '.env')
        os.environ['SNAP_USER_DATA'] = self._tmp_dir.name
        os.environ['TWITAUDIOONLY'] = '0'
        os.environ['TWITCLUBSHOWFOLDERS'] = '0'
        os.environ['TWITFUZZYSEARCH'] = '1'
        os.environ['TWITPHONETICSEARCH'] = '1'

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)
        self._tmp_dir.cleanup()

    def _make_form(self, app_id: str) -> TwitTUIForm:
        form = TwitTUIForm(
            formal_name='TWIT.tv TUI',
            app_id=app_id,
            cache_db_path=':memory:',
        )
        self.addCleanup(
            lambda f=form: (
                getattr(f, 'loop', None)
                and not f.loop.is_running()
                and not f.loop.is_closed()
                and f.loop.close()
            )
        )
        return form

    def test_tui_open_and_close_preferences_via_button_shortcuts_escape_and_titlebar(self) -> None:
        form = self._make_form('org.twit.tui-prefs-nav')

        async def run_scenario() -> None:
            with patch.object(form, '_refresh_catalog', lambda: None), \
                 patch.object(form, 'show_splash_screen', lambda *a, **kw: None):
                async with form._impl.native.run_test(size=(100, 24)) as pilot:
                    await pilot.pause()
                    app = pilot.app
                    main_screen = form.main_window._impl.native
                    self.assertIs(app.screen, main_screen)

                    # 1. Open via Preferences button press on main window
                    form.preferences_button._impl.native.press()
                    await pilot.pause()

                    prefs_win = form._preferences_window
                    self.assertIsNotNone(prefs_win)
                    prefs_screen = prefs_win._impl.native
                    self.assertIs(app.screen, prefs_screen)
                    self.assertTrue(prefs_win.visible)

                    # Verify all Preferences controls are mounted in the live Textual screen DOM
                    for widget in (
                        form.app_id_input,
                        form.app_key_input,
                        form.test_api_button,
                        form.url_input,
                        form.show_url_button,
                        form.dest_input,
                        form.dest_button,
                        form.dest_open_button,
                        form.show_folders_checkbox,
                        form.block_input,
                        form.rate_limit_input,
                        form.streamer_input,
                        form.fuzzy_search_checkbox,
                        form.phonetic_search_checkbox,
                        form.clear_cache_button,
                        form.preferences_close_button,
                    ):
                        self.assertTrue(
                            widget._impl.native.is_attached,
                            f"Preferences widget {widget} was not mounted onto Preferences screen",
                        )

                    # 2. Close via Escape key -> hides without destroying
                    await pilot.press('escape')
                    await pilot.pause()
                    self.assertIs(app.screen, main_screen)
                    self.assertFalse(prefs_win.visible)
                    self.assertFalse(prefs_win.closed)

                    # 3. Reopen via F2 keybinding and toggle closed with F2
                    await pilot.press('f2')
                    await pilot.pause()
                    self.assertIs(app.screen, prefs_screen)
                    self.assertTrue(prefs_win.visible)

                    await pilot.press('f2')
                    await pilot.pause()
                    self.assertIs(app.screen, main_screen)
                    self.assertFalse(prefs_win.visible)

                    # 4. Reopen via Ctrl+O and close via Preferences Close button
                    await pilot.press('ctrl+o')
                    await pilot.pause()
                    self.assertIs(app.screen, prefs_screen)

                    form.preferences_close_button._impl.native.press()
                    await pilot.pause()
                    self.assertIs(app.screen, main_screen)
                    self.assertFalse(prefs_win.visible)
                    self.assertIs(form._preferences_window, prefs_win)

                    # 5. Reopen and close via TitleBar WindowCloseButton ('✕') without destroying window
                    form.show_preferences_window()
                    await pilot.pause()
                    self.assertIs(app.screen, prefs_screen)
                    close_btn = prefs_screen.query_one('WindowCloseButton')
                    close_btn.press()
                    await pilot.pause()
                    self.assertIs(app.screen, main_screen)
                    self.assertFalse(prefs_win.closed)

        asyncio.run(run_scenario())

    def test_tui_command_palette_exposes_and_runs_preferences(self) -> None:
        form = self._make_form('org.twit.tui-prefs-palette')

        async def run_scenario() -> None:
            with patch.object(form, '_refresh_catalog', lambda: None), \
                 patch.object(form, 'show_splash_screen', lambda *a, **kw: None):
                async with form._impl.native.run_test(size=(100, 30)) as pilot:
                    await pilot.pause()
                    app = pilot.app
                    sys_cmds = list(app.get_system_commands(app.screen))
                    by_name = {cmd.title: cmd for cmd in sys_cmds}
                    self.assertIn('Preferences', by_name)
                    self.assertIn('View README Documentation', by_name)
                    self.assertIn('View API Specification (twittv.apib)', by_name)
                    self.assertIn('Get TWiT API Key', by_name)

                    by_name['Preferences'].callback()
                    await pilot.pause()
                    self.assertIsNotNone(form._preferences_window)
                    self.assertTrue(form._preferences_window.visible)
                    self.assertIs(app.screen, form._preferences_window._impl.native)

        asyncio.run(run_scenario())

    def test_tui_preferences_editing_persists_to_env_across_reopen(self) -> None:
        form = self._make_form('org.twit.tui-prefs-persist')

        async def run_scenario() -> None:
            with patch.object(form, '_refresh_catalog', lambda: None), \
                 patch.object(form, 'show_splash_screen', lambda *a, **kw: None):
                async with form._impl.native.run_test(size=(110, 32)) as pilot:
                    await pilot.pause()
                    form.show_preferences_window()
                    await pilot.pause()

                    form.app_id_input.value = 'tui_app_id_123'
                    form.app_key_input.value = 'tui_secret_key_456'
                    form.url_input.value = 'club_secret_token'
                    form.block_input.value = '16384'
                    form.rate_limit_input.value = '9'
                    form.streamer_input.value = 'mpv %f'
                    form.show_folders_checkbox._impl.native_switch.toggle()
                    form.fuzzy_search_checkbox._impl.native_switch.toggle()
                    await pilot.pause()

                    # Close and reopen Preferences to ensure state persists
                    form.on_preferences_close_press()
                    await pilot.pause()
                    form.show_preferences_window()
                    await pilot.pause()

                    self.assertEqual(form.app_id_input.value, 'tui_app_id_123')
                    self.assertEqual(form.app_key_input.value, 'tui_secret_key_456')
                    self.assertEqual(form.url_input.value, 'club_secret_token')
                    self.assertEqual(form.block_input.value, '16384')
                    self.assertEqual(form.rate_limit_input.value, '9')
                    self.assertEqual(form.streamer_input.value, 'mpv %f')
                    self.assertTrue(form.show_folders_checkbox.value)
                    self.assertFalse(form.fuzzy_search_checkbox.value)

        asyncio.run(run_scenario())

        from dotenv import dotenv_values
        self.assertTrue(os.path.isfile(self.env_file))
        parsed_env = dotenv_values(self.env_file)
        self.assertEqual(parsed_env.get('TWITAPI_APPLICATIONID'), 'tui_app_id_123')
        self.assertEqual(parsed_env.get('TWITAPI_APPLICATIONKEYS'), 'tui_secret_key_456')
        self.assertEqual(
            parsed_env.get('twitcluburl'),
            'https://twit.memberfulcontent.com/rss/9041?auth=club_secret_token',
        )
        self.assertEqual(parsed_env.get('twitclubblocksize'), '16384')
        self.assertEqual(parsed_env.get('twitapiratelimit'), '9')
        self.assertEqual(parsed_env.get('twitclubstreamer'), 'mpv %f')
        self.assertEqual(parsed_env.get('TWITCLUBSHOWFOLDERS'), '1')
        self.assertEqual(parsed_env.get('TWITFUZZYSEARCH'), '0')

    def test_tui_preferences_browse_folder_and_test_api_modals_and_clear_cache(self) -> None:
        target_subdir = Path(self._tmp_dir.name) / 'ChosenDownloads'
        target_subdir.mkdir(parents=True, exist_ok=True)
        form = self._make_form('org.twit.tui-prefs-modals')
        form._shows_cache = ['This Week in Tech']

        async def run_scenario() -> None:
            with patch.object(form, '_refresh_catalog', lambda: None), \
                 patch.object(form, 'show_splash_screen', lambda *a, **kw: None):
                async with form._impl.native.run_test(size=(110, 32)) as pilot:
                    await pilot.pause()
                    app = pilot.app
                    form.show_preferences_window()
                    await pilot.pause()
                    prefs_screen = form._preferences_window._impl.native
                    self.assertIs(app.screen, prefs_screen)

                    # 1. Interactive Browse folder dialog: select folder
                    form.dest_input.value = self._tmp_dir.name
                    browse_task = asyncio.create_task(form.on_browse_press(form.dest_button))
                    await pilot.pause()
                    self.assertIsInstance(app.screen, TextualSelectFolderScreen)
                    folder_screen = app.screen
                    folder_input = folder_screen.query_one('#folder_path_input')
                    folder_input.value = str(target_subdir)
                    folder_screen.query_one('#btn_folder_select').press()
                    await browse_task
                    await pilot.pause()

                    self.assertIs(app.screen, prefs_screen)
                    self.assertEqual(Path(form.dest_input.value).resolve(), target_subdir.resolve())

                    # 2. Interactive Browse folder dialog: Escape cancels without changing dest_input
                    cancel_task = asyncio.create_task(form.on_browse_press(form.dest_button))
                    await pilot.pause()
                    self.assertIsInstance(app.screen, TextualSelectFolderScreen)
                    await pilot.press('escape')
                    await cancel_task
                    await pilot.pause()
                    self.assertIs(app.screen, prefs_screen)
                    self.assertEqual(Path(form.dest_input.value).resolve(), target_subdir.resolve())

                    # 3. Test API modal dialog pushed over Preferences and dismissed cleanly without AsyncResult error
                    form.show_api_test_dialog(True, 'Passed: Verified credentials.')
                    await pilot.pause()
                    self.assertIsInstance(app.screen, TextualDialogScreen)
                    await pilot.press('enter')
                    await pilot.pause()
                    self.assertIs(app.screen, prefs_screen)

                    # 4. Clear Cache button clears in-memory cache and updates status
                    form.clear_cache_button._impl.native.press()
                    await pilot.pause()
                    self.assertIsNone(form._shows_cache)
                    self.assertEqual(form.api_status_label.text, 'Cache cleared.')

        asyncio.run(run_scenario())


if __name__ == '__main__':
    unittest.main()
