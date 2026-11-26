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
from twittui._compat import PACKAGE_ROOT
from twittui.cache import SHOW_DATE_BOUNDS_TTL_SECONDS
from twittui.logging_config import configure_logging, get_logger, reset_logging, safe_url_for_log
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
        """Bundled help, feed styles, and icons remain available outside the source tree."""
        from twittui.ui.form import resolve_app_icon

        package_resources = pathlib.Path(PACKAGE_ROOT) / "resources"
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

        with tempfile.TemporaryDirectory() as empty_root:
            with patch("twittui.ui.form.PROJECT_ROOT", empty_root), \
                 patch("twittui.ui.form.os.getcwd", return_value=empty_root), \
                 patch.dict(os.environ, {"SNAP": ""}):
                self.assertEqual(resolve_app_icon(), str(package_resources / "twittui"))

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
        """Verify unified pyproject.toml, setup.py, .gitignore, installer.py, and CI workflow."""
        pyproject_data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = pyproject_data["project"]["dependencies"]
        self.assertTrue(any("yt-dlp" in d for d in deps))
        self.assertTrue(any("toga-gtk" in d and "sys_platform" in d for d in deps))

        opt_deps = pyproject_data["project"]["optional-dependencies"]
        for extra in ("gtk", "textual", "youtube", "security", "fast-search", "dev"):
            self.assertIn(extra, opt_deps)
        for pkg_name in ("twittui", "twittui.search", "twittui.ui"):
            self.assertIn(pkg_name, pyproject_data["tool"]["setuptools"]["packages"])
        self.assertEqual(
            pyproject_data["tool"]["setuptools"]["package-data"]["twittui"],
            ["resources/*"],
        )

        setup_text = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn('packages=["twittui", "twittui.search", "twittui.ui"]', setup_text)
        self.assertIn('"twittui": ["resources/*"]', setup_text)
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
        self.assertNotIn("TWITTUI_CACHE_DB", ci_text)


if __name__ == "__main__":
    unittest.main()
