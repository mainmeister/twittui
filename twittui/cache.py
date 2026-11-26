"""Normalized SQLite persistent cache with WAL mode, 24h TTL, SQL pagination, FTS5, and lazy loading."""

from __future__ import annotations

from collections.abc import ItemsView, KeysView, Mapping, ValuesView
import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from typing import Any

from twittui.logging_config import get_logger

_logger = get_logger("cache")

# Refresh cached show date bounds every 24 hours so active shows stay current
SHOW_DATE_BOUNDS_TTL_SECONDS: float = 86400.0


def _shows_cache_key_hash(app_id: str, app_key: str) -> str:
    """Return a SHA-256 digest of API credentials so secrets are never stored verbatim in SQLite."""
    payload = f"{app_id}\0{app_key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _restrict_file_permissions(file_path: str | None, mode: int = 0o600) -> None:
    """Enforce owner-only permissions on sensitive local files (and SQLite WAL/SHM sidecars)."""
    if not file_path or file_path == ":memory:":
        return
    for candidate in (file_path, f"{file_path}-wal", f"{file_path}-shm"):
        try:
            if os.path.exists(candidate):
                os.chmod(candidate, mode)
        except OSError:
            _logger.debug("Could not chmod %s to %o", candidate, mode, exc_info=True)


def get_cache_db_path(
    app_id: str | None = None,
    custom_path: str | None = None,
    base_dir: str | None = None,
) -> str:
    """Resolve persistent SQLite cache database file path."""
    if custom_path:
        return custom_path
    env_path = os.environ.get("TWITTUI_CACHE_DB") or os.environ.get("TWIT_CACHE_DB")
    if env_path:
        if env_path == ":memory:":
            return ":memory:"
        try:
            parent = os.path.dirname(os.path.abspath(env_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            return os.path.abspath(env_path)
        except OSError:
            _logger.debug("Could not create parent dir for %s", env_path, exc_info=True)
            return env_path

    if app_id == "org.twit.test":
        return os.path.join(tempfile.gettempdir(), f"twittui_test_cache_{secrets.token_hex(8)}.db")

    snap_data = os.environ.get("SNAP_USER_DATA") or os.environ.get("SNAP_USER_COMMON")
    if snap_data:
        try:
            os.makedirs(snap_data, mode=0o700, exist_ok=True)
            return os.path.join(snap_data, "twittui_cache.db")
        except OSError:
            _logger.debug("Could not initialize SNAP_USER_DATA cache dir %s", snap_data, exc_info=True)

    user_cache = os.path.join(os.path.expanduser("~"), ".cache", "twittui")
    try:
        os.makedirs(user_cache, mode=0o700, exist_ok=True)
        try:
            os.chmod(user_cache, 0o700)
        except OSError:
            _logger.debug("Could not chmod cache dir %s", user_cache, exc_info=True)
        return os.path.join(user_cache, "twittui_cache.db")
    except OSError:
        _logger.debug("Could not initialize user cache dir %s", user_cache, exc_info=True)

    try:
        candidate_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(candidate_dir, "twittui_cache.db")
    except OSError:
        return os.path.abspath("twittui_cache.db")


def episode_cache_key(ep: Any) -> tuple[str, ...] | None:
    """Return a canonical deduplication tuple for an episode dict."""
    if not isinstance(ep, dict):
        return None
    ep_id = ep.get("id")
    if ep_id is not None and str(ep_id).strip():
        return ("id", str(ep_id).strip())
    clean_path = ep.get("cleanPath") or ep.get("link")
    if clean_path:
        return ("path", str(clean_path).strip().lower())
    guid = ep.get("guid")
    if guid:
        return ("guid", str(guid).strip())
    num = str(ep.get("number", "")).strip()
    title = str(ep.get("title", "")).strip().lower()
    if num or title:
        return ("num_title", num, title)
    return None


def episode_cache_key_str(ep: Any, fallback_index: int = 0) -> str:
    """Serialize an episode's canonical key into a unique primary-key string."""
    key = episode_cache_key(ep)
    if key is None:
        return f"idx:{fallback_index}"
    return ":".join(key)


def _strip_html_for_fts(text: Any) -> str:
    """Convert raw text or HTML into normalized plain text suitable for FTS5 indexing."""
    if not text:
        return ""
    raw = str(text)
    if "<" in raw and ">" in raw:
        raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def _extract_fts_fields(ep: Any) -> tuple[str, str, str, str, str]:
    """Extract (title, description, hosts, topics, episode_number) text fields for FTS5."""
    if not isinstance(ep, dict):
        return ("", "", "", "", "")

    title = _strip_html_for_fts(ep.get("title") or ep.get("label") or "")

    desc_parts: list[str] = []
    seen_desc: set[str] = set()
    for key in ("description", "summary", "body", "show_notes", "notes", "teaser", "snippet"):
        val = _strip_html_for_fts(ep.get(key))
        if val and val not in seen_desc:
            seen_desc.add(val)
            desc_parts.append(val)
    description = " ".join(desc_parts)

    def _collect_names(keys: tuple[str, ...]) -> str:
        items: list[str] = []
        for k in keys:
            val = ep.get(k)
            if isinstance(val, list):
                for entry in val:
                    if isinstance(entry, dict):
                        name = entry.get("label") or entry.get("name") or entry.get("title")
                        if name:
                            items.append(str(name).strip())
                    elif isinstance(entry, str) and entry.strip():
                        items.append(entry.strip())
            elif isinstance(val, str) and val.strip():
                items.append(val.strip())
        return " ".join(items)

    hosts = _collect_names(("hosts", "guests", "people", "staff"))
    topics = _collect_names(("topics", "tags", "categories"))
    ep_num = str(
        ep.get("number")
        or ep.get("episodeNumber")
        or ep.get("episode")
        or ep.get("episode_number")
        or ""
    ).strip()
    return (title, description, hosts, topics, ep_num)


def _build_fts5_match_query(query: str) -> str:
    """Convert an arbitrary user query into a safe FTS5 prefix-AND ``MATCH`` expression."""
    if not query or not isinstance(query, str):
        return ""
    tokens = re.findall(r"\w+", query.strip(), flags=re.UNICODE)
    if not tokens:
        return ""
    return " ".join(f'"{tok}"*' for tok in tokens)


def ensure_cache_schema(conn: sqlite3.Connection, db_path: str | None = None) -> None:
    """Ensure SQLite WAL journal mode, KV table, normalized episodes table, and FTS5 index exist."""
    if db_path and db_path != ":memory:":
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            _logger.debug("Could not enable WAL journal mode on %s", db_path, exc_info=True)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS twittui_cache (
            category TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            data_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (category, cache_key)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_twittui_cache_category ON twittui_cache(category)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS twittui_episodes (
            show_id TEXT NOT NULL,
            episode_key TEXT NOT NULL,
            position INTEGER NOT NULL,
            airing_date TEXT,
            data_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (show_id, episode_key)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_twittui_episodes_show_pos ON twittui_episodes(show_id, position)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_twittui_episodes_show_date ON twittui_episodes(show_id, airing_date)"
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS twittui_episodes_fts USING fts5(
                show_id UNINDEXED,
                episode_key UNINDEXED,
                title,
                description,
                hosts,
                topics,
                episode_number,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
    except sqlite3.OperationalError:
        _logger.debug("SQLite FTS5 extension unavailable; full-text virtual table skipped", exc_info=True)
    _restrict_file_permissions(db_path, 0o600)


def _sync_fts_rows_for_show(
    conn: sqlite3.Connection,
    show_key: str,
    fts_rows: list[tuple[str, str, str, str, str, str, str]],
) -> None:
    """Replace all FTS5 rows for a single show inside the caller's transaction."""
    try:
        conn.execute("DELETE FROM twittui_episodes_fts WHERE show_id = ?", (show_key,))
        if fts_rows:
            conn.executemany(
                """
                INSERT INTO twittui_episodes_fts (
                    show_id, episode_key, title, description, hosts, topics, episode_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                fts_rows,
            )
    except sqlite3.OperationalError:
        _logger.debug("Skipping FTS5 sync for show %s (FTS5 unavailable)", show_key, exc_info=True)


def save_normalized_episodes(
    conn: sqlite3.Connection,
    show_id: str,
    episodes: list[Any],
    now: float | None = None,
    db_path: str | None = None,
) -> None:
    """Persist a show's deduplicated episodes as normalized rows in ``twittui_episodes`` and FTS5."""
    ts = time.time() if now is None else now
    show_key = str(show_id)
    ensure_cache_schema(conn, db_path=db_path)

    rows: list[tuple[str, str, int, str, str, float]] = []
    fts_rows: list[tuple[str, str, str, str, str, str, str]] = []
    seen_keys: set[str] = set()
    pos = 0
    for idx, ep in enumerate(episodes or []):
        canonical = episode_cache_key(ep)
        ep_key = ":".join(canonical) if canonical is not None else f"idx:{idx}"
        if ep_key in seen_keys:
            # Enforce SQL-level deduplication by canonical episode_key
            continue
        seen_keys.add(ep_key)
        airing_date = ""
        if isinstance(ep, dict):
            raw_date = ep.get("date") or ep.get("airingDate") or ep.get("publishDate") or ""
            airing_date = str(raw_date)[:32]
        rows.append((show_key, ep_key, pos, airing_date, json.dumps(ep), ts))
        title, desc, hosts, topics, ep_num = _extract_fts_fields(ep)
        fts_rows.append((show_key, ep_key, title, desc, hosts, topics, ep_num))
        pos += 1

    conn.execute("DELETE FROM twittui_episodes WHERE show_id = ?", (show_key,))
    if rows:
        conn.executemany(
            """
            INSERT INTO twittui_episodes (show_id, episode_key, position, airing_date, data_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(show_id, episode_key) DO UPDATE SET
                position = excluded.position,
                airing_date = excluded.airing_date,
                data_json = excluded.data_json,
                updated_at = excluded.updated_at
            """,
            rows,
        )
    _sync_fts_rows_for_show(conn, show_key, fts_rows)
    # Remove any legacy monolithic blob row for this show so disk bloat is reclaimed
    conn.execute(
        "DELETE FROM twittui_cache WHERE category = 'episodes' AND cache_key = ?",
        (show_key,),
    )


def upsert_normalized_episodes(
    conn: sqlite3.Connection,
    show_id: str,
    episodes: list[Any],
    now: float | None = None,
    db_path: str | None = None,
) -> int:
    """Incrementally upsert and deduplicate episodes into ``twittui_episodes`` and FTS5."""
    ts = time.time() if now is None else now
    show_key = str(show_id)
    ensure_cache_schema(conn, db_path=db_path)

    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM twittui_episodes WHERE show_id = ?",
        (show_key,),
    ).fetchone()
    next_pos = (int(row[0]) if row and row[0] is not None else -1) + 1

    rows: list[tuple[str, str, int, str, str, float]] = []
    fts_rows: list[tuple[str, str, str, str, str, str, str]] = []
    seen_keys: set[str] = set()
    for idx, ep in enumerate(episodes or []):
        canonical = episode_cache_key(ep)
        ep_key = ":".join(canonical) if canonical is not None else f"idx:{next_pos + idx}"
        if ep_key in seen_keys:
            continue
        seen_keys.add(ep_key)
        airing_date = ""
        if isinstance(ep, dict):
            raw_date = ep.get("date") or ep.get("airingDate") or ep.get("publishDate") or ""
            airing_date = str(raw_date)[:32]
        rows.append((show_key, ep_key, next_pos, airing_date, json.dumps(ep), ts))
        title, desc, hosts, topics, ep_num = _extract_fts_fields(ep)
        fts_rows.append((show_key, ep_key, title, desc, hosts, topics, ep_num))
        next_pos += 1

    if not rows:
        return 0

    conn.executemany(
        """
        INSERT INTO twittui_episodes (show_id, episode_key, position, airing_date, data_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(show_id, episode_key) DO UPDATE SET
            airing_date = excluded.airing_date,
            data_json = excluded.data_json,
            updated_at = excluded.updated_at
        """,
        rows,
    )
    try:
        conn.executemany(
            "DELETE FROM twittui_episodes_fts WHERE show_id = ? AND episode_key = ?",
            [(r[0], r[1]) for r in fts_rows],
        )
        conn.executemany(
            """
            INSERT INTO twittui_episodes_fts (
                show_id, episode_key, title, description, hosts, topics, episode_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            fts_rows,
        )
    except sqlite3.OperationalError:
        _logger.debug("Skipping FTS5 upsert sync for show %s (FTS5 unavailable)", show_key, exc_info=True)
    return len(rows)


def _migrate_legacy_episode_blob_if_needed(
    conn: sqlite3.Connection,
    show_key: str,
    db_path: str | None = None,
) -> list[Any] | None:
    """Lazily migrate a legacy monolithic episode blob for ``show_key`` into ``twittui_episodes``."""
    cur = conn.cursor()
    cur.execute(
        "SELECT data_json FROM twittui_cache WHERE category = 'episodes' AND cache_key = ?",
        (show_key,),
    )
    legacy_row = cur.fetchone()
    if legacy_row and legacy_row[0]:
        episodes = json.loads(legacy_row[0])
        if isinstance(episodes, list):
            try:
                save_normalized_episodes(conn, show_key, episodes, db_path=db_path)
                conn.commit()
            except sqlite3.Error:
                _logger.debug("Lazy episode migration failed for show %s", show_key, exc_info=True)
        return episodes if isinstance(episodes, list) else None
    return None


def load_normalized_episodes(
    conn: sqlite3.Connection,
    show_id: str,
    db_path: str | None = None,
) -> list[Any] | None:
    """Load a show's episodes from ``twittui_episodes``, lazily migrating legacy blobs if present."""
    show_key = str(show_id)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT data_json FROM twittui_episodes WHERE show_id = ? ORDER BY position ASC",
            (show_key,),
        )
        norm_rows = cur.fetchall()
    except sqlite3.OperationalError:
        norm_rows = []

    if norm_rows:
        return [json.loads(row[0]) for row in norm_rows if row and row[0]]

    return _migrate_legacy_episode_blob_if_needed(conn, show_key, db_path=db_path)


def count_normalized_episodes(
    conn: sqlite3.Connection,
    show_id: str,
    db_path: str | None = None,
) -> int:
    """Return total cached episode count for ``show_id`` using SQL ``COUNT(*)``."""
    show_key = str(show_id)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM twittui_episodes WHERE show_id = ?",
            (show_key,),
        ).fetchone()
        count = int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        count = 0

    if count > 0:
        return count

    migrated = _migrate_legacy_episode_blob_if_needed(conn, show_key, db_path=db_path)
    if migrated is None:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) FROM twittui_episodes WHERE show_id = ?",
        (show_key,),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else len(migrated)


def load_episodes_page(
    conn: sqlite3.Connection,
    show_id: str,
    page: int = 1,
    page_size: int = 50,
    *,
    sort_by: str = "position",
    ascending: bool = True,
    db_path: str | None = None,
) -> list[Any]:
    """Fetch a single paginated slice of a show's episodes directly via SQL ``LIMIT/OFFSET``."""
    show_key = str(show_id)
    page_num = max(1, int(page or 1))
    limit = max(1, int(page_size or 50))
    offset = (page_num - 1) * limit

    if sort_by == "airing_date":
        order_clause = "airing_date ASC, position ASC" if ascending else "airing_date DESC, position ASC"
    else:
        order_clause = "position ASC" if ascending else "position DESC"

    def _query_page() -> list[tuple[Any, ...]]:
        return conn.execute(
            f"SELECT data_json FROM twittui_episodes WHERE show_id = ? ORDER BY {order_clause} LIMIT ? OFFSET ?",
            (show_key, limit, offset),
        ).fetchall()

    try:
        rows = _query_page()
    except sqlite3.OperationalError:
        rows = []

    if rows:
        return [json.loads(r[0]) for r in rows if r and r[0]]

    # Check if this show only exists as a legacy monolithic blob before returning empty
    try:
        existing = conn.execute(
            "SELECT 1 FROM twittui_episodes WHERE show_id = ? LIMIT 1",
            (show_key,),
        ).fetchone()
    except sqlite3.OperationalError:
        existing = None
    if existing is None:
        migrated = _migrate_legacy_episode_blob_if_needed(conn, show_key, db_path=db_path)
        if migrated:
            rows = _query_page()
            return [json.loads(r[0]) for r in rows if r and r[0]]

    return []


def ensure_fts_indexed(
    conn: sqlite3.Connection,
    show_id: str | None = None,
    db_path: str | None = None,
) -> int:
    """Ensure ``twittui_episodes_fts`` is populated for existing ``twittui_episodes`` rows."""
    ensure_cache_schema(conn, db_path=db_path)
    try:
        if show_id is not None:
            show_key = str(show_id)
            ep_count = conn.execute(
                "SELECT COUNT(*) FROM twittui_episodes WHERE show_id = ?",
                (show_key,),
            ).fetchone()[0]
            fts_count = conn.execute(
                "SELECT COUNT(*) FROM twittui_episodes_fts WHERE show_id = ?",
                (show_key,),
            ).fetchone()[0]
            if ep_count == fts_count:
                return 0
            raw_rows = conn.execute(
                "SELECT show_id, episode_key, data_json FROM twittui_episodes WHERE show_id = ?",
                (show_key,),
            ).fetchall()
            fts_rows: list[tuple[str, str, str, str, str, str, str]] = []
            for s_id, ep_key, data_json in raw_rows:
                try:
                    ep = json.loads(data_json)
                except (ValueError, TypeError):
                    continue
                title, desc, hosts, topics, ep_num = _extract_fts_fields(ep)
                fts_rows.append((s_id, ep_key, title, desc, hosts, topics, ep_num))
            _sync_fts_rows_for_show(conn, show_key, fts_rows)
            conn.commit()
            return len(fts_rows)

        ep_count = conn.execute("SELECT COUNT(*) FROM twittui_episodes").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM twittui_episodes_fts").fetchone()[0]
        if ep_count == fts_count:
            return 0
        raw_rows = conn.execute(
            "SELECT show_id, episode_key, data_json FROM twittui_episodes"
        ).fetchall()
        fts_rows = []
        for s_id, ep_key, data_json in raw_rows:
            try:
                ep = json.loads(data_json)
            except (ValueError, TypeError):
                continue
            title, desc, hosts, topics, ep_num = _extract_fts_fields(ep)
            fts_rows.append((s_id, ep_key, title, desc, hosts, topics, ep_num))
        conn.execute("DELETE FROM twittui_episodes_fts")
        if fts_rows:
            conn.executemany(
                """
                INSERT INTO twittui_episodes_fts (
                    show_id, episode_key, title, description, hosts, topics, episode_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                fts_rows,
            )
        conn.commit()
        return len(fts_rows)
    except sqlite3.OperationalError:
        _logger.debug("FTS5 index backfill skipped (FTS5 unavailable)", exc_info=True)
        return 0


def search_episodes_fts(
    conn: sqlite3.Connection,
    query: str,
    show_id: str | None = None,
    limit: int = 200,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Run an indexed SQLite FTS5 full-text search across normalized episode rows."""
    match_expr = _build_fts5_match_query(query)
    if not match_expr:
        return []

    max_rows = max(1, int(limit or 200))
    show_key = str(show_id) if show_id is not None and str(show_id).strip() else None

    if show_key is not None:
        # Ensure legacy blob for this specific show is migrated before searching
        try:
            has_norm = conn.execute(
                "SELECT 1 FROM twittui_episodes WHERE show_id = ? LIMIT 1",
                (show_key,),
            ).fetchone()
        except sqlite3.OperationalError:
            has_norm = None
        if has_norm is None:
            _migrate_legacy_episode_blob_if_needed(conn, show_key, db_path=db_path)
    else:
        # All-shows search must include old cache rows without forcing unrelated
        # cache reads during app startup; migrate them once as part of this search.
        try:
            legacy_keys = conn.execute(
                "SELECT cache_key FROM twittui_cache WHERE category = 'episodes'"
            ).fetchall()
        except sqlite3.OperationalError:
            legacy_keys = []
        for (legacy_key,) in legacy_keys:
            try:
                has_norm = conn.execute(
                    "SELECT 1 FROM twittui_episodes WHERE show_id = ? LIMIT 1",
                    (str(legacy_key),),
                ).fetchone()
                if has_norm is None:
                    _migrate_legacy_episode_blob_if_needed(
                        conn, str(legacy_key), db_path=db_path
                    )
            except (sqlite3.Error, ValueError, TypeError):
                _logger.debug(
                    "Skipping legacy cache migration for show %s during FTS search",
                    legacy_key,
                    exc_info=True,
                )

    ensure_fts_indexed(conn, show_id=show_key, db_path=db_path)

    try:
        if show_key is not None:
            rows = conn.execute(
                """
                SELECT e.data_json
                FROM twittui_episodes_fts AS f
                JOIN twittui_episodes AS e
                  ON e.show_id = f.show_id AND e.episode_key = f.episode_key
                WHERE twittui_episodes_fts MATCH ? AND f.show_id = ?
                ORDER BY bm25(twittui_episodes_fts), e.position ASC
                LIMIT ?
                """,
                (match_expr, show_key, max_rows),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT e.data_json
                FROM twittui_episodes_fts AS f
                JOIN twittui_episodes AS e
                  ON e.show_id = f.show_id AND e.episode_key = f.episode_key
                WHERE twittui_episodes_fts MATCH ?
                ORDER BY bm25(twittui_episodes_fts), e.position ASC
                LIMIT ?
                """,
                (match_expr, max_rows),
            ).fetchall()
        return [json.loads(r[0]) for r in rows if r and r[0]]
    except sqlite3.OperationalError:
        _logger.debug("FTS5 query failed; falling back to SQL LIKE search", exc_info=True)
        tokens = re.findall(r"\w+", query.strip().lower(), flags=re.UNICODE)
        if not tokens:
            return []
        like_clauses = " AND ".join("LOWER(data_json) LIKE ?" for _ in tokens)
        params: list[Any] = [f"%{tok}%" for tok in tokens]
        if show_key is not None:
            sql = (
                f"SELECT data_json FROM twittui_episodes WHERE show_id = ? AND {like_clauses} "
                "ORDER BY position ASC LIMIT ?"
            )
            params = [show_key, *params, max_rows]
        else:
            sql = (
                f"SELECT data_json FROM twittui_episodes WHERE {like_clauses} "
                "ORDER BY position ASC LIMIT ?"
            )
            params.append(max_rows)
        try:
            rows = conn.execute(sql, params).fetchall()
            return [json.loads(r[0]) for r in rows if r and r[0]]
        except sqlite3.Error:
            _logger.debug("SQL LIKE fallback search failed", exc_info=True)
            return []


def delete_persistent_cache(db_path: str | None, category: str | None = None) -> None:
    """Delete one category or clear all persistent cache tables and compact the database."""
    if not db_path:
        return
    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            ensure_cache_schema(conn, db_path=db_path)
            should_vacuum = False
            if category == "episodes":
                conn.execute("DELETE FROM twittui_episodes")
                try:
                    conn.execute("DELETE FROM twittui_episodes_fts")
                except sqlite3.OperationalError:
                    _logger.debug("Skipping FTS5 clear (FTS5 unavailable)", exc_info=True)
                conn.execute("DELETE FROM twittui_cache WHERE category = 'episodes'")
                conn.commit()
                should_vacuum = True
            elif category:
                conn.execute("DELETE FROM twittui_cache WHERE category = ?", (category,))
                conn.commit()
            else:
                conn.execute("DELETE FROM twittui_episodes")
                try:
                    conn.execute("DELETE FROM twittui_episodes_fts")
                except sqlite3.OperationalError:
                    _logger.debug("Skipping FTS5 clear (FTS5 unavailable)", exc_info=True)
                conn.execute("DELETE FROM twittui_cache")
                conn.commit()
                should_vacuum = True

            if should_vacuum and db_path != ":memory:":
                try:
                    conn.execute("VACUUM")
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    _logger.debug("VACUUM/checkpoint skipped on %s", db_path, exc_info=True)
                _restrict_file_permissions(db_path, 0o600)
    except sqlite3.Error:
        _logger.debug("Failed deleting persistent cache (category=%s)", category, exc_info=True)


class _LazySQLiteEpisodesCache(dict):
    """Dictionary backed by normalized SQLite rows that loads per-show episode lists on demand."""

    def __init__(self, db_path: str | None = None, unloaded_keys: set[str] | None = None) -> None:
        super().__init__()
        self._db_path = db_path
        self._unloaded_keys: set[str] = set(unloaded_keys) if unloaded_keys else set()

    def _load_key(self, key: str) -> None:
        self._unloaded_keys.discard(key)
        if not self._db_path:
            return
        try:
            with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                episodes = load_normalized_episodes(conn, key, db_path=self._db_path)
                if episodes is not None:
                    super().__setitem__(key, episodes)
        except (sqlite3.Error, ValueError, TypeError):
            _logger.debug("Lazy load failed for show %s", key, exc_info=True)

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key) or (isinstance(key, str) and key in self._unloaded_keys)

    def __getitem__(self, key: str) -> Any:
        if not super().__contains__(key) and isinstance(key, str) and key in self._unloaded_keys:
            self._load_key(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        if not super().__contains__(key) and isinstance(key, str) and key in self._unloaded_keys:
            self._load_key(key)
        return super().get(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if not super().__contains__(key) and isinstance(key, str) and key in self._unloaded_keys:
            self._load_key(key)
        if super().__contains__(key):
            return super().__getitem__(key)
        self[key] = default
        return default

    def __setitem__(self, key: str, value: Any) -> None:
        if isinstance(key, str):
            self._unloaded_keys.discard(key)
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        was_unloaded = isinstance(key, str) and key in self._unloaded_keys
        if was_unloaded:
            self._unloaded_keys.discard(key)
        if super().__contains__(key):
            super().__delitem__(key)
        elif not was_unloaded:
            raise KeyError(key)

    def pop(self, key: str, *args: Any) -> Any:
        if not super().__contains__(key) and isinstance(key, str) and key in self._unloaded_keys:
            self._load_key(key)
        return super().pop(key, *args)

    def update(self, *args: Any, **kwargs: Any) -> None:
        if len(args) > 1:
            raise TypeError(f"update expected at most 1 arguments, got {len(args)}")
        if args:
            other = args[0]
            if isinstance(other, _LazySQLiteEpisodesCache):
                for k, v in dict.items(other):
                    self[k] = v
                for k in other._unloaded_keys:
                    if not super().__contains__(k):
                        self._unloaded_keys.add(k)
            elif isinstance(other, Mapping):
                for k in other:
                    self[k] = other[k]
            elif hasattr(other, "keys"):
                for k in other.keys():
                    self[k] = other[k]
            else:
                for k, v in other:
                    self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def __iter__(self) -> Any:
        loaded = list(dict.keys(self))
        yield from loaded
        loaded_set = set(loaded)
        for k in list(self._unloaded_keys):
            if k not in loaded_set:
                yield k

    def keys(self) -> Any:
        return KeysView(self)

    def values(self) -> Any:
        return ValuesView(self)

    def items(self) -> Any:
        return ItemsView(self)

    def __or__(self, other: Any) -> Any:
        if not isinstance(other, dict):
            return NotImplemented
        merged = self.copy()
        merged.update(other)
        return merged

    def __ior__(self, other: Any) -> "_LazySQLiteEpisodesCache":
        self.update(other)
        return self

    def clear(self) -> None:
        self._unloaded_keys.clear()
        super().clear()

    def __len__(self) -> int:
        return super().__len__() + len(self._unloaded_keys)

    def __bool__(self) -> bool:
        return bool(super().__len__() or self._unloaded_keys)

    def copy(self) -> "_LazySQLiteEpisodesCache":
        clone = _LazySQLiteEpisodesCache(self._db_path, set(self._unloaded_keys))
        for k, v in dict.items(self):
            dict.__setitem__(clone, k, v)
        return clone

    def count_episodes(self, show_id: str) -> int:
        """Return episode count for ``show_id`` without hydrating unloaded SQLite rows."""
        key = str(show_id)
        if super().__contains__(key):
            val = super().__getitem__(key)
            return len(val) if isinstance(val, list) else 0
        if key not in self._unloaded_keys or not self._db_path or self._db_path == ":memory:":
            return 0
        try:
            with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                return count_normalized_episodes(conn, key, db_path=self._db_path)
        except sqlite3.Error:
            _logger.debug("SQL count_episodes failed for show %s", key, exc_info=True)
            return 0

    def get_page(
        self,
        show_id: str,
        page: int = 1,
        page_size: int = 50,
        *,
        sort_by: str = "position",
        ascending: bool = True,
    ) -> list[Any]:
        """Return one paginated slice of episodes via RAM (if hydrated) or SQL ``LIMIT/OFFSET``."""
        key = str(show_id)
        page_num = max(1, int(page or 1))
        limit = max(1, int(page_size or 50))
        start = (page_num - 1) * limit
        end = start + limit

        if super().__contains__(key):
            items = list(super().__getitem__(key) or [])
            if sort_by == "airing_date":
                items.sort(
                    key=lambda ep: str(
                        (ep.get("date") or ep.get("airingDate") or ep.get("publishDate") or "")
                        if isinstance(ep, dict)
                        else ""
                    ),
                    reverse=not ascending,
                )
            elif not ascending:
                items.reverse()
            return items[start:end]

        if key not in self._unloaded_keys or not self._db_path or self._db_path == ":memory:":
            return []
        try:
            with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                return load_episodes_page(
                    conn,
                    key,
                    page=page_num,
                    page_size=limit,
                    sort_by=sort_by,
                    ascending=ascending,
                    db_path=self._db_path,
                )
        except (sqlite3.Error, ValueError, TypeError):
            _logger.debug("SQL get_page failed for show %s page %s", key, page_num, exc_info=True)
            return []

    def search_fts(
        self,
        query: str,
        show_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Query the normalized SQLite FTS5 index without hydrating full show catalogs into RAM."""
        if not query or not str(query).strip():
            return []
        if not self._db_path or self._db_path == ":memory:":
            return []
        try:
            with sqlite3.connect(self._db_path, timeout=10.0) as conn:
                return search_episodes_fts(
                    conn,
                    str(query),
                    show_id=show_id,
                    limit=limit,
                    db_path=self._db_path,
                )
        except (sqlite3.Error, ValueError, TypeError):
            _logger.debug("SQL FTS5 search failed for query %r", query, exc_info=True)
            return []
