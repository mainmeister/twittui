**Runtime Environment Verified (Baseline Audit)**: Python 3.12.3, `toga` / `toga-gtk` / `toga-textual` 0.5.7, `textual` 3.7.1, 263 discovered `unittest` cases across 20 test modules.
**Post-Remediation Status**: All **23 confirmed bugs** and **7 architectural/quality suggestions** implemented and verified — **335 / 335 `unittest` cases passing across 25 test modules** (`.env` untouched, zero shadowed `print` definitions/calls in `twittui/` or `twittui_form.py`, zero silent or unlogged broad `except Exception` handlers, and URL diagnostics redact credentials, paths, and query values).

> **Path Note**: The requested path referenced `/home/mainmeister/PythonProjects/twittui/antigravity_neon_bugs_or_suggestions.md`; because `/home/mainmeister/PythonProjects` does not exist and the active project workspace is `/home/mainmeister/PycharmProjects/twittui`, this report was saved inside the active repository root.

---

## Executive Summary

TwitTUI is an ambitious dual-backend (GTK 3 + Textual TUI) TWiT.tv podcast browser with resilient API/RSS/webpage ingestion, sliding-window rate limiting, tiered fuzzy/phonetic search, and Snap/PyInstaller packaging. Static inspection and empirical testing originally uncovered **23 concrete bugs** (spanning security, data loss, UI deadlocks, broken TUI widgets, search/phonetic defects, download failures, Snap packaging issues, and test-suite hazards) alongside **7 high-impact architectural, performance, and documentation improvements**. Every finding and suggestion below has now been remediated and covered by automated regression tests.

### Findings at a Glance

| Severity | Count | Status | Highlights |
| :--- | :---: | :---: | :--- |
| **Critical / High** | 7 | **7 / 7 Fixed** | Plaintext API secret in world-readable SQLite cache; XSS regex sanitizer bypasses; RSS XSLT strips its own `<style>` block; `_LazySQLiteEpisodesCache.setdefault()` wipes cached pages; `_run_network` leaks stuck modal overlays on error; `TextualWebView` & `TextualDivider` crash on instantiation; unsafe background-thread UI/dialog access & unguarded concurrent downloads. |
| **Medium** | 13 | **13 / 13 Fixed** | Dead GTK auto-scroll to search match; Double Metaphone `TH`/`TCH`/`SCH`/`Ç`/`Ñ` bugs; `tiered_search` omits hosts/topics/teaser from filtering & inverts tier scores; dead RSS cache lookup in `get_available_resolutions`; cache reconciliation double-fetch on sort change; YouTube `glob.glob` fails on `[`/`]` titles; duration (`length`) confused with byte size; FD double-close hazard; TUI `Enter` streams wrong row under multi-select; double redirect resolution; Textual secondary-window `hide()` hangs modal futures; TTY-hanging & `.env`-mutating unit tests; Snap bundles all 20 test files and omits `shared-mime-info` from `stage-packages`. |
| **Low / Edge Cases** | 3 | **3 / 3 Fixed** | CLI splash printed on `--help`/Ctrl+C launches default backend/unbounded `StringIO` stdout sink; PyInstaller checks calling interpreter instead of `--python-executable`; `.env` keystroke write storms, custom Club TWiT feed ID loss, deprecated Toga 0.4 dialog calls. |
| **Suggestions** | 7 | **7 / 7 Applied** | Decompose 7,691-line monolith; replace 142 silent `except Exception: pass` blocks; normalize 128 MB SQLite cache & stop blocking cold start; unify dependency manifests; consolidate 4 diverging show maps; repo hygiene; resolve extensive `Technical_review.md` drift. |

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
- **Applied Fix & Verification**:
  Implemented `_shows_cache_key_hash()` (SHA-256 over `f"{app_id}\0{app_key}"`) and `_restrict_file_permissions()` (`0o600` on `twittui_cache.db`, `-wal`, and `-shm`; `0o700` on `~/.cache/twittui`) in `twittui/cache.py`, plus automatic startup migration of legacy `app_id:app_key` rows with `PRAGMA secure_delete = ON` in `twittui_form.py`. Verified by `test_critical_fixes.py:test_1_shows_cache_hashes_credentials_enforces_0600_and_migrates_legacy`.

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
- **Applied Fix & Verification**:
  Replaced the regex sanitizer fallback with `_AllowlistHTMLSanitizer` (`html.parser.HTMLParser` allowlist + multi-pass dangerous-tag pre-stripping + entity/control-char URI normalization) in `twittui/viewer.py:sanitize_html_content()` (delegating to optional `bleach`/`nh3` when installed, with `nh3` declared under `security` extras in `pyproject.toml` and `setup.py`). Verified by `test_critical_fixes.py:test_2_sanitize_html_blocks_all_xss_bypasses_and_preserves_valid_html`.

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
- **Applied Fix & Verification**:
  Updated `render_rss_feed_to_html()` in `twittui_form.py` to sanitize untrusted RSS body content before injecting the trusted `feed-style.css` `<style>` block and HTML shell. Verified by `test_critical_fixes.py:test_3_rss_xslt_preserves_style_and_sanitizes_body`.

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
- **Applied Fix & Verification**:
  Implemented `setdefault`, `update`, `__iter__`, `__delitem__`, `keys`, `items`, `values`, `__or__`, `__ior__`, `pop`, `copy`, and `clear` on `_LazySQLiteEpisodesCache` (`twittui/cache.py`), keeping `_unloaded_keys` consistent without eager SQLite hydration. Verified by `test_critical_fixes.py:test_4_lazy_sqlite_cache_setdefault_update_keys_and_delitem`.

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
- **Applied Fix & Verification**:
  - Updated `_run_network(self, work, done, on_error=None, on_finally=None)` (`twittui_form.py:912-972`) with an idempotent `_invoke_finally()` executed inside `async def run()`'s `finally:` block, attached via `task.add_done_callback()` (handling cancellation before the first event-loop tick), and invoked immediately with `coro.close()` if `self.loop.create_task()` raises.
  - Added `_call_run_network()` (`twittui_form.py:974-1012`) to pass `on_error`/`on_finally` directly to `_run_network` in production while remaining backward-compatible with 2-argument `(work, done)` test stubs.
  - Wired all callers to idempotent `on_finally` cleanup and removed the impossible inner condition:
    - `_refresh_catalog()` (`twittui_form.py:1190-1275`): idempotent `catalog_released` guard + `_release_catalog_if_unstarted` `on_finally` callback.
    - `_refresh_show_dates()` (`twittui_form.py:1295-1387`): per-iteration `settled_box` + `_settle_job` `on_finally` callback so `in_flight` decrements and `callback()` fires even if `_set_show_selector_items()` raises or a task is cancelled.
    - `load_episodes_for_selected_show()` (`twittui_form.py:7456-7560`): idempotent `_release_episode_wait` `on_finally` callback.
    - `on_next_press()` (`twittui_form.py:7572-7612`): idempotent `_release_next_wait` `on_finally` callback.
    - `on_search_press()` (`twittui_form.py:7396-7442`): dispatched via `_call_run_network()`.
  - Verified in `test_critical_fixes.py:test_5_network_exceptions_never_leave_wait_or_splash_stuck` (`test_critical_fixes.py:230-361`, covering `work()` exceptions, `asyncio.CancelledError`, `loop.create_task()` failures, `_set_show_selector_items()` errors, and `_refresh_catalog()` scheduling failures) and the full `300 / 300` `unittest` suite.

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
- **Applied Fix & Verification**:
  - Updated `TextualWebView` (`toga_textual_backend.py:1416-1510`) to implement the full Toga 0.5 contract (`get_user_agent`, `set_user_agent`, `set_on_webview_load`, `SUPPORTS_ON_WEBVIEW_LOAD = True`, `SUPPORTS_ON_NAVIGATION_STARTING = False`, `set_content`, `set_url`, `get_url`, `get_cookies` returning `CookiesResult(CookieJar)`, `evaluate_javascript` returning `JavaScriptResult(None)`, and `rehint`).
  - Rendered content and URLs via `Static(..., markup=False)` inside a focusable `VerticalScroll` container (resetting scroll to top on new content), completely preventing `rich.errors.MarkupError` on API Blueprint (`twittv.apib`) and bracketed query URLs (`filter[shows]=...`) both before and after mounting.
  - Updated `_focus_first_content_control()` (`toga_textual_backend.py:1998-2021`) so secondary windows whose root content widget is focusable (such as `TextualWebView`'s `VerticalScroll`) receive automatic keyboard focus upon opening, enabling immediate `Up`/`Down`/`PageUp`/`PageDown` scrolling in `--tui` documentation windows.
  - Updated `TextualDivider` (`toga_textual_backend.py:1512-1540`) to implement `get_direction()`, `set_direction()` (for both `HORIZONTAL` and `VERTICAL`, including dynamic switching), and orientation-aware `rehint()`.
  - Verified in `test_critical_fixes.py:test_6_textual_webview_and_divider_toga05_contract_and_apib_markup` (including a live headless Textual pilot test of `app.show_apib_viewer()` asserting automatic focus and keyboard `pagedown` scrolling on `twittv.apib`).

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
- **Applied Fix & Verification**:
  - Hardened `_show_dialog_threadsafe()` (`twittui_form.py:561-604`, adding `prefer_main` so `main_window` is resolved on the UI thread) and `update_progress()` (`twittui_form.py:1904-1940`) so background threads marshal exclusively via `loop.call_soon_threadsafe()` and **never** fall through to direct off-thread native widget/dialog access if the loop rejects scheduling or is absent.
  - Updated `show_download_complete_dialog()` (`twittui_form.py:4556-4565`) and `download_youtube_video()` (`twittui_form.py:4109-4137`) to route dialogs via `_show_dialog_threadsafe(..., prefer_main=True)` instead of accessing `self.main_window` or calling dialogs directly from worker threads.
  - Captured widget inputs on the UI thread prior to spawning background threads in `on_show_club_url_press()`, `on_open_destination_press()`, and `on_download_press()` (`twittui_form.py:4713-4865`) / `download_episodes_batch()` (`twittui_form.py:4567-4711`) via `_network_snapshot()`, merging resolution-discovery and worker caches back under `self._cache_lock` (`threading.RLock`).
  - Guarded `on_download_press()` against both active downloads (`self._is_downloading`) and re-entrant clicks during `await` resolution prompts (`self._download_starting`), backed by non-blocking `self._download_lock` acquisition in `download_episodes_batch()`.
  - Verified by `test_critical_fixes.py:test_7_offthread_dialogs_use_call_soon_threadsafe_and_concurrent_downloads_blocked` (`test_critical_fixes.py:441-598`, checks `7a`–`7g`, including closed-loop off-thread safety, re-entrant `on_download_press()` blocking during `await prompt_resolution_choice()`, and UI-thread destination capture).

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
- **Applied Fix & Verification**:
  1. **GTK `native_textview` & Realization-Safe Scrolling (`twittui_form.py:7126-7183`)**: Updated `_show_episode_metadata()` so `_scroll_desc_to_match()` targets `desc_input._impl.native_textview` (falling back to `impl.native` / `impl.native.get_child()` if needed), schedules execution via `GLib.idle_add` after `win.show()`, guards against stale idle callbacks if `_metadata_window` has been closed or replaced, safely validates/clamps `char_offset` against `buf.get_char_count()`, places the cursor via `buf.place_cursor(iter_pos)`, scrolls via `textview.scroll_to_iter(iter_pos, 0.1, True, 0.0, 0.2)`, and falls back to `textview.scroll_to_mark(buf.get_insert(), 0.1, True, 0.0, 0.2)` whenever GTK 3 returns `False` prior to completing wrapped line-height validation.
  2. **100% Search-to-UI Offset & Field Parity (`tiered_search.py:189-201, 437-443`, `twittui_form.py:6752-6763`)**: Updated `tiered_search._clean_html_for_search()` to strip HTML tags/entities and unconditionally collapse `\n{3,}` → `\n\n` (matching `TwitTUIForm.clean_html_text()` identically for both HTML and plain-text descriptions), and aligned `TwitTUIForm.extract_episode_metadata_fields()` description key precedence (`description` → `summary` → `body` → `show_notes` → `notes` → `teaser` → `snippet`) with `tiered_search.get_episode_fields()`.
  3. **Verification**: Verified live under real GTK 3.0 (`toga-gtk` 0.5.7 / `xvfb-run` secondary `toga.Window` with 400 wrapped HTML paragraphs: `buf_text_at_offset == 'SpinRite'`, `visible == True`) and via unit tests in `test_medium_fixes.py:47-201` (`test_8_gtk_autoscroll_targets_native_textview_with_cleaned_html_offset`, `test_8b_gtk_autoscroll_offset_parity_for_show_notes_and_plain_newlines`, `test_8c_gtk_autoscroll_falls_back_to_scroll_to_mark_and_skips_stale_window`).

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
- **Applied Fix & Verification**:
  1. **Character Preservation & Padding (`double_metaphone.py:16-38, 72-76, 408-412`)**: Preserved `'Ç'`, `'Ñ'`, and collapsed single spaces prior to encoding, and backed `substr()` with `padded = s + "      "` so `Ç`/`Ñ` branches and all boundary/space-matching rules (`"VAN "`, `"VON "`, `"SAN "`, `" C"`, `"IER "`, `"JOSE "`, trailing `" "`) are live and reachable.
  2. **Canonical Slice Lengths, Emissions & `is_slavo_germanic` Guards (`double_metaphone.py`)**:
     - `C` (`lines 100-104`): `CHAE` emits `('K', 'X')` (`MICHAEL` → `('MKL', 'MXL')`).
     - `D` (`lines 194-205`): `DG` (non-`I/E/Y`) emits `('TK', 'TK')` (`EDGAR` → `('ATKR', 'ATKR')`).
     - `G` (`lines 258-276, 294-311`): Fixed `GN` (`SIGN` → `('SN', 'SKN')`, `COGNAC` → `('KNK', 'KKNK')`, `AGNOSTIC` → `('AKNS', 'ANST')`, tautology removed), `GLI` (`TAGLIARO` → `('TKLR', 'TLR')`), and Italian `AGGI`/`OGGI` (`BAGGIO` → `('PJ', 'PK')`, `AGGI` → `('AJ', 'AK')`, `POGGIO` → `('PJ', 'PK')`) while keeping English hard `-UGGI`/`-IGGI` (`MUGGING` → `('MKNK', 'MKNK')`, `DIGGING` → `('TKNK', 'TKNK')`).
     - `J` & `L` (`lines 345-352, 374-379`): Fixed `J` vowel-context rule to check `not is_slavo_germanic` (replacing dead `not string_at(0, 4, "SAN ")`: `BAJA` → `('PJ', 'PH')`, `WOJAK` → `('AJK', 'FJK')`), and removed empty `secondary.append('')` calls that polluted `len(secondary)` and prematurely terminated the 4-character loop (`CABALLEROS` → `('KPLR', 'KPRS')`).
     - `R` & `S` (`lines 438-440, 468-476, 487-496`): Gated French final `-IER` and `SIO`/`SIA`/`SIAN` on `not is_slavo_germanic` (`ROGIER` → `('RJ', 'RJR')`, `KROGIER` → `('KRJR', 'KRJR')`, `ASIA` → `('AS', 'AX')`, `KASIA` → `('KS', 'KS')`), and fixed `SCH` secondary (`SCHOOL` → `('SKL', 'SKL')`, `SCHOONER` → `('SKNR', 'SKNR')`, `SCHENKER` → `('XNKR', 'SKNK')`).
     - `T`, `W`, & `Z` (`lines 531-545, 569-586, 609-613`): Split `TION`/`TIA`/`TCH` (`('X', 'X')`, `current += 3`, removing non-canonical `"TIEN"`) from `TH`/`TTH` (`('0', 'T')`, `current += 2`), fixed `WICZ`/`WITZ` emissions (`('TS', 'FX')`) and initial `W` fallthrough (`WITZ` → `('ATS', 'FFX')`, `LEWITZ` → `('LTS', 'LFX')`), and fixed `Z` to check `is_slavo_germanic` instead of inverted `not string_at(0, 4, "VAN ", "VON ")` (`AMAZING` → `('AMSN', 'AMSN')`, `LAZY` → `('LS', 'LS')`, `PIZZA` → `('PS', 'PTS')`, `KAZAKH` → `('KSK', 'KTSK')`).
  3. **Verification**: Added 8 dedicated canonical vector test methods in `test_double_metaphone.py` (all passing; AST check confirmed 0 `string_at` slice-length mismatches).

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
- **Applied Fix & Verification**:
  1. **Zero-Drift Field Parity (`tiered_search.py:204-214, 418-448`)**: Derived `extract_searchable_text()` purely from `get_episode_fields()` (`" ".join(field_text for _, field_text in get_episode_fields(episode) if field_text)`), covering `Title`, `Hosts / Guests`, `Topics`, `Description / Show Notes`, `Episode Number`, `Length`, and `Size`, plus a separate `Summary / Teaser` field for any distinct secondary descriptive keys (`teaser`, `summary`, `notes`, `snippet`) present alongside a primary description — ensuring `rank_and_filter_episodes()` and `find_match_context()` always inspect the exact same text without interfering with GTK `Description / Show Notes` offset auto-scrolling.
  2. **Unified Tier 2 / Tier 3 Precedence & Thresholds (`tiered_search.py:298-311, 541-625`)**: Aligned `compute_match_score()` and `find_match_context()` on the same short-word threshold (`max(min_word_threshold, 80.0)` for `< 4`-char tokens; `min_word_threshold` default `68.0`), aligned Tier 3 phonetic fallback (`< 80.0`, scoring `80.0` primary / `72.0` secondary) so weak phonetic hits never outrank stronger fuzzy matches, and normalized multi-space queries (`q_clean = " ".join(q_words)`).
  3. **All-Token Gating & High-Signal Multi-Word Context (`tiered_search.py:627-671`)**: Required every query token to match in `find_match_context()` (eliminating partial-query false positives such as `"Episode ZZZZZNOTFOUND"`), and for mixed exact + fuzzy/phonetic multi-word queries (e.g., `"Security ballacer"`), selected the highest-signal non-exact token (`Description / Show Notes`: `Phonetic Match ("ballacer" ≈ "Ballecer")`) with its aggregate score aligned to `compute_match_score()` (`<= 99.0`) rather than misleadingly reporting `Exact Match (100.0)` on `"Security"`.
  4. **Verification**: Verified by `test_medium_fixes.py:205-285` (`test_10_tiered_search_includes_hosts_topics_teaser_and_blocks_partial_false_positives` and `test_10b_tiered_search_multiword_signal_secondary_teaser_and_threshold_parity`).

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
- **Applied Fix & Verification**:
  1. **Live `_show_rss_cache` Key Lookup & Thread-Safe Snapshotting (`twittui_form.py:2130-2139, 2231-2236, 5351-5398`)**: Updated Section 3 of `get_available_resolutions()` to read the actual `{show_key}_video` and `{show_key}_audio` cache keys populated by `fetch_show_rss_items()` in mode-preferred order (`('audio', 'video')` when `audio_only=True`, else `('video', 'audio')`), snapshotted under `self._cache_lock` (and guarded `_show_rss_cache` reads/writes in `fetch_show_rss_items()` under `self._cache_lock` as well, while preserving optional backward-compatible lookup of any externally seeded `rss_{feed_file}` entries).
  2. **Dict Targets, Integer Episode Numbers & `"All TWiT.tv Shows"` Resolution (`twittui_form.py:5184-5230`)**: Fixed `get_available_resolutions()` with a type-safe `_scalar_str()` helper to extract and stringify `target_num`, `target_title`, `clean_path`, and `ep_id` from `ep_dict` (`episode`/`number`/`episodeNumber`, `title`/`label`, `cleanPath`, `id`) as well as row attributes (preventing empty identifiers, `int.lower()` errors, or non-string attribute leaks into `_match_rss_item()`), fall back to `target.show` / `ep_dict['show_name']` when `show_name` is omitted or `"All TWiT.tv Shows"` is selected, and normalize display-formatted show labels via `_show_names_by_display`.
  3. **Verification**: Verified by `test_medium_fixes.py:290-360` (`test_11_get_available_resolutions_finds_cached_show_rss_entries` and `test_11b_get_available_resolutions_matches_plain_dict_and_all_shows_context`).

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
- **Applied Fix & Verification**:
  1. **Canonical Newest-First Fetching, Deduplicated `fetched_pages` & Gap-Safe Reconciliation (`twittui_form.py:5908-6025`)**: Updated `fetch_episodes()` to always fetch and cache canonical newest-first (`-airingDate`) pages when `sort` is not explicitly supplied (leaving UI sort changes client-side in `update_episodes_display()`), tracked `fetched_pages` so no page is ever re-requested across reconciliation passes, and preserved uncached `tail_new_items`/`tail_acc` entries on any page containing a cache hit instead of dropping the remainder of that page.
  2. **Two-Phase Non-Blocking Backfill & Thread-Local Rate-Limiter Wait Suppression (`twittui_form.py:7537-7713, 1577-1580, 7851-7854`, `twittui/rate_limiter.py:32-43, 81-89`)**: Refactored `load_episodes_for_selected_show()` so Phase 1 loads Page 1 under the modal wait dialog, immediately renders the first 50 episodes, closes the modal wait overlay, and invokes `callback()` (dismissing `SplashScreen`), while Phase 2 backfills remaining pages asynchronously inside `api_rate_limiter.suppress_wait_notifications()` (sharing the global rate-limiter window without re-opening modal wait dialogs). Sort toggles during backfill (`_episodes_backfilling`) sort immediately in memory without restarting Page 1.
  3. **Normalized Per-Episode WAL SQLite Storage & Single Deferred Persist (`twittui/cache.py:141-246`, `twittui_form.py:7562-7684`)**: Normalized episode storage into per-episode `twittui_episodes` rows in WAL mode and deferred SQLite writes via `_defer_episodes_persist` so multi-page loads persist **once** instead of O(N²) per page.
  4. **Verification**: Verified by `test_medium_fixes.py:364-569` (`test_12_fetch_episodes_avoids_double_page_fetch_and_defers_sqlite_writes` and `test_12b_canonical_sort_gap_preservation_and_nonblocking_backfill`) and `test_architecture_suggestions.py`.

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
- **Applied Fix & Verification**:
  1. **`glob.escape()` for `[` / `]` Filenames, `%` Template Escaping & Sidecar Filtering (`twittui_form.py:4170-4224`)**: Escaped `temp_prefix`, `dest_path`, and stem paths with `glob.escape()` across both `_cleanup_stale_parts()` and `_find_and_promote_output()`, escaped literal `%` characters in `outtmpl` (`temp_prefix.replace('%', '%%')`) so titles like `"Security Now [100%]"` never break `yt-dlp`, and excluded `.part` / `.part.*` / `.ytdl` / `.info.json` / `.description` fragments from promotion candidates.
  2. **Container Extension Alignment Without `ffmpeg` & Sibling Skip Detection (`twittui_form.py:4128-4150, 4230-4244`)**: When `ffmpeg` is unavailable, aligned `final_dest` to the real downloaded container for both audio (`.m4a`/`.webm`/`.opus`/`.ogg`/`.aac`/`.mp3`/`.flac`) and video (`.mp4`/`.webm`/`.mkv`/`.mov`/`.m4v`) instead of misnaming them, and updated the pre-download skip check to detect existing aligned sibling containers so re-downloads skip cleanly.
  3. **Validate-Before-Replace Atomic Promotion (`twittui_form.py:4225-4244, 4321-4333, 4389-4400, 4532`)**: Validated `self.is_valid_media_file(found_file)` *before* promoting via atomic `os.replace(found_file, final_dest)` (eliminating both the `os.remove`+`os.rename` data-loss window and the risk of corrupt/HTML downloads overwriting existing valid files or returning false positives via `or dest_path`), and ensured `download_episode_file()` promotes via atomic `os.replace()`.
  4. **Verification**: Verified by `test_medium_fixes.py:573-701` (`test_13_youtube_brackets_filename_and_audio_extension_without_ffmpeg` and `test_13b_youtube_validates_before_replace_skips_aligned_existing_and_escapes_percent`).

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
- **Applied Fix & Verification**:
  1. **Dedicated Byte-Size Extraction Excluding Top-Level `length` (`twittui_form.py:4618-4706, 4756-4790`)**: Extracted `_parse_expected_byte_size()` and `_extract_expected_byte_size(target, media_url=..., matched_resolution=...)` and wired them into `download_episodes_batch()`. Top-level `'length'` (duration) is completely excluded from byte-size extraction, while `'length'` is still honored strictly inside explicit RSS 2.0 `enclosure` / `enclosures` sub-dictionaries (stripping whitespace/commas and rejecting booleans or values `<= 1000`).
  2. **Per-Format Size Alignment**: Prioritized the matched resolution's `'size'` or the format sub-dictionary (`video_hd`, `video_large`, `video_small`, `video_audio`, `audio`) whose URL matches the chosen `media_url` — preventing an HD video's top-level `size` from being passed as `expected_size` when downloading an audio-only `.mp3` format (which would otherwise force redundant re-downloads in `is_existing_file_identical()`).
  3. **Verification**: Verified by `test_medium_fixes.py:705-804` (`test_14_batch_download_ignores_duration_length_as_expected_size` and `test_14b_batch_download_reads_enclosure_length_and_per_format_size`).

---

### 15. File Descriptor Double-Close Hazard in `write_restricted_file()`
- **Severity**: Medium
- **Location**: `twittui_form.py:608-624`
- **Root Cause**:
  Once `os.fdopen(fd, ...)` succeeds, the context manager `handle` takes ownership of `fd` and closes it upon exiting the `with` block. If `handle.write(content)` fails (e.g. disk full), `with` closes `fd`, and the outer `except Exception:` block calls `os.close(fd)` a **second time**. In a multi-threaded application, closing an already-recycled FD can silently close another thread's socket, SQLite handle, or download file. Additionally, `os.chmod(file_path, 0o600)` has a TOCTOU window compared to `os.fchmod(fd, 0o600)`.
- **Recommended Fix**:
  Track `fd_owned = True`, set `fd_owned = False` immediately after `os.fdopen(fd, ...)` succeeds, only call `os.close(fd)` when `fd_owned` is `True`, and use `os.fchmod(fd, 0o600)` where supported.
- **Applied Fix & Verification**:
  1. **Single-Owner FD Lifecycle & `finally:` Cleanup (`twittui/config.py:52-79`, re-exported from `twittui_form.py`)**: Tracked descriptor ownership via `fd_owned = True`, transitioned `fd_owned = False` immediately once `os.fdopen(fd, "w", encoding="utf-8")` succeeds, and moved cleanup into a `finally:` block so `os.close(fd)` is never called after `os.fdopen()` assumes ownership (eliminating double-close on write errors) while still closing raw FDs cleanly on any `os.fdopen()` error or `BaseException` (with `_logger.debug` on close error).
  2. **TOCTOU-Free Permissions & `O_CLOEXEC` (`twittui/config.py:54-69`, `twittui/logging_config.py:48-51`)**: Applied `os.fchmod(fd, 0o600)` directly on the open file descriptor on POSIX (falling back to `os.chmod` only where `fchmod` is unavailable/unsupported) and added `os.O_CLOEXEC` so sensitive `.env`/log file descriptors cannot leak across concurrent child subprocesses.
  3. **Verification**: Verified by `test_medium_fixes.py:808-868` (`test_15_write_restricted_file_no_double_close_on_write_failure` and `test_15b_write_restricted_file_closes_fd_on_fdopen_failure_and_uses_fchmod`) and `test_security.py:test_write_restricted_file_sets_0600_mode`.

---

### 16. TUI Row Activation (`Enter` / Click) Streams the Wrong Episode When Multi-Select Marks Exist
- **Severity**: Medium (UX Bug)
- **Location**: `twittui_form.py:5470-5471`, `toga_textual_backend.py:1129-1135, 1253-1259`
- **Root Cause**:
  `on_episode_activate(self, widget, row, **kwargs)` discards its `row` argument and calls `await self.on_stream_press(widget)`, which selects `self.episodes_list.selection[0]`. In TUI multi-select mode (`TogaDataTable`), if the user has marked row 0 with `Space` (`☑`), scrolls to row 5, and presses `Enter` (or clicks row 5), `selection[0]` returns row 0 rather than the activated row 5.
- **Recommended Fix**:
  Update `on_stream_press(self, widget=None, target_row=None)` and forward `row` from `on_episode_activate`, streaming `target_row` whenever explicitly provided.
- **Applied Fix & Verification**:
  1. **Direct Activated-Row Streaming & Rapid-Activation Superseding (`twittui_form.py:5630-5662`)**: Updated `on_stream_press(self, widget=None, target_row=None)` and `on_episode_activate(self, widget, row, **kwargs)` so activating a row (`Enter` / click via `TogaDataTable.on_data_table_row_selected` in `toga_textual_backend.py:1130-1136`) forwards `target_row=row` and streams the activated row directly rather than `episodes_list.selection[0]`. Added a monotonic `self._stream_request` token inside `stale()` so rapid overlapping activations supersede earlier in-flight stream resolutions instead of launching duplicate media players.
  2. **Verification**: Verified end-to-end on a live headless Textual `TogaDataTable` (`Space` mark on row 0 → `Down` → `Enter` on row 2 streams row 2 while `selection` retains row 0) and on rapid overlapping activations in `test_episode_activation.py:15-134`, alongside `test_medium_fixes.py:875-900` (`test_16_and_17_activate_streams_clicked_row_resolves_once_and_silences_browser_fds`).

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
- **Applied Fix & Verification**:
  1. **Single Redirect Resolution (`twittui/media.py:47-99, 151-192`, `twittui_form.py:351-366, 5713-5741`)**: Added `resolve: bool = True` to `launch_stream_safe()` (both `twittui/media.py` and the `twittui_form.py` wrapper) and passed `resolve=False` from `on_stream_press()` after pre-resolving once with `resolve_stream_url()`. Also expanded `resolve_stream_url()`'s YouTube skip pattern (`youtube.com`, `youtube-nocookie.com`, `youtu.be`, `yt.be`) and ensured `head_resp.close()` always runs in a `finally:` block.
  2. **OS-Level Stdio-Silenced Browser Launches (`twittui_form.py:689-733, 5717-5724`)**: Routed YouTube streaming in `on_stream_press()` through `_open_browser_quietly()`, which in live POSIX Textual TUI mode validates the URL (rejecting empty or leading-`-` option strings) and launches OS openers (`open` on macOS; `xdg-open` with `gio open` / `sensible-browser` fallbacks on Linux/Unix, catching `OSError`) with `stdin`/`stdout`/`stderr=subprocess.DEVNULL` and `start_new_session=True` instead of mutating process-global `sys.stdout`/`sys.stderr`.
  3. **Verification**: Verified by `test_medium_fixes.py:875-967` (`test_16_and_17_activate_streams_clicked_row_resolves_once_and_silences_browser_fds` and `test_17b_youtube_stream_routes_through_quiet_posix_opener_without_mutating_stdio`).

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
- **Applied Fix & Verification**:
  1. **Modal Dismissal & Loop-Safety in `Window.hide()` (`toga_textual_backend.py:239-328, 357-503, 539-717, 2241-2297`)**: Hardened `_patched_win_hide()` (wrapped in `_ensure_active_app()`) to resolve any pending `future`/`_future` via `_resolve_dialog_future()` with `default_result`, mark `_finished = True` / `_close_requested = True`, invoke `top_screen.dismiss(default_result)` on active modals (firing Textual `push_screen(..., callback=...)` handlers) with `pop_screen()` fallback, and guard the loop against non-shrinking stacks (`len(stack) >= before_len`). Made `_finish()` idempotent (`self._finished`) across `TextualDialogScreen`, `TextualChoiceDialogScreen` (now forwarding `ChoiceDialog.default_result`), and `TextualSelectFolderScreen`.
  2. **Unified Dialog Future Resolution (`toga_textual_backend.py:221-237, 745-764`)**: Updated `OpenFileDialog` and `SaveFileDialog` (also preserving `self.file_types`) to resolve via `_resolve_dialog_future(future, None)` so `await window.dialog(...)` works cleanly with Toga 0.5's `Dialog`/`AsyncResult` wrappers across all dialog classes.
  3. **`ProgressBar` Pre-Mount & Indeterminate Sync (`toga_textual_backend.py:1402-1476`)**: Applied pre-mount `set_max()`/`set_value()` updates immediately, added `TogaProgressBar.on_mount()` synchronization, returned `None` from `get_value()` when `max is None` (matching Toga 0.5's indeterminate contract), and clamped/reset `value` cleanly on `max` transitions.
  4. **`ActivityIndicator` Visibility & Animation Timer Control (`toga_textual_backend.py:1605-1662`)**: Introduced `TogaLoadingIndicator(LoadingIndicator)` whose `auto_refresh` property and `on_mount()` synchronize both `display` and Textual's 16 FPS animation timer with `TextualActivityIndicator.start()/stop()`, preventing background timer ticks while stopped and avoiding pre-mount event-loop errors.
  5. **Incremental `TextualTable` Operations (`toga_textual_backend.py:1263-1370`)**: Implemented O(1) tail `add_row()` in `source_insert()` (with negative-index normalization and shift-anchor maintenance), O(1) `remove_row()` in `source_remove()` (preserving and visually refreshing shifted `_marked_rows`), and O(columns) in-place `update_cell(..., update_width=True)` in `source_change()` so cells widen cleanly without `clear(columns=True)` rebuilds.
  6. **Verification**: Verified by `test_medium_fixes.py:976-1200` (`test_18_textual_backend_dialogs_progressbar_indicator_table_and_hide` and `test_18b_textual_backend_edge_cases`).

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
- **Applied Fix & Verification**:
  1. **Interactive TTY Hang Fixed (`test_install.py:334-354`)**: Updated `test_resolve_toga_backend_clean_flag` and `test_resolve_toga_backend_install_flag` to mock `sys.exit` with `side_effect=SystemExit(0)` and `assertRaises(SystemExit)` so `--clean` and `--install` terminate immediately without reaching `input()`. Verified directly under a real PTY (`pty.openpty()`, `< 1s`).
  2. **Real `.env` Isolation & Defense-in-Depth Guard (`twittui_form.py:1462-1469`, `test_security.py:158-186`, `test_episode_search.py:109-127`, `test_tooltips.py:101-122`, `test_preferences.py:22-45, 102-118`, `test_open_destination.py:17-29`)**: Isolated `SNAP_USER_DATA` with `tempfile.TemporaryDirectory()` and restored `os.environ` in test setups, and added an automatic guard in `TwitTUIForm.save_env_setting()` that skips real `.env` writes for `org.twit.test` / `org.twit.test.*` app IDs whenever `SNAP_USER_DATA`/`SNAP_USER_COMMON` is unset (while preserving writes into isolated temp dirs when explicitly set).
  3. **Non-Skippable Snap YAML Checks & `PyYAML` Dev Dependency (`test_snap.py:24-138`, `pyproject.toml:45-49`, `.github/workflows/ci.yml:36`, `snap/snapcraft.yaml:109`)**: Added `"PyYAML>=6.0"` to `pyproject.toml`'s `dev` extras (installed in CI), added `shared-mime-info` to `snap/snapcraft.yaml` `stage-packages`, and extracted an indentation-aware `_extract_yaml_list()` fallback parser in `test_snap.py` (with dedicated `test_yaml_fallback_parser_and_pyyaml_dev_dependency()`) so Snap package assertions always execute even without `PyYAML`.
  4. **Zero Event-Loop Leaks (`toga_textual_backend.py:48-63, 2007-2032`, `twittui_form.py:308-355, 516-519`, `test_backend_factory.py:120-129, 174-182`, `test_open_destination.py:24-29`, `test_tooltips.py:117-122`)**: Broke the `App <-> loop.call_soon_threadsafe` reference cycle via `weakref.ref(self)`, registered `weakref.finalize(..., _close_idle_event_loop, loop)` on Textual `App`, GTK `App`, and `TwitTUIForm` instances, and closed idle test loops in `tearDown`/`finally`, eliminating all `ResourceWarning: unclosed event loop` emissions across the entire suite.
  5. **Verification**: Verified by `test_medium_fixes.py:1205-1260` (`test_19_test_suite_hygiene_env_guard_tty_exit_and_loop_cleanup`), `test_snap.py:24-138`, `test_install.py:334-354`, and full `python -W always::ResourceWarning -m unittest discover` run (zero TTY hangs, zero unclosed event-loop warnings, `.env` untouched).

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
- **Applied Fix & Verification**:
  1. **Clean Runtime-Only Snap Packaging & Secret Hygiene (`snap/snapcraft.yaml:16-28, 64-154`)**: Removed `cp -a *.py` and `*.py`/`*.md` wildcards from `stage`/`prime` (installing Python modules cleanly into site-packages via `pip install --no-deps .`), added `PATH` containing `${SNAP}/bin:${SNAP}/usr/bin`, and added `override-pull:` (`craftctl default` + stripping `.env` / `*.env`, `.git`, `.venv`, `parts`, `stage`, `prime`, `.scratch`, `*.snap` while preserving `.env.example`) so local `snapcraft` runs never retain developer `.env` credential copies; also removed the stale `parts/twittui/{src,build}/.env` duplicates.
  2. **Reproducible Dependency Lockfile (`requirements-snap.txt:1-27`, `snap/snapcraft.yaml:126-130`)**: Created `requirements-snap.txt` pinning all 25 verified `core24` / Python 3.12 runtime packages with exact `==` versions and wired `override-build:` to install from `requirements-snap.txt` + `pip install --no-deps .`.
  3. **`shared-mime-info`, Bundled Media Tools & Strict-Confinement Streaming (`snap/snapcraft.yaml:110-112`, `snap/local/launcher.sh:5-36`, `.env.example:1-20`, `twittui_form.py:1438-1467, 3883-3891`)**: Added `shared-mime-info`, `mpv`, and `ffmpeg` to `stage-packages`; updated `snap/local/launcher.sh` to prepend `$SNAP/bin:$SNAP/usr/bin` to `PATH` and initialize `$SNAP_USER_DATA/.env` by atomically hard-linking a fully written temporary file with `0600` permissions, without replacing an existing configuration; the launcher and `_default_streamer_template()` prefer bundled `mpv %f` whenever present, even if host VLC is visible. Fixed `.env.example` (`TWITCLUBSHOWFOLDERS=0` and commented-out optional keys so `load_twittui_dotenv(override=True)` never clobbers launcher-exported `TWITCLUBSTREAMER`/`TWITCLUBDESTINATION`) and migrated the legacy VLC default in strict Snap environments.
  4. **Verification**: Verified via `bash -n snap/local/launcher.sh`, `test_snap.py` (10 tests, including a launcher integration check), and `test_medium_fixes.py:1265-1326` (`test_20_snap_strict_confinement_streamer_and_env_template`).

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
- **Applied Fix & Verification**:
  1. **Deferred Splash & Clean `Ctrl+C` Abort (`main.py:268-289, 358-375, 434-435`)**: Moved `show_terminal_splash()` after `resolve_toga_backend(argv)` so `--help`, `--clean`, and `--install` exit cleanly without emitting loading or closing banners, and updated `KeyboardInterrupt` handling during the interactive backend prompt to abort cleanly with `sys.exit(130)`.
  2. **Deduplicated Startup Patching (`main.py:305-316`, `twittui_form.py:241-355`)**: Removed duplicate `patch_toga_icons()`/`patch_toga_gtk_app()` invocations from `main()` (keeping idempotent `_twittui_*_patched` guards in `twittui_form.py`).
  3. **Apostrophe-Agnostic GTK→Textual Fallback (`main.py:360-433`)**: Matched `"recognize the image file format"` (covering both ASCII `'` and curly `’` U+2019), dropped the redundant `(RuntimeError, Exception)` tuple, applied `_configure_textual_warnings()`, closed any stale idle GTK event loop and reset `toga.App.app = None` before constructing the fallback Textual app, and cleared Toga backend/factory caches.
  4. **Zero-Allocation Text Stream Sinks & `StderrRedirector` Compliance (`main.py:21-35, 333-358`, `toga_textual_backend.py:2076-2108`)**: Replaced unbounded `io.StringIO()` stdout sinks with zero-allocation `_NullTextIO` / `_DiscardingTextIO` implementing standard text-I/O attributes/methods (`encoding`, `errors`, `closed`, `write`, `writelines`, `flush`, `isatty`, `writable`, `readable`), and returned integer character counts from `StderrRedirector.write()`.
  5. **Verification**: Verified by `test_low_fixes.py:36-135` (`test_21_cli_bootstrap_splash_order_ctrl_c_fallback_and_null_sink` and `test_21b_cli_fallback_resets_stale_app_curly_apostrophe_and_stream_contract`).

### 22. PyInstaller Packaging Edge Cases (`installer.py`)
- **Location**: `installer.py:173-177`, `installer.py:215-216`, `installer.py:250-266`, `installer.py:418`
- **Issues**:
  - `build_executable()` checks `importlib.util.find_spec("toga_gtk")` and `"gi"` in the **calling** Python interpreter rather than in `python_executable`, breaking cross-interpreter builds (`--python-executable /usr/bin/python3`).
  - `--hidden-import=gi.overrides.Gtk` and `gi.overrides.Pango` are passed unconditionally even when GTK/`gi` is unavailable or on Windows/macOS.
  - `yt_dlp` is not collected despite being in `requirements.txt`.
  - `find_local_executable_path()` falls back to the first writable directory in `PATH`, which may be an active virtualenv (`.venv/bin`), `~/.cargo/bin`, or `.`.
  - `os.chmod(destination_path, current_mode | 0o755)` widens group/world permissions even under restrictive umasks (`0o077`).
  - `--strip` on Linux can corrupt certain binary wheels / PyGObject shared libraries; consider making it opt-in.
- **Applied Fix & Verification**:
  1. **Cross-Interpreter Package Probing (`installer.py:217-257`)**: Added `_probe_packages_in_interpreter()` to probe optional packages (`toga_gtk`, `gi`, `yt_dlp`, `defusedxml`, `nh3`) inside the target `--python-executable` via subprocess when it differs from `sys.executable`, returning `set()` on cross-probe failure rather than leaking host-interpreter packages.
  2. **Platform-Scoped `gi.overrides` & Complete Collection (`installer.py:325-343`)**: Gated `--hidden-import=gi.overrides.Gtk` and `gi.overrides.Pango` on `"gi" in optional_available and platform.system() not in ("Windows", "Darwin")`, and collected `twittui`, `yt_dlp`, `defusedxml`, and `nh3` when present in the target interpreter.
  3. **Safe `PATH` Resolution (`installer.py:136-214`)**: Filtered relative paths (`.`/`./`), `/tmp`/`/var/tmp`/`/`, active `VIRTUAL_ENV` / `CONDA_PREFIX` / `sys.prefix` virtualenvs, and language-toolchain paths (`/.venv/`, `/venv/`, `/.conda/`, `/.cargo/`, `/.rustup/`, `/.nvm/`, `/.pyenv/`, `/.rbenv/`, `/.asdf/`, `/.poetry/`, `/node_modules/`) out of `find_local_executable_path()`.
  4. **Umask-Safe Atomic Binary Install & Opt-In `--strip` (`installer.py:289-293, 463-526, 585-605`, `main.py:172-177, 221-229`)**: Made `--strip` opt-in (`strip_binary=False` by default, exposed as `--strip` in both `installer.py` and `main.py`), staged the copied binary in the target directory, applied `(0o755 & ~current_umask) | 0o700` inside a `try/finally` umask restore block, and promoted via atomic `os.replace()` (preventing `ETXTBSY` on live upgrades and removing any leftover staged file on error).
  5. **Verification**: Verified by `test_low_fixes.py:140-279` (`test_22_installer_cross_probe_path_exclusions_umask_and_opt_in_strip` and `test_22b_installer_macos_gi_gate_main_strip_conda_path_and_atomic_install`) and `test_install.py`.

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
- **Applied Fix & Verification**:
  1. **Debounced & Validated `.env` Persistence (`twittui_form.py:625-683, 3140-3149, 3926-3962`)**: Added 0.35s UI-loop debouncing via `_schedule_env_save()` / `_flush_pending_env_saves()` (cancelling stale pending writes if a field reverts to its last-saved value, and flushing on Preferences close and app exit), rejected non-numeric/non-positive values in `on_block_change()` and `on_rate_limit_change()`, and kept `api_rate_limiter.rate_limit` bound to the callable `self.get_rate_limit` getter.
  2. **Custom Club TWiT Feed ID Preservation (`twittui_form.py:2895-2914, 3550-3562, 3978-3999`)**: Preserved non-default Memberful feed IDs (e.g. `.../rss/9055?auth=TOKEN`) across `_build_preferences_box()`, `on_url_change()`, and `get_full_club_twit_url()`.
  3. **Clean Shutdown & Active `yt-dlp` Subprocess Termination (`twittui_form.py:481, 685-730, 4379-4449, 5831-5889`)**: Tracked active `yt-dlp` subprocesses in `self._active_download_proc` (closing `proc.stdout` cleanly in `finally:`), added `_terminate_active_download_proc()` (escalating `terminate()` → `kill()` on timeout) invoked by both `_cleanup_resources_for_exit()` (`on_close_press`) and `on_cancel_press()`, flushed pending `.env` saves, and shut down `_LocalHTMLServer` cleanly.
  4. **Bounded `0o600` Preview HTML Files (`twittui_form.py:3390-3438`)**: Pruned stale `twittui_preview_*.html` files in `~/.cache/twittui/` (retaining `<= 5`) and tightened permissions via `os.fchmod(fd, 0o600)` inside a context-managed `NamedTemporaryFile` before writing HTML content.
  5. **Filesystem-Safe Filenames & Folders (`twittui_form.py:4001-4157`)**: Added `_sanitize_fs_component()` stripping control characters (`\x00-\x1f`, `\x7f`), path separators, leading/trailing dots, escaping Windows reserved device basenames even with extensions (`CON.txt`, `COM1.mp4`) and superscript variants (`COM¹`–`COM³`, `LPT¹`–`LPT³`), and capping UTF-8 byte length to POSIX 255-byte `NAME_MAX`.
  6. **Toga 0.5 Dialogs, Lightweight API Test, Transcript Resolution & Cleanups (`twittui_form.py:1-80, 534-578, 5915-5951, 6854-6968`, `twittui/config.py:17`)**: Migrated all 14 dialog sites to Toga 0.5 `InfoDialog`/`ErrorDialog` via `_present_window_dialog()` (zero `DeprecationWarning`s), switched `test_api_credentials()` to `shows?page=1&range=1`, removed dead dict mutation and gated unverified transcript URL guesses behind `allow_guess=False`, removed `.git` from `TWITTUI_HOMEPAGE_URL`, eliminated duplicate `ep_title` extraction, and removed all unused imports across `twittui_form.py`, `tiered_search.py`, and `double_metaphone.py`.
  7. **Verification**: Verified by `test_low_fixes.py:285-471` (`test_23a`, `test_23b`, and `test_23c`).

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
- **Applied Implementation & Verification**:
  Completed the full architectural decomposition of the 8,109-line `twittui_form.py` monolith into the complete `twittui/` package layout:
  - **Core Package (`twittui/`)**: `_compat.py` (shared `PROJECT_ROOT`, `compat_attr`, `ApiRateLimiter`/`api_rate_limiter`, `launch_stream_safe`), `cli.py`, `config.py` (`ConfigMixin` + `.env`/`0o600` helpers), `rate_limiter.py`, `cache.py`, `shows.py`, `catalog.py` (`CatalogMixin`), `rss.py` (`RssMixin`), `media.py` (`MediaMixin`), `downloader.py` (`DownloaderMixin`), `viewer.py` (`ViewerMixin`), and `logging_config.py`.
  - **Search & UI Subpackages**: `twittui/search/{__init__,tiered_search,double_metaphone}.py` and `twittui/ui/{__init__,form,preferences,metadata,textual_backend}.py` (`TwitTUIForm` composing all 8 cohesive mixins in `twittui/ui/form.py`).
  - **Thin Facade & Packaging**: Reduced `twittui_form.py` from **8,109 lines → 173 lines (-97.9%)** as a backward-compatibility facade preserving 100% of historical imports and test monkeypatch targets; updated `pyproject.toml` and `setup.py` for `twittui`, `twittui.search`, and `twittui.ui`, and bundled runtime help, API, RSS styles, and icons under `twittui/resources/` with package-relative lookup.
  - **Verification**: Verified by `test_architecture_suggestions.py` (`test_twittui_package_exports_and_form_compat`, `test_monolith_decomposed_into_package_layout`, `test_package_runtime_resources_and_icon_fallback`, `test_no_silent_broad_except_pass_handlers_remain` over `twittui/**/*.py`, `test_packaging_hygiene_and_ci_workflow`) and full 332-test suite.

### 2. Replace Pervasive Silent Exception Swallowing with Structured Logging
An AST audit across the 7 source modules found **242 broad `except Exception` handlers**, of which **142 are completely silent `except Exception: pass`** (`twittui_form.py`: 84; `toga_textual_backend.py`: 49; `main.py`: 4; `tiered_search.py`: 3; `installer.py`: 2). This pattern hid bugs #6 (`TextualWebView` crash) and #8 (dead GTK auto-scroll) from developers and tests.
- Narrow exception types where failure modes are known (`OSError`, `LookupError`, `ValueError`).
- Log unexpected failures via `_logger.debug("...", exc_info=True)` and add a `--log-file` / `TWITTUI_LOG_FILE` option for diagnosing TUI issues without polluting stdout.
- Stop shadowing Python's built-in `print` at module level (`twittui_form.py:86`); replace `print(...)` calls directly with `_logger.info()` / `_logger.warning()` / `_logger.debug()`.
- **Applied Implementation & Verification**:
  - Added `twittui/logging_config.py` (`configure_logging`, `get_logger`, `reset_logging`) with `--log-file` / `--log-level` CLI flags (`main.py`) and `TWITTUI_LOG_FILE` / `TWITTUI_LOG_LEVEL` env vars (`0o600` + `O_CLOEXEC` log files; silent `NullHandler` and `propagate = False` by default).
  - Redacted logged URLs to scheme and host only, preventing signed query parameters, URL userinfo, and sensitive path tokens from entering diagnostic logs.
  - Removed module-level `print` shadowing (`quiet_print`) from `twittui/_compat.py`, `twittui_form.py`, and all `twittui/` modules, migrating all **84** shadowed `print(...)` calls across 9 modules (`twittui/catalog.py`: 9, `twittui/config.py`: 2, `twittui/downloader.py`: 29, `twittui/media.py`: 2, `twittui/rss.py`: 3, `twittui/viewer.py`: 16, `twittui/ui/form.py`: 19, `twittui/ui/metadata.py`: 3, `twittui/ui/preferences.py`: 1) directly to structured `_logger.info(...)` / `_logger.warning(...)` calls.
  - Narrowed known failure modes to specific exception types (`OSError`, `ValueError`, `TypeError`, `AttributeError`, `ImportError`, `NoMatches`, `RuntimeError`, `OverflowError`, `subprocess.SubprocessError`) across `toga_textual_backend.py`, `installer.py`, `twittui/config.py`, `twittui/downloader.py`, `twittui/media.py`, `twittui/rss.py`, and `twittui/ui/metadata.py`.
  - Eliminated all 142+ broad silent `except Exception: pass` handlers and added direct `_logger.debug(..., exc_info=True)` / `_logger.warning(..., exc_info=True)` diagnostics to every remaining broad `except Exception:` block across `toga_textual_backend.py`, `installer.py`, `twittui/catalog.py`, `twittui/config.py`, `twittui/ui/form.py`, and `twittui/ui/metadata.py` (**0** unlogged broad handlers remaining).
  - Verified by `test_architecture_suggestions.py` (`test_structured_logging_file_permissions_and_cli_flags`, `test_signed_url_details_are_redacted_from_logs`, `test_no_silent_broad_except_pass_handlers_remain`, `test_no_print_shadowing_or_unlogged_broad_exceptions`) enforcing zero `print` shadowing, zero unlogged broad `except` handlers across all core files, and verified `--log-file` runtime emission with zero `sys.stdout` pollution.

### 3. Eliminate Cold-Start Blocking & Normalize SQLite Cache
- **Non-blocking show date scraping**: On cold start, `_refresh_show_dates()` scrapes up to ~146 public archive pages (73 shows × 2 pages) **sequentially** while holding `SplashScreen` and `RateLimitScreen` open. Dismiss the splash screen once the show catalog and initial episodes load, and scrape show date bounds asynchronously in the background with bounded concurrency (e.g., `asyncio.Semaphore(4)`) and a TTL (e.g., 24 hours).
- **Normalized SQLite schema**: Store episodes as individual rows `(show_id TEXT, episode_key TEXT, airing_date TEXT, data_json TEXT, updated_at REAL, PRIMARY KEY (show_id, episode_key))` with `PRAGMA journal_mode=WAL;` and periodic `VACUUM` on cache clear. This eliminates the 128 MB bloat and enables instant SQL-level pagination, deduplication, and full-text search (`FTS5`).
- **Applied Implementation & Verification**:
  - **Non-blocking Cold-Start Show-Date Scraping (`twittui/ui/form.py`, `twittui/catalog.py`, `twittui/ui/preferences.py`)**: Refactored `_refresh_catalog()` so `SplashScreen` and `_catalog_wait_held` / `RateLimitScreen` dismiss immediately once the show catalog and initial selected show's Page 1 episodes complete, while `_refresh_show_dates()` scrapes missing/expired archive date bounds asynchronously in the background with bounded concurrency (`max_concurrent=4`). Added live runtime 24-hour TTL tracking (`SHOW_DATE_BOUNDS_TTL_SECONDS = 86400`, `_show_date_cache_ts`) alongside startup SQLite TTL purging so long-running sessions automatically expire and refresh stale show date bounds without blocking startup.
  - **Normalized SQLite Schema, SQL Pagination, Deduplication, `FTS5` & `VACUUM` (`twittui/cache.py`, `twittui/catalog.py`)**: Implemented normalized `twittui_episodes(show_id, episode_key, position, airing_date, data_json, updated_at, PRIMARY KEY (show_id, episode_key))` with `PRAGMA journal_mode = WAL`, lazy on-first-read migration of legacy monolithic `twittui_cache` blobs, canonical SQL-level deduplication (`save_normalized_episodes()` and incremental `upsert_normalized_episodes()`), instant SQL `LIMIT/OFFSET` pagination (`load_episodes_page()`, `count_normalized_episodes()`, `_LazySQLiteEpisodesCache.get_page()` / `count_episodes()`, wired into `CatalogMixin.fetch_episodes()`), an indexed SQLite `FTS5` virtual table (`twittui_episodes_fts`, `ensure_fts_indexed()`, `search_episodes_fts()`, `_LazySQLiteEpisodesCache.search_fts()`, integrated as Tier 4b in `CatalogMixin.search_episodes()`), and `VACUUM` + `PRAGMA wal_checkpoint(TRUNCATE)` + `0o600` permission hardening on both `category='episodes'` and full cache clear. Deferred first-page loads bypass full-cache reconciliation so partial archives cannot block startup; incomplete backfills preserve the prior cache, and cache clearing invalidates active workers so stale results cannot repopulate memory or SQLite.
  - **Verification**: Verified by `test_architecture_suggestions.py` (`test_normalized_episodes_table_wal_mode_and_roundtrip`, `test_legacy_episode_blob_lazily_migrated_on_first_read`, `test_all_shows_fts_search_migrates_legacy_episode_blobs`, `test_show_date_bounds_24h_ttl_expiration`, `test_refresh_show_dates_bounded_concurrency`, `test_cold_start_nonblocking_date_scraping_and_runtime_ttl`, `test_normalized_sqlite_pagination_deduplication_fts5_and_vacuum`) and `test_show_catalog.py` (`test_refresh_catalog_releases_wait_and_splash_after_episodes_while_dates_scrape_in_background`, `test_refresh_catalog_holds_wait_dialog_when_dates_finish_before_episodes`, `test_deferred_first_episode_page_does_not_reconcile_entire_partial_cache`, `test_incomplete_background_backfill_preserves_existing_episode_cache`, `test_clear_cache_invalidates_active_episode_backfill`).

### 4. Unify Dependency & Packaging Metadata
- `pyproject.toml`, `setup.py`, and `requirements.txt` have drifted:
  - `yt-dlp` is in `requirements.txt` but missing from `pyproject.toml` and `setup.py`.
  - Optional/security/performance libraries referenced in code (`defusedxml`, `nh3`/`bleach`, `rapidfuzz`, `lxml`, `PyYAML` for tests) are absent from all manifests.
  - `toga-gtk` is listed as an unconditional core dependency, blocking clean installs on macOS/Windows/headless Linux.
  - `setup.py:8` leaks an unclosed `open("README.md")` handle, and `package_data={"": [...]}` does not behave reliably for `py_modules`-only distributions.
- **Suggestion**: Delete redundant `setup.py` and consolidate on `pyproject.toml` using `[project.optional-dependencies]` (`gtk`, `textual`, `youtube`, `security`, `fast-search`, `dev`), moving source modules into a proper `twittui/` package so package data (`resources/`, `feed-style.*`, `twittv.apib`) is cleanly included via `importlib.resources`.
- **Applied Implementation & Verification**:
  - **Deleted Redundant `setup.py` & Consolidated on `pyproject.toml`**: Removed `setup.py` (eliminating manifest drift and its unclosed `open("README.md")` handle) and made `pyproject.toml` (`setuptools.build_meta`) the single PEP 621 / PEP 517 build manifest. `requirements.txt` now contains only `.` so pip resolves runtime requirements from package metadata; CI installs the project with its selected extras.
  - **Headless-Linux-Safe Core Dependencies & Optional Extras**: Replaced the `toga` metapackage with `toga-core` and removed `toga-gtk` from unconditional core `[project].dependencies` (unblocking clean installs on headless Linux and non-Linux platforms), retained `yt-dlp` in core dependencies, and defined `[project.optional-dependencies]` extras: `gtk` (`toga-gtk`, `PyGObject`, `pycairo` with `sys_platform == 'linux'`), `textual`, `youtube`, `security` (`defusedxml`, `nh3`), `fast-search` (`rapidfuzz`), `xml` (`lxml`), `dev` (`PyYAML`, `ruff`, `mypy`, and Python < 3.11 `tomli`), and `all`.
  - **Package Data Loaded via `importlib.resources`**: Turned `twittui.resources` into an explicit subpackage (`twittui/resources/__init__.py`) declared under `[tool.setuptools]` with `[tool.setuptools.package-data]`, and wired `twittui/viewer.py` (`show_document_viewer()`, `render_rss_feed_to_html()`) and `twittui/ui/form.py` (`resolve_app_icon()`) to load packaged docs, feed styles, and icons through `importlib.resources`. Archive-backed icon resources are materialized in a private process-lifetime temporary directory, while other path lookups return only persistent filesystem paths; `about:blank` is used as the WebView base when documentation is archive-backed. Added `--collect-all=twittui` in `installer.py`.
  - **Verification**: Verified by `test_architecture_suggestions.py` (`test_package_runtime_resources_and_icon_fallback`, `test_archive_backed_icon_resource_path_remains_valid`, `test_packaging_hygiene_and_ci_workflow`, and end-to-end PEP 517 wheel build check `test_pep517_wheel_build_bundles_resources_and_excludes_tests`), `test_snap.py:test_requirements_and_pyproject`, and `test_install.py:test_pyproject_includes_all_source_modules`; `uv.lock` resolves the `toga-core` core dependency without GTK.

### 5. Consolidate the Four Diverging Show Registries
Show-to-feed/slug/abbreviation tables are duplicated across four separate dictionaries in `twittui_form.py`:
- `KNOWN_SHOW_FEEDS` (line 510)
- `MEMBERFUL_SHOW_FEEDS` (line 534)
- `abbrevs` inside `search_episodes()` (line 6167)
- `short_map` inside `generate_transcript_slug_candidates()` (line 6569)

Several shows (e.g., *FLOSS Weekly*, *Hands-On Photography*, *This Week in Enterprise Tech*, *This Week in Google*, *All About Android*, *Intelligent Machines*) appear in some tables and are missing from others. Consolidate into a single `SHOW_REGISTRY` dataclass mapping.
- **Applied Implementation & Verification**:
  - **Single-Source `SHOW_REGISTRY` (`twittui/shows.py`)**: Created frozen `ShowEntry` (covering canonical `key`, `display_name`, `default_show_id`, `public_feeds`, `memberful_feeds`, `search_slugs`, `transcript_slugs`, `aliases`, `include_in_default_shows`, `is_host_feed`) and derived **all** lookup tables purely from `SHOW_REGISTRY` with zero hand-maintained duplicates: `KNOWN_SHOW_FEEDS`, `MEMBERFUL_SHOW_FEEDS`, `MEMBERFUL_HOST_FEEDS`, `SHOW_SEARCH_SLUGS`, `TRANSCRIPT_SLUG_MAP`, `SHOW_ABBREVIATIONS`, and `DEFAULT_SHOWS` across all 38 registered shows (including *FLOSS Weekly*, *Hands-On Photography*, *This Week in Enterprise Tech*, *This Week in Google*, *All About Android*, *Intelligent Machines*, *Smart Tech Today*, and *Know How*).
  - **Unified Lookup & Bug Fixes (`twittui/shows.py`, `twittui/rss.py`, `twittui/media.py`, `twittui/catalog.py`, `twittui/ui/metadata.py`)**: Added punctuation/hyphen-tolerant and unambiguous-slug alias resolution in `get_show_entry()` (resolving e.g. `"Security Now!"`, `"Know How..."`, `"Hands On Tech"`, `"twiet"`, `"floss"`), wired all RSS/media/catalog/metadata consumers through `get_show_entry()`, fixed `"Ask The Tech Guy"` transcript slug resolution so `"the tech guy"`'s `"ttg"` substring no longer clobbers `"ask-tech-guys"`, and replaced hardcoded episode-prefix regexes in `twittui/ui/metadata.py` with a single regex compiled from `SHOW_ABBREVIATIONS`.
  - **Verification**: Verified by `test_architecture_suggestions.py` (`test_unified_show_registry_completeness_and_derivation`, `test_transcript_slug_candidates_cover_newly_unified_shows`, `test_show_registry_alias_lookup_and_no_inline_diverging_maps`).

### 6. Repository Hygiene & CI Automation
- Remove `twittui.egg-info/` from git tracking (`git rm -r --cached twittui.egg-info`) and add `*.egg-info/`, `*.log`, and `*.spec` to `.gitignore`.
- Remove or relocate untracked/scratch artifacts (`build.log`, `build_verbose.log`, `parts/twittui/*/.env`) and consider moving large static API captures (`shows.json`, `shows_2.json`, `shows_3.json`, `shows_4.json` — ~1.8 MB total, `sn_ballecer.txt`, `scenarios.jsonl`) out of the repository root.
- Add a GitHub Actions CI workflow running `ruff`, `mypy`, and the test suite (both Textual headless and `xvfb-run` GTK tests) with `SNAP_USER_DATA` pointed at a temp directory and `PyYAML` installed.
- **Applied Implementation & Verification**:
  - **Repository Cleanup & `.gitignore`**: Untracked `twittui.egg-info/` (`git rm -r --cached`), removed tracked scratch build logs (`build.log`, `build_verbose.log`) and leftover temp directory `.test-issue23-MdpsIu/`, verified zero `.env` files remain under `parts/`/`stage/`/`prime/`, relocated ~1.8 MB of static API captures and scenario fixtures (`shows.json`, `shows_2.json`, `shows_3.json`, `shows_4.json`, `sn_ballecer.txt`, `scenarios.jsonl`) out of the repository root into `docs/fixtures/`, and expanded `.gitignore` (`*.egg-info/`, `*.log`, `*.spec`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `overlay/`).
  - **Static Analysis & Type Checking (`ruff`, `mypy`)**: Added `[tool.ruff]` and `[tool.mypy]` configuration to `pyproject.toml` and resolved all 26 `ruff` unused-import/variable warnings and all `mypy` type issues across core modules (`tiered_search.py`, `installer.py`, `main.py`, `toga_textual_backend.py`, `twittui/{catalog,config,downloader,media,rss,ui/form,ui/metadata}.py`) so both `ruff check` and `mypy` pass locally with 0 errors.
  - **GitHub Actions CI (`.github/workflows/ci.yml`)**: Runs on Python 3.11 and 3.12 with `PyYAML`, `ruff`, and `mypy` installed via `pip install -e ".[gtk,security,fast-search,xml,dev]"` plus system GTK, `xvfb`, and `openbox`, executing `ruff check`, `mypy`, `py_compile`, a dedicated headless Textual smoke suite (`DISPLAY=""`), and the full `xvfb-run -a python -W always::ResourceWarning -m unittest discover` suite with isolated `SNAP_USER_DATA`. Verified by `test_architecture_suggestions.py:test_packaging_hygiene_and_ci_workflow`.

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

- **Applied Implementation & Verification**:
  Reconciled all 11 drifted statements in `Technical_review.md` and updated its architecture diagram, SQLite WAL/TTL schema, `twittui/` package layout and bundled resources, `SHOW_REGISTRY`, security/logging details, Snap/PyInstaller/CI infrastructure, and 25-module / 332-test suite coverage matrix.

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


---

## Remediation & Implementation Log (All Four Executive Summary Sections)

All **23 confirmed bugs** and **7 architectural/quality suggestions** catalogued across the four sections of the Executive Summary have been implemented and verified.

### Verification Summary

| Executive Summary Section | Items | Status | Regression Test Suite |
| :--- | :---: | :---: | :--- |
| **1. Critical / High** | 7 (#1–#7) | Complete | `test_critical_fixes.py` (7 tests) |
| **2. Medium** | 13 (#8–#20) | Complete | `test_double_metaphone.py` (8 tests), `test_medium_fixes.py` (21 tests), `test_episode_activation.py` (3 tests), updated `test_install.py` / `test_snap.py` (10 tests) / `test_security.py` / `test_episode_search.py` / `test_tooltips.py` / `test_open_destination.py` / `test_backend_factory.py` |
| **3. Low / Edge Cases** | 3 (#21–#23) | Complete | `test_low_fixes.py` (7 tests) |
| **4. Architectural & Quality Suggestions** | 7 (#1–#7) | Complete | `test_architecture_suggestions.py` (20 tests) |
| **Total Test Suite** | **30 items** | **335 / 335 Passing** | `python -W always::ResourceWarning -m unittest discover -s . -p "test_*.py" -v` (25 modules, 0 `ResourceWarning`s; pending asyncio task warning at shutdown; `.env` untouched) |

---

### Section 1: Critical / High Fixes Implemented (#1–#7)

1. **Plaintext API Secret in World-Readable SQLite Cache (#1)**:
   - Added `_shows_cache_key_hash(app_id, app_key)` (`SHA-256` over `f"{app_id}\0{app_key}"`) so API credentials are never stored verbatim in `twittui_cache.db`.
   - Enforced `0o700` permissions on `~/.cache/twittui` and `0o600` on `twittui_cache.db` (and SQLite `-wal`/`-shm` sidecars) via `_restrict_file_permissions()`.
   - Added automatic startup migration of legacy `app_id:app_key` rows using `PRAGMA secure_delete = ON`.
2. **HTML Sanitizer XSS Bypasses & Attribute Corruption (#2)**:
   - Replaced the regex-only fallback with a strict pure-Python allowlist `html.parser.HTMLParser` (`_AllowlistHTMLSanitizer`, alongside optional `bleach`/`nh3`) and multi-pass dangerous-container pre-stripping handling whitespace before `>` (e.g., `</script >`).
   - Added entity unescaping and ASCII control-character stripping before URI scheme validation so ` &#106;avascript:`, `java\tscript:`, `vbscript:`, `data:`, `style=...`, `srcdoc`, and `formaction` payloads are blocked cleanly without corrupting attribute quotes.
3. **RSS XSLT Renderer Stripping Its Own `<style>` Block (#3)**:
   - Updated `render_rss_feed_to_html()` to sanitize untrusted RSS body content *before* injecting the trusted local `feed-style.css` `<style>` block and HTML shell, preserving visual styling while keeping feed payloads sanitized.
4. **`_LazySQLiteEpisodesCache` Data Loss & `dict` Contract (#4)**:
   - Implemented the full Python mapping contract on `_LazySQLiteEpisodesCache` (`setdefault`, `update`, `__iter__`, `__delitem__`, `keys`, `items`, `values`, `__or__`, `__ior__`, `pop`, `copy`, `clear`) so `setdefault()` hydrates unloaded shows instead of overwriting cached pages with `[]`, and `update()` keeps `_unloaded_keys` synchronized without eager SQLite loads.
5. **Uncaught `_run_network` Exceptions Freezing Modal Overlays (#5)**:
   - Extended `_run_network(self, work, done, on_error=None, on_finally=None)` (`twittui_form.py:912-972`) with an idempotent `_invoke_finally()` executed inside `async def run()`'s `finally:` block, attached via `task.add_done_callback()` (catching pre-start task cancellation), and invoked directly with `coro.close()` if `self.loop.create_task()` fails — guaranteeing `on_finally` executes **exactly once** on the UI event loop under unhandled `work()`/`done()` exceptions, `asyncio.CancelledError`, or scheduling errors.
   - Added `_call_run_network()` (`twittui_form.py:974-1012`) so every network caller wires guaranteed idempotent `on_finally` cleanup while staying compatible with 2-arg `(work, done)` test stubs:
     - `_refresh_catalog()` (`twittui_form.py:1190-1275`): idempotent `catalog_released` flag and `_release_catalog_if_unstarted` callback release `SplashScreen`, `_catalog_wait_held`, and `_api_wait_count`; dead contradictory inner guard removed.
     - `_refresh_show_dates()` (`twittui_form.py:1295-1387`): per-iteration `settled_box` binding and `_settle_job` `on_finally` callback guarantee `in_flight` decrements, queued shows dispatch, and `callback()` fires even if `_set_show_selector_items()` raises or a task is cancelled.
     - `load_episodes_for_selected_show()` (`twittui_form.py:7456-7560`) and `on_next_press()` (`twittui_form.py:7572-7612`): idempotent `_release_episode_wait` / `_release_next_wait` callbacks always release `_set_rate_limit_wait(False)` and callbacks exactly once.
     - `on_search_press()` (`twittui_form.py:7396-7442`): routed through `_call_run_network()`.
   - Expanded `test_critical_fixes.py:test_5_network_exceptions_never_leave_wait_or_splash_stuck` (`test_critical_fixes.py:230-361`) to test unhandled `work()` errors, `asyncio.CancelledError`, `loop.create_task()` failures, `_set_show_selector_items()` exceptions during date refresh, and `_refresh_catalog()` scheduling failures (`300 / 300` suite passing).
6. **`TextualWebView` & `TextualDivider` Crashes Under Toga 0.5.7 (#6)**:
   - Implemented the full Toga 0.5 widget interface on `TextualWebView` (`get_user_agent`, `set_user_agent`, `set_on_webview_load`, `SUPPORTS_ON_WEBVIEW_LOAD`, `SUPPORTS_ON_NAVIGATION_STARTING`, `get_cookies`, `evaluate_javascript`, `set_content`, `set_url`, `get_url`) and `TextualDivider` (`get_direction`, `set_direction`, orientation-aware `rehint`) in `toga_textual_backend.py`.
   - Wrapped `TextualWebView`'s `Static(..., markup=False)` inside a focusable `VerticalScroll` container and updated `_focus_first_content_control()` so secondary documentation windows (`Help -> View README` / `View API Specification`) automatically focus the scroll container and scroll cleanly via keyboard without raising `rich.errors.MarkupError` on `twittv.apib` or bracketed URLs (`test_critical_fixes.py:366-437`).
7. **Thread-Unsafe Background UI/Dialog Access & Concurrent Batch Downloads (#7)**:
   - Hardened `_show_dialog_threadsafe(..., prefer_main=...)` (`twittui_form.py:561-604`) and `update_progress()` (`twittui_form.py:1904-1940`) so background threads marshal strictly via `loop.call_soon_threadsafe()` and never fall through to direct off-thread native widget/dialog access; routed `show_download_complete_dialog()` (`twittui_form.py:4556-4565`) and `download_youtube_video()` (`twittui_form.py:4109-4137`) through `_show_dialog_threadsafe(..., prefer_main=True)`.
   - Captured live widget values on the UI thread prior to spawning workers in `on_show_club_url_press()`, `on_open_destination_press()`, and `on_download_press()` (`twittui_form.py:4713-4865`) / `download_episodes_batch()` (`twittui_form.py:4567-4711`) using `_network_snapshot()`, protected resolution-discovery and worker cache merges with `self._cache_lock` (`threading.RLock`), and guarded against overlapping/re-entrant downloads across both `await` boundaries (`self._download_starting`) and worker execution (`self._is_downloading` + non-blocking `self._download_lock`), verified by `test_critical_fixes.py:441-598` (`7a`–`7g`).

---

### Section 2: Medium Fixes Implemented (#8–#20)

8. **GTK Auto-Scroll to Search Match & Offset Alignment (#8)**:
   - Updated `_show_episode_metadata()` (`twittui_form.py:7126-7183`) so `_scroll_desc_to_match()` targets `desc_input._impl.native_textview` via `GLib.idle_add` after `win.show()`, guards against stale callbacks after window close/replacement, clamps `char_offset` safely to the buffer length, invokes `scroll_to_iter()`, and falls back to `scroll_to_mark(buf.get_insert(), ...)` when GTK 3 defers scrolling prior to wrapped line-height validation.
   - Aligned `TwitTUIForm.extract_episode_metadata_fields()` (`twittui_form.py:6752-6763`) description field precedence (`description` → `summary` → `body` → `show_notes` → `notes` → `teaser` → `snippet`) with `tiered_search.get_episode_fields()` (`tiered_search.py:437-443`), and updated `_clean_html_for_search()` (`tiered_search.py:189-201`) to collapse `\n{3,}` unconditionally so plain-text and HTML `MatchContext.char_offset` values match `desc_input.value` identically. Verified under real GTK 3 (`xvfb-run`) and by `test_medium_fixes.py:47-201` (`test_8`, `test_8b`, `test_8c`).
9. **Double Metaphone Phonetic Rules & Dead Code (`double_metaphone.py`) (#9)**:
   - Preserved `'Ç'`, `'Ñ'`, and collapsed word-boundary spaces prior to encoding (`double_metaphone.py:16-38, 72-76, 408-412`), wired `padded` into `substr()` so all boundary/space-matching rules are reachable, and audited every `string_at()` slice length via AST.
   - Aligned every rule against Lawrence Philips' canonical specification: `CHAE` (`('K', 'X')`), `DG` (`('TK', 'TK')`), `GN` / `GLI`, Italian `AGGI`/`OGGI` (without corrupting English `-UGGI`/`-IGGI`), `J` & `L` (proper `not is_slavo_germanic` guard and removal of empty `secondary.append('')` that truncated secondary codes like `CABALLEROS`), `R` `-IER` & `S` `SIO`/`SIA`/`SIAN` `is_slavo_germanic` guards, `SCH` secondary (`SK`), `TION`/`TIA`/`TCH` vs `TH`/`TTH` (removing non-canonical `"TIEN"`), initial `W` fallthrough & `WICZ`/`WITZ` (`('TS', 'FX')`), and `Z` `is_slavo_germanic` guard (`AMAZING`/`LAZY`/`PIZZA`/`KAZAKH`), verified by 8 canonical vector tests in `test_double_metaphone.py`.
10. **Tiered Search Field Omissions, Score Inversion & Partial-Query False Positives (`tiered_search.py`) (#10)**:
    - Derived `extract_searchable_text()` (`tiered_search.py:204-214`) purely from `get_episode_fields()` (`tiered_search.py:418-448`), adding a distinct `Summary / Teaser` field for secondary descriptive keys alongside `Description / Show Notes` so filtering and hover context inspection never drift and GTK Description auto-scroll offsets stay aligned.
    - Aligned Tier 2 (Fuzzy) and Tier 3 (Phonetic) precedence, fallback threshold (`< 80.0`), scores (`80.0` primary / `72.0` secondary), multi-space query normalization, and short-word thresholds (`max(min_word_threshold, 80.0)` for `< 4`-char tokens; `68.0` default) between `compute_match_score()` (`tiered_search.py:298-311`) and `find_match_context()` (`tiered_search.py:541-625`).
    - Required every query token to match in `find_match_context()` (`tiered_search.py:627-671`), eliminating partial-query false positives, and selected the highest-signal non-exact token with score aligned to `compute_match_score()` for mixed multi-word queries, verified by `test_medium_fixes.py:205-285` (`test_10`, `test_10b`).
11. **Dead RSS Cache Lookup in `get_available_resolutions()` (#11)**:
    - Replaced the dead `f"rss_{feed_file}"`-only cache lookup (`twittui_form.py:5351-5398`) with mode-ordered lookups of the live `f"{show_key}_video"` and `f"{show_key}_audio"` keys written by `fetch_show_rss_items()` (`twittui_form.py:2130-2139, 2231-2236`), snapshotted safely under `self._cache_lock`.
    - Fixed `get_available_resolutions()` (`twittui_form.py:5184-5230`) with `_scalar_str()` to extract and stringify `target_num`/`target_title`/`clean_path`/`ep_id` from plain episode dicts (including integer `episodeNumber`), fall back to target show metadata when `"All TWiT.tv Shows"` is selected, and normalize display-formatted show labels via `_show_names_by_display`, verified by `test_medium_fixes.py:290-360` (`test_11`, `test_11b`).
12. **Episode Cache Reconciliation Double-Fetch, Modal Lockup & Write Amplification (#12)**:
    - Updated `fetch_episodes()` (`twittui_form.py:5908-6025`) to always fetch canonical newest-first (`-airingDate`) pages by default (sorting client-side in memory), track `fetched_pages` across reconciliation loops so no page is ever requested twice, and preserve uncached gap episodes on pages with cache hits.
    - Refactored `load_episodes_for_selected_show()` (`twittui_form.py:7537-7713`) into two-phase loading: Phase 1 displays Page 1 and immediately releases the modal wait / `SplashScreen`, while Phase 2 asynchronously backfills pages 2+ under `api_rate_limiter.suppress_wait_notifications()` (`twittui/rate_limiter.py:32-43, 81-89`) with a single deferred write into normalized WAL-mode `twittui_episodes` rows (`twittui/cache.py:141-246`); sort clicks during backfill (`_episodes_backfilling`) re-sort immediately in memory without restarting Page 1. Verified by `test_medium_fixes.py:364-569` (`test_12`, `test_12b`).
13. **YouTube Bracket Filenames, Misnamed Audio/Video Containers & Non-Atomic Replace (#13)**:
    - Wrapped `temp_prefix`, `dest_path`, and stem patterns with `glob.escape()` in `download_youtube_video()` (`twittui_form.py:4170-4224`), escaped literal `%` in `outtmpl`, and filtered `.part`/`.ytdl`/metadata sidecars so bracketed (`[...]`) and `%`-containing titles locate and clean up reliably.
    - Aligned output file extensions to the actual downloaded audio (`.m4a`/`.webm`/`.opus`) or video (`.webm`/`.mkv`) container when `ffmpeg` is absent (`twittui_form.py:4230-4244`) and checked aligned sibling containers during pre-download skip detection (`twittui_form.py:4128-4150`).
    - Validated `is_valid_media_file(found_file)` *before* atomic `os.replace()` promotion (`twittui_form.py:4225-4244, 4321-4333, 4389-4400, 4532`) so corrupt/HTML outputs never overwrite existing valid files or return false positives, verified by `test_medium_fixes.py:573-701` (`test_13`, `test_13b`).
14. **Duration (`length`) Confused with Byte Size (`expected_size`) (#14)**:
    - Extracted `_parse_expected_byte_size()` and `_extract_expected_byte_size()` (`twittui_form.py:4618-4706, 4756-4790`) for `download_episodes_batch()`, removing top-level `'length'` (duration) from byte-size lookup, reading `'length'` as bytes strictly inside explicit RSS `enclosure`/`enclosures` sub-dictionaries, and matching per-format byte sizes against the selected `media_url` so an HD video's top-level `size` never triggers redundant audio re-downloads, verified by `test_medium_fixes.py:705-804` (`test_14`, `test_14b`).
15. **File Descriptor Double-Close & TOCTOU Permissions in `write_restricted_file()` (#15)**:
    - Hardened `write_restricted_file()` (`twittui/config.py:52-79`, re-exported from `twittui_form.py`) with `fd_owned` tracking and `finally:` cleanup so `os.close(fd)` is never called after `os.fdopen()` assumes ownership yet always closes raw FDs if `os.fdopen()` fails or a `BaseException` occurs, tightened permissions directly on the open descriptor via `os.fchmod(fd, 0o600)`, and added `os.O_CLOEXEC` (also applied to `_create_restricted_log_file()` in `twittui/logging_config.py:48-51`), verified by `test_medium_fixes.py:808-868` (`test_15`, `test_15b`).
16. **TUI Row Activation Streaming Wrong Episode Under Multi-Select (#16)**:
    - Updated `on_stream_press(self, widget=None, target_row=None)` and `on_episode_activate(self, widget, row, **kwargs)` (`twittui_form.py:5630-5662`) to forward and stream the explicitly activated `row` (`toga_textual_backend.py:1130-1136`) even when other rows are marked (`☑`), and added monotonic `self._stream_request` superseding in `stale()` so rapid overlapping activations launch only the latest episode; verified end-to-end under headless Textual in `test_episode_activation.py:15-134` and `test_medium_fixes.py:875-900`.
17. **Double Redirect Resolution & Unsilenced Browser Launches in TUI Mode (#17)**:
    - Added `resolve: bool = True` to `launch_stream_safe()` (`twittui/media.py:151-192`, `twittui_form.py:351-366`), passed `resolve=False` from `on_stream_press()` (`twittui_form.py:5713-5741`) after pre-resolution, aligned YouTube skip matching (`youtube-nocookie.com`/`yt.be`), and ensured `head_resp.close()` always runs in `resolve_stream_url()` (`twittui/media.py:47-99`).
    - Routed YouTube streaming through `_open_browser_quietly()` (`twittui_form.py:689-733`), which rejects empty or `-`-prefixed strings and in live POSIX Textual TUI mode spawns `open` (macOS) or `xdg-open` / `gio open` / `sensible-browser` (Linux/Unix, with `OSError` fallback) with `stdin`/`stdout`/`stderr=subprocess.DEVNULL` and `start_new_session=True` instead of mutating process-global `sys.stdout`/`sys.stderr`, verified by `test_medium_fixes.py:875-967` (`test_16_and_17`, `test_17b`).
18. **Textual Backend Lifecycle & Widget Gaps (`toga_textual_backend.py`) (#18)**:
    - Hardened `_patched_win_hide()` (`toga_textual_backend.py:2241-2297`) under `_ensure_active_app()` to resolve stacked modal futures via `_resolve_dialog_future()`, mark `_finished`/`_close_requested`, invoke `dismiss(default_result)` (running `push_screen` callbacks) with `pop_screen()` fallback and a non-shrinking-stack loop guard, and made `_finish()` idempotent across `TextualDialogScreen`, `TextualChoiceDialogScreen` (forwarding `ChoiceDialog.default_result`), and `TextualSelectFolderScreen` (`toga_textual_backend.py:239-328, 357-503, 539-717`).
    - Routed `OpenFileDialog` and `SaveFileDialog` (`toga_textual_backend.py:745-764`, storing `file_types`) through `_resolve_dialog_future(future, None)` so `await window.dialog(...)` resolves cleanly on Toga 0.5's `Dialog`/`AsyncResult` wrappers.
    - Added `TogaProgressBar.on_mount()` sync and Toga 0.5 indeterminate (`max=None` → `value=None`) + clamp handling in `TextualProgressBarImpl` (`toga_textual_backend.py:1402-1476`), introduced `TogaLoadingIndicator` (`toga_textual_backend.py:1605-1662`) to synchronize both `display` and the 16 FPS `auto_refresh` timer on `start()`/`stop()` and mount, and implemented incremental `TextualTable` `source_insert()` (with negative-index normalization), `source_remove()` (with shifted `_marked_rows` visual refresh), and `source_change()` (`update_cell(..., update_width=True)`) (`toga_textual_backend.py:1263-1370`), verified by `test_medium_fixes.py:976-1200` (`test_18`, `test_18b`).
19. **Test Suite TTY Hang, Real `.env` Mutation, Skipped Snap Checks & Event-Loop Leaks (#19)**:
    - Updated `test_install.py:334-354` to mock `sys.exit` with `side_effect=SystemExit(0)` and `assertRaises(SystemExit)`, verified non-blocking under a real PTY.
    - Isolated `SNAP_USER_DATA` with `tempfile.TemporaryDirectory()` across `test_security.py`, `test_episode_search.py`, `test_tooltips.py`, `test_preferences.py`, and `test_open_destination.py`, and added a defense-in-depth guard in `TwitTUIForm.save_env_setting()` (`twittui_form.py:1462-1469`) skipping real `.env` writes for `org.twit.test*` app IDs unless `SNAP_USER_DATA`/`SNAP_USER_COMMON` is explicitly set.
    - Declared `"PyYAML>=6.0"` in `pyproject.toml:45-49` (`dev` extras, installed in `.github/workflows/ci.yml:36`), added `shared-mime-info` to `snap/snapcraft.yaml:110`, and added `_extract_yaml_list()` + `test_yaml_fallback_parser_and_pyyaml_dev_dependency()` in `test_snap.py:24-138` so Snap checks never silently skip.
    - Eliminated all `ResourceWarning: unclosed event loop` leaks by breaking the `App <-> loop.call_soon_threadsafe` reference cycle with `weakref.ref(self)` and registering `weakref.finalize(..., _close_idle_event_loop, loop)` across Textual `App` (`toga_textual_backend.py:48-63, 2007-2032`), GTK `App` (`twittui_form.py:308-355`), and `TwitTUIForm.__init__` (`twittui_form.py:516-519`), plus explicit loop cleanup in `test_backend_factory.py`, `test_open_destination.py`, and `test_tooltips.py`, verified by `test_medium_fixes.py:1205-1260` (`test_19`).
20. **Snap Packaging Hygiene, `shared-mime-info`, Lockfile, `.env.example`, and Bundled Media Tools (#20)**:
    - Hardened `snap/snapcraft.yaml:16-154` to remove `cp -a *.py` and `*.py`/`*.md` wildcards, expose `${SNAP}/bin:${SNAP}/usr/bin` on `PATH`, add `override-pull:` stripping developer `.env`/`*.env` and build artifacts (purging stale `parts/twittui/{src,build}/.env`), stage `shared-mime-info`, `mpv`, and `ffmpeg`, run `update-mime-database`, and install pinned dependencies from `requirements-snap.txt:1-27` + `pip install --no-deps .`.
    - Fixed `.env.example:1-20` (`TWITCLUBSHOWFOLDERS=0` and commented-out optional overrides so `load_twittui_dotenv(override=True)` preserves launcher exports), updated `snap/local/launcher.sh:5-36` to prepend `$SNAP/bin:$SNAP/usr/bin`, atomically initialize `$SNAP_USER_DATA/.env` with `0600` permissions, and prefer bundled `mpv %f` even when host VLC is visible. Added `TwitTUIForm._default_streamer_template()` (`twittui_form.py:1438-1467, 3883-3891`) to apply the same strict-Snap default and migrate the legacy VLC template, verified by `test_snap.py` and `test_medium_fixes.py:1265-1326` (`test_20`).

---

### Section 3: Low / Edge-Case Fixes Implemented (#21–#23)

21. **CLI Bootstrap & Fallback Quirks (`main.py`, `toga_textual_backend.py`) (#21)**:
    - Moved `show_terminal_splash()` after `resolve_toga_backend(argv)` (`main.py:370-374`) so `--help`, `--clean`, and `--install` do not emit loading or closing banners, and handled `KeyboardInterrupt` during the interactive backend prompt (`main.py:286-288`) by aborting cleanly with exit code `130`.
    - Removed duplicate `patch_toga_icons()`/`patch_toga_gtk_app()` invocations on startup (`main.py:305-316`) and returned integer character counts from `StderrRedirector.write()` (`main.py:25-29`).
    - Made the GTK→Textual fallback (`main.py:383-433`) apostrophe-agnostic (`"recognize the image file format"`), removed the redundant `(RuntimeError, Exception)` tuple, applied `_configure_textual_warnings()`, closed any stale idle GTK loop and cleared `toga.App.app = None` prior to fallback Textual instantiation, and replaced unbounded `io.StringIO()` stdout sinks with zero-allocation `_NullTextIO` (`main.py:333-358`) / `_DiscardingTextIO` (`toga_textual_backend.py:2076-2108`) supporting standard text-stream methods/attributes, verified by `test_low_fixes.py:36-135` (`test_21`, `test_21b`).
22. **PyInstaller Packaging Edge Cases (`installer.py`, `main.py`) (#22)**:
    - Added `_probe_packages_in_interpreter()` (`installer.py:217-257`) to inspect `toga_gtk`, `gi`, `yt_dlp`, `defusedxml`, and `nh3` inside the target `--python-executable` via subprocess (returning `set()` on cross-probe failure rather than leaking host packages).
    - Scoped `--hidden-import=gi.overrides.Gtk` and `gi.overrides.Pango` to non-Windows/non-macOS builds where `gi` is available (`installer.py:325-343`), and collected `twittui`, `yt_dlp`, `defusedxml`, and `nh3` when present.
    - Filtered active virtualenvs (`VIRTUAL_ENV`, `CONDA_PREFIX`, `sys.prefix`), relative `.`, `/tmp`/`/var/tmp`, and language-toolchain directories (`/.venv/`, `/.conda/`, `/.cargo/`, `/.rustup/`, `/.nvm/`, `/.pyenv/`, `/.rbenv/`, `/.asdf/`, `/.poetry/`, `/node_modules/`) out of `find_local_executable_path()` (`installer.py:136-214`).
    - Staged binaries in exclusive, uniquely named temporary files in the install directory and atomically replaced the destination only after applying umask-respecting executable permissions (`(0o755 & ~umask) | 0o700`, `installer.py:490-530`); failed promotion preserves the old binary and cleans only the owned temporary file. Made `--strip` opt-in (`strip_binary=False` by default, exposed via `--strip` in both `installer.py:585-605` and `main.py:172-177, 221-229`), verified by `test_low_fixes.py:140-279` (`test_22`, `test_22b`) and `test_install.py` staging-collision and replacement-failure tests.
23. **Configuration, Cleanup, Filename, Dialog & API Edge Cases (`twittui_form.py`) (#23)**:
    - Added `_schedule_env_save()` / `_flush_pending_env_saves()` (`twittui_form.py:625-683`, 0.35s UI-loop debounce cancelling stale pending writes on revert and flushing on Preferences close and app exit), numeric validation in `on_block_change()` / `on_rate_limit_change()` (`twittui_form.py:3926-3962`), and kept `api_rate_limiter.rate_limit` bound to `self.get_rate_limit`.
    - Preserved custom Club TWiT Memberful feed IDs (e.g. `.../rss/9055?auth=...`) across `_build_preferences_box()`, `on_url_change()`, and `get_full_club_twit_url()` (`twittui_form.py:2895-2914, 3550-3562, 3978-3999`).
    - Added `_terminate_active_download_proc()` and `_cleanup_resources_for_exit()` (`twittui_form.py:685-730, 4379-4449, 5831-5889`) to flush pending `.env` writes, set `_cancel_download = True`, terminate/kill active `yt-dlp` subprocesses (closing `proc.stdout` cleanly), and shut down `_LocalHTMLServer` (`shutdown()` + `server_close()`).
    - Pruned stale temporary preview HTML files with `os.fchmod(..., 0o600)` inside a context manager in `open_html_in_browser()` (`twittui_form.py:3390-3438`), added `_sanitize_fs_component()` (`twittui_form.py:4001-4157`, stripping control chars, leading/trailing dots, escaping reserved Windows basenames even when extensions are present, and clamping to POSIX 255-byte `NAME_MAX`), migrated all 14 dialog sites to Toga 0.5 `InfoDialog`/`ErrorDialog` via `_present_window_dialog()` (`twittui_form.py:534-578`), switched `test_api_credentials()` (`twittui_form.py:5915-5951`) to `shows?page=1&range=1`, guarded unverified guessed transcript URLs behind `allow_guess=False` (`twittui_form.py:6854-6948`), removed `.git` from `TWITTUI_HOMEPAGE_URL`, removed duplicate `ep_title` extraction, and removed all unused imports across `twittui_form.py`, `tiered_search.py`, and `double_metaphone.py`, verified by `test_low_fixes.py:285-471` (`test_23a`, `test_23b`, `test_23c`).

---

### Section 4: Architectural & Quality Suggestions Implemented (#1–#7)

1. **Decomposed the 8,109-Line `twittui_form.py` Monolith into the `twittui/` Package Layout (Suggestion #1)**:
   - Partitioned all 176 members of `TwitTUIForm` (verified 100% via AST) into cohesive domain and UI modules matching the suggested layout: `twittui/_compat.py`, `twittui/cli.py`, `twittui/config.py` (`ConfigMixin`), `twittui/rate_limiter.py`, `twittui/cache.py`, `twittui/shows.py`, `twittui/catalog.py` (`CatalogMixin`), `twittui/rss.py` (`RssMixin`), `twittui/media.py` (`MediaMixin`), `twittui/downloader.py` (`DownloaderMixin`), `twittui/viewer.py` (`ViewerMixin`), `twittui/logging_config.py`, `twittui/search/{__init__,tiered_search,double_metaphone}.py`, and `twittui/ui/{__init__,form,preferences,metadata,textual_backend}.py`.
   - Reduced `twittui_form.py` from **8,109 lines → 173 lines (-97.9%)** as a thin backward-compatibility facade preserving every historical import and mock target (`twittui_form.requests`, `twittui_form.resolve_stream_url`, `twittui_form.launch_stream_safe`, `twittui_form.subprocess.Popen`, `twittui_form.api_rate_limiter`, etc.).
   - Updated `pyproject.toml`, `setup.py`, `.github/workflows/ci.yml`, and `test_architecture_suggestions.py` (`test_monolith_decomposed_into_package_layout`, recursive `twittui/**/*.py` AST guard) so all subpackages build, compile, and test cleanly.
2. **Structured Logging, Elimination of Silent/Unlogged Broad Exceptions & Removal of `print` Shadowing (Suggestion #2)**:
   - Implemented `twittui/logging_config.py` (`configure_logging`, `get_logger`, `reset_logging`) with `--log-file` / `--log-level` CLI switches in `main.py` and `TWITTUI_LOG_FILE` / `TWITTUI_LOG_LEVEL` environment support, creating `0o600` + `O_CLOEXEC` log files while keeping default logging silent (`NullHandler`, `propagate = False`).
   - Removed module-level `print` shadowing (`quiet_print`) from `twittui/_compat.py`, `twittui_form.py`, and all `twittui/` modules, replacing all **84** shadowed `print(...)` calls across 9 modules directly with structured `_logger.info(...)` / `_logger.warning(...)` calls.
   - Narrowed known failure modes (`OSError`, `ValueError`, `TypeError`, `AttributeError`, `ImportError`, `NoMatches`, `RuntimeError`, `OverflowError`, `subprocess.SubprocessError`) across `toga_textual_backend.py`, `installer.py`, `twittui/config.py`, `twittui/downloader.py`, `twittui/media.py`, `twittui/rss.py`, and `twittui/ui/metadata.py`, and ensured every remaining broad `except Exception:` handler across all core source modules emits structured `_logger` diagnostics, re-raises, or presents an error dialog (0 silent or unlogged broad handlers remaining, enforced by AST + runtime regression tests `test_no_silent_broad_except_pass_handlers_remain` and `test_no_print_shadowing_or_unlogged_broad_exceptions` in `test_architecture_suggestions.py`).
3. **Non-Blocking Cold-Start Date Scraping & Normalized SQLite Cache with SQL Pagination, Deduplication, `FTS5` & `VACUUM` (Suggestion #3)**:
   - Refactored `_refresh_catalog()` (`twittui/ui/form.py`) to dismiss `SplashScreen` and release `_catalog_wait_held` / `RateLimitScreen` as soon as the show catalog and initial Page 1 episodes load, running `_refresh_show_dates()` asynchronously in the background with bounded concurrency (`max_concurrent=4`).
   - Enforced a 24-hour TTL (`SHOW_DATE_BOUNDS_TTL_SECONDS = 86400`) on `show_date_bounds` both during startup cache hydration (purging expired SQLite rows) and at runtime via `_show_date_cache_ts` in `_refresh_show_dates()` and `fetch_show_date_bounds()`.
   - Added the normalized `twittui_episodes(show_id, episode_key, position, airing_date, data_json, updated_at)` table (`PRIMARY KEY (show_id, episode_key)`) with `PRAGMA journal_mode = WAL`, indexes on `(show_id, position)` and `(show_id, airing_date)`, lazy on-first-read migration of legacy monolithic `twittui_cache` episode blobs, true SQL-level deduplication (`save_normalized_episodes()` and incremental `upsert_normalized_episodes()`), instant SQL `LIMIT/OFFSET` pagination (`load_episodes_page()`, `count_normalized_episodes()`, `_LazySQLiteEpisodesCache.get_page()`/`count_episodes()`, integrated in `CatalogMixin.fetch_episodes()`), SQLite `FTS5` full-text indexing (`twittui_episodes_fts`, `ensure_fts_indexed()`, `search_episodes_fts()`, `_LazySQLiteEpisodesCache.search_fts()`, integrated as Tier 4b in `CatalogMixin.search_episodes()`), and `VACUUM` + `PRAGMA wal_checkpoint(TRUNCATE)` + `0o600` permission enforcement on both `episodes` and full cache clear (`twittui/cache.py`).
4. **Unified Dependency & Packaging Metadata via `pyproject.toml` & `importlib.resources` (Suggestion #4)**:
   - Deleted redundant `setup.py` and consolidated all PEP 621 / PEP 517 build metadata into `pyproject.toml` (`setuptools.build_meta`), synchronized with `requirements.txt` and `.github/workflows/ci.yml` (`pip install -e ".[gtk,security,fast-search,xml,dev]"`).
   - Removed `toga-gtk` from unconditional core dependencies so clean installs succeed on macOS, Windows, and headless Linux; declared `yt-dlp` in core dependencies and provided `[project.optional-dependencies]` extras (`gtk` [`toga-gtk`, `PyGObject`, `pycairo` for Linux], `textual`, `youtube`, `security` [`defusedxml`, `nh3`], `fast-search` [`rapidfuzz`], `xml` [`lxml`], `dev` [`PyYAML`, `ruff`, `mypy`], and `all`).
   - Added `twittui/resources/__init__.py` backed by `importlib.resources.files("twittui.resources")`, declared `twittui.resources` and its asset globs in `pyproject.toml`, wired `twittui/viewer.py` and `twittui/ui/form.py` to load bundled docs, RSS stylesheets, and icons via `importlib.resources`, kept `--collect-all=twittui` in `installer.py`, and verified clean wheel generation (excluding `test_*.py`, `.env`, and `setup.py`) via `test_pep517_wheel_build_bundles_resources_and_excludes_tests`.
5. **Consolidated All Diverging Show Registries into `SHOW_REGISTRY` (Suggestion #5)**:
   - Created frozen `ShowEntry` and single-source `SHOW_REGISTRY` in `twittui/shows.py` deriving `KNOWN_SHOW_FEEDS`, `MEMBERFUL_SHOW_FEEDS`, `MEMBERFUL_HOST_FEEDS`, `SHOW_SEARCH_SLUGS` (replacing inline `abbrevs` in `search_episodes()`), `TRANSCRIPT_SLUG_MAP` (replacing inline `short_map` in `generate_transcript_slug_candidates()`), `SHOW_ABBREVIATIONS` (replacing hardcoded title-prefix regexes in `twittui/ui/metadata.py`), and `DEFAULT_SHOWS` with zero hand-maintained duplicate tables, filling in missing entries for *FLOSS Weekly*, *Hands-On Photography*, *This Week in Enterprise Tech*, *This Week in Google*, *All About Android*, *Intelligent Machines*, *Smart Tech Today*, and *Know How*.
   - Upgraded `get_show_entry()` with punctuation/alias/unique-slug resolution, wired `twittui/rss.py`, `twittui/media.py`, `twittui/catalog.py`, and `twittui/ui/metadata.py` through it, and eliminated the `"Ask The Tech Guy"` vs. `"The Tech Guy"` transcript slug substring collision (`test_show_registry_alias_lookup_and_no_inline_diverging_maps`).
6. **Repository Hygiene & GitHub Actions CI (`ruff`, `mypy`, Textual + Xvfb/Openbox GTK) (Suggestion #6)**:
   - Expanded `.gitignore` (`*.egg-info/`, `*.log`, `*.spec`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `overlay/`), untracked `twittui.egg-info/`, removed tracked scratch logs (`build.log`, `build_verbose.log`) and empty `.test-issue23-MdpsIu/`, and relocated `shows.json`, `shows_2.json`, `shows_3.json`, `shows_4.json`, `sn_ballecer.txt`, and `scenarios.jsonl` into `docs/fixtures/`.
   - Added `[tool.ruff]` and `[tool.mypy]` config in `pyproject.toml`, fixed all 26 `ruff` lint findings and all `mypy` errors across core modules so both checks pass with zero errors, and upgraded `.github/workflows/ci.yml` to install `openbox`, run `ruff check`, `mypy`, `py_compile`, a headless `DISPLAY=""` Textual suite, and the full `xvfb-run -a python -W always::ResourceWarning -m unittest discover` suite on Python 3.11 and 3.12 with `PyYAML` and isolated `SNAP_USER_DATA`.
7. **Reconciled Documentation Drift in `Technical_review.md` (Suggestion #7)**:
   - Updated every drifted section of `Technical_review.md` to accurately reflect the `twittui/` architecture and packaged resources, `SHOW_REGISTRY`, `RateLimitScreen`, `TextualSelectFolderScreen`, `patch_toga_gtk_app()`, allowlist `HTMLParser` / `nh3` / `bleach` sanitizer, path-segment `_LocalHTMLHandler` token + clean shutdown, non-reentrant `ApiRateLimiter.lock`, normalized WAL SQLite schema + SHA-256 keys + 24-hour TTL, `tiered_search.py` threshold (`68.0`) & field priority, debounced `0o600` `.env` persistence, Snap/PyInstaller/CI tooling, and the 25-module / 324-test suite matrix.

---

### Complete File Change Inventory

| Category | Files Added / Modified / Untracked |
| :--- | :--- |
| **New Core Package (`twittui/`)** | `twittui/__init__.py`, `twittui/_compat.py`, `twittui/cache.py`, `twittui/catalog.py`, `twittui/cli.py`, `twittui/config.py`, `twittui/downloader.py`, `twittui/logging_config.py`, `twittui/media.py`, `twittui/rate_limiter.py`, `twittui/rss.py`, `twittui/shows.py`, `twittui/viewer.py`, `twittui/resources/__init__.py`, `twittui/resources/*`, `twittui/search/{__init__,tiered_search,double_metaphone}.py`, `twittui/ui/{__init__,form,metadata,preferences,textual_backend}.py` |
| **Core Application Modules** | `twittui_form.py` (180-line compatibility facade), `toga_textual_backend.py`, `main.py`, `tiered_search.py`, `double_metaphone.py`, `installer.py` |
| **Packaging, Snap & CI** | `pyproject.toml` (consolidated + `[tool.ruff]`/`[tool.mypy]`; removed redundant `setup.py`), `requirements.txt`, `requirements-snap.txt`, `.env.example`, `snap/snapcraft.yaml`, `snap/local/launcher.sh`, `.gitignore`, `.github/workflows/ci.yml`, untracked `twittui.egg-info/*`, removed `build.log`/`build_verbose.log`, relocated `docs/fixtures/*` |
| **Documentation** | `Technical_review.md`, `antigravity_neon_bugs_or_suggestions.md` |
| **New Regression Suites** | `test_critical_fixes.py`, `test_double_metaphone.py`, `test_medium_fixes.py`, `test_low_fixes.py`, `test_architecture_suggestions.py` |
| **Updated Test Suites** | `test_episode_activation.py`, `test_episode_search.py`, `test_install.py`, `test_open_destination.py`, `test_preferences.py`, `test_security.py`, `test_show_catalog.py`, `test_snap.py`, `test_tooltips.py`, `test_tui_streaming_and_stdout.py` |
