"""Regression tests for TUI stdout corruption and streaming hangs."""

import asyncio
import io
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOGA_BACKEND", "toga_textual")

import toga
import toga.platform
from textual.widgets import Button
from toga_textual_backend import (
    ChoiceDialog,
    RateLimitScreen,
    SplashScreen,
    TextualChoiceDialogScreen,
    patch_toga_textual,
)
from twittui_form import TwitTUIForm, launch_stream_safe, resolve_stream_url


class TestTUIStreamingAndStdout(unittest.TestCase):
    """Verify --tui does not emit spurious stdout output and does not hang when streaming."""

    def setUp(self) -> None:
        os.environ["TOGA_BACKEND"] = "toga_textual"
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()
        patch_toga_textual()

    def test_tui_multi_resolution_stream_prompts_and_completes_without_hanging(self) -> None:
        """Streaming a multi-resolution episode in --tui must open TextualChoiceDialogScreen and not hang."""
        form = TwitTUIForm(
            formal_name="TWIT.tv TUI",
            app_id="org.twit.tui-stream-test",
            cache_db_path=":memory:",
        )

        ep_data = {
            "id": "999",
            "number": "999",
            "title": "Security Now 999",
            "video_hd": {"mediaUrl": "https://cdn.twit.tv/sn0999_h264m_1280x720_1872.mp4", "fileSize": 800000000},
            "video_small": {"mediaUrl": "https://cdn.twit.tv/sn0999_h264b_640x368_256.mp4", "fileSize": 150000000},
        }

        class MockRow:
            def __init__(self, data: dict):
                self.episode = data["number"]
                self.title = data["title"]
                self.episode_data = data

        launched = []

        async def run_scenario() -> None:
            with patch.object(form, "_refresh_catalog", lambda: None):
                async with form._impl.native.run_test() as pilot:
                    await pilot.pause()
                    form.is_audio_only = lambda: False
                    form.episodes_list = type("MockTable", (), {"selection": [MockRow(ep_data)]})()

                    with patch("twittui_form.resolve_stream_url", side_effect=lambda u: u), \
                         patch("twittui_form.launch_stream_safe", side_effect=lambda tmpl, url: launched.append((tmpl, url))):
                        stream_task = asyncio.create_task(form.on_stream_press())

                        # Wait briefly for resolution choice screen to appear
                        for _ in range(20):
                            await pilot.pause()
                            if isinstance(form._impl.native.screen, TextualChoiceDialogScreen):
                                break

                        self.assertIsInstance(
                            form._impl.native.screen,
                            TextualChoiceDialogScreen,
                            "Expected TextualChoiceDialogScreen to be pushed for multi-resolution streaming",
                        )

                        # Focus second resolution button and press Enter
                        opt_btn = form._impl.native.screen.query_one("#opt_btn_1", Button)
                        opt_btn.focus()
                        await pilot.press("enter")
                        await asyncio.wait_for(stream_task, timeout=2.0)

        asyncio.run(run_scenario())
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0][1], "https://cdn.twit.tv/sn0999_h264b_640x368_256.mp4")

    def test_choice_dialog_implements_toga_dialog_protocol(self) -> None:
        """ChoiceDialog must implement Toga 0.5's _show(window) protocol so Window.dialog() works."""
        dlg = ChoiceDialog(
            "Select Stream Quality",
            "Choose quality:",
            [{"id": "hd", "label": "HD"}, {"id": "sd", "label": "SD"}],
        )
        self.assertTrue(hasattr(dlg, "_show"), "ChoiceDialog must implement _show(window)")

    def test_spurious_stdout_not_printed_by_application_operations(self) -> None:
        """Application operations in TUI mode must not print spurious messages to sys.stdout."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            form = TwitTUIForm(
                formal_name="TWIT.tv TUI",
                app_id="org.twit.stdout-test",
                cache_db_path=":memory:",
            )
            form.episodes_list = type("MockTable", (), {"selection": []})()

            # 1. Calling on_stream_press with no selection previously printed to stdout
            asyncio.run(form.on_stream_press())

            # 2. Failed redirect resolution previously printed to stdout
            with patch("requests.head", side_effect=OSError("offline")), \
                 patch("requests.get", side_effect=OSError("offline")):
                resolve_stream_url("https://twit.tv/stream_test.mp3")

            # 3. Closing in TUI mode previously printed an ASCII banner directly to stdout
            mock_stdout = MagicMock(wraps=buf)
            mock_stdout.isatty.return_value = True
            with patch("sys.stdout", mock_stdout), \
                 patch.object(form, "show_splash_screen"), \
                 patch.object(form, "exit"):
                form.on_close_press(None)

        self.assertEqual(
            buf.getvalue(),
            "",
            f"Expected no spurious stdout output, but got:\n{buf.getvalue()!r}",
        )

    def test_launch_stream_safe_silences_stdio_when_tui_active(self) -> None:
        """When Textual TUI is running, launch_stream_safe must redirect player stdio to DEVNULL."""
        form = TwitTUIForm(
            formal_name="TWIT.tv TUI",
            app_id="org.twit.stdio-test",
            cache_db_path=":memory:",
        )

        async def run_check() -> dict:
            captured_kwargs = {}
            with patch.object(form, "_refresh_catalog", lambda: None):
                async with form._impl.native.run_test() as pilot:
                    await pilot.pause()
                    with patch("twittui_form.resolve_stream_url", return_value="https://cdn.twit.tv/test.mp3"), \
                         patch("subprocess.Popen") as mock_popen:
                        launch_stream_safe("env LC_ALL=C vlc %f", "https://cdn.twit.tv/test.mp3")
                        self.assertTrue(mock_popen.called)
                        _, kwargs = mock_popen.call_args
                        captured_kwargs.update(kwargs)
            return captured_kwargs

        kwargs = asyncio.run(run_check())
        self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)
        self.assertEqual(kwargs.get("stdout"), subprocess.DEVNULL)
        self.assertEqual(kwargs.get("stderr"), subprocess.DEVNULL)

    def test_rate_limit_screen_close_before_mount_does_not_stick(self) -> None:
        """Calling close_wait() immediately after push_screen() before mount must not leave RateLimitScreen stuck."""
        from textual.app import App

        async def run_race() -> None:
            app = App()
            async with app.run_test() as pilot:
                screen = RateLimitScreen()
                app.push_screen(screen)
                # Immediately close BEFORE pilot.pause() processes push_screen!
                screen.close_wait()
                await pilot.pause()
                await pilot.pause()
                self.assertIsNot(
                    app.screen,
                    screen,
                    "RateLimitScreen remained stuck on top of screen stack after early close_wait()",
                )

        asyncio.run(run_race())

    def test_headless_tui_vlc_adds_dummy_interface_flag(self) -> None:
        """On headless Unix without DISPLAY/WAYLAND_DISPLAY, VLC in TUI mode gets -I dummy."""
        form = TwitTUIForm(
            formal_name="TWIT.tv TUI",
            app_id="org.twit.headless-vlc-test",
            cache_db_path=":memory:",
        )

        async def run_check() -> list[str]:
            captured_args: list[str] = []
            with patch.object(form, "_refresh_catalog", lambda: None):
                async with form._impl.native.run_test() as pilot:
                    await pilot.pause()
                    with patch.dict(os.environ, {}, clear=False), \
                         patch("sys.platform", "linux"), \
                         patch("twittui_form.resolve_stream_url", return_value="https://cdn.twit.tv/test.mp3"), \
                         patch("subprocess.Popen") as mock_popen:
                        os.environ.pop("DISPLAY", None)
                        os.environ.pop("WAYLAND_DISPLAY", None)
                        launch_stream_safe("env LC_ALL=C vlc %f", "https://cdn.twit.tv/test.mp3")
                        args, _ = mock_popen.call_args
                        captured_args.extend(args[0])
            return captured_args

        cmd_args = asyncio.run(run_check())
        self.assertEqual(cmd_args, ["env", "LC_ALL=C", "vlc", "-I", "dummy", "https://cdn.twit.tv/test.mp3"])

    def test_gtk_backend_prompt_resolution_choice_uses_modal_window(self) -> None:
        """Desktop (non-Textual) backend must not short-circuit prompt_resolution_choice to None via ChoiceDialog."""
        form = TwitTUIForm(
            formal_name="TWIT.tv Desktop",
            app_id="org.twit.gtk-dialog-test",
            cache_db_path=":memory:",
        )
        form._impl = MagicMock()
        form._impl.native = MagicMock()
        form._impl.native.__class__.__module__ = "toga_gtk.app"

        resolutions = [
            {"id": "video_hd", "label": "HD Video", "url": "https://cdn.twit.tv/hd.mp4"},
            {"id": "video_sd", "label": "SD Video", "url": "https://cdn.twit.tv/sd.mp4"},
        ]

        created_buttons = []

        def fake_button(label, on_press=None, **kwargs):
            btn = MagicMock()
            btn.label = label
            btn.on_press = on_press
            created_buttons.append(btn)
            return btn

        mock_win = MagicMock()

        def trigger_first_choice():
            for b in created_buttons:
                if b.label == "SD Video" and callable(b.on_press):
                    b.on_press(b)
                    break

        mock_win.show.side_effect = trigger_first_choice

        with patch("twittui_form.toga.Window", return_value=mock_win), \
             patch("twittui_form.toga.Box"), \
             patch("twittui_form.toga.Label"), \
             patch("twittui_form.toga.Button", side_effect=fake_button):
            chosen = asyncio.run(form.prompt_resolution_choice("Choose", "Select format", resolutions))

        self.assertEqual(chosen, resolutions[1])

    def test_lazy_episodes_cache_and_fast_snapshot_prevent_large_db_hang(self) -> None:
        """Large SQLite episode caches must load on demand without eager JSON parsing or slow deepcopy."""
        import json
        import tempfile
        import time

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        seed_form = TwitTUIForm("Seed", "org.twit.seed", cache_db_path=db_path)
        big_show_eps = [
            {"id": str(i), "number": str(i), "title": f"Ep {i}", "showNotes": "x" * 2000}
            for i in range(500)
        ]
        seed_form._save_to_persistent_cache("episodes", "65161", big_show_eps)
        seed_form._save_to_persistent_cache("episodes", "1636", [{"id": "1", "number": "1", "title": "SN 1"}])

        with patch("json.loads", wraps=json.loads) as spy_loads:
            form = TwitTUIForm("LazyApp", "org.twit.lazy", cache_db_path=db_path)
            # Neither episode cache row should have been eagerly json.loads'd during __init__
            self.assertEqual(spy_loads.call_count, 0)
            self.assertIn("65161", form._episodes_cache)
            self.assertIn("1636", form._episodes_cache)

            # Snapshot must NOT trigger loading unloaded shows
            form.current_episodes = big_show_eps
            t0 = time.monotonic()
            snap = form._network_snapshot()
            elapsed = time.monotonic() - t0
            self.assertEqual(spy_loads.call_count, 0)
            self.assertLess(elapsed, 0.2)
            self.assertEqual(len(snap.current_episodes), 500)

            # Accessing a single show loads only that show's JSON
            sn_eps = form._episodes_cache["1636"]
            self.assertEqual(len(sn_eps), 1)
            self.assertEqual(spy_loads.call_count, 1)


if __name__ == "__main__":
    unittest.main()
