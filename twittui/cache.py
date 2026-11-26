"""Normalized SQLite persistent cache with WAL mode, 24h TTL, and lazy episode loading."""

from __future__ import annotations

from collections.abc import ItemsView, KeysView, Mapping, ValuesView
import hashlib
import json
import os
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


def ensure_cache_schema(conn: sqlite3.Connection, db_path: str | None = None) -> None:
    """Ensure SQLite WAL journal mode, legacy KV table, and normalized episodes table exist."""
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
    _restrict_file_permissions(db_path, 0o600)


def save_normalized_episodes(
    conn: sqlite3.Connection,
    show_id: str,
    episodes: list[Any],
    now: float | None = None,
    db_path: str | None = None,
) -> None:
    """Persist a show's episodes as individual normalized rows in ``twittui_episodes``."""
    ts = time.time() if now is None else now
    show_key = str(show_id)
    ensure_cache_schema(conn, db_path=db_path)

    rows: list[tuple[str, str, int, str, str, float]] = []
    seen_keys: set[str] = set()
    for pos, ep in enumerate(episodes or []):
        ep_key = episode_cache_key_str(ep, fallback_index=pos)
        if ep_key in seen_keys:
            ep_key = f"{ep_key}#dup{pos}"
        seen_keys.add(ep_key)
        airing_date = ""
        if isinstance(ep, dict):
            raw_date = ep.get("date") or ep.get("airingDate") or ep.get("publishDate") or ""
            airing_date = str(raw_date)[:32]
        rows.append((show_key, ep_key, pos, airing_date, json.dumps(ep), ts))

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
    # Remove any legacy monolithic blob row for this show so disk bloat is reclaimed
    conn.execute(
        "DELETE FROM twittui_cache WHERE category = 'episodes' AND cache_key = ?",
        (show_key,),
    )


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

    # Fallback: legacy single-blob JSON row in twittui_cache; migrate lazily on first read
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
        return episodes

    return None


def delete_persistent_cache(db_path: str | None, category: str | None = None) -> None:
    """Delete one category or clear all persistent cache tables and compact the database."""
    if not db_path:
        return
    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            ensure_cache_schema(conn, db_path=db_path)
            if category == "episodes":
                conn.execute("DELETE FROM twittui_episodes")
                conn.execute("DELETE FROM twittui_cache WHERE category = 'episodes'")
                conn.commit()
            elif category:
                conn.execute("DELETE FROM twittui_cache WHERE category = ?", (category,))
                conn.commit()
            else:
                conn.execute("DELETE FROM twittui_episodes")
                conn.execute("DELETE FROM twittui_cache")
                conn.commit()
                if db_path != ":memory:":
                    try:
                        conn.execute("VACUUM")
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    except sqlite3.Error:
                        _logger.debug("VACUUM/checkpoint skipped on %s", db_path, exc_info=True)
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
