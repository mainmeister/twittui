"""Unit tests for TwitTUI startup and shutdown splash screen implementations."""

import asyncio
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import LoadingIndicator
from toga_textual_backend import SplashScreen, patch_toga_textual
from twittui_form import TwitTUIForm
from main import show_terminal_splash


class TestTextualSplashScreen(unittest.TestCase):
    """Test Textual modal SplashScreen widget behavior."""

    def setUp(self) -> None:
        patch_toga_textual()

    def test_splash_screen_displays_and_closes(self) -> None:
        async def run():
            app = App()
            async with app.run_test() as pilot:
                screen = SplashScreen(title="TwitTUI Media Browser", message="Loading TwitTUI. Please wait...")
                await app.push_screen(screen)
                self.assertIs(app.screen, screen)
                self.assertEqual(len(screen.query(LoadingIndicator)), 1)
                self.assertIn("TwitTUI Media Browser", str(screen.query_one("#splash_title").renderable))
                self.assertIn("Loading TwitTUI", str(screen.query_one("#splash_message").renderable))

                screen.update_message("Loading show archive dates...")
                self.assertIn("Loading show archive dates...", str(screen.query_one("#splash_message").renderable))

                screen.close_splash()
                await pilot.pause()
                self.assertIsNot(app.screen, screen)

        asyncio.run(run())

    def test_splash_screen_closes_after_overlapping_screen(self) -> None:
        async def run():
            app = App()
            async with app.run_test() as pilot:
                screen = SplashScreen()
                await app.push_screen(screen)
                other = ModalScreen()
                await app.push_screen(other)
                screen.close_splash()
                self.assertIs(app.screen, other)
                other.dismiss()
                await pilot.pause()
                self.assertIsNot(app.screen, screen)

        asyncio.run(run())


class TestFormSplashScreenIntegration(unittest.TestCase):
    """Test TwitTUIForm splash screen lifecycle on startup and close."""

    def setUp(self) -> None:
        patch_toga_textual()
        self.form = TwitTUIForm(formal_name='TwitTUI', app_id='org.twit.splash-test', cache_db_path=':memory:')

    def test_show_and_close_splash_screen_textual(self) -> None:
        mock_native_app = MagicMock()
        self.form._impl = MagicMock()
        self.form._impl.native = mock_native_app
        self.form._impl.native.__class__.__module__ = 'toga_textual.app'

        self.form.show_splash_screen("Loading TwitTUI...", "TwitTUI")
        self.assertIsNotNone(self.form._splash_window)
        mock_native_app.push_screen.assert_called_once()

        self.form.close_splash_screen()
        self.assertIsNone(self.form._splash_window)

    def test_show_and_close_splash_screen_desktop_fallback(self) -> None:
        self.form._impl = MagicMock()
        self.form._impl.native = MagicMock()
        self.form._impl.native.__class__.__module__ = 'toga_gtk.app'
        self.form._main_window = MagicMock()
        self.form._main_window.position = (100, 100)
        self.form._main_window.size = (800, 600)

        mock_window = MagicMock(spec=['show', 'hide', 'close', '_impl', 'position', 'size', 'content'])
        with patch('twittui_form.toga.Window', return_value=mock_window) as mock_win_cls, \
             patch('twittui_form.toga.Box'), \
             patch('twittui_form.toga.Label'), \
             patch('twittui_form.toga.ActivityIndicator'):
            self.form.show_splash_screen("Loading...", "TwitTUI")
            self.assertEqual(mock_win_cls.call_count, 1)
            mock_window.show.assert_called_once()

            self.form.close_splash_screen()
            mock_window.close.assert_called_once()
            self.assertIsNone(self.form._splash_window)

    def test_on_close_press_shows_closing_splash(self) -> None:
        with patch.object(self.form, 'show_splash_screen') as mock_show_splash, \
             patch.object(self.form, 'exit') as mock_exit:
            self.form.on_close_press(None)
            mock_show_splash.assert_called_once_with("Closing TwitTUI. Please wait...", title="TWiT.tv TUI")
            mock_exit.assert_called_once()

    def test_on_cancel_press_shows_closing_splash_when_not_downloading(self) -> None:
        self.form._is_downloading = False
        with patch.object(self.form, 'show_splash_screen') as mock_show_splash, \
             patch.object(self.form, 'exit') as mock_exit:
            self.form.on_cancel_press(None)
            mock_show_splash.assert_called_once_with("Closing TwitTUI. Please wait...", title="TWiT.tv TUI")
            mock_exit.assert_called_once()


class TestTerminalSplashBanner(unittest.TestCase):
    """Test CLI / terminal banner output for startup and shutdown."""

    def test_show_terminal_splash_output(self) -> None:
        buffer = io.StringIO()
        mock_stdout = MagicMock(wraps=buffer)
        mock_stdout.isatty.return_value = True

        with patch('sys.stdout', mock_stdout):
            show_terminal_splash("Loading TwitTUI, please wait...")

        output = buffer.getvalue()
        self.assertIn("TwitTUI: TWiT.tv Terminal & Desktop Media Browser", output)
        self.assertIn("Loading TwitTUI, please wait...", output)


if __name__ == '__main__':
    unittest.main()
