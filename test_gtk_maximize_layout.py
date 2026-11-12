"""Tests verifying GTK form maximization expands episodes_list vertically and pushes bottom controls down."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from toga_textual_backend import patch_toga_textual
patch_toga_textual()

import toga
from twittui_form import TwitTUIForm


class TestGtkMaximizeLayoutUnit(unittest.TestCase):
    """Unit tests for flexible episode list layout and GTK window maximize handling."""

    def setUp(self) -> None:
        patch_toga_textual()
        os.environ['TWITAUDIOONLY'] = '0'
        os.environ['TWITCLUBSHOWFOLDERS'] = '0'
        self.form = TwitTUIForm(
            formal_name='TwitTUI',
            app_id='org.twit.maximize-layout-test',
            cache_db_path=':memory:',
        )
        with patch.object(self.form, '_refresh_catalog'), \
             patch.object(self.form, 'show_splash_screen'):
            self.form.startup()

    def tearDown(self) -> None:
        loop = getattr(self.form, 'loop', None)
        if loop and not loop.is_running() and not loop.is_closed():
            loop.close()

    def test_episodes_list_is_sole_vertical_flex_widget_in_main_box(self) -> None:
        """episodes_list must have flex=1 without fixed height, and bottom controls must not steal vertical flex."""
        self.assertEqual(self.form.episodes_list.style.flex, 1.0)
        self.assertEqual(self.form.episodes_list.style.height, 'none')
        self.assertEqual(self.form.button_box.style.flex, 0.0)
        self.assertEqual(self.form.progress_bar.style.flex, 0.0)

        main_children = list(self.form.main_window.content.children)
        ep_idx = main_children.index(self.form.episodes_list)
        btn_idx = main_children.index(self.form.button_box)
        pb_idx = main_children.index(self.form.progress_bar)
        self.assertLess(ep_idx, btn_idx)
        self.assertLess(btn_idx, pb_idx)
        self.assertEqual(pb_idx, len(main_children) - 1)

    def test_configure_gtk_episodes_layout_sets_min_height_vexpand_and_signal(self) -> None:
        """_configure_gtk_episodes_layout sets 200px min height, vexpand, and connects window-state-event."""
        FakeGtkTableImpl = type('FakeGtkTableImpl', (), {'__module__': 'toga_gtk.widgets.table'})
        fake_table_impl = FakeGtkTableImpl()
        fake_table_impl.rehint = MagicMock()
        fake_table_impl.native = MagicMock()

        fake_container = MagicMock()
        fake_native_win = MagicMock()
        fake_win_impl = SimpleNamespace(container=fake_container, native=fake_native_win)

        orig_table_impl = self.form.episodes_list._impl
        orig_win_impl = self.form.main_window._impl
        try:
            self.form.episodes_list._impl = fake_table_impl
            self.form.main_window._impl = fake_win_impl
            self.form._gtk_maximize_handler_connected = False

            self.form._configure_gtk_episodes_layout()

            self.assertEqual(self.form.episodes_list._MIN_HEIGHT, 200)
            fake_table_impl.rehint.assert_called_once()
            fake_table_impl.native.set_vexpand.assert_called_once_with(True)
            fake_table_impl.native.set_hexpand.assert_called_once_with(True)
            fake_container.set_vexpand.assert_called_once_with(True)
            fake_container.set_hexpand.assert_called_once_with(True)
            self.assertTrue(fake_native_win.connect.called)
            self.assertTrue(self.form._gtk_maximize_handler_connected)
        finally:
            self.form.episodes_list._impl = orig_table_impl
            self.form.main_window._impl = orig_win_impl

    def test_on_gtk_window_state_event_refreshes_layout_on_maximize_and_unmaximize(self) -> None:
        """Maximizing and unmaximizing triggers container dirty/refresh and clears any fixed height."""
        fake_container = MagicMock()
        orig_win_impl = self.form.main_window._impl
        try:
            self.form.main_window._impl = SimpleNamespace(container=fake_container, native=MagicMock())
            self.form.episodes_list.style.height = 200

            fake_widget = MagicMock()
            fake_widget.is_maximized.return_value = True

            res = self.form._on_gtk_window_state_event(fake_widget, None)
            self.assertFalse(res)
            self.assertTrue(self.form._gtk_window_maximized)
            self.assertEqual(self.form.episodes_list.style.height, 'none')
            self.assertTrue(fake_container.make_dirty.called)

            fake_container.make_dirty.reset_mock()
            # Repeated event with same state does not redundantly trigger
            self.form._on_gtk_window_state_event(fake_widget, None)
            self.assertFalse(fake_container.make_dirty.called)

            # Unmaximize transition triggers refresh again
            fake_widget.is_maximized.return_value = False
            self.form._on_gtk_window_state_event(fake_widget, None)
            self.assertFalse(self.form._gtk_window_maximized)
            self.assertTrue(fake_container.make_dirty.called)
        finally:
            self.form.main_window._impl = orig_win_impl


class TestGtkMaximizeIntegration(unittest.TestCase):
    """End-to-end GTK layout verification when maximizing and unmaximizing TwitTUIForm."""

    @unittest.skipUnless(
        shutil.which('xvfb-run') and shutil.which('openbox'),
        'Requires xvfb-run and openbox for full GTK window manager maximize verification',
    )
    def test_gtk_maximize_expands_episode_list_and_pushes_controls_to_bottom(self) -> None:
        """Verify under GTK + Xvfb + Openbox that maximizing fills vertical height and pins bottom controls."""
        probe_script = textwrap.dedent(
            """
            import json
            import os
            import tempfile
            os.environ["TOGA_BACKEND"] = "toga_gtk"
            import toga.constants
            from toga_gtk.libs import GLib
            from twittui_form import TwitTUIForm

            TwitTUIForm._refresh_catalog = lambda self: None
            TwitTUIForm.show_splash_screen = lambda self, *a, **kw: None

            db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            db.close()
            app = TwitTUIForm("TWIT.tv TUI", "org.twit.gtkmaxtest", cache_db_path=db.name)
            results = {}

            orig_startup = app.startup
            def wrapped_startup():
                orig_startup()
                app.current_episodes = [
                    {"number": str(i), "title": f"Episode {i}", "date": "2026-01-01", "length": "01:00:00", "size": 10485760}
                    for i in range(1, 30)
                ]
                app.update_episodes_display()

                def snapshot(key):
                    win = app.main_window
                    cont = win._impl.container
                    sw = app.episodes_list._impl.native
                    results[key] = {
                        "container_height": cont.get_allocated_height(),
                        "table_layout_top": app.episodes_list.layout.absolute_content_top,
                        "table_layout_height": app.episodes_list.layout.content_height,
                        "table_native_height": sw.get_allocated_height(),
                        "button_box_top": app.button_box.layout.absolute_content_top,
                        "button_box_height": app.button_box.layout.content_height,
                        "progress_bar_top": app.progress_bar.layout.absolute_content_top,
                        "progress_bar_height": app.progress_bar.layout.content_height,
                    }

                def step1():
                    snapshot("initial")
                    app.main_window.state = toga.constants.WindowState.MAXIMIZED
                    GLib.timeout_add(300, step2)
                    return False

                def step2():
                    snapshot("maximized")
                    app.main_window.state = toga.constants.WindowState.NORMAL
                    GLib.timeout_add(300, step3)
                    return False

                def step3():
                    snapshot("restored")
                    app._impl.native.quit()
                    return False

                GLib.timeout_add(300, step1)

            app.startup = wrapped_startup
            app.main_loop()
            os.unlink(db.name)
            print("GTK_LAYOUT_JSON:" + json.dumps(results))
            """
        )

        shell_cmd = (
            "openbox >/dev/null 2>&1 & OB_PID=$!; sleep 0.4; "
            f"{sys.executable} -c {subprocess.list2cmdline([probe_script])}; "
            "RC=$?; kill $OB_PID 2>/dev/null || true; wait $OB_PID 2>/dev/null || true; exit $RC"
        )
        proc = subprocess.run(
            ['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', 'bash', '-c', shell_cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=f"GTK probe failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

        json_line = next(
            (line[len('GTK_LAYOUT_JSON:'):] for line in proc.stdout.splitlines() if line.startswith('GTK_LAYOUT_JSON:')),
            None,
        )
        self.assertIsNotNone(json_line, msg=f"Missing GTK_LAYOUT_JSON output:\n{proc.stdout}")
        data = json.loads(json_line)

        initial = data['initial']
        maximized = data['maximized']
        restored = data['restored']

        # Initial unmaximized table preserves 200px minimum height
        self.assertGreaterEqual(initial['table_layout_height'], 200)
        self.assertEqual(initial['table_native_height'], initial['table_layout_height'])

        # Maximized container and table height grow substantially to fill the vertical space
        container_growth = maximized['container_height'] - initial['container_height']
        table_growth = maximized['table_layout_height'] - initial['table_layout_height']
        self.assertGreater(container_growth, 300)
        self.assertEqual(table_growth, container_growth)
        self.assertEqual(maximized['table_native_height'], maximized['table_layout_height'])

        # Controls below episodes_list (button_box and progress_bar) are pushed to the bottom of the form
        self.assertGreater(maximized['button_box_top'], initial['button_box_top'] + 300)
        self.assertGreater(maximized['progress_bar_top'], initial['progress_bar_top'] + 300)
        bottom_edge = maximized['progress_bar_top'] + maximized['progress_bar_height'] + 10  # 5px progress margin + 5px main_box margin
        self.assertEqual(bottom_edge, maximized['container_height'])

        # Restoring from maximized returns layout cleanly
        self.assertEqual(restored['table_layout_height'], initial['table_layout_height'])
        self.assertEqual(restored['progress_bar_top'], initial['progress_bar_top'])


if __name__ == '__main__':
    unittest.main()
