"""Regression tests verifying fixes for all 7 Critical/High audit findings."""

import asyncio
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOGA_BACKEND", "toga_textual")

import toga
import toga.platform
from toga.constants import Direction
from toga_textual_backend import TextualDivider, TextualWebView, patch_toga_textual
from twittui_form import TwitTUIForm, _LazySQLiteEpisodesCache, _shows_cache_key_hash


class TestCriticalFixes(unittest.TestCase):
    """Comprehensive tests covering all 7 Critical/High fixes."""

    def setUp(self) -> None:
        os.environ["TOGA_BACKEND"] = "toga_textual"
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()
        patch_toga_textual()

    # ------------------------------------------------------------------
    # Bug 1: Hashed SQLite shows cache key, 0o600 permissions, migration
    # ------------------------------------------------------------------
    def test_1_shows_cache_hashes_credentials_enforces_0600_and_migrates_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "cache.db")
            secret_id = "my_app_id"
            secret_key = "SUPER_SECRET_API_KEY_12345"

            form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=db_path)
            resp = MagicMock(status_code=200)
            resp.json.return_value = {
                "shows": [{"label": "Security Now", "id": 1636, "active": True}]
            }

            with patch("twittui_form.load_twittui_dotenv"), \
                 patch("twittui_form.api_rate_limiter.get", return_value=resp), \
                 patch.object(form, "get_api_app_id", return_value=secret_id), \
                 patch.object(form, "get_api_app_key", return_value=secret_key):
                shows = form.fetch_shows()
                self.assertIn("Security Now", shows)

            # File permissions must be restricted to 0o600
            mode = stat.S_IMODE(os.stat(db_path).st_mode)
            self.assertEqual(mode, 0o600)

            # SQLite must NOT store plaintext app_key or app_id:app_key
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT cache_key FROM twittui_cache WHERE category = 'shows'"
                ).fetchall()
            self.assertEqual(len(rows), 1)
            stored_key = rows[0][0]
            self.assertEqual(stored_key, _shows_cache_key_hash(secret_id, secret_key))
            self.assertNotIn(secret_key, stored_key)
            self.assertNotIn(":", stored_key)

            # Seed a legacy plaintext 'app_id:app_key' row and verify automatic migration/scrubbing
            legacy_id = "legacy_id"
            legacy_key = "LEGACY_PLAINTEXT_SECRET_999"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "INSERT INTO twittui_cache (category, cache_key, data_json, created_at, updated_at) "
                    "VALUES ('shows', ?, ?, 1.0, 1.0)",
                    (f"{legacy_id}:{legacy_key}", '{"shows": ["TWiT"], "show_ids": {"TWiT": 1}, "show_active": {}, "show_date_bounds": {}}'),
                )
                conn.commit()

            form2 = TwitTUIForm("TestApp2", "org.twit.test", cache_db_path=db_path)
            expected_legacy_hash = _shows_cache_key_hash(legacy_id, legacy_key)
            self.assertIn(expected_legacy_hash, form2._shows_cache)
            with sqlite3.connect(db_path) as conn:
                all_keys = [
                    r[0]
                    for r in conn.execute("SELECT cache_key FROM twittui_cache WHERE category = 'shows'").fetchall()
                ]
            self.assertIn(expected_legacy_hash, all_keys)
            for k in all_keys:
                self.assertNotIn(legacy_key, k)
                self.assertNotIn(":", k)
            # PRAGMA secure_delete = ON must also zero out the deleted plaintext secret on disk
            with open(db_path, "rb") as raw_db:
                raw_bytes = raw_db.read()
            self.assertNotIn(legacy_key.encode("utf-8"), raw_bytes)

    # ------------------------------------------------------------------
    # Bug 2: HTML sanitizer allowlist blocks XSS bypasses & quote bugs
    # ------------------------------------------------------------------
    def test_2_sanitize_html_blocks_all_xss_bypasses_and_preserves_valid_html(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")

        # Force fallback path even if bleach/nh3 were installed
        with patch.dict(sys.modules, {"bleach": None, "nh3": None}):
            # Whitespace/tab/entity obfuscated javascript: schemes
            for dirty in (
                '<a href=" &#106;avascript:alert(1)">x</a>',
                '<a href="java\tscript:alert(1)">x</a>',
                '<a href="java\nscript:alert(1)">x</a>',
                '<a href="javascript&colon;alert(1)">x</a>',
                '<a href="javascript:alert(1)" >x</a>',
                '<a href="data:text/html,<script>alert(1)</script>">x</a>',
            ):
                clean = form.sanitize_html(dirty)
                self.assertNotIn("javascript", clean.lower(), f"Failed on {dirty!r} -> {clean!r}")
                self.assertNotIn("alert(1)", clean, f"Failed on {dirty!r} -> {clean!r}")
                self.assertNotIn('""', clean, f"Corrupted double quote in {clean!r}")
                self.assertIn('href="#"', clean)

            # Whitespace-padded closing script tags & unclosed script tags
            for dirty in (
                "<script>alert(1)</script >",
                "<SCRIPT>alert(1)</SCRIPT\t>",
                "<script>alert(1)",
                "<scr<script>ipt>alert(1)</script>",
                "<svg/onload=alert(1)>",
            ):
                clean = form.sanitize_html(dirty)
                self.assertNotIn("script", clean.lower())
                self.assertNotIn("alert(1)", clean)
                self.assertNotIn("onload", clean.lower())

            # Inline style & exotic event handlers stripped
            clean_style = form.sanitize_html('<div style="background:url(javascript:alert(1))">hi</div>')
            self.assertEqual(clean_style, "<div>hi</div>")
            clean_details = form.sanitize_html('<details open ontoggle="alert(1)">x</details>')
            self.assertEqual(clean_details, "x")

            # Valid Markdown/RSS markup preserved with proper escaping
            valid = '<h2 id="table-of-contents">TOC</h2><p><a href="https://twit.tv?a=1&b=2" target="_blank">TWiT</a></p>'
            clean_valid = form.sanitize_html(valid)
            self.assertIn('id="table-of-contents"', clean_valid)
            self.assertIn('href="https://twit.tv?a=1&amp;b=2"', clean_valid)

    # ------------------------------------------------------------------
    # Bug 3: RSS XSLT path preserves trusted <style> while sanitizing body
    # ------------------------------------------------------------------
    def test_3_rss_xslt_preserves_style_and_sanitizes_body(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")

        fake_xslt_html = (
            "<!DOCTYPE html><html><head><title>TWiT &amp; Friends</title>"
            "<style>.fallback { color: blue; }</style></head>"
            '<body><div class="container"><h1>Show</h1>'
            '<script>alert("xss")</script>'
            '<a href=" &#106;avascript:alert(1)">Bad</a>'
            '<p>Safe episode notes</p></div></body></html>'
        )

        fake_lxml = types.ModuleType("lxml")
        fake_etree = types.ModuleType("lxml.etree")
        fake_etree.XMLParser = MagicMock(return_value=object())
        fake_etree.XML = MagicMock(return_value=object())
        fake_etree.fromstring = MagicMock(return_value=object())
        fake_etree.XSLT = MagicMock(return_value=MagicMock(return_value=fake_xslt_html))
        fake_lxml.etree = fake_etree

        with patch.dict(sys.modules, {"lxml": fake_lxml, "lxml.etree": fake_etree, "bleach": None, "nh3": None}):
            out = form.render_rss_feed_to_html(b"<rss><channel><title>TWiT</title></channel></rss>")

        self.assertIn("<!DOCTYPE html>", out)
        self.assertIn("<style>", out)
        self.assertIn("--primary:", out)  # feed-style.css injected
        self.assertIn("<title>TWiT &amp; Friends</title>", out)
        self.assertIn("Safe episode notes", out)
        self.assertNotIn("<script>", out)
        self.assertNotIn("alert(", out)
        self.assertNotIn("javascript:", out.lower())

    # ------------------------------------------------------------------
    # Bug 4: _LazySQLiteEpisodesCache dict protocol (setdefault/update/keys/del)
    # ------------------------------------------------------------------
    def test_4_lazy_sqlite_cache_setdefault_update_keys_and_delitem(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        f1 = TwitTUIForm("Seed", "org.twit.test", cache_db_path=db_path)
        f1._save_to_persistent_cache("episodes", "1636", [{"id": 1}, {"id": 2}])
        f1._save_to_persistent_cache("episodes", "1635", [{"id": 10}])

        f2 = TwitTUIForm("Read", "org.twit.test", cache_db_path=db_path)
        cache = f2._episodes_cache
        self.assertIsInstance(cache, _LazySQLiteEpisodesCache)
        self.assertIsInstance(cache, dict)

        # keys() / __iter__() expose unloaded keys without hydrating them
        with patch("json.loads", side_effect=AssertionError("Should not load JSON for keys()")):
            self.assertEqual(set(cache.keys()), {"1636", "1635"})
            self.assertEqual(len(cache), 2)

        # setdefault() must hydrate existing SQLite row instead of wiping it with []
        existing = cache.setdefault("1636", [])
        self.assertEqual(existing, [{"id": 1}, {"id": 2}])
        self.assertNotIn("1636", cache._unloaded_keys)

        # setdefault() on missing key sets and returns default
        missing = cache.setdefault("9999", [{"id": 99}])
        self.assertEqual(missing, [{"id": 99}])
        self.assertEqual(cache["9999"], [{"id": 99}])

        # update() from copied lazy snapshot must clear _unloaded_keys without eagerly loading untouched shows
        f3 = TwitTUIForm("Merge", "org.twit.test", cache_db_path=db_path)
        snap = f3._episodes_cache.copy()
        snap["1636"] = [{"id": 1}, {"id": 2}, {"id": 3}]
        with patch("json.loads", side_effect=AssertionError("update() must not eagerly load untouched show 1635")):
            f3._episodes_cache.update(snap)
        self.assertNotIn("1636", f3._episodes_cache._unloaded_keys)
        self.assertIn("1635", f3._episodes_cache._unloaded_keys)
        self.assertEqual(len(f3._episodes_cache["1636"]), 3)

        # del works on unloaded keys
        del f3._episodes_cache["1635"]
        self.assertNotIn("1635", f3._episodes_cache)

    # ------------------------------------------------------------------
    # Bug 5: _run_network & callers always release modal overlays on error
    # ------------------------------------------------------------------
    def test_5_network_exceptions_never_leave_wait_or_splash_stuck(self) -> None:
        async def run_checks() -> None:
            form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
            form._impl = SimpleNamespace(loop=asyncio.get_running_loop(), native=SimpleNamespace())
            form.show_combo = SimpleNamespace(items=[], value="Security Now")
            form.show_ids = {"Security Now": 1636}
            form.api_status_label = SimpleNamespace(text="")
            form.episodes_list = MagicMock()
            form.search_input = SimpleNamespace(value="")
            form.update_episodes_display = MagicMock()
            form._cancel_hover_timer = MagicMock()

            wait_events: list[bool] = []
            splash_closed = []
            form._set_rate_limit_wait = lambda w: wait_events.append(w)
            form.close_splash_screen = lambda: splash_closed.append(True)

            # 1. load_episodes_for_selected_show: worker raises RuntimeError
            bad_worker = MagicMock()
            bad_worker.fetch_episodes.side_effect = RuntimeError("SQLite disk error")
            with patch.object(form, "_network_snapshot", return_value=bad_worker):
                cb_called = []
                form.load_episodes_for_selected_show(callback=lambda: cb_called.append(True))
                await asyncio.sleep(0.05)
            self.assertEqual(wait_events, [True, False])
            self.assertEqual(cb_called, [True])

            # 2. on_next_press: worker raises RuntimeError
            wait_events.clear()
            with patch.object(form, "_network_snapshot", return_value=bad_worker):
                form.on_next_press(None)
                await asyncio.sleep(0.05)
            self.assertEqual(wait_events, [True, False])

            # 3. _refresh_catalog: fetch_shows raises RuntimeError -> splash & wait still released
            wait_events.clear()
            splash_closed.clear()
            form.show_ids = {}
            bad_cat_worker = MagicMock()
            bad_cat_worker.fetch_shows.side_effect = RuntimeError("Unexpected crash")
            bad_cat_worker.show_ids = {}
            bad_cat_worker.show_active = {}
            bad_cat_worker.show_date_bounds = {}
            bad_cat_worker.api_status_label = SimpleNamespace(text="")
            with patch.object(form, "_network_snapshot", return_value=bad_cat_worker):
                form._refresh_catalog()
                await asyncio.sleep(0.05)
            self.assertFalse(getattr(form, "_catalog_wait_held", False))
            self.assertEqual(wait_events, [True, False])
            self.assertEqual(len(splash_closed), 1)

            # 4. _run_network on_error & on_finally callbacks fire on unhandled work/done exceptions
            errors: list[Exception] = []
            finally_hits: list[str] = []
            form._run_network(
                lambda: (_ for _ in ()).throw(ValueError("boom")),
                lambda res: None,
                on_error=errors.append,
                on_finally=lambda: finally_hits.append("work_err"),
            )
            await asyncio.sleep(0.05)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValueError)
            self.assertEqual(finally_hits, ["work_err"])

            # 5. _run_network on_finally runs even when the asyncio task is cancelled (CancelledError)
            cancelled_finally: list[bool] = []
            import threading
            gate = threading.Event()
            task = form._run_network(
                lambda: gate.wait(timeout=1.0),
                lambda res: None,
                on_finally=lambda: cancelled_finally.append(True),
            )
            self.assertIsNotNone(task)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                gate.set()
            self.assertEqual(cancelled_finally, [True])

            # 6. _run_network on_finally runs when loop.create_task fails (e.g. closed loop)
            schedule_errors: list[Exception] = []
            schedule_finally: list[bool] = []
            bad_loop = MagicMock()
            bad_loop.create_task.side_effect = RuntimeError("Event loop is closed")
            orig_impl = form._impl
            form._impl = SimpleNamespace(loop=bad_loop, native=SimpleNamespace())
            try:
                res_task = form._run_network(
                    lambda: "ok",
                    lambda res: None,
                    on_error=schedule_errors.append,
                    on_finally=lambda: schedule_finally.append(True),
                )
            finally:
                form._impl = orig_impl
            self.assertIsNone(res_task)
            self.assertEqual(len(schedule_errors), 1)
            self.assertEqual(schedule_finally, [True])

            # 7. _refresh_show_dates still invokes callback even if _set_show_selector_items raises
            form._catalog_request = 10
            form.show_ids = {"Security Now": 1636}
            form.show_active = {"Security Now": True}
            form.show_date_bounds = {"Security Now": (None, None)}
            form._show_date_cache = {}
            dates_cb: list[bool] = []
            dates_worker = MagicMock()
            dates_worker.fetch_show_date_bounds.return_value = ("2005-08-18", "2025-03-04")
            with patch.object(form, "_network_snapshot", return_value=dates_worker), \
                 patch.object(form, "_set_show_selector_items", side_effect=RuntimeError("UI update failed")):
                form._refresh_show_dates(10, ["Security Now"], callback=lambda: dates_cb.append(True))
                await asyncio.sleep(0.05)
            self.assertEqual(dates_cb, [True])

            # 8. _refresh_catalog releases splash & wait overlay even if loop.create_task fails
            wait_events.clear()
            splash_closed.clear()
            form._impl = SimpleNamespace(loop=bad_loop, native=SimpleNamespace())
            try:
                form._refresh_catalog()
            finally:
                form._impl = orig_impl
            self.assertFalse(getattr(form, "_catalog_wait_held", False))
            self.assertEqual(wait_events, [True, False])
            self.assertEqual(len(splash_closed), 1)

        asyncio.run(run_checks())

    # ------------------------------------------------------------------
    # Bug 6: TextualWebView & TextualDivider instantiate & render cleanly
    # ------------------------------------------------------------------
    def test_6_textual_webview_and_divider_toga05_contract_and_apib_markup(self) -> None:
        wv = toga.WebView()
        self.assertIsInstance(wv._impl, TextualWebView)
        self.assertEqual(wv.user_agent, "TwitTUI")
        wv.user_agent = "CustomAgent/1.0"
        self.assertEqual(wv.user_agent, "CustomAgent/1.0")

        # Brackets from twittv.apib must NOT trigger Rich MarkupError
        apib_html = "<pre>GET [/shows{?page,range}] [/?{filter%5Blabel%5D}] [/unmatched]</pre>"
        wv.set_content("file://twittv.apib", apib_html)
        rendered = wv._impl.native_static.render()
        self.assertIn("[/shows{?page,range}]", str(rendered))
        self.assertIn("[/unmatched]", str(rendered))

        # set_on_webview_load, bracketed URLs, and VerticalScroll wrapping satisfy Toga 0.5
        load_hits = []
        wv._impl.set_on_webview_load(load_hits.append)
        wv.on_webview_load = lambda widget: load_hits.append(widget)
        wv.url = "https://twit.tv/api/v1.0/episodes?filter[shows]=1636"
        self.assertIn("filter[shows]=1636", str(wv._impl.native_static.render()))
        self.assertGreaterEqual(len(load_hits), 1)

        from textual.containers import VerticalScroll
        self.assertIsInstance(wv._impl.native, VerticalScroll)

        # Divider supports both horizontal and vertical directions and dynamic switching without AttributeError
        div_h = toga.Divider(direction=Direction.HORIZONTAL)
        self.assertIsInstance(div_h._impl, TextualDivider)
        self.assertEqual(div_h.direction, Direction.HORIZONTAL)
        self.assertEqual(div_h._impl.native.orientation, "horizontal")
        div_h.direction = Direction.VERTICAL
        self.assertEqual(div_h.direction, Direction.VERTICAL)
        self.assertEqual(div_h._impl.native.orientation, "vertical")

        div_v = toga.Divider(direction=Direction.VERTICAL)
        self.assertEqual(div_v.direction, Direction.VERTICAL)
        self.assertEqual(div_v._impl.native.orientation, "vertical")

        # Async Toga 0.5.7 WebView APIs (load_url, cookies, evaluate_javascript) and live TUI doc viewer
        async def check_async_and_live_tui() -> None:
            from http.cookiejar import CookieJar
            await wv.load_url("https://twit.tv")
            self.assertEqual(wv.url, "https://twit.tv")
            cookies = await wv.cookies
            self.assertIsInstance(cookies, CookieJar)
            js_res = await wv.evaluate_javascript("1 + 1")
            self.assertIsNone(js_res)

            # Live Textual run_test() rendering real twittv.apib via show_document_viewer
            form = TwitTUIForm("TestDocTUI", "org.twit.test.doc", cache_db_path=":memory:")
            with patch.object(form, "_refresh_catalog"):
                form.startup()
            tapp = form._impl.native
            async with tapp.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                form.show_document_viewer("twittv.apib", "TWiT API Blueprint")
                await pilot.pause()
                self.assertGreaterEqual(len(tapp.screen_stack), 2)
                scr = tapp.screen
                vs_widgets = list(scr.query(VerticalScroll))
                self.assertEqual(len(vs_widgets), 1)
                self.assertGreater(vs_widgets[0].max_scroll_y, 0)
                self.assertIs(scr.focused, vs_widgets[0])
                await pilot.press("pagedown")
                await pilot.pause()
                self.assertGreater(vs_widgets[0].scroll_y, 0)
                # Ensure pressing Escape closes the document viewer screen cleanly
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(check_async_and_live_tui())

    # ------------------------------------------------------------------
    # Bug 7: Thread-safe dialogs, UI-thread snapshotting & download guard
    # ------------------------------------------------------------------
    def test_7_offthread_dialogs_use_call_soon_threadsafe_and_concurrent_downloads_blocked(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")

        # 7a. on_show_club_url_press captures URL on UI thread and passes it to worker
        with patch.object(form, "get_full_club_twit_url", return_value="https://twit.memberfulcontent.com/rss/9041?auth=tok") as mock_get_url, \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            form.on_show_club_url_press()
            mock_get_url.assert_called_once()
            mock_thread_cls.assert_called_once_with(
                target=form.open_club_twit_url,
                args=("https://twit.memberfulcontent.com/rss/9041?auth=tok",),
                daemon=True,
            )

        # 7b. Off-thread error dialog marshals via loop.call_soon_threadsafe
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        form._impl = SimpleNamespace(loop=mock_loop, native=SimpleNamespace())
        mock_win = MagicMock()
        form._main_window = mock_win

        def run_from_bg() -> None:
            form._show_dialog_threadsafe("error", "Test Error", "Something failed")

        t = threading.Thread(target=run_from_bg)
        t.start()
        t.join(timeout=2.0)
        mock_loop.call_soon_threadsafe.assert_called_once()
        # Execute scheduled UI callback and verify error_dialog invoked
        scheduled_fn = mock_loop.call_soon_threadsafe.call_args[0][0]
        scheduled_fn()
        mock_win.error_dialog.assert_called_once_with("Test Error", "Something failed")

        # 7c. Concurrent on_download_press is blocked while a download is active
        form._is_downloading = True
        form.episodes_list = SimpleNamespace(selection=[SimpleNamespace(title="Ep 1", episode="1")])
        with patch.object(form, "_show_dialog_threadsafe") as mock_dlg, \
             patch("threading.Thread") as mock_thread_cls:
            asyncio.run(form.on_download_press())
            mock_dlg.assert_called_once()
            self.assertEqual(mock_dlg.call_args[0][0], "info")
            mock_thread_cls.assert_not_called()

        # 7d. download_episodes_batch lock prevents direct concurrent overlapping invocations
        form._is_downloading = False
        started = threading.Event()
        release = threading.Event()
        calls = []

        def slow_download(url, dest_path, block_size, progress_callback=None, expected_size=None):
            calls.append(url)
            started.set()
            release.wait(timeout=2.0)
            return True

        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch.object(form, "download_episode_file", side_effect=slow_download), \
             patch.object(form, "show_download_complete_dialog"):
            target = SimpleNamespace(
                title="Ep 1",
                episode="1",
                selected_media_url="https://cdn.twit.tv/ep1.mp4",
                episode_data={"title": "Ep 1", "number": "1"},
            )
            snap = {
                "base_dest_dir": tmp_dir,
                "block_size": 8192,
                "show_folders": False,
                "audio_only": False,
                "worker": form._network_snapshot(),
            }
            t1 = threading.Thread(target=form.download_episodes_batch, args=([target],), kwargs={"download_snapshot": snap})
            t1.start()
            self.assertTrue(started.wait(timeout=2.0))
            # Second concurrent call must return immediately without downloading
            form.download_episodes_batch([target], download_snapshot=snap)
            release.set()
            t1.join(timeout=2.0)
            self.assertEqual(calls, ["https://cdn.twit.tv/ep1.mp4"])

        # 7e. Off-thread dialog/progress never fall through to direct native mutation if loop fails
        failing_loop = MagicMock()
        failing_loop.is_running.return_value = True
        failing_loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
        form._impl = SimpleNamespace(loop=failing_loop, native=SimpleNamespace())
        mock_win_fail = MagicMock()
        form._main_window = mock_win_fail
        mock_bar = MagicMock()
        form.progress_bar = mock_bar

        def bg_fail_calls() -> None:
            form._show_dialog_threadsafe("error", "Closed Loop", "Should not touch UI off-thread")
            form.show_download_complete_dialog("/tmp", ["ep1.mp4"])
            form.update_progress(50.0, 100.0)

        t_fail = threading.Thread(target=bg_fail_calls)
        t_fail.start()
        t_fail.join(timeout=2.0)
        mock_win_fail.error_dialog.assert_not_called()
        mock_win_fail.info_dialog.assert_not_called()
        self.assertEqual(failing_loop.call_soon_threadsafe.call_count, 3)

        # 7f. Re-entrant on_download_press while first call is awaiting resolution prompt is blocked
        form._is_downloading = False
        form._download_starting = False
        form.episodes_list = SimpleNamespace(selection=[SimpleNamespace(title="Ep 1", episode="1")])

        async def test_concurrent_on_download_press_during_await() -> None:
            entered = asyncio.Event()
            release = asyncio.Event()
            worker_stub = MagicMock()
            worker_stub.get_available_resolutions.return_value = [
                {"id": "video_hd", "label": "HD", "url": "https://cdn.twit.tv/ep1_hd.mp4"},
                {"id": "video_sd", "label": "SD", "url": "https://cdn.twit.tv/ep1_sd.mp4"},
            ]

            async def slow_prompt(*args, **kwargs):
                entered.set()
                await release.wait()
                return {"id": "video_hd", "url": "https://cdn.twit.tv/ep1_hd.mp4"}

            with patch.object(form, "_network_snapshot", return_value=worker_stub), \
                 patch.object(form, "prompt_resolution_choice", side_effect=slow_prompt), \
                 patch.object(form, "_show_dialog_threadsafe") as mock_dlg, \
                 patch.object(form, "download_episodes_batch") as mock_batch:
                t_first = asyncio.create_task(form.on_download_press())
                await asyncio.wait_for(entered.wait(), timeout=2.0)
                # Second press while first is awaiting prompt must be blocked cleanly
                await form.on_download_press()
                mock_dlg.assert_called_once()
                self.assertEqual(mock_dlg.call_args[0][0], "info")
                release.set()
                await t_first
                # Wait briefly for single background download thread to invoke mock_batch
                for _ in range(50):
                    if mock_batch.call_count >= 1:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(mock_batch.call_count, 1)
                self.assertFalse(form._download_starting)

        asyncio.run(test_concurrent_on_download_press_during_await())

        # 7g. on_open_destination_press captures destination on UI thread before spawning worker
        with patch.object(form, "get_destination_folder", return_value="/tmp/twit_dl") as mock_get_dest, \
             patch("threading.Thread") as mock_thread_cls:
            mock_thread_cls.return_value = MagicMock()
            form.on_open_destination_press()
            mock_get_dest.assert_called_once()
            mock_thread_cls.assert_called_once_with(
                target=form.open_destination_folder,
                args=("/tmp/twit_dl",),
                daemon=True,
            )


if __name__ == "__main__":
    unittest.main()
