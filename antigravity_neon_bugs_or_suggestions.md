**Runtime Environment Verified**: Python 3.12.3, `toga` / `toga-gtk` / `toga-textual` 0.5.7, `textual` 3.7.1, 263 discovered `unittest` cases across 20 test modules.

> **Path Note**: The requested path referenced `/home/mainmeister/PythonProjects/twittui/antigravity_neon_bugs_or_suggestions.md`; because `/home/mainmeister/PythonProjects` does not exist and the active project workspace is `/home/mainmeister/PycharmProjects/twittui`, this report was saved inside the active repository root.

---

## Executive Summary

TwitTUI is an ambitious dual-backend (GTK 3 + Textual TUI) TWiT.tv podcast browser with resilient API/RSS/webpage ingestion, sliding-window rate limiting, tiered fuzzy/phonetic search, and Snap/PyInstaller packaging. However, static inspection and empirical testing uncovered **23 concrete bugs** (spanning security, data loss, UI deadlocks, broken TUI widgets, search/phonetic defects, download failures, Snap packaging issues, and test-suite hazards) alongside **high-impact architectural, performance, and documentation improvements**.

### Findings at a Glance

| Severity | Count | Highlights |
| :--- | :---: | :--- |
| **Critical / High** | 7 | Plaintext API secret in world-readable SQLite cache; XSS regex sanitizer bypasses; RSS XSLT strips its own `<style>` block; `_LazySQLiteEpisodesCache.setdefault()` wipes cached pages; `_run_network` leaks stuck modal overlays on error; `TextualWebView` & `TextualDivider` crash on instantiation; unsafe background-thread UI/dialog access & unguarded concurrent downloads. |
| **Medium** | 13 | Dead GTK auto-scroll to search match; Double Metaphone `TH`/`TCH`/`SCH`/`Ç`/`Ñ` bugs; `tiered_search` omits hosts/topics/teaser from filtering & inverts tier scores; dead RSS cache lookup in `get_available_resolutions`; cache reconciliation double-fetch on sort change; YouTube `glob.glob` fails on `[`/`]` titles; duration (`length`) confused with byte size; FD double-close hazard; TUI `Enter` streams wrong row under multi-select; double redirect resolution; Textual secondary-window `hide()` hangs modal futures; TTY-hanging & `.env`-mutating unit tests; Snap bundles all 20 test files and omits `shared-mime-info` from `stage-packages`. |
| **Low / Edge Cases** | 3 | CLI splash printed on `--help`/Ctrl+C launches default backend/unbounded `StringIO` stdout sink; PyInstaller checks calling interpreter instead of `--python-executable`; `.env` keystroke write storms, custom Club TWiT feed ID loss, deprecated Toga 0.4 dialog calls. |
| **Suggestions** | 7 | Decompose 7,691-line monolith; replace 142 silent `except Exception: pass` blocks; normalize 128 MB SQLite cache & stop blocking cold start; unify dependency manifests; consolidate 4 diverging show maps; repo hygiene; resolve extensive `Technical_review.md` drift. |

---

## Part 1: Confirmed Bugs (Critical & High Severity)

### 1. Plaintext API Secret Stored in World-Readable SQLite Cache
- **Severity**: Critical (Security / Credential Exposure)
- **Location**: `twittui_form.py:295-314`, `twittui_form.py:1064-1066`, `twittui_form.py:2461`
- **Root Cause**:
  `fetch_shows()` persists the shows catalog with the plaintext API credentials concatenated into SQLite's `cache_key` column:
  ```python
  self._save_to_persistent_cache('shows', f"{app_id}:{app_key}", cached_shows_obj)
  ```
  Meanwhile, `get_cache_db_path()` creates `~/.cache/twittui` without restricting permissions (`os.makedirs(user_cache, exist_ok=True)`), and `sqlite3.connect()` creates `twittui_cache.db` with the process default umask (`0o644`). Additionally, splitting on `:` in `_init_persistent_cache_db()` (`key.split(':', 1)`) breaks if `app_id` ever contains a colon.
- **Verified Evidence**:
  Inspecting the live `~/.cache/twittui/twittui_cache.db` confirmed file permissions `0o644` (world-readable) and a `shows` row with a 41-character `cache_key` containing a colon at position 9 (the plaintext `app_id:app_key` pair), contradicting the `0o600` protection enforced for `.env`.
- **Recommended Fix**:
  Hash credentials with SHA-256 (e.g., `hashlib.sha256(f"{app_id}\0{app_key}".encode()).hexdigest()`) before using them as a cache key, and enforce `0o700` on the cache directory and `0o600` on `twittui_cache.db` upon creation.

---

### 2. HTML Sanitizer Fallback Has Multiple XSS Bypasses & Attribute Corruption
- **Severity**: High (Security)
- **Location**: `twittui_form.py:3115-3202`
- **Root Cause**:
  `sanitize_html()` attempts to import `bleach` or `nh3`, neither of which is listed in `requirements.txt`/`pyproject.toml` or installed in `.venv`. Execution therefore always falls back to regex sanitization (lines 3121-3202), which exhibits several verified failures:
  1. **Leading whitespace inside quoted attributes bypasses URI filtering**: `r'\b(href|src)(\s*=\s*)([\"\']?)([^\"\'\s>]+)'` stops at whitespace, so `<a href=" &#106;avascript:alert(1)">x</a>` passes through **completely unmodified**.
  2. **Embedded control characters (tab/newline) bypass scheme detection**: `<a href="java\tscript:alert(1)">x</a>` passes through unmodified, though browsers strip ASCII tabs/newlines inside URI schemes.
  3. **Whitespace before `>` in closing tags leaves script bodies intact**: `re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", ...)` fails on `</script >` or `</SCRIPT\t>`, leaving `alert(1)</script >` in output.
  4. **Dangerous attributes not stripped**: `style="background:url(javascript:...)"`, `formaction`, `srcdoc`, and `xlink:href` pass through untouched.
  5. **Corrupted closing quote**: When neutralizing `href="javascript:alert(1)"`, `_neutralize_schemes()` returns `f'{attr}{eq}{quote}#{quote}'` even though the regex did not consume the trailing quote, emitting malformed `<a href="#"">`.
- **Verified Evidence**:
  Direct execution of `TwitTUIForm.sanitize_html()` produced:
  - `'<a href=" &#106;avascript:alert(1)">x</a>'` → `'<a href=" &#106;avascript:alert(1)">x</a>'`
  - `'<a href="java\tscript:alert(1)">x</a>'` → `'<a href="java\tscript:alert(1)">x</a>'`
  - `'<script>alert(1)</script >'` → `'alert(1)</script >'`
  - `'<a href="javascript:alert(1)" >x</a>'` → `'<a href="#"" >x</a>'`
- **Recommended Fix**:
  Add `nh3` (fast Rust-backed HTML sanitizer with prebuilt wheels) to `pyproject.toml` and `requirements.txt`, and replace the regex fallback with an allowlist-based `html.parser.HTMLParser` implementation that strips control characters before scheme validation.

---

### 3. RSS XSLT Renderer Immediately Strips Its Own `<style>` Block
- **Severity**: High (Functional Bug)
- **Location**: `twittui_form.py:3660-3665`
- **Root Cause**:
  In `render_rss_feed_to_html()`, when `lxml` is installed, lines 3661-3664 inject `feed-style.css` into the XSLT output's `<style>...</style>` tag, and line 3665 immediately passes the entire HTML document through `self.sanitize_html(html_out)`. Because `sanitize_html()` lists `"style"` in `dangerous_tags` (line 3122), it strips the entire `<style>...</style>` block that was just injected (and if `bleach`/`nh3` is installed, it also strips `<!DOCTYPE>`, `<html>`, `<head>`, `<meta>`, `<title>`, and `<body>`).
- **Verified Evidence**:
  Passing a styled HTML document into `sanitize_html()` confirmed `<style>...</style>` is completely removed (`"<style>" in output == False`).
- **Recommended Fix**:
  Sanitize untrusted RSS fields (`description`, `content:encoded`, links) *before* XSLT/HTML assembly, or inject the trusted local CSS `<style>` block *after* sanitizing the body HTML (matching the ElementTree fallback path at lines 3753-3803).

---

### 4. `_LazySQLiteEpisodesCache` Silently Wipes Cached Pages on `setdefault()` and Violates the `dict` Contract
- **Severity**: High (Data Loss / Cache Corruption)
- **Location**: `twittui_form.py:99-162`, `twittui_form.py:6011`, `twittui_form.py:7530`
- **Root Cause**:
  `_LazySQLiteEpisodesCache` subclasses `dict` and overrides `__contains__`, `__getitem__`, `get`, `__setitem__`, `pop`, `clear`, `__len__`, `__bool__`, and `copy`, but omits `setdefault`, `update`, `keys`, `items`, `values`, `__iter__`, and `__delitem__`.
  In CPython, `dict.setdefault()` and `dict.update()` execute in C and bypass overridden Python dunder methods:
  1. On `twittui_form.py:6011` (`fetch_episodes`, `page > 1`), `self._episodes_cache.setdefault(show_id_key, [])` does **not** load an unloaded show from SQLite; it inserts and returns `[]`, and line 6020 then saves that truncated list back to SQLite — **permanently erasing earlier pages from the persistent cache**.
  2. On `twittui_form.py:7530`, `self._episodes_cache.update(worker._episodes_cache)` bypasses `__setitem__`, leaving updated keys inside `_unloaded_keys`.
  3. `list(cache.keys())` returns `[]` even when `len(cache) == 1`.
- **Verified Evidence**:
  Empirically reproduced with a SQLite DB seeded with show `'1636'` (2 episodes):
  - `'1636' in cache` was `True`, `len(cache)` was `1`, yet `list(cache.keys())` returned `[]`.
  - `cache.setdefault('1636', [])` returned `[]` and left `cache['1636'] == []`.
  - `cache.update(snap)` left `'1636'` inside `_unloaded_keys`.
- **Recommended Fix**:
  Subclass `collections.abc.MutableMapping` (wrapping an internal `dict`) or explicitly override `setdefault`, `update`, `__iter__`, `__delitem__`, `keys`, `items`, and `values` so every access properly hydrates or discards `_unloaded_keys`.

---

### 5. Uncaught Exceptions in `_run_network` Permanently Lock the UI Behind Modal Wait/Splash Screens
- **Severity**: High (UI Deadlock)
- **Location**: `twittui_form.py:1168-1175`, `twittui_form.py:1355-1407`, `twittui_form.py:1429-1471`, `twittui_form.py:7494-7550`, `twittui_form.py:7578-7593`
- **Root Cause**:
  ```python
  def _run_network(self, work, done):
      async def run():
          try:
              result = await asyncio.to_thread(work)
              done(result)
          except Exception as e:
              print(f"Network operation failed: {e}")
      self.loop.create_task(run())
  ```
  When `work()` raises any exception (e.g., `sqlite3.Error`, `TimeoutError` from `_rate_limit_wait_changed`, or unexpected `AttributeError`/`TypeError`), `done()` is **never called**. Every caller that holds a modal overlay relies on `done()` to release it:
  - `_refresh_catalog()` leaves `_catalog_wait_held = True`, `SplashScreen` open, and `_api_wait_count` permanently incremented.
  - `load_episodes_for_selected_show()` (`held=True`) never calls `_set_rate_limit_wait(False)`.
  - `on_next_press()` never calls `_set_rate_limit_wait(False)`.
  - `_refresh_show_dates()` stops its sequential chain and never invokes `callback()`.

  In addition, `_refresh_catalog()` lines 1374-1378 contain an unreachable dead-code guard:
  ```python
  if token != getattr(self, '_catalog_request', 0):
      if getattr(self, '_catalog_wait_held', False) and getattr(self, '_catalog_request', 0) == token:
  ```
  The inner condition contradicts the outer `if` and can never execute.
- **Recommended Fix**:
  Add an `on_error` or `on_finally` callback to `_run_network()` (guaranteed to execute on the UI loop in a `finally:` block) so `_api_wait_count`, `_catalog_wait_held`, and `SplashScreen` are always cleanly released. Remove the impossible inner condition on line 1375.

---

### 6. `TextualWebView` and `TextualDivider` Crash Immediately Under Toga 0.5.7 (Breaking In-App Docs in `--tui`)
- **Severity**: High (Runtime Crash)
- **Location**: `toga_textual_backend.py:1337-1388`, `twittui_form.py:3506-3515`
- **Root Cause**:
  1. `toga.WebView.__init__` in Toga 0.5.7 invokes `self._impl.set_user_agent(value)`. `TextualWebView` does not implement `set_user_agent` (nor `get_user_agent`, `set_on_webview_load`, `get_cookies`, or `evaluate_javascript`), causing **every** `toga.WebView()` instantiation in `--tui` mode to immediately raise `AttributeError`. Consequently, **Help -> View README Documentation** and **View API Specification (`twittv.apib`)** can never use the TUI viewer and always fall back to an external web browser (failing on headless SSH/TTY sessions).
  2. Even if `set_user_agent` is added, `TextualWebView.set_content()` passes unescaped plain text to `textual.widgets.Static.update()`, which interprets Rich `[...]` markup by default. Passing `twittv.apib` (which uses API Blueprint `[GET /shows]` syntax) crashes with `rich.errors.MarkupError`. Furthermore, `Static` is non-scrollable, clipping long documentation.
  3. `toga.Divider()` similarly crashes on instantiation with `AttributeError: 'TextualDivider' object has no attribute 'set_direction'`.
- **Verified Evidence**:
  - `toga.WebView()` → `AttributeError: 'TextualWebView' object has no attribute 'set_user_agent'`
  - `toga.Divider()` → `AttributeError: 'TextualDivider' object has no attribute 'set_direction'`
  - `TextualWebView.set_content(..., apib_html)` → `MarkupError: closing tag '[/?{filter%5Bmajor_version%5D,...}]' does not match any open tag`
- **Recommended Fix**:
  Implement the missing Toga 0.5 widget methods on `TextualWebView` and `TextualDivider`, instantiate `Static(..., markup=False)` (or wrap text in `rich.text.Text`), and embed it in a Textual `VerticalScroll` container.

---

### 7. Background Threads Directly Access Live UI Widgets, Spawn Dialogs Off-Thread, and Allow Concurrent Batch Downloads
- **Severity**: High (Concurrency / Thread Safety)
- **Location**: `twittui_form.py:3810-3838`, `twittui_form.py:3856-3918`, `twittui_form.py:4698-4891`
- **Root Cause**:
  1. `on_show_club_url_press()` (line 3838) and `on_open_destination_press()` (line 3917) launch raw `threading.Thread` workers that directly read Toga widgets (`self.url_input.value`, `self.dest_input.value`) and, in their `except` handlers (lines 3832 and 3907), call `host_win.error_dialog(...)` **directly from the background thread** without `loop.call_soon_threadsafe`. On GTK this violates single-thread affinity and risks segfaults/freezes; on Textual it violates event-loop affinity.
  2. `download_episodes_batch()` (spawned on a background thread at line 4889) does **not** use `_network_snapshot()`. It reads live UI widgets (`dest_input`, `block_input`, `show_folders_checkbox`, `show_combo`, `audio_only_checkbox`, `app_id_input`, `app_key_input`, `url_input`) and mutates shared cache dicts (`_memberful_feeds_cache`, `_show_rss_cache`, `_media_webpage_cache`, `_episode_detail_cache`) from the worker thread without locking.
  3. `on_download_press()` never checks `self._is_downloading`. Clicking **Download** while a batch is active spawns a second concurrent download thread fighting over shared `self._is_downloading`, `self._cancel_download`, and `self.progress_bar`.
- **Recommended Fix**:
  Capture all widget values on the UI thread prior to spawning workers (using `_network_snapshot()`), route all dialog calls through a helper that dispatches via `loop.call_soon_threadsafe`, guard `on_download_press()` against overlapping downloads (or queue them cleanly), and protect shared caches with a lock.

---

## Part 2: Confirmed Bugs (Medium Severity)

### 8. GTK Auto-Scroll to Search Match in Episode Details Is Dead Code & Offset-Misaligned
- **Severity**: Medium
- **Location**: `twittui_form.py:7173-7186`, `tiered_search.py:433`
- **Root Cause**:
  1. In `toga-gtk` 0.5.7, `MultilineTextInput._impl.native` is a `Gtk.ScrolledWindow`, whereas the `Gtk.TextView` lives at `desc_input._impl.native_textview`. Line 7179-7180 checks `native = desc_input._impl.native; if hasattr(native, 'get_buffer'):`, which is **always `False`** on GTK, making auto-scrolling completely dead code.
  2. Even once fixed to use `native_textview`, `match_ctx.char_offset` is computed in `tiered_search.find_match_context()` against raw HTML (`ep_data.get('description')`, e.g., `<p>Discussing <b>SpinRite</b>...` → offset 17), whereas `desc_input` holds `clean_html_text(desc_raw)` (`Discussing SpinRite...` → offset 11). The cursor therefore scrolls to the wrong offset (or past the end of the buffer).
- **Recommended Fix**:
  Inspect `getattr(desc_input._impl, 'native_textview', None)` (scrolling via `GLib.idle_add` after the window realizes), and compute `MatchContext` offsets on HTML-cleaned description text matching `desc_input.value`.

---

### 9. Multiple Phonetic Algorithm Bugs & Unreachable Dead Code in `double_metaphone.py`
- **Severity**: Medium
- **Location**: `double_metaphone.py:16, 40, 71, 200, 258-268, 271, 293, 405, 481-493, 533-542, 581-589`
- **Root Cause & Verified Output**:
  1. **Premature stripping creates dead code** (line 16: `s = re.sub(r'[^A-Z]', '', s)`): Removes `'Ç'`, `'Ñ'`, and spaces before entering the main loop. As a result, `elif ch == 'Ç':` (line 71), `elif ch == 'Ñ':` (line 405), and all 11+ space-matching rules (`"VAN "`, `"VON "`, `"SAN "`, `" C"`, `"IER "`, etc.) are unreachable. `padded = s + "     "` (line 40) is unused.
     - Verified: `double_metaphone("GARÇON")` → `('KRN', 'KRN')` (drops `S`); `double_metaphone("PIÑATA")` → `('PT', 'PT')` (drops `N`).
  2. **`TH` and `TCH` slice-length bug** (line 533: `if string_at(current, 3, "TCH", "TH"):`): Extracts a **3-character** slice and tests membership against 2-character `"TH"`, so `"TH"` never matches except at the very end of a word. Meanwhile, 3-character `"TCH"` emits theta `('0', 'T')` and advances `current += 2` instead of emitting `('X', 'X')` and advancing `current += 3`.
     - Verified: `THE` → `('T', 'T')` (should be `('0', 'T')`), `THINK` → `('TNK', 'TNK')` (should be `('0NK', 'TNK')`), `MATCH` → `('M0', 'MT')` (should be `('MX', 'MX')`), `WITCH` → `('A0', 'FT')` (should be `('AX', 'FX')`).
  3. **`GGI` slice-length bug** (line 293: `string_at(current - 1, 4, "GGIE", "GGI")`): 4-character slice cannot match 3-character `"GGI"` mid-word (`AGGI` → `('AK', 'AK')`).
  4. **`SCH` secondary typo** (lines 488-491): Appends `K, K` to `secondary` instead of `S, K` (`SCHOOL` → `('SKL', 'KKL')`, `SCHOONER` → `('SKNR', 'KKNR')`).
  5. **`GN` / `GLI` / `DG` / `WICZ` divergences**: Line 262 checks `substr(current + 1, 1) != "Y"` inside `if substr(current + 1, 1) == 'N':` (tautology); `COGNAC` → `('KNK', 'KKK')`, `SIGN` → `('SN', 'SK')`; `DG` (line 200) emits `T`/`K` instead of `TK`/`TK`; `GLI` (line 271) emits `K`/`L` instead of `KL`/`L`; `WICZ`/`WITZ` (line 581) emits `TSX`/`TFX` instead of `TS`/`FX`.
- **Recommended Fix**:
  Correct the slice lengths and rule emissions against Lawrence Philips' canonical specification (preserving `Ç`/`Ñ` before ASCII normalization), and add a dedicated `test_double_metaphone.py` covering standard test vectors.

---

### 10. Tiered Search Engine Field Omissions, Score Inversion & Partial-Query False Positives
- **Severity**: Medium
- **Location**: `tiered_search.py:185-235`, `tiered_search.py:238-339`, `tiered_search.py:467-602`
- **Root Cause & Verified Output**:
  1. **Field mismatch between filtering and context extraction**: `extract_searchable_text()` (used by `rank_and_filter_episodes()`) omits `hosts`, `guests`, `people`, `staff`, `topics`, `tags`, `categories`, `teaser`, and `snippet`, whereas `get_episode_fields()` includes all of them. Searching `"Leo Laporte"` (in `hosts`) or `"Cryptography"` (in `teaser`) returns **0 results** from `rank_and_filter_episodes()`, even though `find_match_context()` knows how to match them.
  2. **Inverted tier priority between `compute_match_score()` and `find_match_context()`**: `compute_match_score()` runs Tier 2 (Fuzzy) before Tier 3 (Phonetic fallback when `< 75.0`, max score `80.0`) and enforces threshold `80.0` for `< 4`-char tokens. `find_match_context()` reverses this: it checks Phonetic *first* (skipping Fuzzy via `continue`), scores Phonetic `95.0/88.0` above Fuzzy (`<= 90.0`), and omits the short-word threshold.
  3. **Partial multi-word false positives in `find_match_context()`**: Lines 526-540 score each query token independently without verifying that all query words matched; querying `"Episode ZZZZZNOTFOUND"` on `"Episode 100"` returns `MatchContext(match_tier='Exact Match', score=100.0)`.
- **Recommended Fix**:
  Derive `extract_searchable_text()` directly from `get_episode_fields()` so searched fields and inspected fields can never drift; unify tier precedence/thresholds between scoring and context extraction; and require multi-word queries to match all tokens (or pick the highest-signal non-exact token for hover explanations).

---

### 11. Dead RSS Cache Lookup in `get_available_resolutions()`
- **Severity**: Medium
- **Location**: `twittui_form.py:5336-5358` vs `twittui_form.py:2204`
- **Root Cause**:
  `fetch_show_rss_items()` caches show RSS lists under keys `f"{show_key}_audio"` or `f"{show_key}_video"` (line 2204). However, Section 3 of `get_available_resolutions()` queries:
  ```python
  for feed_file in KNOWN_SHOW_FEEDS.get(show_key, []):
      cache_key = f"rss_{feed_file}"
      items = self._show_rss_cache.get(cache_key, [])
  ```
  Nothing in the codebase ever writes keys prefixed with `"rss_"`, so this entire fallback resolution block is dead and never yields RSS quality alternatives.
- **Recommended Fix**:
  Store per-feed items consistently (or look up `f"{show_key}_video"` and `f"{show_key}_audio"` in `_show_rss_cache`).

---

### 12. Episode Cache Reconciliation Loops Twice on Sort Changes & Blocks UI for Minutes on Large Shows
- **Severity**: Medium (Performance & Logic Bug)
- **Location**: `twittui_form.py:5916-6006`, `twittui_form.py:7499-7511`
- **Root Cause**:
  1. When `cached_list` holds partial episodes (e.g., descending) and `fetch_episodes(page=1)` is called with a different sort (ascending/title), `hit_cache` remains `False`, walking every page from `curr_page = 2` onward. Then, if `len(seen_keys) < total_count` (line 5957), a **second** loop `for p in range(2, total_pages + 1):` restarts at page 2 and re-fetches the same pages all over again under the 5 req/min API limit.
  2. `load_episodes_for_selected_show()` eagerly loops `page = 1, 2, 3, ...` until `_episodes_all_loaded` is `True` while holding the modal `RateLimitScreen` open. For shows with 1,000+ episodes (21+ API pages for *Security Now*; 200+ pages for *All TWiT.tv Shows*), first-time selection blocks the UI for **4 to 40+ minutes** (and renders the `Next` button largely redundant).
  3. On every single page, `fetch_episodes()` re-serializes and writes the entire growing episode list to SQLite (O(N²) write amplification).
- **Verified Evidence**:
  On this workstation, `~/.cache/twittui/twittui_cache.db` grew to **134.7 MB (128.4 MiB)** for only **2 shows** in the `episodes` category (`67.6 MB` JSON payload + ~67 MB SQLite page bloat).
- **Recommended Fix**:
  Always fetch and cache canonical newest-first pages (sort client-side in memory); track `fetched_pages` to avoid duplicate requests; normalize episodes into per-episode SQLite rows `(show_id, episode_key, data_json)`; and paginate on demand (or backfill asynchronously without blocking the UI behind a modal).

---

### 13. YouTube Downloads Fail on `[` / `]` Filenames, Misname Audio Containers, and Use Non-Atomic Replace
- **Severity**: Medium
- **Location**: `twittui_form.py:4255-4274`, `twittui_form.py:4355-4372`, `twittui_form.py:4439-4456`, `twittui_form.py:4597-4599`
- **Root Cause**:
  1. `download_youtube_video()` locates downloaded files and cleans stale parts via `glob.glob(f"{temp_prefix}.*")` and `glob.glob(f"{dest_path}.part*")` without `glob.escape()`. Any episode title containing brackets `[...]` (e.g., `"Security Now [Special] 1000"`) causes `glob.glob()` to interpret `[Special]` as a character class and return `[]` (empirically confirmed), failing the download and leaving the `.twittui_yt_...mp4` file orphaned on disk.
  2. When `audio_only=True` and `ffmpeg` is unavailable, `yt-dlp` downloads `.m4a`/`.webm`/`.opus` (`bestaudio[ext=m4a]/bestaudio/best`), which line 4372/4456 blindly renames to `dest_path` (which defaults to `.mp3` from `determine_download_filename()`), producing misnamed audio containers.
  3. Final file promotion executes `os.remove(dest_path)` followed by `os.rename(temp_path, dest_path)` instead of `os.replace(temp_path, dest_path)`, creating a data-loss window if rename fails or the process crashes between the two calls.
- **Recommended Fix**:
  Wrap `temp_prefix` and `dest_path` with `glob.escape()`, align the destination extension to the actual downloaded container when `ffmpeg` is absent, and replace `os.remove` + `os.rename` with atomic `os.replace()`.

---

### 14. Episode Duration (`length`) Confused with Byte Size (`expected_size`) During Batch Downloads
- **Severity**: Medium
- **Location**: `twittui_form.py:4751-4763`
- **Root Cause**:
  `download_episodes_batch()` extracts `expected_size` (in bytes) by iterating:
  ```python
  for k in ['file_size', 'enclosure_length', 'length', 'size', 'bytes', 'content_length']:
  ```
  Throughout `twittui_form.py` (e.g., lines 2132, 5717), top-level `'length'` stores **duration** (not file size). If an episode lacks `file_size`/`enclosure_length` and has a numeric duration > 1000 seconds (e.g., `'3600'` for 1 hour), `expected_size` is erroneously set to `3600` bytes. `is_existing_file_identical()` (line 4162) then rejects every valid local file because `local_size != 3600`, forcing redundant re-downloads.
- **Recommended Fix**:
  Remove `'length'` from top-level size key extraction (only interpret `'length'` as bytes inside RSS enclosure sub-dictionaries).

---

### 15. File Descriptor Double-Close Hazard in `write_restricted_file()`
- **Severity**: Medium
- **Location**: `twittui_form.py:608-624`
- **Root Cause**:
  Once `os.fdopen(fd, ...)` succeeds, the context manager `handle` takes ownership of `fd` and closes it upon exiting the `with` block. If `handle.write(content)` fails (e.g. disk full), `with` closes `fd`, and the outer `except Exception:` block calls `os.close(fd)` a **second time**. In a multi-threaded application, closing an already-recycled FD can silently close another thread's socket, SQLite handle, or download file. Additionally, `os.chmod(file_path, 0o600)` has a TOCTOU window compared to `os.fchmod(fd, 0o600)`.
- **Recommended Fix**:
  Track `fd_owned = True`, set `fd_owned = False` immediately after `os.fdopen(fd, ...)` succeeds, only call `os.close(fd)` when `fd_owned` is `True`, and use `os.fchmod(fd, 0o600)` where supported.

---

### 16. TUI Row Activation (`Enter` / Click) Streams the Wrong Episode When Multi-Select Marks Exist
- **Severity**: Medium (UX Bug)
- **Location**: `twittui_form.py:5470-5471`, `toga_textual_backend.py:1129-1135, 1253-1259`
- **Root Cause**:
  `on_episode_activate(self, widget, row, **kwargs)` discards its `row` argument and calls `await self.on_stream_press(widget)`, which selects `self.episodes_list.selection[0]`. In TUI multi-select mode (`TogaDataTable`), if the user has marked row 0 with `Space` (`☑`), scrolls to row 5, and presses `Enter` (or clicks row 5), `selection[0]` returns row 0 rather than the activated row 5.
- **Recommended Fix**:
  Update `on_stream_press(self, widget=None, target_row=None)` and forward `row` from `on_episode_activate`, streaming `target_row` whenever explicitly provided.

---

### 17. Redundant Stream Redirect Resolution & Unsilenced Browser Launches in TUI Mode
- **Severity**: Medium
- **Location**: `twittui_form.py:779`, `twittui_form.py:997-1005`, `twittui_form.py:5520-5536`
- **Root Cause**:
  1. `on_stream_press()` calls `resolve_stream_url(media_url)` (line 5520) and then passes the result to `launch_stream_safe()` (line 5536), which calls `resolve_stream_url()` **a second time** (line 779) — doubling network HEAD/GET latency on every stream.
  2. For YouTube streams (line 5528), `on_stream_press()` calls `webbrowser.open()` directly instead of `_open_browser_quietly()`, risking TUI display corruption.
  3. `_open_browser_quietly()` uses `contextlib.redirect_stdout`/`redirect_stderr`, which only redirects Python streams — **not** OS file descriptors 1 and 2 inherited by child browser processes (`xdg-open`, Firefox, Chrome) — and mutating global `sys.stdout`/`sys.stderr` is not thread-safe when invoked from background threads (`on_show_club_url_press`, `on_open_destination_press`).
- **Recommended Fix**:
  Add `resolve: bool = True` to `launch_stream_safe()` and pass `resolve=False` from `on_stream_press()`; on POSIX in live TUI mode, launch browsers via `subprocess.Popen(['xdg-open', url], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)` (macOS `open`) instead of mutating `sys.stdout`/`sys.stderr`.

---

### 18. Textual Backend Lifecycle & Widget Gaps (`hide()`, File Dialogs, `ProgressBar`, `ActivityIndicator`, `Table`)
- **Severity**: Medium
- **Location**: `toga_textual_backend.py:728, 739, 1181, 1292-1335, 1390-1409, 1972-1979`
- **Root Cause**:
  1. **Orphaned modal futures on `Window.hide()`** (lines 1974-1977): `_patched_win_hide()` pops every screen above `self.native` with `app_native.pop_screen()` without calling `_finish()` or resolving dialog futures on any modal screens above it, which can leave `await window.dialog(...)` coroutines permanently hung.
  2. **Broken `OpenFileDialog` / `SaveFileDialog` future resolution** (lines 728, 739): Calls `future.done()` directly instead of `_resolve_dialog_future(future, None)`, failing on Toga 0.5's `Dialog`/`AsyncResult` wrapper.
  3. **`TextualProgressBarImpl` drops pre-mount updates** (lines 1292-1335): `set_value()` and `set_max()` only update `self.native` when `is_mounted` is `True`, and `TogaProgressBar` defines no `on_mount` hook. Verified: `toga.ProgressBar(max=200.0, value=75.0)` retains `native.total=100.0, native.progress=0.0`.
  4. **`TextualActivityIndicator.stop()` is a no-op visually** (lines 1390-1409): Toggles `self._running` but never hides or pauses Textual's `LoadingIndicator`.
  5. **`TextualTable` O(N²) incremental updates** (lines 1181, 1227-1251): Every `source_insert`, `source_remove`, or `source_change` calls `clear(columns=True)` and rebuilds the entire `DataTable`.
- **Recommended Fix**:
  Dismiss active modals properly in `_patched_win_hide()`, use `_resolve_dialog_future()` in all dialog classes, add `on_mount()` sync to `TogaProgressBar`, toggle `self.native.display` in `TextualActivityIndicator.start()/stop()`, and apply incremental row operations in `TextualTable`.

---

### 19. Test Suite Hangs Indefinitely on Interactive TTYs, Mutates Real `.env`, and Silently Skips Broken Snap Checks
- **Severity**: Medium (QA / Developer Experience)
- **Location**: `test_install.py:334-348`, `test_security.py:175-182`, `test_episode_search.py:108-123`, `test_tooltips.py:205-215`, `test_snap.py:37-58`
- **Root Cause & Verified Evidence**:
  1. **Interactive TTY hang**: `test_install.py` lines 337 and 345 mock `sys.exit` with a plain `MagicMock` (`patch("sys.exit")`) without `side_effect=SystemExit`. Execution falls through past `sys.exit(0)` in `main.resolve_toga_backend()` straight into the interactive `input("Select backend [1/2]...")` prompt, hanging `python -m unittest discover` indefinitely on any TTY (confirmed: timed out with exit code `124`).
  2. **Silent `.env` mutation**: `test_security.py:175-182` (`test_initial_streamer_migrates_legacy_defaults`), `test_episode_search.py:108-123` (`test_preferences_search_toggles`), and `test_tooltips.py:205-215` (`test_dynamic_audio_only_tooltip`) invoke `save_env_setting()` without mocking it or setting a temporary `SNAP_USER_DATA`, **silently overwriting the user's real `.env` file** whenever tests run (confirmed via `.env` mtime changing during test execution).
  3. **Silently skipped failing Snap test**: `test_snap.py:37-58` wraps all YAML assertions inside `if yaml is not None:`. Because `PyYAML` is not installed in `.venv`, those tests never run — masking the fact that `test_snap.py:56` asserts `"shared-mime-info"` is in `stage-packages`, which is **missing** from `snap/snapcraft.yaml`!
  4. **Event loop leaks**: Multiple test files emit `ResourceWarning: unclosed event loop` because `TwitTUIForm` instances' loops are not closed in `tearDown`.
- **Recommended Fix**:
  Use `patch("sys.exit", side_effect=SystemExit(0))` with `assertRaises(SystemExit)` in `test_install.py`; isolate `save_env_setting()` in test setups (or auto-disable `.env` writes when `app_id == 'org.twit.test'` unless explicitly tested); add `PyYAML` to dev/test dependencies; and fix the `shared-mime-info` discrepancy in `snap/snapcraft.yaml`.

---

### 20. Snap Packaging Bundles All Test Files, Duplicates Modules, Omits `shared-mime-info`, and Cannot Launch Host VLC Under Strict Confinement
- **Severity**: Medium (Packaging / Distribution)
- **Location**: `snap/snapcraft.yaml:64-144`, `snap/local/launcher.sh:12-16`
- **Root Cause & Verified Evidence**:
  1. `unsquashfs -l twittui_1.1.0_amd64.snap` confirmed that `cp -a *.py $CRAFT_PART_INSTALL/` (line 140) and `prime: ["*.py", "*.md"]` ship **all 20 `test_*.py` files, `setup.py`, and `generate_icon.py`** into the root of the production Snap, and duplicate every application module already installed into `lib/python3.12/site-packages` by `pip install .` (line 121).
  2. `shared-mime-info` is listed under `build-packages` (line 97) but **omitted from `stage-packages`** (lines 98-108), even though line 128 runs `update-mime-database $CRAFT_PART_INSTALL/usr/share/mime/` and `test_snap.py:56` expects it in `stage-packages`.
  3. `snap/local/launcher.sh:13` attempts to copy `$SNAP/.env.example`, which does not exist in the repository or Snap.
  4. Under `confinement: strict`, the snap does not stage `vlc`, `mpv`, or `ffmpeg`; the default streamer (`env LC_ALL=C vlc %f`) cannot execute host `/usr/bin/vlc` inside strict confinement.
  5. Local `snapcraft` runs copy the developer's `.env` into `parts/twittui/src/.env` and `parts/twittui/build/.env` (excluded from `prime/` today only via the explicit whitelist, leaving duplicate credential files on disk).
- **Recommended Fix**:
  Explicitly list only runtime modules (or rely solely on the `pip install .` entry point without `cp -a *.py`), add `shared-mime-info` to `stage-packages`, add a `.env.example` template (or remove the dead check), pin build dependencies from a lockfile for reproducibility, and either stage a lightweight player/ffmpeg (`mpv` or `vlc` + `ffmpeg`) or document strict-confinement streaming behavior clearly.

---

## Part 3: Confirmed Bugs (Low Severity & Edge Cases)

### 21. CLI Bootstrap & Fallback Quirks (`main.py`)
- **Location**: `main.py:180-203`, `main.py:258-259`, `main.py:276-285`, `main.py:306-355`
- **Issues**:
  - `show_terminal_splash("Loading TwitTUI, please wait...")` runs on line 306 *before* `resolve_toga_backend(argv)`, printing a loading banner even for `--help`, `--clean`, and `--install`.
  - Pressing `Ctrl+C` (`KeyboardInterrupt`) during the interactive backend prompt (line 258) does not abort startup — it catches `KeyboardInterrupt` and silently launches the default backend.
  - `patch_toga_icons()` and `patch_toga_gtk_app()` are called twice per launch (lines 279-285 and lines 321-325).
  - In the GTK→Textual crash fallback (lines 333-353): `"Couldn’t recognize the image file format"` matches only a curly apostrophe (`’`, U+2019), missing ASCII `Couldn't`; `warnings.filterwarnings` for `[toga_textual]` is not installed; and `(RuntimeError, Exception)` is redundant.
  - `main.py:330` and `toga_textual_backend.py:1804` redirect `stdout` into an unbounded in-memory `io.StringIO()` for the entire app lifetime; redirecting to `open(os.devnull, "w")` (or a bounded/discarding stream) prevents unbounded memory growth.

### 22. PyInstaller Packaging Edge Cases (`installer.py`)
- **Location**: `installer.py:173-177`, `installer.py:215-216`, `installer.py:250-266`, `installer.py:418`
- **Issues**:
  - `build_executable()` checks `importlib.util.find_spec("toga_gtk")` and `"gi"` in the **calling** Python interpreter rather than in `python_executable`, breaking cross-interpreter builds (`--python-executable /usr/bin/python3`).
  - `--hidden-import=gi.overrides.Gtk` and `gi.overrides.Pango` are passed unconditionally even when GTK/`gi` is unavailable or on Windows/macOS.
  - `yt_dlp` is not collected despite being in `requirements.txt`.
  - `find_local_executable_path()` falls back to the first writable directory in `PATH`, which may be an active virtualenv (`.venv/bin`), `~/.cargo/bin`, or `.`.
  - `os.chmod(destination_path, current_mode | 0o755)` widens group/world permissions even under restrictive umasks (`0o077`).
  - `--strip` on Linux can corrupt certain binary wheels / PyGObject shared libraries; consider making it opt-in.

### 23. Configuration, Cleanup, Filename & API Edge Cases (`twittui_form.py`)
- **Location**: `twittui_form.py:571, 1528, 2875-2881, 3455, 3954-4003, 4045, 4133, 5556-5595, 5654, 6697`
- **Issues**:
  - **No input validation & keystroke write storms**: Every Preferences `on_change` handler rewrites `.env` on **every keystroke** without debouncing; `on_block_change` and `on_rate_limit_change` persist invalid non-numeric/negative strings directly to `.env`. `on_rate_limit_change` (line 3972) also replaces the callable `api_rate_limiter.rate_limit = self.get_rate_limit` with a static `int`.
  - **Custom Club TWiT feed IDs silently overwritten**: If a user configures a non-default feed ID (e.g. `.../rss/9055?auth=TOKEN`), `_build_preferences_box()` (line 2879) strips everything before `?auth=` and displays only `TOKEN` next to the hardcoded `9041` prefix; any subsequent edit overwrites `.env` with feed `9041` (line 3994).
  - **Unclean shutdown during downloads**: `on_close_press()` does not set `self._cancel_download = True` or shut down `_LocalHTMLServer`, leaving `.part` files or `yt-dlp` subprocesses behind if closed mid-download.
  - **Unbounded HTML temp files**: `open_html_in_browser()` fallback (line 3455) creates `NamedTemporaryFile(delete=False)` files in `~/.cache/twittui/` that are never pruned.
  - **Filename / folder edge cases**: `determine_download_filename()` (line 4133) and `get_show_folder_name()` (line 4045) do not strip leading/trailing dots (e.g., `..` traversal or hidden dotfiles), control characters (`\x00-\x1f`), or cap filenames to the POSIX 255-byte `NAME_MAX` limit.
  - **Deprecated Toga 0.4 dialog APIs**: 14 call sites still invoke `info_dialog()` / `error_dialog()` (emitting `DeprecationWarning` under Toga 0.5.7) rather than `dialog(toga.InfoDialog(...))` / `dialog(toga.ErrorDialog(...))`.
  - **Heavyweight API credential test**: `test_api_credentials()` (line 5654) queries `shows?range=1000000` (pulling the entire catalog) instead of `shows?page=1&range=1`.
  - **Dead write & unverified URL in `resolve_transcript_url()`**: Line 6697 mutates a discarded local dict `ep_data['transcript_url'] = candidates[0]` and returns an unverified guessed URL that may 404 on older/non-transcribed shows.
  - **Minor**: `TWITTUI_HOMEPAGE_URL` (line 571) has a trailing `.git` suffix; `extract_episode_metadata_fields()` computes `ep_title` redundantly on lines 6720 and 6734; unused imports exist (`MatchContext` in `twittui_form.py`, `Set` in `tiered_search.py`, `List` in `double_metaphone.py`).

---

## Part 4: Suggested Architectural & Quality Improvements

### 1. Decompose the 7,691-Line Monolith (`twittui_form.py`)
`TwitTUIForm` spans **6,806 lines with 164 methods** in a single class (top methods exceed 200-290 lines each), coupling UI layout, GTK-specific layout workarounds, SQLite caching, TWiT REST pagination, RSS/HTML scraping, media URL heuristics, chunked/YouTube downloading, HTML/Markdown rendering, an embedded HTTP server, and `.env` serialization.

**Suggested Package Layout**:
```text
twittui/
├── __init__.py
├── cli.py              # main.py bootstrap, CLI flags, backend fallback
├── config.py           # .env loading/saving (debounced, validated, 0o600)
├── rate_limiter.py     # ApiRateLimiter (decoupled from UI widget callbacks)
├── cache.py            # Normalized SQLite store with TTL & hashed keys
├── catalog.py          # Show registry (single source of truth) & API/archive fetchers
├── rss.py              # Public & Club TWiT RSS parsers (defusedxml)
├── media.py            # Media/resolution extraction, redirect resolution, stream launcher
├── downloader.py       # Single-flight/queued chunked & yt-dlp downloader
├── viewer.py           # Markdown/RSS HTML rendering, nh3 sanitization, _LocalHTMLServer
├── search/
│   ├── tiered_search.py
│   └── double_metaphone.py
└── ui/
    ├── form.py         # TwitTUIForm controller & main window layout
    ├── preferences.py  # Preferences window
    ├── metadata.py     # Episode details & hover dwell controller
    └── textual_backend.py
```

### 2. Replace Pervasive Silent Exception Swallowing with Structured Logging
An AST audit across the 7 source modules found **242 broad `except Exception` handlers**, of which **142 are completely silent `except Exception: pass`** (`twittui_form.py`: 84; `toga_textual_backend.py`: 49; `main.py`: 4; `tiered_search.py`: 3; `installer.py`: 2). This pattern hid bugs #6 (`TextualWebView` crash) and #8 (dead GTK auto-scroll) from developers and tests.
- Narrow exception types where failure modes are known (`OSError`, `LookupError`, `ValueError`).
- Log unexpected failures via `_logger.debug("...", exc_info=True)` and add a `--log-file` / `TWITTUI_LOG_FILE` option for diagnosing TUI issues without polluting stdout.
- Stop shadowing Python's built-in `print` at module level (`twittui_form.py:86`); replace `print(...)` calls directly with `_logger.info()` / `_logger.warning()` / `_logger.debug()`.

### 3. Eliminate Cold-Start Blocking & Normalize SQLite Cache
- **Non-blocking show date scraping**: On cold start, `_refresh_show_dates()` scrapes up to ~146 public archive pages (73 shows × 2 pages) **sequentially** while holding `SplashScreen` and `RateLimitScreen` open. Dismiss the splash screen once the show catalog and initial episodes load, and scrape show date bounds asynchronously in the background with bounded concurrency (e.g., `asyncio.Semaphore(4)`) and a TTL (e.g., 24 hours).
- **Normalized SQLite schema**: Store episodes as individual rows `(show_id TEXT, episode_key TEXT, airing_date TEXT, data_json TEXT, updated_at REAL, PRIMARY KEY (show_id, episode_key))` with `PRAGMA journal_mode=WAL;` and periodic `VACUUM` on cache clear. This eliminates the 128 MB bloat and enables instant SQL-level pagination, deduplication, and full-text search (`FTS5`).

### 4. Unify Dependency & Packaging Metadata
- `pyproject.toml`, `setup.py`, and `requirements.txt` have drifted:
  - `yt-dlp` is in `requirements.txt` but missing from `pyproject.toml` and `setup.py`.
  - Optional/security/performance libraries referenced in code (`defusedxml`, `nh3`/`bleach`, `rapidfuzz`, `lxml`, `PyYAML` for tests) are absent from all manifests.
  - `toga-gtk` is listed as an unconditional core dependency, blocking clean installs on macOS/Windows/headless Linux.
  - `setup.py:8` leaks an unclosed `open("README.md")` handle, and `package_data={"": [...]}` does not behave reliably for `py_modules`-only distributions.
- **Suggestion**: Delete redundant `setup.py` and consolidate on `pyproject.toml` using `[project.optional-dependencies]` (`gtk`, `textual`, `youtube`, `security`, `fast-search`, `dev`), moving source modules into a proper `twittui/` package so package data (`resources/`, `feed-style.*`, `twittv.apib`) is cleanly included via `importlib.resources`.

### 5. Consolidate the Four Diverging Show Registries
Show-to-feed/slug/abbreviation tables are duplicated across four separate dictionaries in `twittui_form.py`:
- `KNOWN_SHOW_FEEDS` (line 510)
- `MEMBERFUL_SHOW_FEEDS` (line 534)
- `abbrevs` inside `search_episodes()` (line 6167)
- `short_map` inside `generate_transcript_slug_candidates()` (line 6569)

Several shows (e.g., *FLOSS Weekly*, *Hands-On Photography*, *This Week in Enterprise Tech*, *This Week in Google*, *All About Android*, *Intelligent Machines*) appear in some tables and are missing from others. Consolidate into a single `SHOW_REGISTRY` dataclass mapping.

### 6. Repository Hygiene & CI Automation
- Remove `twittui.egg-info/` from git tracking (`git rm -r --cached twittui.egg-info`) and add `*.egg-info/`, `*.log`, and `*.spec` to `.gitignore`.
- Remove or relocate untracked/scratch artifacts (`build.log`, `build_verbose.log`, `parts/twittui/*/.env`) and consider moving large static API captures (`shows.json`, `shows_2.json`, `shows_3.json`, `shows_4.json` — ~1.8 MB total, `sn_ballecer.txt`, `scenarios.jsonl`) out of the repository root.
- Add a GitHub Actions CI workflow running `ruff`, `mypy`, and the test suite (both Textual headless and `xvfb-run` GTK tests) with `SNAP_USER_DATA` pointed at a temp directory and `PyYAML` installed.

### 7. Reconcile Extensive Documentation Drift in `Technical_review.md`
`Technical_review.md` (committed `18ea458`) contains numerous statements that contradict the actual implementation:

| Claim in `Technical_review.md` | Actual Code Reality |
| :--- | :--- |
| `sanitize_html` uses `html.parser.HTMLParser` (L192) | Uses regexes with optional `bleach`/`nh3` fallback (`twittui_form.py:3115`). |
| `_LocalHTMLHandler` validates a 32-char hex `?token=<token>` query param (L195-196) | Uses `secrets.token_urlsafe(24)` as the **first URL path segment** (`/<token>/<page>`, `twittui_form.py:827`). |
| `_LocalHTMLServer` shuts down cleanly on termination (L197) | Runs as a daemon thread; `shutdown()`/`server_close()` is never called. |
| `tiered_search.py` applies field multipliers (`Title: 1.3x`, `Hosts: 1.25x`, `Topics: 1.2x`, `Ep#: 1.1x`) and threshold `65.0` (L389-400) | No field multipliers exist; default threshold is `68.0`, and `find_match_context` ranks `Description` (3) > `Hosts` (2) > `Title` (1). |
| `RateLimitScreen` shows a visual countdown (L115) | Shows static label + spinner (`LoadingIndicator`) only (`toga_textual_backend.py:101-103`). |
| `TextualSelectFolderScreen` supports directory creation and breadcrumb tracking (L116) | Provides path text input, `Up` button, and directory tree only (`toga_textual_backend.py:595-624`). |
| `ApiRateLimiter.lock` is a re-entrant lock (L256) | Uses non-reentrant `threading.Lock()` (`twittui_form.py:169`). |
| `patch_toga_gtk_app()` calls `Gtk.Window.set_default_icon_from_file()` (L187) | Sets `interface._app_id = None` and `Gio.ApplicationFlags.NON_UNIQUE` (`twittui_form.py:465-491`). |
| `save_env_setting` uses atomic file replacement (L545) | Fallback writes in-place with `os.O_TRUNC` (`twittui_form.py:610`). |
| `test_caching.py` verifies TTL expiration (L580) | SQLite cache has no TTL or expiration logic (`twittui_form.py:1036-1115`). |
| All 263 tests pass via `python -m unittest discover` (L600-604) | Hangs indefinitely on interactive TTYs in `test_install.py` and silently skips YAML checks in `test_snap.py`. |

---

## Suggested Remediation Priority Order

1. **Immediate (Security & Stability)**:
   - Hash `app_id`/`app_key` in SQLite `cache_key` and lock `twittui_cache.db` permissions to `0o600` (Bug #1).
   - Add `nh3` and fix `sanitize_html()` + RSS XSLT `<style>` stripping (Bugs #2, #3).
   - Fix `_LazySQLiteEpisodesCache` missing `dict` methods (`setdefault`, `update`, `__iter__`, etc.) (Bug #4).
   - Add guaranteed `finally`/error cleanup to `_run_network()` so modals never permanently freeze the UI (Bug #5).
   - Fix `TextualWebView` (`set_user_agent`, `markup=False`, `VerticalScroll`) and `TextualDivider` (`set_direction`) (Bug #6).
2. **Short-Term (Correctness & UX)**:
   - Move thread-unsafe widget reads & error dialogs onto the UI thread and prevent concurrent batch downloads (Bug #7).
   - Fix `test_install.py` TTY hang, isolate `.env` in tests, and add `shared-mime-info` to `snap/snapcraft.yaml` (Bugs #19, #20).
   - Fix GTK search-match auto-scroll (`native_textview` + cleaned-text offset), `glob.escape()` in YouTube downloads, `length`-vs-`size` confusion, `on_episode_activate` row targeting, `write_restricted_file` double-close, and dead RSS cache key in `get_available_resolutions` (Bugs #8, #11, #13, #14, #15, #16).
   - Fix `double_metaphone.py` (`TH`/`TCH`/`SCH`/`Ç`/`Ñ`) and unify `tiered_search.py` field extraction & tier scoring (Bugs #9, #10).
3. **Medium-Term (Architecture & Performance)**:
   - Normalize SQLite episodes table + background non-blocking show-date scraping (Bug #12 + Suggestion #3).
   - Decompose `twittui_form.py` into a clean `twittui/` package, consolidate `pyproject.toml`, reduce silent `except Exception: pass` blocks, migrate deprecated Toga dialog APIs, and update `Technical_review.md`.

