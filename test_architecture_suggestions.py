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
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOGA_BACKEND", "toga_textual")

import main as main_mod
import twittui
import twittui_form
from twittui.cache import SHOW_DATE_BOUNDS_TTL_SECONDS
from twittui.logging_config import configure_logging, get_logger, reset_logging
from twittui.shows import (
    KNOWN_SHOW_FEEDS,
    MEMBERFUL_SHOW_FEEDS,
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

    def test_unified_show_registry_completeness_and_derivation(self) -> None:
        """All 4 derived show lookup tables come from SHOW_REGISTRY and include previously missing shows."""
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

        # Previously diverging shows are now unified across feeds, search slugs, and transcript slugs
        for show_key in (
            "floss weekly",
            "hands-on photography",
            "this week in enterprise tech",
            "this week in google",
            "all about android",
            "intelligent machines",
        ):
            entry = get_show_entry(show_key)
            self.assertIsNotNone(entry, f"Missing ShowEntry for {show_key}")
            self.assertIn(show_key, KNOWN_SHOW_FEEDS)
            self.assertIn(show_key, SHOW_SEARCH_SLUGS)
            self.assertIn(show_key, TRANSCRIPT_SLUG_MAP)

    def test_transcript_slug_candidates_cover_newly_unified_shows(self) -> None:
        """generate_transcript_slug_candidates uses unified TRANSCRIPT_SLUG_MAP for all shows."""
        form = TwitTUIForm("SlugApp", "org.twit.test")
        im_cands = form.generate_transcript_slug_candidates("Intelligent Machines", "800")
        self.assertTrue(any("/im-800-transcript" in c for c in im_cands))
        aaa_cands = form.generate_transcript_slug_candidates("All About Android", "650")
        self.assertTrue(any("/aaa-650-transcript" in c for c in aaa_cands))
        hop_cands = form.generate_transcript_slug_candidates("Hands-On Photography", "200")
        self.assertTrue(any("/hop-200-transcript" in c for c in hop_cands))

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

    def test_no_silent_broad_except_pass_handlers_remain(self) -> None:
        """AST guard ensuring no broad `except Exception: pass` silent swallowers remain in core code."""
        source_files = [
            PROJECT_ROOT / "twittui_form.py",
            PROJECT_ROOT / "toga_textual_backend.py",
            PROJECT_ROOT / "main.py",
            PROJECT_ROOT / "tiered_search.py",
            PROJECT_ROOT / "installer.py",
            *sorted((PROJECT_ROOT / "twittui").glob("*.py")),
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

    def test_packaging_hygiene_and_ci_workflow(self) -> None:
        """Verify unified pyproject.toml, setup.py, .gitignore, installer.py, and CI workflow."""
        pyproject_data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = pyproject_data["project"]["dependencies"]
        self.assertTrue(any("yt-dlp" in d for d in deps))
        self.assertTrue(any("toga-gtk" in d and "sys_platform" in d for d in deps))

        opt_deps = pyproject_data["project"]["optional-dependencies"]
        for extra in ("gtk", "textual", "youtube", "security", "fast-search", "dev"):
            self.assertIn(extra, opt_deps)
        self.assertIn("twittui", pyproject_data["tool"]["setuptools"]["packages"])

        setup_text = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn('packages=["twittui"]', setup_text)
        self.assertIn("with open(readme_path", setup_text)

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


if __name__ == "__main__":
    unittest.main()
