"""Regression tests verifying fixes for Medium-severity audit findings (#8, #10-#20)."""

import asyncio
import os
import subprocess
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOGA_BACKEND", "toga_textual")

import toga
import toga.platform
from tiered_search import (
    compute_match_score,
    extract_searchable_text,
    find_match_context,
    rank_and_filter_episodes,
)
from toga_textual_backend import (
    OpenFileDialog,
    SaveFileDialog,
    TextualActivityIndicator,
    TextualDialogScreen,
    TextualProgressBarImpl,
    TextualTable,
    patch_toga_textual,
)
from twittui_form import TwitTUIForm, launch_stream_safe, write_restricted_file


class TestMediumFixes(unittest.TestCase):
    """Comprehensive regression suite covering Medium bugs #8 and #10-#20."""

    def setUp(self) -> None:
        os.environ["TOGA_BACKEND"] = "toga_textual"
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()
        patch_toga_textual()

    # ------------------------------------------------------------------
    # Bug 8: GTK auto-scroll uses native_textview & HTML-cleaned offsets
    # ------------------------------------------------------------------
    def test_8_gtk_autoscroll_targets_native_textview_with_cleaned_html_offset(self) -> None:
        ep_data = {
            "number": "1000",
            "title": "Security Now 1000",
            "date": "2025-01-01",
            "show_name": "Security Now",
            "description": "<p>Discussing <b>SpinRite</b> and modern cryptography.</p>",
        }
        ctx = find_match_context(ep_data, "SpinRite")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.field_name, "Description / Show Notes")
        cleaned = TwitTUIForm.clean_html_text(ep_data["description"])
        self.assertEqual(cleaned[ctx.char_offset : ctx.char_offset + len("SpinRite")], "SpinRite")

        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        form.search_input = SimpleNamespace(value="SpinRite")
        fake_gtk_app = SimpleNamespace(__class__=SimpleNamespace(__module__="toga_gtk.app"))
        form._impl = SimpleNamespace(native=fake_gtk_app)

        mock_buf = MagicMock()
        mock_buf.get_char_count.return_value = len(cleaned)
        mock_iter = object()
        mock_buf.get_iter_at_offset.return_value = mock_iter
        mock_textview = MagicMock()
        mock_textview.get_buffer.return_value = mock_buf
        # Simulate toga-gtk 0.5.7 where native is Gtk.ScrolledWindow (no get_buffer)
        mock_scrolled = SimpleNamespace()  # intentionally lacks get_buffer

        real_multiline = toga.MultilineTextInput

        def fake_multiline(*args, **kwargs):
            widget = real_multiline(*args, **kwargs)
            # Keep real widget._impl so toga.Box.add() succeeds; its .native lacks get_buffer
            # (mirroring Gtk.ScrolledWindow in toga-gtk 0.5.7), while .native_textview holds Gtk.TextView.
            widget._impl.native_textview = mock_textview
            return widget

        target = SimpleNamespace(episode_data=ep_data, title="Security Now 1000", episode="1000", show="Security Now")
        scheduled_idle = []

        fake_glib = SimpleNamespace(idle_add=lambda fn: scheduled_idle.append(fn))
        fake_gi = types.ModuleType("gi")
        fake_gi_repo = types.ModuleType("gi.repository")
        fake_gi_repo.GLib = fake_glib
        fake_gi.repository = fake_gi_repo

        with patch.dict(os.environ, {"TOGA_BACKEND": "toga_gtk"}), \
             patch("twittui_form.toga.Window") as mock_win_cls, \
             patch("twittui_form.toga.MultilineTextInput", side_effect=fake_multiline), \
             patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": fake_gi_repo}):
            mock_win_cls.return_value = MagicMock()
            form.show_episode_metadata_dialog(target)

        self.assertEqual(len(scheduled_idle), 1)
        scheduled_idle[0]()
        mock_buf.get_iter_at_offset.assert_called_once_with(ctx.char_offset)
        mock_buf.place_cursor.assert_called_once_with(mock_iter)
        mock_textview.scroll_to_iter.assert_called_once_with(mock_iter, 0.1, True, 0.0, 0.2)

    def test_8b_gtk_autoscroll_offset_parity_for_show_notes_and_plain_newlines(self) -> None:
        """Description precedence (show_notes/notes) and plain-text newline collapsing must match between search and UI."""
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")

        # 1. show_notes takes precedence over teaser in both tiered_search and extract_episode_metadata_fields
        ep_notes = {
            "number": "1001",
            "title": "Security Now 1001",
            "show_notes": "<p>Intro block</p><p>Deep dive into <b>WireGuard</b> keys.</p>",
            "teaser": "Short teaser mentioning WireGuard at a totally different offset.",
        }
        ctx_notes = find_match_context(ep_notes, "WireGuard")
        self.assertIsNotNone(ctx_notes)
        self.assertEqual(ctx_notes.field_name, "Description / Show Notes")
        meta_notes = form.extract_episode_metadata_fields(ep_notes)
        self.assertEqual(
            meta_notes["description"][ctx_notes.char_offset : ctx_notes.char_offset + len("WireGuard")],
            "WireGuard",
        )

        # 2. Plain text with 3+ consecutive newlines (no '<' or '&') collapses identically in both layers
        ep_plain = {
            "number": "1002",
            "title": "Security Now 1002",
            "description": "Intro paragraph.\n\n\n\n\nSecond paragraph discussing Passkeys in detail.",
        }
        ctx_plain = find_match_context(ep_plain, "Passkeys")
        self.assertIsNotNone(ctx_plain)
        self.assertEqual(ctx_plain.field_name, "Description / Show Notes")
        meta_plain = form.extract_episode_metadata_fields(ep_plain)
        self.assertEqual(
            meta_plain["description"][ctx_plain.char_offset : ctx_plain.char_offset + len("Passkeys")],
            "Passkeys",
        )

    def test_8c_gtk_autoscroll_falls_back_to_scroll_to_mark_and_skips_stale_window(self) -> None:
        """If GTK scroll_to_iter returns False before line validation, fall back to scroll_to_mark; skip if closed."""
        ep_data = {
            "number": "1003",
            "title": "Security Now 1003",
            "description": "<p>Header</p><p>Needle <b>Quantum</b> appears here.</p>",
        }
        ctx = find_match_context(ep_data, "Quantum")
        self.assertIsNotNone(ctx)
        cleaned = TwitTUIForm.clean_html_text(ep_data["description"])

        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        form.search_input = SimpleNamespace(value="Quantum")
        fake_gtk_app = SimpleNamespace(__class__=SimpleNamespace(__module__="toga_gtk.app"))
        form._impl = SimpleNamespace(native=fake_gtk_app)

        mock_buf = MagicMock()
        mock_buf.get_char_count.return_value = len(cleaned)
        mock_iter = object()
        mock_mark = object()
        mock_buf.get_iter_at_offset.return_value = mock_iter
        mock_buf.get_insert.return_value = mock_mark
        mock_textview = MagicMock()
        mock_textview.get_buffer.return_value = mock_buf
        mock_textview.scroll_to_iter.return_value = False

        real_multiline = toga.MultilineTextInput

        def fake_multiline(*args, **kwargs):
            widget = real_multiline(*args, **kwargs)
            widget._impl.native_textview = mock_textview
            return widget

        target = SimpleNamespace(episode_data=ep_data, title="Security Now 1003", episode="1003", show="Security Now")
        scheduled_idle = []
        fake_glib = SimpleNamespace(idle_add=lambda fn: scheduled_idle.append(fn))
        fake_gi = types.ModuleType("gi")
        fake_gi_repo = types.ModuleType("gi.repository")
        fake_gi_repo.GLib = fake_glib
        fake_gi.repository = fake_gi_repo

        with patch.dict(os.environ, {"TOGA_BACKEND": "toga_gtk"}), \
             patch("twittui_form.toga.Window") as mock_win_cls, \
             patch("twittui_form.toga.MultilineTextInput", side_effect=fake_multiline), \
             patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": fake_gi_repo}):
            mock_win_cls.return_value = MagicMock()
            form.show_episode_metadata_dialog(target)

        self.assertEqual(len(scheduled_idle), 1)
        scheduled_idle[0]()
        mock_textview.scroll_to_iter.assert_called_once_with(mock_iter, 0.1, True, 0.0, 0.2)
        mock_textview.scroll_to_mark.assert_called_once_with(mock_mark, 0.1, True, 0.0, 0.2)

        # If metadata window was closed before idle ran, callback is a safe no-op
        mock_textview.reset_mock()
        mock_buf.reset_mock()
        form._metadata_window = None
        scheduled_idle[0]()
        mock_buf.get_iter_at_offset.assert_not_called()
        mock_textview.scroll_to_iter.assert_not_called()

    # ------------------------------------------------------------------
    # Bug 10: Tiered search field parity, multi-word gating, thresholds
    # ------------------------------------------------------------------
    def test_10_tiered_search_includes_hosts_topics_teaser_and_blocks_partial_false_positives(self) -> None:
        ep = {
            "title": "Episode 100",
            "hosts": [{"label": "Leo Laporte"}, {"name": "Steve Gibson"}],
            "topics": [{"name": "Quantum Computing"}],
            "teaser": "Deep dive into Cryptography fundamentals.",
        }
        # Hosts, topics, and teaser must all be found by rank_and_filter_episodes()
        text = extract_searchable_text(ep)
        self.assertIn("Leo Laporte", text)
        self.assertIn("Quantum Computing", text)
        self.assertIn("Cryptography", text)
        self.assertEqual(len(rank_and_filter_episodes([ep], "Leo Laporte")), 1)
        self.assertEqual(len(rank_and_filter_episodes([ep], "Quantum Computing")), 1)
        self.assertEqual(len(rank_and_filter_episodes([ep], "Cryptography")), 1)

        # Partial multi-word false positive must return None (NOT Exact Match 100.0)
        self.assertIsNone(find_match_context(ep, "Episode ZZZZZNOTFOUND"))

        # Multi-word cross-field match still succeeds when ALL words match
        cross = find_match_context(ep, "Leo Cryptography")
        self.assertIsNotNone(cross)

        # Short-word (< 4 chars) threshold consistency between compute_match_score and find_match_context
        # 'cat' vs 'card' has fuzzy_ratio=71.4% (>= 68% default, < 80% short-word threshold)
        short_ep = {"title": "Card Game", "description": "Playing deck games."}
        self.assertEqual(compute_match_score("cat", extract_searchable_text(short_ep)), 0.0)
        self.assertIsNone(find_match_context(short_ep, "cat"))

        # Strong fuzzy match (87.5%) must outrank a weaker phonetic-only hit (80.0)
        # 'aecurity' (DM=AKRT) has 87.5% fuzzy ratio to 'Security' (DM=SKRT),
        # while 'akrt' (DM=AKRT) matches phonetically (80.0) with lower fuzzy similarity.
        rank_ep = {
            "title": "Security Architecture",
            "description": "Unrelated acronym akrt in notes.",
        }
        ctx = find_match_context(rank_ep, "aecurity")
        self.assertIsNotNone(ctx)
        self.assertIn("Fuzzy Match", ctx.match_tier)
        self.assertEqual(ctx.matched_token.lower(), "security")

    def test_10b_tiered_search_multiword_signal_secondary_teaser_and_threshold_parity(self) -> None:
        """Multi-word hover context highlights non-exact tokens; secondary teaser stays in sync; thresholds match."""
        # 1. Multi-word mixed exact + phonetic/fuzzy highlights the high-signal non-exact token
        ep_mixed = {
            "title": "Security Now 520",
            "description": "Fr. Robert Ballecer joins Leo Laporte to discuss routers.",
        }
        score = compute_match_score("Security ballacer", extract_searchable_text(ep_mixed))
        ctx_mixed = find_match_context(ep_mixed, "Security ballacer")
        self.assertIsNotNone(ctx_mixed)
        self.assertEqual(ctx_mixed.field_name, "Description / Show Notes")
        self.assertIn("Phonetic Match", ctx_mixed.match_tier)
        self.assertEqual(ctx_mixed.matched_token, "Ballecer")
        self.assertLess(ctx_mixed.score, 100.0)
        self.assertAlmostEqual(ctx_mixed.score, score, places=3)

        # 2. Secondary teaser alongside description is found by BOTH rank_and_filter_episodes AND find_match_context
        ep_dual = {
            "title": "Linux Weekly 10",
            "description": "Main show notes covering kernel updates.",
            "teaser": "Bonus segment about WireGuard VPN tunnels.",
        }
        self.assertEqual(len(rank_and_filter_episodes([ep_dual], "WireGuard")), 1)
        ctx_dual = find_match_context(ep_dual, "WireGuard")
        self.assertIsNotNone(ctx_dual)
        self.assertEqual(ctx_dual.field_name, "Summary / Teaser")
        self.assertEqual(ctx_dual.matched_token, "WireGuard")

        # 3. Phonetic fallback below 80.0 and custom min_word_threshold > 80.0 agree in both functions
        # 'phillip' vs 'filip': fuzzy_ratio ~76.9% (< 80.0), primary Double Metaphone = 'FLP' (score 80.0)
        ep_phon = {"title": "Guest Filip", "description": "Talking with Filip today."}
        text_phon = extract_searchable_text(ep_phon)
        self.assertGreaterEqual(compute_match_score("phillip", text_phon, min_word_threshold=78.0), 80.0)
        self.assertIsNotNone(find_match_context(ep_phon, "phillip", min_word_threshold=78.0))
        # Short word (< 4 chars) respects stricter min_word_threshold=90.0 in both functions
        ep_short = {"title": "Jon speaks", "description": "Talking with Jon."}
        self.assertEqual(compute_match_score("john", extract_searchable_text(ep_short), min_word_threshold=90.0), 0.0)
        self.assertIsNone(find_match_context(ep_short, "john", min_word_threshold=90.0))
        self.assertEqual(compute_match_score("jon", extract_searchable_text({"title": "John"}), min_word_threshold=90.0), 0.0)
        self.assertIsNone(find_match_context({"title": "John"}, "jon", min_word_threshold=90.0))

    # ------------------------------------------------------------------
    # Bug 11: get_available_resolutions reads real _show_rss_cache keys
    # ------------------------------------------------------------------
    def test_11_get_available_resolutions_finds_cached_show_rss_entries(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        form._show_rss_cache["security now_video"] = [
            {
                "title": "Security Now 1050",
                "number": "1050",
                "enclosure_url": "https://cdn.twit.tv/video/sn/sn1050/sn1050_h264m_1280x720_1872.mp4",
                "enclosure_length": "900000000",
                "feed_file": "sn_video_hd.xml",
            }
        ]
        form._show_rss_cache["security now_audio"] = [
            {
                "title": "Security Now 1050",
                "number": "1050",
                "enclosure_url": "https://cdn.twit.tv/audio/sn/sn1050/sn1050.mp3",
                "enclosure_length": "55000000",
                "feed_file": "sn.xml",
            }
        ]
        target = SimpleNamespace(
            title="Security Now 1050",
            episode="1050",
            show="Security Now",
            episode_data={"title": "Security Now 1050", "number": "1050"},
        )
        with patch.object(form, "fetch_club_twit_rss_items", return_value=[]):
            res_video = form.get_available_resolutions(target, show_name="Security Now", audio_only=False)
            res_audio = form.get_available_resolutions(target, show_name="Security Now", audio_only=True)

        self.assertTrue(any(r["url"].endswith("sn1050_h264m_1280x720_1872.mp4") for r in res_video))
        self.assertTrue(any(r["url"].endswith("sn1050.mp3") for r in res_audio))

    def test_11b_get_available_resolutions_matches_plain_dict_and_all_shows_context(self) -> None:
        """Plain episode dicts with integer numbers and 'All TWiT.tv Shows' selection still resolve cached RSS feeds."""
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        form.show_combo = SimpleNamespace(value="All TWiT.tv Shows")
        form._show_names_by_display = {"Security Now (2005-2026)": "Security Now"}
        form._show_rss_cache["security now_video"] = [
            {
                "title": "Security Now 1051",
                "number": "1051",
                "enclosure_url": "https://cdn.twit.tv/video/sn/sn1051/sn1051_h264m_1280x720_1872.mp4",
                "enclosure_length": "850000000",
                "feed_file": "sn_video_hd.xml",
            }
        ]
        form._show_rss_cache["security now_audio"] = [
            {
                "title": "Security Now 1051",
                "number": "1051",
                "enclosure_url": "https://cdn.twit.tv/audio/sn/sn1051/sn1051.mp3",
                "enclosure_length": "52000000",
                "feed_file": "sn.xml",
            }
        ]
        # Plain dict with integer episodeNumber and no explicit show_name argument
        ep_dict = {
            "title": "Security Now 1051",
            "episodeNumber": 1051,
            "show_name": "Security Now",
        }
        with patch.object(form, "fetch_club_twit_rss_items", return_value=[]):
            res_video = form.get_available_resolutions(ep_dict, audio_only=False)
            res_audio = form.get_available_resolutions(ep_dict, show_name="Security Now (2005-2026)", audio_only=True)

        self.assertEqual([r["id"] for r in res_video], ["video_hd", "rss_audio"])
        self.assertTrue(res_video[0]["url"].endswith("sn1051_h264m_1280x720_1872.mp4"))
        self.assertEqual([r["id"] for r in res_audio], ["rss_audio"])
        self.assertTrue(res_audio[0]["url"].endswith("sn1051.mp3"))

    # ------------------------------------------------------------------
    # Bug 12: No duplicate page fetches & single deferred SQLite persist
    # ------------------------------------------------------------------
    def test_12_fetch_episodes_avoids_double_page_fetch_and_defers_sqlite_writes(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        form.show_combo = SimpleNamespace(value="Security Now")
        form.show_ids = {"Security Now": 1636}
        # Pre-seed partial cache (only oldest 2 items), then trigger reconciliation with explicit ascending sort
        form._episodes_cache["1636"] = [
            {"id": 1, "label": "SN 1", "episodeNumber": 1},
            {"id": 2, "label": "SN 2", "episodeNumber": 2},
        ]

        requested_pages: list[int] = []

        def fake_get(url, headers=None, timeout=None):
            import re
            m = re.search(r"page=(\d+)", url)
            p = int(m.group(1)) if m else 1
            requested_pages.append(p)
            resp = MagicMock(status_code=200)
            if p == 1:
                resp.json.return_value = {
                    "count": 110,
                    "episodes": [{"id": i, "label": f"SN {i}", "episodeNumber": i} for i in range(110, 60, -1)],
                    "_links": {"next": {"href": "?page=2"}},
                }
            elif p == 2:
                resp.json.return_value = {
                    "count": 110,
                    "episodes": [{"id": i, "label": f"SN {i}", "episodeNumber": i} for i in range(60, 10, -1)],
                    "_links": {"next": {"href": "?page=3"}},
                }
            else:
                resp.json.return_value = {
                    "count": 110,
                    "episodes": [{"id": i, "label": f"SN {i}", "episodeNumber": i} for i in range(10, 0, -1)],
                    "_links": {},
                }
            return resp

        with patch("twittui_form.load_twittui_dotenv"), \
             patch("twittui_form.api_rate_limiter.get", side_effect=fake_get), \
             patch.object(form, "get_api_app_id", return_value="id"), \
             patch.object(form, "get_api_app_key", return_value="key"):
            eps = form.fetch_episodes(1636, page=1, sort="airingDate")

        # Every page 1, 2, 3 must be requested AT MOST ONCE (no second loop re-fetching page 2!)
        self.assertEqual(requested_pages, [1, 2, 3])
        self.assertEqual(len({e["id"] for e in eps}), 110)

        # Multi-page load_episodes_for_selected_show must persist once instead of once per page
        form2 = TwitTUIForm("TestApp2", "org.twit.test", cache_db_path=":memory:")
        form2.show_combo = SimpleNamespace(value="Security Now")
        form2.show_ids = {"Security Now": 1636}
        form2.search_input = SimpleNamespace(value="")
        form2.update_episodes_display = MagicMock()
        form2._cancel_hover_timer = MagicMock()
        form2._set_rate_limit_wait = MagicMock()

        save_calls = []
        orig_save = TwitTUIForm._save_to_persistent_cache

        def track_save(self_obj, category, key, data):
            if category == "episodes":
                save_calls.append((key, len(data)))
            return orig_save(self_obj, category, key, data)

        with patch("twittui_form.load_twittui_dotenv"), \
             patch("twittui_form.api_rate_limiter.get", side_effect=fake_get), \
             patch.object(TwitTUIForm, "_save_to_persistent_cache", track_save), \
             patch.object(form2, "get_api_app_id", return_value="id"), \
             patch.object(form2, "get_api_app_key", return_value="key"), \
             patch.object(form2, "_run_network", side_effect=lambda work, done: done(work())):
            form2.load_episodes_for_selected_show()

        self.assertEqual(len(save_calls), 1)
        self.assertEqual(save_calls[0], ("1636", 110))

    def test_12b_canonical_sort_gap_preservation_and_nonblocking_backfill(self) -> None:
        """Uncached fetches use canonical -airingDate, page-1 hits never drop gap items, and backfill is non-blocking."""
        from twittui_form import api_rate_limiter

        # 1. Uncached fetch uses canonical newest-first '-airingDate' even when UI is set to Ascending Title sort
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        form.show_combo = SimpleNamespace(value="Security Now")
        form.show_ids = {"Security Now": 1636}
        form.title_radio = SimpleNamespace(text="☑ Episode Title")
        form.sort_order_button = SimpleNamespace(text="▲ Ascending")
        requested_urls: list[str] = []

        def fake_get_canonical(url, headers=None, timeout=None):
            requested_urls.append(url)
            resp = MagicMock(status_code=200)
            resp.json.return_value = {
                "count": 2,
                "episodes": [
                    {"id": 2, "label": "SN 2", "episodeNumber": 2},
                    {"id": 1, "label": "SN 1", "episodeNumber": 1},
                ],
                "_links": {},
            }
            return resp

        with patch("twittui_form.load_twittui_dotenv"), \
             patch("twittui_form.api_rate_limiter.get", side_effect=fake_get_canonical), \
             patch.object(form, "get_api_app_id", return_value="id"), \
             patch.object(form, "get_api_app_key", return_value="key"):
            form.fetch_episodes(1636, page=1)
        self.assertEqual(len(requested_urls), 1)
        self.assertIn("sort=-airingDate", requested_urls[0])

        # 2. Partial cache where episode at index 0 of page 1 already exists does NOT discard remaining 49 page-1 items
        form_gap = TwitTUIForm("TestGap", "org.twit.test", cache_db_path=":memory:")
        form_gap.show_combo = SimpleNamespace(value="Security Now")
        form_gap.show_ids = {"Security Now": 1636}
        form_gap._episodes_cache["1636"] = [{"id": 50, "label": "SN 50", "episodeNumber": 50}]

        def fake_get_gap(url, headers=None, timeout=None):
            resp = MagicMock(status_code=200)
            resp.json.return_value = {
                "count": 50,
                "episodes": [{"id": i, "label": f"SN {i}", "episodeNumber": i} for i in range(50, 0, -1)],
                "_links": {},
            }
            return resp

        with patch("twittui_form.load_twittui_dotenv"), \
             patch("twittui_form.api_rate_limiter.get", side_effect=fake_get_gap), \
             patch.object(form_gap, "get_api_app_id", return_value="id"), \
             patch.object(form_gap, "get_api_app_key", return_value="key"):
            reconciled = form_gap.fetch_episodes(1636, page=1)
        self.assertEqual(len(reconciled), 50)
        self.assertEqual({e["id"] for e in reconciled}, set(range(1, 51)))
        self.assertTrue(form_gap._episodes_all_loaded)

        # 3. Multi-page load_episodes_for_selected_show unlocks modal wait & fires callback right after page 1,
        #    and backfills pages 2+ without firing rate-limiter modal wait notifications.
        form_nb = TwitTUIForm("TestNB", "org.twit.test", cache_db_path=":memory:")
        form_nb.show_combo = SimpleNamespace(value="Security Now")
        form_nb.show_ids = {"Security Now": 1636}
        form_nb.search_input = SimpleNamespace(value="")
        form_nb.update_episodes_display = MagicMock()
        form_nb._cancel_hover_timer = MagicMock()
        wait_events: list[bool] = []
        form_nb._set_rate_limit_wait = lambda waiting: wait_events.append(bool(waiting))
        cb_fired: list[bool] = []
        queued_jobs: list[tuple] = []

        def fake_http_get(url, headers=None, timeout=None):
            import re
            m = re.search(r"page=(\d+)", url)
            p = int(m.group(1)) if m else 1
            resp = MagicMock(status_code=200)
            if p == 1:
                resp.json.return_value = {
                    "count": 75,
                    "episodes": [{"id": i, "label": f"SN {i}", "episodeNumber": i} for i in range(75, 25, -1)],
                    "_links": {"next": {"href": "?page=2"}},
                }
            else:
                resp.json.return_value = {
                    "count": 75,
                    "episodes": [{"id": i, "label": f"SN {i}", "episodeNumber": i} for i in range(25, 0, -1)],
                    "_links": {},
                }
            return resp

        orig_wait_cb = api_rate_limiter.wait_callback
        limiter_wait_calls: list[bool] = []
        api_rate_limiter.wait_callback = lambda w: limiter_wait_calls.append(bool(w))
        try:
            with patch("twittui_form.load_twittui_dotenv"), \
                 patch("twittui_form.requests.get", side_effect=fake_http_get), \
                 patch.object(api_rate_limiter, "_sleep"), \
                 patch.object(form_nb, "get_api_app_id", return_value="id"), \
                 patch.object(form_nb, "get_api_app_key", return_value="key"), \
                 patch.object(form_nb, "_run_network", side_effect=lambda work, done: queued_jobs.append((work, done))):
                api_rate_limiter.timestamps.clear()
                form_nb.load_episodes_for_selected_show(callback=lambda: cb_fired.append(True))

                # Phase 1 scheduled; modal wait open
                self.assertEqual(len(queued_jobs), 1)
                self.assertEqual(wait_events, [True])

                # Complete Phase 1 (Page 1 only)
                p1_result = queued_jobs[0][0]()
                queued_jobs[0][1](p1_result)

                # UI immediately unlocked with first 50 episodes & callback invoked BEFORE Phase 2 runs!
                self.assertEqual(wait_events, [True, False])
                self.assertEqual(cb_fired, [True])
                self.assertEqual(len(form_nb.current_episodes), 50)
                self.assertTrue(form_nb._episodes_backfilling)
                self.assertEqual(len(queued_jobs), 2)

                # Phase 2 runs without opening any modal wait dialog or firing rate-limiter wait_callback
                limiter_wait_calls.clear()
                p2_result = queued_jobs[1][0]()
                queued_jobs[1][1](p2_result)

                self.assertEqual(wait_events, [True, False])
                self.assertEqual(limiter_wait_calls, [])
                self.assertFalse(form_nb._episodes_backfilling)
                self.assertTrue(form_nb._episodes_all_loaded)
                self.assertEqual(len(form_nb.current_episodes), 75)
        finally:
            api_rate_limiter.wait_callback = orig_wait_cb

    # ------------------------------------------------------------------
    # Bug 13: YouTube [brackets] glob.escape, audio ext alignment, atomic replace
    # ------------------------------------------------------------------
    def test_13_youtube_brackets_filename_and_audio_extension_without_ffmpeg(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        with tempfile.TemporaryDirectory() as tmp_dir:
            # 13a. Bracketed filename + video download succeeds via glob.escape()
            dest_video = os.path.join(tmp_dir, "Security Now [Special] 1000.mp4")

            def mock_popen_video(cmd, **kwargs):
                out_tmpl = cmd[cmd.index("-o") + 1]
                out_file = out_tmpl.replace("%(ext)s", "mp4")
                with open(out_file, "wb") as f:
                    f.write(b"\x00\x00\x00\x18ftypmp42" + (b"0" * 2048))
                proc = MagicMock()
                proc.stdout.readline.return_value = ""
                proc.poll.return_value = 0
                proc.wait.return_value = 0
                return proc

            form.is_audio_only = lambda: False
            with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"), \
                 patch("subprocess.Popen", side_effect=mock_popen_video), \
                 patch("os.replace", wraps=os.replace) as spy_replace:
                self.assertTrue(form.download_youtube_video(yt_url, dest_video))
                self.assertTrue(os.path.isfile(dest_video))
                spy_replace.assert_called_once()

            # 13b. Audio-only without ffmpeg aligns .m4a container instead of misnaming to .mp3
            dest_mp3 = os.path.join(tmp_dir, "Audio [Live] 1001.mp3")
            expected_m4a = os.path.join(tmp_dir, "Audio [Live] 1001.m4a")

            def mock_popen_audio(cmd, **kwargs):
                out_tmpl = cmd[cmd.index("-o") + 1]
                out_file = out_tmpl.replace("%(ext)s", "m4a")
                with open(out_file, "wb") as f:
                    f.write(b"\x00\x00\x00\x18ftypM4A " + (b"1" * 2048))
                proc = MagicMock()
                proc.stdout.readline.return_value = ""
                proc.poll.return_value = 0
                proc.wait.return_value = 0
                return proc

            form.is_audio_only = lambda: True
            with patch("shutil.which", side_effect=lambda x: "/usr/bin/yt-dlp" if x == "yt-dlp" else None), \
                 patch("subprocess.Popen", side_effect=mock_popen_audio):
                self.assertTrue(form.download_youtube_video(yt_url, dest_mp3))
                self.assertTrue(os.path.isfile(expected_m4a))
                self.assertFalse(os.path.exists(dest_mp3))

    def test_13b_youtube_validates_before_replace_skips_aligned_existing_and_escapes_percent(self) -> None:
        """Corrupt downloads never clobber existing files, aligned containers skip re-download, and '%' / '.part' are safe."""
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1. Corrupt HTML download must NOT overwrite an existing valid file at dest_path and must return False
            dest_existing = os.path.join(tmp_dir, "Security Now [100%] 1002.mp4")
            original_payload = b"\x00\x00\x00\x18ftypmp42" + (b"V" * 4096)
            with open(dest_existing, "wb") as f:
                f.write(original_payload)
            stale_bracket_part = dest_existing + ".part.f140.m4a"
            with open(stale_bracket_part, "wb") as f:
                f.write(b"stale")

            captured_outtmpl = []

            def mock_popen_html(cmd, **kwargs):
                out_tmpl = cmd[cmd.index("-o") + 1]
                captured_outtmpl.append(out_tmpl)
                # Simulate yt-dlp interpreting '%%' as literal '%' and writing HTML + a .part sidecar
                out_file = out_tmpl.replace("%%", "%").replace("%(ext)s", "mp4")
                with open(out_file, "wb") as f:
                    f.write(b"<!DOCTYPE html><html><body>Error page</body></html>" + (b" " * 2048))
                with open(out_file + ".part", "wb") as f:
                    f.write(b"\x00\x00\x00\x18ftypmp42" + (b"P" * 2048))
                proc = MagicMock()
                proc.stdout.readline.return_value = ""
                proc.poll.return_value = 0
                proc.wait.return_value = 0
                return proc

            form.is_audio_only = lambda: False
            # Force download attempt even though dest_existing exists (e.g. smaller than 500KB YouTube skip threshold)
            with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"), \
                 patch("subprocess.Popen", side_effect=mock_popen_html):
                self.assertFalse(form.download_youtube_video(yt_url, dest_existing))

            # Original file untouched, stale bracketed .part purged, and literal '%' escaped in outtmpl
            with open(dest_existing, "rb") as f:
                self.assertEqual(f.read(), original_payload)
            self.assertFalse(os.path.exists(stale_bracket_part))
            self.assertEqual(len(captured_outtmpl), 1)
            self.assertIn("[100%%]", captured_outtmpl[0])

            # 2. Re-downloading audio-only without ffmpeg skips an already-downloaded aligned .m4a file
            dest_mp3 = os.path.join(tmp_dir, "Audio [Live] 1003.mp3")
            existing_m4a = os.path.join(tmp_dir, "Audio [Live] 1003.m4a")
            with open(existing_m4a, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypM4A " + (b"A" * (1100 * 1024)))

            form.is_audio_only = lambda: True
            with patch("shutil.which", side_effect=lambda x: "/usr/bin/yt-dlp" if x == "yt-dlp" else None), \
                 patch("subprocess.Popen") as mock_popen_skip:
                self.assertTrue(form.download_youtube_video(yt_url, dest_mp3))
                mock_popen_skip.assert_not_called()
                self.assertEqual(form._last_downloaded_path, existing_m4a)

            # 3. Video-only without ffmpeg aligns .webm container instead of misnaming it to .mp4
            dest_mp4 = os.path.join(tmp_dir, "Video [WebM] 1004.mp4")
            expected_webm = os.path.join(tmp_dir, "Video [WebM] 1004.webm")

            def mock_popen_webm(cmd, **kwargs):
                out_tmpl = cmd[cmd.index("-o") + 1]
                out_file = out_tmpl.replace("%%", "%").replace("%(ext)s", "webm")
                with open(out_file, "wb") as f:
                    f.write(b"\x1a\x45\xdf\xa3" + (b"W" * 2048))
                proc = MagicMock()
                proc.stdout.readline.return_value = ""
                proc.poll.return_value = 0
                proc.wait.return_value = 0
                return proc

            form.is_audio_only = lambda: False
            with patch("shutil.which", side_effect=lambda x: "/usr/bin/yt-dlp" if x == "yt-dlp" else None), \
                 patch("subprocess.Popen", side_effect=mock_popen_webm):
                self.assertTrue(form.download_youtube_video(yt_url, dest_mp4))
                self.assertTrue(os.path.isfile(expected_webm))
                self.assertFalse(os.path.exists(dest_mp4))

    # ------------------------------------------------------------------
    # Bug 14: Duration 'length' not mistaken for byte size expected_size
    # ------------------------------------------------------------------
    def test_14_batch_download_ignores_duration_length_as_expected_size(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        captured_expected = []

        def fake_dl(url, dest_path, block_size, progress_callback=None, expected_size=None):
            captured_expected.append(expected_size)
            return True

        with tempfile.TemporaryDirectory() as tmp_dir:
            form.download_episode_file = fake_dl
            form.show_download_complete_dialog = MagicMock()
            target = SimpleNamespace(
                title="Long Episode",
                episode="42",
                selected_media_url="https://cdn.twit.tv/ep42.mp4",
                episode_data={"title": "Long Episode", "number": "42", "length": "3600"},
            )
            snap = {
                "base_dest_dir": tmp_dir,
                "block_size": 8192,
                "show_folders": False,
                "audio_only": False,
                "worker": form._network_snapshot(),
            }
            form.download_episodes_batch([target], download_snapshot=snap)

        self.assertEqual(captured_expected, [None])

    # ------------------------------------------------------------------
    # Bug 15: write_restricted_file never double-closes FD on write error
    # ------------------------------------------------------------------
    def test_15_write_restricted_file_no_double_close_on_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = os.path.join(tmp_dir, ".env")
            real_fdopen = os.fdopen

            class FailingWriter:
                def __init__(self, real_handle):
                    self._h = real_handle

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    self._h.close()
                    return False

                def write(self, data):
                    raise OSError("Simulated disk full")

            with patch("os.fdopen", side_effect=lambda fd, *a, **kw: FailingWriter(real_fdopen(fd, *a, **kw))), \
                 patch("os.close") as mock_close:
                with self.assertRaises(OSError):
                    write_restricted_file(target, "SECRET=1\n")
                mock_close.assert_not_called()

    # ------------------------------------------------------------------
    # Bug 16 & 17: Row activation targets activated row; single resolve; quiet POSIX browser
    # ------------------------------------------------------------------
    def test_16_and_17_activate_streams_clicked_row_resolves_once_and_silences_browser_fds(self) -> None:
        form = TwitTUIForm("TestApp", "org.twit.test", cache_db_path=":memory:")
        row0 = SimpleNamespace(
            title="Marked Episode 0",
            episode="1",
            episode_data={"title": "Marked Episode 0", "video_hd": {"mediaUrl": "https://cdn.twit.tv/ep0.mp4"}},
        )
        row5 = SimpleNamespace(
            title="Activated Episode 5",
            episode="5",
            episode_data={"title": "Activated Episode 5", "video_hd": {"mediaUrl": "https://cdn.twit.tv/ep5.mp4"}},
        )
        form.is_audio_only = lambda: False
        form.episodes_list = SimpleNamespace(selection=[row0])  # row0 marked via Space

        with patch("twittui_form.resolve_stream_url", side_effect=lambda u: u) as mock_resolve, \
             patch("subprocess.Popen") as mock_popen:
            asyncio.run(form.on_episode_activate(form.episodes_list, row=row5))

        # Bug 16: streamed row5, NOT marked row0
        cmd = mock_popen.call_args[0][0]
        self.assertIn("https://cdn.twit.tv/ep5.mp4", cmd)
        self.assertNotIn("https://cdn.twit.tv/ep0.mp4", cmd)
        # Bug 17: resolve_stream_url called ONCE (not twice via launch_stream_safe)
        mock_resolve.assert_called_once_with("https://cdn.twit.tv/ep5.mp4")

        # Bug 17: direct launch_stream_safe with resolve=False skips resolve_stream_url
        with patch("twittui_form.resolve_stream_url") as mock_res2, \
             patch("subprocess.Popen") as mock_popen2:
            launch_stream_safe("vlc %f", "https://cdn.twit.tv/ep5.mp4", resolve=False)
            mock_res2.assert_not_called()
            mock_popen2.assert_called_once()

        # Bug 17: _open_browser_quietly in live TUI spawns POSIX opener with DEVNULL stdio
        with patch("twittui_form._is_textual_tui_running", return_value=True), \
             patch("sys.platform", "linux"), \
             patch("shutil.which", return_value="/usr/bin/xdg-open"), \
             patch("subprocess.Popen") as mock_browser_popen:
            opened = form._open_browser_quietly("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertTrue(opened)
            mock_browser_popen.assert_called_once_with(
                ["/usr/bin/xdg-open", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    # ------------------------------------------------------------------
    # Bug 18: Textual backend widget & lifecycle fixes
    # ------------------------------------------------------------------
    def test_18_textual_backend_dialogs_progressbar_indicator_table_and_hide(self) -> None:
        # 18a. ProgressBar retains pre-mount max and value
        pb = toga.ProgressBar(max=200.0, value=75.0)
        self.assertIsInstance(pb._impl, TextualProgressBarImpl)
        self.assertEqual(pb._impl.native.total, 200.0)
        self.assertEqual(pb._impl.native.progress, 75.0)

        # 18b. ActivityIndicator toggles native.display on start()/stop()
        ind = toga.ActivityIndicator()
        self.assertIsInstance(ind._impl, TextualActivityIndicator)
        self.assertFalse(ind._impl.native.display)
        ind.start()
        self.assertTrue(ind._impl.native.display)
        ind.stop()
        self.assertFalse(ind._impl.native.display)

        # 18c. OpenFileDialog / SaveFileDialog resolve Toga DialogResult wrappers cleanly
        class WrapperResult:
            def __init__(self):
                self.value = "UNSET"

            def set_result(self, v):
                self.value = v

        w1, w2 = WrapperResult(), WrapperResult()
        OpenFileDialog("Open").show(None, w1)
        SaveFileDialog("Save", "out.txt").show(None, w2)
        self.assertIsNone(w1.value)
        self.assertIsNone(w2.value)

        # 18d. Incremental TextualTable insert/change/remove avoids clear(columns=True) rebuilds
        #      and Window.hide() resolves pending modal futures above it instead of hanging
        async def run_live_tui_checks() -> None:
            form = TwitTUIForm("TableHideTest", "org.twit.test.tui18", cache_db_path=":memory:")
            with patch.object(form, "_refresh_catalog"):
                form.startup()
            tapp = form._impl.native
            async with tapp.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                # Populate episodes table and verify incremental ops do not call clear(columns=True)
                tbl = form.episodes_list
                self.assertIsInstance(tbl._impl, TextualTable)
                tbl.data = [{"episode": "1", "title": "Ep 1", "date": "2025-01-01", "length": "1:00", "size": "10 MB"}]
                await pilot.pause()
                with patch.object(tbl._impl.native, "clear", wraps=tbl._impl.native.clear) as spy_clear:
                    tbl.data.append({"episode": "2", "title": "Ep 2", "date": "2025-01-02", "length": "1:00", "size": "20 MB"})
                    row_obj = tbl.data[1]
                    row_obj.title = "Ep 2 Updated"
                    tbl._impl.source_change(row_obj)
                    del tbl.data[0]
                    spy_clear.assert_not_called()
                self.assertEqual(tbl._impl.native.row_count, 1)

                # Open secondary window + modal dialog on top, then hide secondary window -> future resolves!
                sec_win = toga.Window(title="Secondary")
                sec_win.content = toga.Box(children=[toga.Label("Hello")])
                sec_win.show()
                await pilot.pause()
                pending_fut = asyncio.get_running_loop().create_future()
                modal = TextualDialogScreen("Notice", "Waiting...", [("OK", True)], pending_fut, default_result=False)
                tapp.push_screen(modal)
                await pilot.pause()
                sec_win.hide()
                await pilot.pause()
                self.assertTrue(pending_fut.done())
                self.assertEqual(pending_fut.result(), False)

        asyncio.run(run_live_tui_checks())


if __name__ == "__main__":
    unittest.main()
