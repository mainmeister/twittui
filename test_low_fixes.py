"""Regression tests verifying fixes for Low/Edge-case audit findings (#21-#23)."""

import asyncio
import os
import stat
import sys
import tempfile
import time
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOGA_BACKEND", "toga_textual")

import installer
import main as twittui_main
import toga
import toga.platform
from toga_textual_backend import patch_toga_textual
from twittui_form import TWITTUI_HOMEPAGE_URL, TwitTUIForm, api_rate_limiter


class TestLowAndEdgeCaseFixes(unittest.TestCase):
    """Comprehensive tests covering Low / Edge-case fixes #21, #22, and #23."""

    def setUp(self) -> None:
        os.environ["TOGA_BACKEND"] = "toga_textual"
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()
        patch_toga_textual()

    # ------------------------------------------------------------------
    # Bug 21: CLI bootstrap, Ctrl+C abort, fallback apostrophe, null sink
    # ------------------------------------------------------------------
    def test_21_cli_bootstrap_splash_order_ctrl_c_fallback_and_null_sink(self) -> None:
        # 21a. --clean / --help exits inside resolve_toga_backend BEFORE loading splash is shown
        with patch.object(twittui_main, "show_terminal_splash") as mock_splash, \
             patch.object(twittui_main, "resolve_toga_backend", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit) as cm:
                twittui_main.main(["--help"])
            self.assertEqual(cm.exception.code, 0)
            mock_splash.assert_not_called()

        # 21b. Ctrl+C (KeyboardInterrupt) during interactive backend prompt aborts with exit 130
        with patch.object(twittui_main, "get_installed_toga_backends", return_value={"gtk": True, "textual": True}), \
             patch.object(twittui_main, "is_graphical_display_available", return_value=True), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", side_effect=KeyboardInterrupt):
            with self.assertRaises(SystemExit) as cm:
                twittui_main.resolve_toga_backend([], prompt_interactive=True)
            self.assertEqual(cm.exception.code, 130)

        # 21c. GTK -> Textual fallback triggers on ASCII apostrophe "Couldn't recognize the image file format"
        fake_gtk_app = MagicMock()
        fake_gtk_app.main_loop.side_effect = RuntimeError("Couldn't recognize the image file format")
        fake_tui_app = MagicMock()
        with patch.object(twittui_main, "resolve_toga_backend", return_value="toga_gtk"), \
             patch.object(twittui_main, "show_terminal_splash"), \
             patch.object(twittui_main, "get_installed_toga_backends", return_value={"gtk": True, "textual": True}), \
             patch.object(twittui_main, "_configure_textual_warnings") as mock_warn_cfg, \
             patch("twittui_form.load_twittui_dotenv"), \
             patch("twittui_form.main", side_effect=[fake_gtk_app, fake_tui_app]):
            twittui_main.main([])
        mock_warn_cfg.assert_called_once()
        fake_tui_app.main_loop.assert_called_once()

        # 21d. _NullTextIO discards writes without buffering
        sink = twittui_main._NullTextIO()
        self.assertEqual(sink.write("hello"), 5)
        self.assertFalse(sink.isatty())
        sink.flush()

    def test_21b_cli_fallback_resets_stale_app_curly_apostrophe_and_stream_contract(self) -> None:
        """Verify curly-apostrophe fallback resets stale GTK app/loop, splash skips --clean/--install, and stream contracts hold."""
        # Curly apostrophe (U+2019) triggers fallback, closes stale GTK loop, and resets toga.App.app before Textual create_app
        stale_loop = MagicMock()
        stale_loop.is_running.return_value = False
        stale_loop.is_closed.return_value = False
        fake_gtk_app = MagicMock(_impl=SimpleNamespace(loop=stale_loop))
        fake_gtk_app.main_loop.side_effect = RuntimeError("Couldn\u2019t recognize the image file format")

        app_singleton_seen_by_fallback: list[object] = []
        fake_tui_app = MagicMock()

        def _create_app_side_effect():
            if not app_singleton_seen_by_fallback:
                toga.App.app = fake_gtk_app
                app_singleton_seen_by_fallback.append("gtk_created")
                return fake_gtk_app
            app_singleton_seen_by_fallback.append(toga.App.app)
            return fake_tui_app

        with patch.object(twittui_main, "resolve_toga_backend", return_value="toga_gtk"), \
             patch.object(twittui_main, "show_terminal_splash"), \
             patch.object(twittui_main, "get_installed_toga_backends", return_value={"gtk": True, "textual": True}), \
             patch.object(twittui_main, "_configure_textual_warnings") as mock_warn_cfg, \
             patch("twittui_form.load_twittui_dotenv"), \
             patch("twittui_form.main", side_effect=_create_app_side_effect):
            twittui_main.main([])

        stale_loop.close.assert_called_once()
        self.assertEqual(app_singleton_seen_by_fallback, ["gtk_created", None])
        mock_warn_cfg.assert_called_once()
        fake_tui_app.main_loop.assert_called_once()

        # --clean and --install never emit loading or closing splash banners
        with patch.object(twittui_main, "show_terminal_splash") as mock_splash, \
             patch("installer.clean_build_artifacts"), \
             patch("installer.install_twittui"):
            with self.assertRaises(SystemExit) as cm_clean:
                twittui_main.main(["--clean"])
            self.assertEqual(cm_clean.exception.code, 0)
            with self.assertRaises(SystemExit) as cm_install:
                twittui_main.main(["--install"])
            self.assertEqual(cm_install.exception.code, 0)
            mock_splash.assert_not_called()

        # _NullTextIO supports standard text stream attributes/methods without buffering
        sink = twittui_main._NullTextIO()
        self.assertEqual(sink.encoding, "utf-8")
        self.assertEqual(sink.errors, "replace")
        self.assertFalse(sink.closed)
        self.assertTrue(sink.writable())
        self.assertFalse(sink.readable())
        sink.writelines(["line 1\n", "line 2\n"])

        # StderrRedirector returns character counts cleanly
        buf = MagicMock()
        buf.write.return_value = 5
        redir = twittui_main.StderrRedirector(buf)
        self.assertEqual(redir.write("hello"), 5)
        suppressed = "Gtk-Message: Failed to load module \"xapp-gtk3-module\"\n"
        self.assertEqual(redir.write(suppressed), len(suppressed))
        buf.write.assert_called_once_with("hello")

    # ------------------------------------------------------------------
    # Bug 22: PyInstaller cross-interpreter probe, gi/yt_dlp, umask, PATH, strip
    # ------------------------------------------------------------------
    def test_22_installer_cross_probe_path_exclusions_umask_and_opt_in_strip(self) -> None:
        # 22a. --strip omitted by default; included only when strip_binary=True; gi hidden imports gated; yt_dlp collected
        with tempfile.TemporaryDirectory() as tmp_dir:
            dist_dir = os.path.join(tmp_dir, "dist")
            os.makedirs(dist_dir, exist_ok=True)
            fake_exe = os.path.join(dist_dir, installer.get_default_executable_name())
            with open(fake_exe, "w") as f:
                f.write("bin")

            with patch("installer.check_python_shared_library", return_value=(True, "")), \
                 patch("installer._probe_packages_in_interpreter", return_value={"yt_dlp"}), \
                 patch("shutil.which", return_value="/usr/bin/strip"), \
                 patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as mock_run:
                installer.build_executable(project_root=tmp_dir, output_dir=dist_dir, python_executable="python_test")
                cmd = mock_run.call_args[0][0]
                self.assertNotIn("--strip", cmd)
                self.assertIn("--collect-all=yt_dlp", cmd)
                self.assertNotIn("--hidden-import=gi.overrides.Gtk", cmd)
                self.assertNotIn("--hidden-import=gi.overrides.Pango", cmd)

                installer.build_executable(
                    project_root=tmp_dir, output_dir=dist_dir, python_executable="python_test", strip_binary=True
                )
                cmd_stripped = mock_run.call_args[0][0]
                if sys.platform != "win32":
                    self.assertIn("--strip", cmd_stripped)

        # 22b. Cross-interpreter probe queries target executable via subprocess when path exists on disk
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout='["toga_gtk", "yt_dlp"]', stderr="")) as mock_probe, \
             patch("os.path.isfile", return_value=True):
            found = installer._probe_packages_in_interpreter(("toga_gtk", "gi", "yt_dlp"), "/usr/bin/python3.99")
            self.assertEqual(found, {"toga_gtk", "yt_dlp"})
            mock_probe.assert_called_once()

        # 22c. find_local_executable_path skips '.', active VIRTUAL_ENV, and .cargo/bin
        with tempfile.TemporaryDirectory() as tmp_dir:
            venv_bin = os.path.join(tmp_dir, ".venv", "bin")
            cargo_bin = os.path.join(tmp_dir, ".cargo", "bin")
            good_bin = os.path.join(tmp_dir, "mytools")
            for d in (venv_bin, cargo_bin, good_bin):
                os.makedirs(d, exist_ok=True)
            env_path = os.pathsep.join([".", venv_bin, cargo_bin, good_bin])
            with patch.dict(os.environ, {"PATH": env_path, "VIRTUAL_ENV": os.path.join(tmp_dir, ".venv")}):
                resolved = installer.find_local_executable_path()
                self.assertEqual(resolved, os.path.abspath(good_bin))

        # 22d. install_twittui respects restrictive umask (0o077 -> 0o700, no group/other bits)
        if sys.platform != "win32":
            with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as target_dir:
                dist_dir = os.path.join(project_dir, "dist")
                os.makedirs(dist_dir, exist_ok=True)
                fake_exe = os.path.join(dist_dir, "twittui")
                with open(fake_exe, "w") as f:
                    f.write("#!/bin/sh\n")
                old_umask = os.umask(0o077)
                try:
                    with patch("installer.ensure_pyinstaller_installed", return_value=True), \
                         patch("installer.build_executable", return_value=fake_exe):
                        installed = installer.install_twittui(
                            target_dir=target_dir,
                            project_root=project_dir,
                            clean_build_artifacts=False,
                        )
                    mode = stat.S_IMODE(os.stat(installed).st_mode)
                    self.assertEqual(mode, 0o700)
                finally:
                    os.umask(old_umask)

    def test_22b_installer_macos_gi_gate_main_strip_conda_path_and_atomic_install(self) -> None:
        """Verify Darwin/Windows gate gi overrides, cross-probe never leaks host pkgs, CONDA_PREFIX excluded, and main --strip works."""
        # 1. On macOS (Darwin), gi.overrides hidden imports are NOT passed even if gi is present
        with tempfile.TemporaryDirectory() as tmp_dir:
            dist_dir = os.path.join(tmp_dir, "dist")
            os.makedirs(dist_dir, exist_ok=True)
            fake_exe = os.path.join(dist_dir, "twittui")
            with open(fake_exe, "w") as f:
                f.write("bin")

            with patch("platform.system", return_value="Darwin"), \
                 patch("installer.check_python_shared_library", return_value=(True, "")), \
                 patch("installer._probe_packages_in_interpreter", return_value={"gi", "yt_dlp", "nh3"}), \
                 patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as mock_run:
                installer.build_executable(project_root=tmp_dir, output_dir=dist_dir, python_executable="python_mac")
                cmd = mock_run.call_args[0][0]
                self.assertIn("--collect-all=yt_dlp", cmd)
                self.assertIn("--collect-all=nh3", cmd)
                self.assertNotIn("--hidden-import=gi.overrides.Gtk", cmd)
                self.assertNotIn("--hidden-import=gi.overrides.Pango", cmd)

        # 2. Failed cross-interpreter subprocess probe returns empty set instead of falling back to host packages
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="error")), \
             patch("os.path.isfile", return_value=True), \
             patch("importlib.util.find_spec", side_effect=AssertionError("Must not probe host interpreter on cross-probe failure")):
            found = installer._probe_packages_in_interpreter(("toga_gtk", "gi"), "/usr/bin/python3.99")
            self.assertEqual(found, set())

        # 3. find_local_executable_path excludes CONDA_PREFIX, .rustup, and .pyenv
        with tempfile.TemporaryDirectory() as tmp_dir:
            conda_bin = os.path.join(tmp_dir, "miniconda", "bin")
            pyenv_bin = os.path.join(tmp_dir, ".pyenv", "shims")
            good_bin = os.path.join(tmp_dir, "custom_bin")
            for d in (conda_bin, pyenv_bin, good_bin):
                os.makedirs(d, exist_ok=True)
            env_path = os.pathsep.join([conda_bin, pyenv_bin, good_bin])
            with patch.dict(os.environ, {"PATH": env_path, "CONDA_PREFIX": os.path.join(tmp_dir, "miniconda")}):
                self.assertEqual(installer.find_local_executable_path(), os.path.abspath(good_bin))

        # 4. main.py forwards --strip to install_twittui(..., strip_binary=True)
        with patch("installer.install_twittui") as mock_install, \
             patch("sys.exit", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                twittui_main.resolve_toga_backend(["--install", "--strip", "--install-dir", "/tmp/bin22"])
            mock_install.assert_called_once_with(
                target_dir="/tmp/bin22",
                python_executable=None,
                clean_build_artifacts=True,
                strip_binary=True,
            )

        # 5. install_twittui stages and atomically replaces existing binary without leaving temp files
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as target_dir:
            dist_dir = os.path.join(project_dir, "dist")
            os.makedirs(dist_dir, exist_ok=True)
            exe_name = installer.get_default_executable_name()
            fake_exe = os.path.join(dist_dir, exe_name)
            with open(fake_exe, "w") as f:
                f.write("#!/bin/sh\necho v2\n")
            existing = os.path.join(target_dir, exe_name)
            with open(existing, "w") as f:
                f.write("#!/bin/sh\necho v1\n")

            with patch("installer.ensure_pyinstaller_installed", return_value=True), \
                 patch("installer.build_executable", return_value=fake_exe):
                installed = installer.install_twittui(
                    target_dir=target_dir,
                    project_root=project_dir,
                    clean_build_artifacts=False,
                )
            with open(installed, "r") as f:
                self.assertIn("echo v2", f.read())
            self.assertEqual(os.listdir(target_dir), [exe_name])

    # ------------------------------------------------------------------
    # Bug 23a: Input validation, callable rate_limit, debouncing, custom Club TWiT feed ID
    # ------------------------------------------------------------------
    def test_23a_config_validation_debouncing_and_custom_club_feed_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch.dict(os.environ, {"SNAP_USER_DATA": tmp_dir, "twitcluburl": "https://twit.memberfulcontent.com/rss/9055?auth=OLDTOK"}, clear=False):
            form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
            form._build_preferences_box()

            # Custom feed ID 9055 preserved in prefix label, input, and subsequent edits
            self.assertEqual(form.url_prefix.text, "https://twit.memberfulcontent.com/rss/9055?auth=")
            self.assertEqual(form.url_input.value, "OLDTOK")
            form.url_input.value = "NEWTOK"
            form.on_url_change()
            self.assertEqual(os.environ.get("twitcluburl"), "https://twit.memberfulcontent.com/rss/9055?auth=NEWTOK")
            self.assertEqual(form.get_full_club_twit_url(), "https://twit.memberfulcontent.com/rss/9055?auth=NEWTOK")

            # Invalid block size & rate limit are rejected and NOT persisted
            saved = {}
            with patch.object(form, "save_env_setting", side_effect=lambda k, v: saved.__setitem__(k, v)):
                form.block_input.value = "not-a-number"
                form.on_block_change()
                form.block_input.value = "-50"
                form.on_block_change()
                self.assertNotIn("twitclubblocksize", saved)

                form.rate_limit_input.value = "0"
                form.on_rate_limit_change()
                form.rate_limit_input.value = "abc"
                form.on_rate_limit_change()
                self.assertNotIn("twitapiratelimit", saved)

                form.rate_limit_input.value = "7"
                form.on_rate_limit_change()
                self.assertEqual(saved.get("twitapiratelimit"), "7")
                # api_rate_limiter.rate_limit must remain callable (bound getter), not frozen int
                self.assertTrue(callable(api_rate_limiter.rate_limit))
                self.assertEqual(api_rate_limiter.rate_limit(), 7)

            # Debouncing coalesces rapid keystrokes under a running event loop
            async def check_debounce() -> None:
                save_calls = []
                form._impl = SimpleNamespace(loop=asyncio.get_running_loop(), native=SimpleNamespace())
                with patch.object(TwitTUIForm, "save_env_setting", side_effect=lambda k, v: save_calls.append((k, v))):
                    for ch in ("a", "ab", "abc", "abcd"):
                        form.app_id_input.value = ch
                        form.on_app_id_change()
                    self.assertEqual(save_calls, [])
                    form._flush_pending_env_saves()
                    self.assertEqual(save_calls, [("TWITAPI_APPLICATIONID", "abcd")])

            asyncio.run(check_debounce())

    # ------------------------------------------------------------------
    # Bug 23b: Shutdown cleanup, HTML preview pruning, filename sanitization,
    #          Toga 0.5 dialog API, lightweight API test, transcript URL, homepage
    # ------------------------------------------------------------------
    def test_23b_cleanup_pruning_filenames_dialogs_api_test_transcript_and_homepage(self) -> None:
        self.assertEqual(TWITTUI_HOMEPAGE_URL, "https://github.com/mainmeister/twittui")

        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")

        # Clean shutdown cancels download and stops _LocalHTMLServer
        mock_server = MagicMock()
        form._local_server = mock_server
        form._is_downloading = True
        form._cancel_download = False
        with patch.object(form, "show_splash_screen"), patch.object(form, "exit"):
            form.on_close_press(None)
        self.assertTrue(form._cancel_download)
        mock_server.shutdown.assert_called_once()
        mock_server.server_close.assert_called_once()
        self.assertIsNone(form._local_server)

        # Fallback HTML temp files in cache dir are pruned (keeping <= 5 files)
        with tempfile.TemporaryDirectory() as tmp_cache:
            with patch.object(form, "_ensure_local_server", return_value=None), \
                 patch.object(form, "get_app_cache_dir", return_value=tmp_cache), \
                 patch.object(form, "_open_browser_quietly"):
                for i in range(8):
                    form.open_html_in_browser(f"<html><body>Page {i}</body></html>")
                    time.sleep(0.005)
            remaining = [f for f in os.listdir(tmp_cache) if f.startswith("twittui_preview_")]
            self.assertLessEqual(len(remaining), 5)

        # Filename & folder sanitization strips dots/control chars and respects POSIX 255-byte NAME_MAX
        traversal_target = SimpleNamespace(show="... \x00\x07 ..", title="... \x01secret\x1f ...", episode="1")
        folder = form.get_show_folder_name(traversal_target)
        self.assertFalse(folder.startswith("."))
        self.assertNotIn("\x00", folder)
        self.assertNotIn("..", folder)

        long_title = "É" * 200  # 400 UTF-8 bytes
        long_target = SimpleNamespace(title=long_title, episode="99", episode_data={"title": long_title, "number": "99"})
        filename = form.determine_download_filename(long_target, "https://cdn.twit.tv/ep.mp4")
        self.assertTrue(filename.endswith(".mp4"))
        self.assertLessEqual(len(filename.encode("utf-8")), 255)
        self.assertFalse(filename.startswith("."))

        # Lightweight API test uses shows?page=1&range=1
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"count": 42, "shows": [{"id": 1}]}
        with patch("twittui_form.api_rate_limiter.get", return_value=mock_resp) as mock_api_get:
            ok, msg = form.test_api_credentials("id1", "key1")
        self.assertTrue(ok)
        self.assertIn("42", msg)
        called_url = mock_api_get.call_args[0][0]
        self.assertIn("page=1&range=1", called_url)
        self.assertNotIn("1000000", called_url)

        # resolve_transcript_url returns '' without fabricating unverified URLs by default
        ep_no_tx = {"title": "Old Show 5", "number": "5", "show_name": "Security Now"}
        self.assertEqual(form.resolve_transcript_url(ep_no_tx, show_name="Security Now"), "")
        self.assertNotIn("transcript_url", ep_no_tx)
        guessed = form.resolve_transcript_url(ep_no_tx, show_name="Security Now", allow_guess=True)
        self.assertTrue(guessed.startswith("https://twit.tv/posts/transcripts/"))

        # Toga 0.5 dialog API on real toga.Window emits ZERO DeprecationWarnings
        real_win = toga.Window(title="TestWin")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            form._present_window_dialog(real_win, "info", "Title", "Body")
            form._present_window_dialog(real_win, "error", "ErrTitle", "ErrBody")
        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        self.assertEqual(dep_warnings, [], f"Unexpected DeprecationWarnings: {[str(w.message) for w in dep_warnings]}")


if __name__ == "__main__":
    unittest.main()
