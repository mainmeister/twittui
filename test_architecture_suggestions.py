"""Regression tests for Part 4 architectural, caching, logging, packaging, and hygiene improvements."""

from __future__ import annotations

import ast
import json
import logging
import os
import pathlib
import sqlite3
import tempfile
import time
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOGA_BACKEND", "toga_textual")

import main as main_mod
import twittui
import twittui_form
from twittui._compat import PACKAGE_ROOT
from twittui.cache import SHOW_DATE_BOUNDS_TTL_SECONDS
from twittui.logging_config import configure_logging, get_logger, reset_logging, safe_url_for_log
from twittui.shows import (
    DEFAULT_SHOWS,
    KNOWN_SHOW_FEEDS,
    MEMBERFUL_HOST_FEEDS,
    MEMBERFUL_SHOW_FEEDS,
    SHOW_ABBREVIATIONS,
    SHOW_REGISTRY,
    SHOW_SEARCH_SLUGS,
    TRANSCRIPT_SLUG_MAP,
    ShowEntry,
    get_show_entry,
)
from twittui_form import TwitTUIForm

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent


class TestArchitectureSuggestions(unittest.TestCase):
    """Verify modular twittui/ package, unified show registry, normalized cache, logging, and CI."""

    def tearDown(self) -> None:
        reset_logging()

    def test_twittui_package_exports_and_form_compat(self) -> None:
        """Extracted twittui package symbols remain 100% compatible with twittui_form imports."""
        self.assertEqual(twittui.__version__, "1.1.0")
        self.assertIs(twittui_form._LocalHTMLServer, twittui._LocalHTMLServer)
        self.assertIs(twittui_form._LocalHTMLHandler, twittui._LocalHTMLHandler)
        self.assertIs(twittui_form.sanitize_html_content, twittui.sanitize_html_content)
        self.assertIs(twittui_form._LazySQLiteEpisodesCache, twittui._LazySQLiteEpisodesCache)
        self.assertIs(twittui_form.SHOW_REGISTRY, SHOW_REGISTRY)
        self.assertTrue(issubclass(twittui_form.ApiRateLimiter, twittui.ApiRateLimiter))

    def test_monolith_decomposed_into_package_layout(self) -> None:
        """Verify twittui_form.py is a thin facade and all suggested twittui/ modules import cleanly."""
        import importlib

        facade_lines = (PROJECT_ROOT / "twittui_form.py").read_text(encoding="utf-8").splitlines()
        self.assertLess(
            len(facade_lines),
            250,
            f"Expected twittui_form.py facade to stay concise (< 250 lines), got {len(facade_lines)}",
        )

        expected_modules = (
            "twittui.cli",
            "twittui.config",
            "twittui.rate_limiter",
            "twittui.cache",
            "twittui.catalog",
            "twittui.rss",
            "twittui.media",
            "twittui.downloader",
            "twittui.viewer",
            "twittui.search",
            "twittui.search.tiered_search",
            "twittui.search.double_metaphone",
            "twittui.ui",
            "twittui.ui.form",
            "twittui.ui.preferences",
            "twittui.ui.metadata",
            "twittui.ui.textual_backend",
        )
        for mod_name in expected_modules:
            mod = importlib.import_module(mod_name)
            self.assertIsNotNone(mod)

        from twittui.catalog import CatalogMixin
        from twittui.config import ConfigMixin
        from twittui.downloader import DownloaderMixin
        from twittui.media import MediaMixin
        from twittui.rss import RssMixin
        from twittui.ui.form import TwitTUIForm as ModularTwitTUIForm
        from twittui.ui.metadata import MetadataMixin
        from twittui.ui.preferences import PreferencesMixin
        from twittui.viewer import ViewerMixin

        self.assertIs(TwitTUIForm, ModularTwitTUIForm)
        for mixin in (
            PreferencesMixin,
            MetadataMixin,
            ViewerMixin,
            DownloaderMixin,
            MediaMixin,
            RssMixin,
            CatalogMixin,
            ConfigMixin,
        ):
            self.assertTrue(issubclass(TwitTUIForm, mixin), f"TwitTUIForm missing mixin {mixin.__name__}")

    def test_package_runtime_resources_and_icon_fallback(self) -> None:
        """Bundled help, feed styles, and icons load cleanly via importlib.resources outside the source tree."""
        from importlib import resources as importlib_resources
        from twittui.resources import read_resource_bytes, read_resource_text
        from twittui.ui.form import resolve_app_icon

        package_resources = pathlib.Path(PACKAGE_ROOT) / "resources"
        res_root = importlib_resources.files("twittui.resources")
        for filename in (
            "README.md",
            "twittv.apib",
            "feed-style.css",
            "feed-style.xsl",
            "twittui.png",
            "twittui.ico",
        ):
            with self.subTest(filename=filename):
                self.assertTrue((package_resources / filename).is_file())
                self.assertTrue(res_root.joinpath(filename).is_file())

        self.assertIn("--primary:", read_resource_text("feed-style.css") or "")
        self.assertGreater(len(read_resource_bytes("twittui.png") or b""), 0)

        with tempfile.TemporaryDirectory() as empty_root:
            with patch("twittui.ui.form.PROJECT_ROOT", empty_root), \
                 patch("twittui.ui.form.os.getcwd", return_value=empty_root), \
                 patch("twittui.viewer.PROJECT_ROOT", empty_root), \
                 patch("twittui.viewer.os.getcwd", return_value=empty_root), \
                 patch.dict(os.environ, {"SNAP": ""}):
                self.assertEqual(resolve_app_icon(), str(package_resources / "twittui"))
                form = TwitTUIForm("ResApp", "org.twit.test")
                rss_xml = b'<?xml version="1.0"?><rss><channel><title>TWiT</title><item><title>Ep 1</title></item></channel></rss>'
                rendered = form.render_rss_feed_to_html(rss_xml)
                self.assertIn("--primary:", rendered)

    def test_archive_backed_icon_resource_path_remains_valid(self) -> None:
        """Icon paths extracted from archive-backed packages remain available after lookup."""
        import zipfile
        import twittui.resources as packaged_resources
        from twittui.resources import locate_resource_file

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = os.path.join(temp_dir, "resources.zip")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("twittui.png", b"archive-icon")

            try:
                with zipfile.ZipFile(archive_path) as archive:
                    resource_root = zipfile.Path(archive)
                    with patch.object(packaged_resources.importlib_resources, "files", return_value=resource_root):
                        self.assertIsNone(locate_resource_file("twittui.png"))
                        icon_path = locate_resource_file("twittui.png", keep_alive=True)
                        self.assertIsNotNone(icon_path)
                        self.assertEqual(pathlib.Path(icon_path).read_bytes(), b"archive-icon")
                self.assertTrue(os.path.isfile(icon_path))
                self.assertEqual(pathlib.Path(icon_path).read_bytes(), b"archive-icon")
            finally:
                packaged_resources._cleanup_materialized_resources()

    def test_unified_show_registry_completeness_and_derivation(self) -> None:
        """All derived show lookup tables (feeds, host feeds, slugs, abbreviations, defaults) come from SHOW_REGISTRY."""
        for key, entry in SHOW_REGISTRY.items():
            self.assertIsInstance(entry, ShowEntry)
            self.assertEqual(entry.key, key)
            if entry.public_feeds:
                self.assertEqual(KNOWN_SHOW_FEEDS[key], list(entry.public_feeds))
            if entry.memberful_feeds:
                self.assertEqual(MEMBERFUL_SHOW_FEEDS[key], list(entry.memberful_feeds))
            if entry.search_slugs:
                self.assertEqual(SHOW_SEARCH_SLUGS[key], list(entry.search_slugs))
            if entry.transcript_slugs:
                self.assertEqual(TRANSCRIPT_SLUG_MAP[key], list(entry.transcript_slugs))

        # DEFAULT_SHOWS and MEMBERFUL_HOST_FEEDS are strictly derived from SHOW_REGISTRY (no duplicate lists)
        expected_defaults = sorted(
            [
                (entry.display_name, entry.default_show_id)
                for entry in SHOW_REGISTRY.values()
                if entry.include_in_default_shows
            ],
            key=lambda pair: pair[0],
        )
        self.assertEqual(DEFAULT_SHOWS, expected_defaults)
        self.assertEqual(len(DEFAULT_SHOWS), 26)

        expected_host_feeds: list[int] = []
        for entry in SHOW_REGISTRY.values():
            if entry.is_host_feed:
                for fid in entry.memberful_feeds:
                    if fid not in expected_host_feeds:
                        expected_host_feeds.append(fid)
        self.assertEqual(MEMBERFUL_HOST_FEEDS, expected_host_feeds)
        self.assertEqual(
            MEMBERFUL_HOST_FEEDS,
            [9073, 9072, 9053, 9052, 9075, 9074, 9069, 9068, 9162, 9161],
        )

        # Previously diverging shows are now unified across feeds, search slugs, transcript slugs, and abbreviations
        for show_key, abbrev in (
            ("floss weekly", "floss"),
            ("hands-on photography", "hop"),
            ("this week in enterprise tech", "twiet"),
            ("this week in google", "twig"),
            ("all about android", "aaa"),
            ("intelligent machines", "im"),
            ("smart tech today", "stt"),
            ("know how", "kh"),
        ):
            entry = get_show_entry(show_key)
            self.assertIsNotNone(entry, f"Missing ShowEntry for {show_key}")
            self.assertIn(show_key, KNOWN_SHOW_FEEDS)
            self.assertIn(show_key, SHOW_SEARCH_SLUGS)
            self.assertIn(show_key, TRANSCRIPT_SLUG_MAP)
            self.assertIn(abbrev, SHOW_ABBREVIATIONS)

    def test_transcript_slug_candidates_cover_newly_unified_shows(self) -> None:
        """generate_transcript_slug_candidates uses unified SHOW_REGISTRY without substring collisions."""
        form = TwitTUIForm("SlugApp", "org.twit.test")
        im_cands = form.generate_transcript_slug_candidates("Intelligent Machines", "800")
        self.assertTrue(any("/im-800-transcript" in c for c in im_cands))
        aaa_cands = form.generate_transcript_slug_candidates("All About Android", "650")
        self.assertTrue(any("/aaa-650-transcript" in c for c in aaa_cands))
        hop_cands = form.generate_transcript_slug_candidates("Hands-On Photography", "200")
        self.assertTrue(any("/hop-200-transcript" in c for c in hop_cands))

        # Exact registry lookup prevents "the tech guy" substring from clobbering "Ask The Tech Guy"
        attg_cands = form.generate_transcript_slug_candidates("Ask The Tech Guy", "1050")
        self.assertTrue(attg_cands[0].endswith("/ask-tech-guys-1050-transcript"))
        self.assertFalse(any("/ttg-1050" in c for c in attg_cands))

    def test_show_registry_alias_lookup_and_no_inline_diverging_maps(self) -> None:
        """get_show_entry resolves aliases/punctuation, metadata parses registry abbreviations, and no inline maps remain."""
        self.assertEqual(get_show_entry("Security Now!").key, "security now")
        self.assertEqual(get_show_entry("Know How...").key, "know how")
        self.assertEqual(get_show_entry("Hands On Tech").key, "hands-on tech")
        self.assertEqual(get_show_entry("twiet").key, "this week in enterprise tech")
        self.assertEqual(get_show_entry("floss").key, "floss weekly")
        self.assertEqual(get_show_entry("hop").key, "hands-on photography")
        self.assertEqual(get_show_entry("aaa").key, "all about android")
        self.assertEqual(get_show_entry("im").key, "intelligent machines")

        # Metadata episode number extraction recognizes abbreviations derived from SHOW_REGISTRY
        form = TwitTUIForm("AbbrevMeta", "org.twit.test")
        for title, expected_num in (
            ("FLOSS 750: Open Source Hardware", "750"),
            ("TWIET 550: Zero Trust", "550"),
            ("HOP 200: Studio Lighting", "200"),
            ("AAA 650: Android 16", "650"),
        ):
            meta = form.extract_episode_metadata_fields({"title": title}, show_name="FLOSS Weekly")
            self.assertEqual(meta["episode"], expected_num)

        # AST guard: legacy inline abbrevs / short_map dictionaries must never reappear in catalog or metadata
        for rel_path in ("twittui/catalog.py", "twittui/ui/metadata.py"):
            tree = ast.parse((PROJECT_ROOT / rel_path).read_text(encoding="utf-8"), rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id in ("abbrevs", "short_map"):
                            self.fail(f"Found legacy inline show map '{target.id}' in {rel_path}:{node.lineno}")

    def test_normalized_episodes_table_wal_mode_and_roundtrip(self) -> None:
        """Episodes persist into normalized twittui_episodes rows with WAL mode and lazy loading."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "norm_cache.db")
            form1 = TwitTUIForm("Norm1", "org.twit.norm1", cache_db_path=db_path)
            eps = [
                {"id": "102", "number": "102", "title": "SN 102", "airingDate": "2025-02-01"},
                {"id": "101", "number": "101", "title": "SN 101", "airingDate": "2025-01-25"},
            ]
            form1._save_to_persistent_cache("episodes", "1636", eps)

            with sqlite3.connect(db_path) as conn:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
                self.assertEqual(journal_mode, "wal")
                norm_rows = conn.execute(
                    "SELECT episode_key, position, airing_date FROM twittui_episodes WHERE show_id = '1636' ORDER BY position ASC"
                ).fetchall()
                self.assertEqual(len(norm_rows), 2)
                self.assertEqual(norm_rows[0], ("id:102", 0, "2025-02-01"))
                self.assertEqual(norm_rows[1], ("id:101", 1, "2025-01-25"))
                legacy_count = conn.execute(
                    "SELECT COUNT(*) FROM twittui_cache WHERE category = 'episodes' AND cache_key = '1636'"
                ).fetchone()[0]
                self.assertEqual(legacy_count, 0)

            with patch("json.loads", wraps=json.loads) as spy_loads:
                form2 = TwitTUIForm("Norm2", "org.twit.norm2", cache_db_path=db_path)
                self.assertEqual(spy_loads.call_count, 0)
                self.assertIn("1636", form2._episodes_cache)
                loaded = form2._episodes_cache["1636"]
                self.assertEqual([e["id"] for e in loaded], ["102", "101"])
                self.assertEqual(spy_loads.call_count, 2)

            # Deleting cache clears twittui_episodes as well
            form2._delete_from_persistent_cache()
            with sqlite3.connect(db_path) as conn:
                remaining = conn.execute("SELECT COUNT(*) FROM twittui_episodes").fetchone()[0]
                self.assertEqual(remaining, 0)

    def test_legacy_episode_blob_lazily_migrated_on_first_read(self) -> None:
        """Legacy monolithic twittui_cache episode blobs migrate lazily into twittui_episodes on read."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "legacy_blob.db")
            legacy_eps = [
                {"id": "50", "number": "50", "title": "Legacy Ep 50", "airingDate": "2024-05-01"},
                {"id": "49", "number": "49", "title": "Legacy Ep 49", "airingDate": "2024-04-24"},
            ]
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE twittui_cache (
                        category TEXT NOT NULL,
                        cache_key TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (category, cache_key)
                    )
                    """
                )
                now = time.time()
                conn.execute(
                    "INSERT INTO twittui_cache VALUES ('episodes', '1636', ?, ?, ?)",
                    (json.dumps(legacy_eps), now, now),
                )
                conn.commit()

            with patch("json.loads", wraps=json.loads) as spy_loads:
                form = TwitTUIForm("MigApp", "org.twit.mig", cache_db_path=db_path)
                # No eager JSON decoding during __init__
                self.assertEqual(spy_loads.call_count, 0)
                self.assertIn("1636", form._episodes_cache)

                # First read loads and migrates lazily
                loaded = form._episodes_cache["1636"]
                self.assertEqual([e["id"] for e in loaded], ["50", "49"])

            with sqlite3.connect(db_path) as conn:
                norm_count = conn.execute(
                    "SELECT COUNT(*) FROM twittui_episodes WHERE show_id = '1636'"
                ).fetchone()[0]
                legacy_count = conn.execute(
                    "SELECT COUNT(*) FROM twittui_cache WHERE category = 'episodes' AND cache_key = '1636'"
                ).fetchone()[0]
                self.assertEqual(norm_count, 2)
                self.assertEqual(legacy_count, 0)

    def test_all_shows_fts_search_migrates_legacy_episode_blobs(self) -> None:
        """All-shows FTS searches include legacy episode blobs before normalized migration."""
        from twittui.cache import ensure_cache_schema, search_episodes_fts

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "legacy_search.db")
            legacy_episode = {
                "id": "legacy-search-1",
                "title": "Legacy archive entry",
                "description": "needleword from the old episode cache",
            }
            with sqlite3.connect(db_path) as conn:
                ensure_cache_schema(conn, db_path=db_path)
                now = time.time()
                conn.execute(
                    "INSERT INTO twittui_cache VALUES ('episodes', '1636', ?, ?, ?)",
                    (json.dumps([legacy_episode]), now, now),
                )
                conn.commit()

                hits = search_episodes_fts(conn, "needleword", show_id=None, db_path=db_path)

            self.assertEqual([episode["id"] for episode in hits], ["legacy-search-1"])

    def test_show_date_bounds_24h_ttl_expiration(self) -> None:
        """show_date_bounds entries older than 24 hours expire and are purged on startup."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "ttl_cache.db")
            seed = TwitTUIForm("TTLSeed", "org.twit.ttl1", cache_db_path=db_path)
            seed._save_to_persistent_cache("show_date_bounds", "fresh_show", ["2020-01-01", "2025-03-01"])
            seed._save_to_persistent_cache("show_date_bounds", "stale_show", ["2015-01-01", "2024-01-01"])

            expired_ts = time.time() - SHOW_DATE_BOUNDS_TTL_SECONDS - 600.0
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE twittui_cache SET updated_at = ? WHERE category = 'show_date_bounds' AND cache_key = 'stale_show'",
                    (expired_ts,),
                )
                conn.commit()

            reloaded = TwitTUIForm("TTLCheck", "org.twit.ttl2", cache_db_path=db_path)
            self.assertEqual(reloaded._show_date_cache.get("fresh_show"), ("2020-01-01", "2025-03-01"))
            self.assertNotIn("stale_show", reloaded._show_date_cache)

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT cache_key FROM twittui_cache WHERE category = 'show_date_bounds'"
                ).fetchall()
                self.assertEqual([r[0] for r in rows], ["fresh_show"])

    def test_refresh_show_dates_bounded_concurrency(self) -> None:
        """_refresh_show_dates dispatches up to max_concurrent jobs in parallel and invokes callback once."""
        form = TwitTUIForm("ConcApp", "org.twit.test")
        form._catalog_request = 1
        shows = [f"Show {i}" for i in range(7)]
        form.show_ids = {name: 100 + i for i, name in enumerate(shows)}
        form.show_active = {name: True for name in shows}
        form.show_date_bounds = {name: (None, None) for name in shows}
        form._show_date_cache = {}
        form.show_combo = SimpleNamespace(value="Show 0", items=[])

        worker = MagicMock()
        worker.fetch_show_date_bounds.side_effect = lambda sid: ("2020-01-01", f"2025-01-{int(sid) - 99:02d}")
        form._network_snapshot = MagicMock(return_value=worker)

        in_flight: list[tuple] = []
        max_observed_in_flight = 0

        def fake_run_network(work, done):
            nonlocal max_observed_in_flight
            in_flight.append((work, done))
            max_observed_in_flight = max(max_observed_in_flight, len(in_flight))

        form._run_network = fake_run_network
        callback = MagicMock()

        form._refresh_show_dates(1, shows, callback=callback, max_concurrent=4)
        # Immediately starts 4 concurrent jobs, never exceeding max_concurrent
        self.assertEqual(len(in_flight), 4)
        self.assertEqual(max_observed_in_flight, 4)
        callback.assert_not_called()

        # Drain jobs FIFO; each completion schedules the next pending show up to 7 total
        completed = 0
        while in_flight:
            work, done = in_flight.pop(0)
            result = work()
            done(result)
            completed += 1
            self.assertLessEqual(len(in_flight), 4)

        self.assertEqual(completed, 7)
        self.assertEqual(max_observed_in_flight, 4)
        callback.assert_called_once()
        for name in shows:
            self.assertIsNotNone(form.show_date_bounds[name][1])

    def test_cold_start_nonblocking_date_scraping_and_runtime_ttl(self) -> None:
        """Cold start dismisses splash & wait right after initial episodes while dates scrape concurrently with 24h TTL."""
        form = TwitTUIForm("ColdStartApp", "org.twit.test")
        shows = [f"Show {i}" for i in range(6)]
        form.show_combo = SimpleNamespace(value="Show 0", items=[])
        form.show_ids = {name: 200 + i for i, name in enumerate(shows)}
        form.show_active = {name: True for name in shows}
        form.show_date_bounds = {name: (None, None) for name in shows}
        form._show_date_cache = {}
        form._show_date_cache_ts = {}
        form._set_rate_limit_wait = MagicMock()
        form.close_splash_screen = MagicMock()
        form.update_episodes_display = MagicMock()

        worker = MagicMock()
        worker.show_ids = dict(form.show_ids)
        worker.show_active = dict(form.show_active)
        worker.show_date_bounds = dict(form.show_date_bounds)
        worker._show_date_cache = {}
        worker._show_date_cache_ts = {}
        worker.api_status_label = SimpleNamespace(text="")
        worker.fetch_shows.return_value = shows
        worker.fetch_episodes.return_value = [{"id": "1", "title": "Ep 1"}]
        worker._episodes_all_loaded = True
        worker.fetch_show_date_bounds.side_effect = lambda sid: ("2020-01-01", f"2025-02-{int(sid) - 199:02d}")
        form._network_snapshot = MagicMock(return_value=worker)

        jobs: list[tuple] = []
        form._run_network = lambda work, done: jobs.append((work, done))

        form._refresh_catalog()
        form._set_rate_limit_wait.assert_called_once_with(True)
        form._set_rate_limit_wait.reset_mock()

        # Shows catalog arrives -> spawns initial episodes + 4 bounded-concurrency background date jobs
        shows_work, shows_done = jobs.pop(0)
        shows_done(shows_work())
        ep_jobs = [j for j in jobs if "fetch_all" in getattr(j[0], "__name__", "")]
        date_jobs = [j for j in jobs if j not in ep_jobs]
        self.assertEqual(len(ep_jobs), 1)
        self.assertEqual(len(date_jobs), 4)

        # Initial episodes finish -> splash & wait overlay dismiss IMMEDIATELY while 6 date scrapes are pending
        jobs.remove(ep_jobs[0])
        ep_jobs[0][1](ep_jobs[0][0]())
        form.close_splash_screen.assert_called_once()
        form._set_rate_limit_wait.assert_called_once_with(False)
        self.assertFalse(getattr(form, "_catalog_wait_held", False))

        # Drain remaining background date jobs; UI stays unlocked and bounds fill in
        while jobs:
            self.assertLessEqual(len(jobs), 4)
            w, d = jobs.pop(0)
            d(w())
        for name in shows:
            self.assertIsNotNone(form.show_date_bounds[name][1])
        form.close_splash_screen.assert_called_once()
        form._set_rate_limit_wait.assert_called_once_with(False)

        # Runtime TTL enforcement: expire one show in-memory (> 24h) and verify _refresh_show_dates re-scrapes it
        expired_sid = str(form.show_ids["Show 0"])
        form._show_date_cache_ts[expired_sid] = time.time() - SHOW_DATE_BOUNDS_TTL_SECONDS - 60.0
        form._refresh_show_dates(form._catalog_request, shows)
        self.assertEqual(len(jobs), 1)
        w, d = jobs.pop(0)
        d(w())
        self.assertGreater(form._show_date_cache_ts[expired_sid], time.time() - 10.0)

    def test_normalized_sqlite_pagination_deduplication_fts5_and_vacuum(self) -> None:
        """Normalized SQLite table supports SQL deduplication, lazy LIMIT/OFFSET pagination, FTS5 search, and VACUUM."""
        from twittui.cache import (
            count_normalized_episodes,
            delete_persistent_cache,
            load_episodes_page,
            search_episodes_fts,
            upsert_normalized_episodes,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "full_norm.db")
            form1 = TwitTUIForm("NormFull1", "org.twit.normfull1", cache_db_path=db_path)

            # Include intentional duplicate episode IDs to verify SQL-level deduplication
            sn_eps = [
                {
                    "id": str(i),
                    "number": str(i),
                    "title": f"Security Now {i}: Passkey & Zero-Trust Deep Dive" if i == 42 else f"Security Now {i}",
                    "airingDate": f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
                    "description": "<p>Steve Gibson examines <b>cryptographic passkeys</b> and DNSSEC.</p>"
                    if i == 42
                    else f"<p>Weekly security briefing episode {i} with padding {'x' * 200}</p>",
                    "hosts": [{"label": "Steve Gibson"}, {"label": "Leo Laporte"}],
                    "topics": ["Cryptography", "Privacy"] if i == 42 else ["Security"],
                }
                for i in range(120, 0, -1)
            ]
            sn_eps_with_dups = [sn_eps[0], *sn_eps, sn_eps[-1]]
            form1._save_to_persistent_cache("episodes", "1636", sn_eps_with_dups)

            twit_eps = [
                {
                    "id": "9001",
                    "number": "900",
                    "title": "TWiT 900: Quantum Computing Breakthrough",
                    "airingDate": "2025-03-01",
                    "description": "Discussion on fault-tolerant qubits and silicon photonics.",
                    "hosts": ["Leo Laporte"],
                    "topics": ["Quantum"],
                }
            ]
            form1._save_to_persistent_cache("episodes", "1634", twit_eps)

            # Verify SQL-level deduplication + incremental upsert_normalized_episodes
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(count_normalized_episodes(conn, "1636"), 120)
                upsert_count = upsert_normalized_episodes(
                    conn,
                    "1636",
                    [
                        {
                            "id": "42",
                            "number": "42",
                            "title": "Security Now 42: Passkey & Hardware Tokens",
                            "airingDate": "2025-07-15",
                            "description": "<p>Updated notes on FIDO2 hardware passkeys.</p>",
                            "hosts": [{"label": "Steve Gibson"}],
                            "topics": ["FIDO2"],
                        },
                        {
                            "id": "121",
                            "number": "121",
                            "title": "Security Now 121: Post-Quantum TLS",
                            "airingDate": "2025-08-01",
                            "description": "ML-KEM deployment across browsers.",
                        },
                    ],
                    db_path=db_path,
                )
                conn.commit()
                self.assertEqual(upsert_count, 2)
                self.assertEqual(count_normalized_episodes(conn, "1636"), 121)

                # SQL pagination helper
                page2_sql = load_episodes_page(conn, "1636", page=2, page_size=50)
                self.assertEqual(len(page2_sql), 50)
                self.assertEqual(page2_sql[0]["id"], "70")

                # Direct FTS5 search (single show, cross-show, and punctuation safety)
                fts_sn = search_episodes_fts(conn, 'FIDO2: "passkeys" (hardware)', show_id="1636")
                self.assertEqual([e["id"] for e in fts_sn], ["42"])
                fts_all = search_episodes_fts(conn, "photonics", show_id=None)
                self.assertEqual([e["id"] for e in fts_all], ["9001"])

            # Fresh instance: SQL-level pagination via fetch_episodes(page=2) decodes ONLY 50 rows, not 121
            with patch("json.loads", wraps=json.loads) as spy_loads:
                form2 = TwitTUIForm("NormFull2", "org.twit.normfull2", cache_db_path=db_path)
                form2.show_combo = MagicMock(value="Security Now")
                form2.show_ids = {"Security Now": 1636, "This Week in Tech": 1634}
                form2._episodes_all_loaded = True
                self.assertEqual(spy_loads.call_count, 0)
                self.assertEqual(form2._episodes_cache.count_episodes("1636"), 121)
                self.assertEqual(spy_loads.call_count, 0)

                with patch.object(form2, "get_api_app_id", return_value="id"), \
                     patch.object(form2, "get_api_app_key", return_value="key"), \
                     patch("twittui_form.load_twittui_dotenv"), \
                     patch("twittui_form.requests.get") as mock_get:
                    page2 = form2.fetch_episodes(1636, page=2)
                    self.assertEqual(len(page2), 50)
                    self.assertEqual(page2[0]["id"], "70")
                    self.assertEqual(mock_get.call_count, 0)
                    # Only the 50 paginated rows were decoded from SQLite; full show stays unloaded
                    self.assertEqual(spy_loads.call_count, 50)
                    self.assertIn("1636", form2._episodes_cache._unloaded_keys)

            # CatalogMixin.search_episodes integrates Tier 4b FTS5 seamlessly (even offline / no API creds)
            with patch.object(form2, "get_api_app_id", return_value=""), \
                 patch.object(form2, "get_api_app_key", return_value=""), \
                 patch.object(form2, "fetch_show_rss_items", return_value=[]), \
                 patch.object(form2, "fetch_club_twit_rss_items", return_value=[]), \
                 patch("twittui_form.load_twittui_dotenv"):
                hits = form2.search_episodes("photonics", show_name="All TWiT.tv Shows")
                self.assertEqual([h["id"] for h in hits], ["9001"])

            # Clearing episodes cache clears FTS5, runs VACUUM/checkpoint, shrinks total DB+WAL footprint, and keeps 0o600
            def _db_footprint(path: str) -> int:
                return sum(
                    os.path.getsize(p)
                    for p in (path, f"{path}-wal")
                    if os.path.exists(p)
                )

            size_before = _db_footprint(db_path)
            delete_persistent_cache(db_path, category="episodes")
            size_after = _db_footprint(db_path)
            self.assertLess(size_after, size_before)
            self.assertEqual(os.stat(db_path).st_mode & 0o777, 0o600)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM twittui_episodes").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM twittui_episodes_fts").fetchone()[0], 0)
                self.assertEqual(conn.execute("PRAGMA freelist_count").fetchone()[0], 0)

    def test_structured_logging_file_permissions_and_cli_flags(self) -> None:
        """--log-file / configure_logging writes structured logs to a 0o600 file while default stays silent."""
        reset_logging()
        logger = get_logger()
        self.assertFalse(logger.propagate)
        self.assertTrue(any(isinstance(h, logging.NullHandler) for h in logger.handlers))

        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = os.path.join(tmp_dir, "twittui_diag.log")
            args = main_mod.parse_backend_args(["--textual", "--log-file", log_path, "--log-level", "DEBUG"])
            self.assertEqual(args.log_file, log_path)
            self.assertEqual(args.log_level, "DEBUG")

            configure_logging(log_file=log_path, level="DEBUG")
            get_logger("test_sub").debug("structured diagnostic marker %s", 42)
            reset_logging()

            self.assertTrue(os.path.isfile(log_path))
            mode = os.stat(log_path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            content = pathlib.Path(log_path).read_text(encoding="utf-8")
            self.assertIn("DEBUG [twittui.test_sub] structured diagnostic marker 42", content)

    def test_signed_url_details_are_redacted_from_logs(self) -> None:
        """URL diagnostics retain the host but never persist credentials, paths, or query values."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = os.path.join(tmp_dir, "redacted.log")
            configure_logging(log_file=log_path, level="DEBUG")
            signed_url = "https://user:pass@example.com/private/token?auth=secret&signature=signed#fragment"
            self.assertEqual(safe_url_for_log(signed_url), "https://example.com")

            from twittui.media import resolve_stream_url

            with patch("twittui.media.requests.head", side_effect=OSError(f"request failed for {signed_url}")):
                resolve_stream_url(signed_url)
            form = TwitTUIForm("LogRedaction", "org.twit.log-redaction", cache_db_path=":memory:")
            with patch.object(form, "get_club_twit_rss_url", return_value=signed_url), \
                 patch("twittui.rss.requests.get", side_effect=OSError(f"request failed for {signed_url}")):
                form.fetch_memberful_feed_items(9041)
            form._open_browser_quietly = MagicMock(side_effect=OSError(f"browser failed for {signed_url}"))
            form._show_dialog_threadsafe = MagicMock()
            form.open_url_in_browser(signed_url)
            reset_logging()

            content = pathlib.Path(log_path).read_text(encoding="utf-8")
            self.assertIn("https://example.com", content)
            for sensitive_value in ("user", "pass", "/private/token", "secret", "signed", "fragment"):
                self.assertNotIn(sensitive_value, content)

    def test_no_silent_broad_except_pass_handlers_remain(self) -> None:
        """AST guard ensuring no broad `except Exception: pass` silent swallowers remain in core code."""
        source_files = [
            PROJECT_ROOT / "twittui_form.py",
            PROJECT_ROOT / "toga_textual_backend.py",
            PROJECT_ROOT / "main.py",
            PROJECT_ROOT / "tiered_search.py",
            PROJECT_ROOT / "installer.py",
            *sorted((PROJECT_ROOT / "twittui").rglob("*.py")),
        ]
        offenders: list[str] = []
        for path in source_files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    is_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                    is_broad = node.type is None or ast.unparse(node.type) == "Exception"
                    if is_pass and is_broad:
                        offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [], f"Found silent broad except-pass handlers: {offenders}")

    def test_no_print_shadowing_or_unlogged_broad_exceptions(self) -> None:
        """AST & runtime guard: zero shadowed prints in twittui/ and zero unlogged broad except handlers."""
        import io
        import twittui._compat as compat_mod

        # 1. Verify quiet_print shadowing helper is removed from twittui._compat and twittui_form
        self.assertFalse(hasattr(compat_mod, "quiet_print"))
        self.assertNotIn("print", twittui_form.__dict__)

        # 2. Verify no file in twittui/ or twittui_form.py shadows `print` or calls bare `print(...)`
        pkg_files = [
            PROJECT_ROOT / "twittui_form.py",
            *sorted((PROJECT_ROOT / "twittui").rglob("*.py")),
        ]
        print_offenders: list[str] = []
        for path in pkg_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        if (alias.asname or alias.name) == "print":
                            print_offenders.append(f"import:{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
                elif isinstance(node, ast.FunctionDef) and node.name == "print":
                    print_offenders.append(f"def:{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    print_offenders.append(f"call:{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
        self.assertEqual(print_offenders, [], f"Found shadowed or bare print() usage: {print_offenders}")

        # 3. Verify every broad `except:` / `except Exception:` across all core modules has direct observability
        core_files = [
            PROJECT_ROOT / "twittui_form.py",
            PROJECT_ROOT / "toga_textual_backend.py",
            PROJECT_ROOT / "main.py",
            PROJECT_ROOT / "tiered_search.py",
            PROJECT_ROOT / "installer.py",
            *sorted((PROJECT_ROOT / "twittui").rglob("*.py")),
        ]

        def _handler_has_direct_observability(handler: ast.ExceptHandler) -> bool:
            stack = list(handler.body)
            while stack:
                node = stack.pop()
                if isinstance(node, ast.ExceptHandler):
                    continue
                if isinstance(node, ast.Raise):
                    return True
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id in ("_logger", "logger", "logging"):
                        return True
                    if node.func.attr in ("error_dialog", "info_dialog", "show_error", "_present_window_dialog"):
                        return True
                stack.extend(ast.iter_child_nodes(node))
            return False

        unlogged_broad: list[str] = []
        for path in core_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    is_broad = node.type is None or (
                        isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")
                    )
                    if is_broad and not _handler_has_direct_observability(node):
                        unlogged_broad.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
        self.assertEqual(unlogged_broad, [], f"Found unlogged broad exception handlers: {unlogged_broad}")

        # 4. Runtime verification: module diagnostics log to --log-file without polluting stdout
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = os.path.join(tmp_dir, "diag_runtime.log")
            configure_logging(log_file=log_path, level="DEBUG")
            captured_out = io.StringIO()
            with patch("sys.stdout", captured_out):
                form = TwitTUIForm("LogRuntime", "org.twit.test")
                with patch("twittui.config.os.makedirs", side_effect=OSError("disk read-only")):
                    fallback_dir = form.get_app_cache_dir()
                self.assertTrue(os.path.isdir(fallback_dir))
                with patch("twittui.catalog.requests.get", side_effect=RuntimeError("boom")):
                    ok, msg = form.test_api_credentials("id", "key")
                self.assertFalse(ok)
                self.assertIn("boom", msg)
            reset_logging()

            self.assertEqual(captured_out.getvalue(), "")
            content = pathlib.Path(log_path).read_text(encoding="utf-8")
            self.assertIn("Unable to create cache directory", content)
            self.assertIn("Error testing TWiT API credentials: boom", content)

    def test_packaging_hygiene_and_ci_workflow(self) -> None:
        """Verify consolidated pyproject.toml (no setup.py), headless-safe deps, .gitignore, installer, and CI."""
        self.assertFalse(
            (PROJECT_ROOT / "setup.py").exists(),
            "Redundant setup.py must be deleted; pyproject.toml is the single source of truth.",
        )

        pyproject_data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = pyproject_data["project"]["dependencies"]
        self.assertTrue(any("yt-dlp" in d for d in deps))
        self.assertIn("toga-core>=0.4.0", deps)
        self.assertFalse(any(d.lower().startswith("toga>=") for d in deps))
        # Core dependencies must stay headless-Linux/macOS/Windows safe (toga-gtk belongs in [gtk] extra)
        self.assertFalse(
            any("toga-gtk" in d for d in deps),
            f"toga-gtk must be optional under [project.optional-dependencies].gtk, found in core: {deps}",
        )

        opt_deps = pyproject_data["project"]["optional-dependencies"]
        for extra in ("gtk", "textual", "youtube", "security", "fast-search", "xml", "dev", "all"):
            self.assertIn(extra, opt_deps)
        self.assertTrue(any("toga-gtk" in d and "sys_platform" in d for d in opt_deps["gtk"]))
        self.assertTrue(any("tomli" in d and "python_version < '3.11'" in d for d in opt_deps["dev"]))
        requirements = [
            line.strip()
            for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(requirements, ["."], "requirements.txt must delegate to pyproject.toml metadata")
        for pkg_name in ("twittui", "twittui.resources", "twittui.search", "twittui.ui"):
            self.assertIn(pkg_name, pyproject_data["tool"]["setuptools"]["packages"])
        res_globs = pyproject_data["tool"]["setuptools"]["package-data"]["twittui.resources"]
        for pattern in ("*.md", "*.apib", "*.css", "*.xsl", "*.png", "*.ico"):
            self.assertIn(pattern, res_globs)

        installer_text = (PROJECT_ROOT / "installer.py").read_text(encoding="utf-8")
        self.assertIn('"twittui"', installer_text)

        gitignore_text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pat in ("*.egg-info/", "*.log", "*.spec"):
            self.assertIn(pat, gitignore_text)

        ci_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci_path.is_file(), ".github/workflows/ci.yml must exist")
        ci_text = ci_path.read_text(encoding="utf-8")
        self.assertIn("xvfb-run", ci_text)
        self.assertIn("SNAP_USER_DATA", ci_text)
        self.assertIn("unittest discover", ci_text)
        self.assertIn('pip install -e ".[gtk,security,fast-search,xml,dev]"', ci_text)
        self.assertNotIn("TWITTUI_CACHE_DB", ci_text)

    def test_pep517_wheel_build_bundles_resources_and_excludes_tests(self) -> None:
        """Building a PEP 517 wheel solely from pyproject.toml bundles package resources and excludes tests/secrets."""
        import contextlib
        import io
        import shutil
        import zipfile
        import setuptools.build_meta

        with tempfile.TemporaryDirectory() as tmp_root:
            src_dir = pathlib.Path(tmp_root) / "src"
            out_dir = pathlib.Path(tmp_root) / "dist"
            src_dir.mkdir()
            out_dir.mkdir()

            # Stage only the distribution sources so PROJECT_ROOT remains untouched
            shutil.copy2(PROJECT_ROOT / "pyproject.toml", src_dir / "pyproject.toml")
            shutil.copy2(PROJECT_ROOT / "README.md", src_dir / "README.md")
            for py_mod in (
                "main.py",
                "installer.py",
                "twittui_form.py",
                "toga_textual_backend.py",
                "generate_icon.py",
                "tiered_search.py",
                "double_metaphone.py",
            ):
                shutil.copy2(PROJECT_ROOT / py_mod, src_dir / py_mod)
            shutil.copytree(
                PROJECT_ROOT / "twittui",
                src_dir / "twittui",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

            prev_cwd = os.getcwd()
            try:
                os.chdir(src_dir)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    wheel_name = setuptools.build_meta.build_wheel(str(out_dir))
            finally:
                os.chdir(prev_cwd)

            wheel_path = out_dir / wheel_name
            self.assertTrue(wheel_path.is_file())
            with zipfile.ZipFile(wheel_path, "r") as zf:
                names = set(zf.namelist())
                for expected in (
                    "twittui/__init__.py",
                    "twittui/resources/__init__.py",
                    "twittui/resources/README.md",
                    "twittui/resources/twittv.apib",
                    "twittui/resources/feed-style.css",
                    "twittui/resources/feed-style.xsl",
                    "twittui/resources/twittui.png",
                    "twittui/resources/twittui.ico",
                    "twittui/search/tiered_search.py",
                    "twittui/ui/form.py",
                    "main.py",
                    "twittui_form.py",
                ):
                    self.assertIn(expected, names, f"Wheel missing expected member: {expected}")

                self.assertFalse(any(os.path.basename(n).startswith("test_") for n in names))
                self.assertFalse(any(os.path.basename(n) == ".env" for n in names))
                self.assertFalse(any(os.path.basename(n) == "setup.py" for n in names))

                meta_names = [n for n in names if n.endswith(".dist-info/METADATA")]
                self.assertEqual(len(meta_names), 1)
                metadata = zf.read(meta_names[0]).decode("utf-8")
                self.assertIn("Provides-Extra: gtk", metadata)
                self.assertIn("Provides-Extra: security", metadata)
                self.assertIn("Provides-Extra: fast-search", metadata)
                self.assertIn("Provides-Extra: xml", metadata)
                self.assertIn("Provides-Extra: dev", metadata)
                # Ensure toga-gtk only appears as an optional extra requirement, never unconditional
                req_lines = [line for line in metadata.splitlines() if line.startswith("Requires-Dist:")]
                gtk_lines = [line for line in req_lines if "toga-gtk" in line]
                self.assertTrue(gtk_lines)
                for line in gtk_lines:
                    self.assertIn("extra == 'gtk'", line.replace('"', "'"))
                    self.assertIn("sys_platform == 'linux'", line.replace('"', "'"))
                self.assertTrue(any(line.startswith("Requires-Dist: toga-core") for line in req_lines))
                self.assertFalse(any(line.startswith("Requires-Dist: toga ") for line in req_lines))


if __name__ == "__main__":
    unittest.main()
