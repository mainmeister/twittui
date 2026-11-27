# TwitTUI: Comprehensive Technical Architecture & Code Review

## 1. Executive Summary & System Overview

TwitTUI is a dual-interface media browser, streaming client, and batch-download manager designed specifically for the [TWiT.tv](https://twit.tv) podcast network. Built on Python 3 (supporting versions 3.10 through 3.12+) and the [BeeWare Toga](https://beeware.org/) cross-platform GUI framework, the application delivers visual and functional parity across two distinct operational backends:
1. **GTK 3 Desktop GUI (`toga-gtk`)**: A graphical desktop application featuring GTK windowing, native header bars, mouse hover dwell detection, and clipboard integration.
2. **Textual Terminal User Interface (`toga-textual`)**: An interactive terminal user interface (TUI) rendered in standard virtual terminals with keyboard-driven multi-selection, custom modal screens, and an integrated directory picker.

The codebase is organized into the modular `twittui/` package (`_compat.py`, `cli.py`, `config.py`, `rate_limiter.py`, `cache.py`, `shows.py`, `catalog.py`, `rss.py`, `media.py`, `downloader.py`, `viewer.py`, `logging_config.py`), its subpackages (`twittui/resources/` loaded via `importlib.resources`, `twittui/search/`, and `twittui/ui/{form,preferences,metadata,textual_backend}.py`), a concise 182-line `twittui_form.py` backward-compatibility facade, Textual backend extensions (`toga_textual_backend.py`), complete API specifications (`twittv.apib`, `openapi.json`), RSS transformation stylesheets (`feed-style.css`, `feed-style.xsl`), Cairo-based vector/raster icon asset pipelines, PyInstaller compilation routines (`installer.py`), GitHub Actions CI (`ruff`, `mypy`, headless Textual, and `xvfb-run` + `openbox` GTK), and an Ubuntu Core 24 strict-confinement Snap packaging configuration.

```
+----------------------------------------------------------------------------------------------------+
|                                             TwitTUI                                                |
+----------------------------------------------------------------------------------------------------+
|                                    main.py / twittui/cli.py                                        |
|   - CLI Parser (--gtk, --textual, --install, --strip, --clean, --log-file, --log-level)            |
|   - Structured File Logging (twittui.logging_config; 0o600+O_CLOEXEC, URL redaction, NullHandler)  |
|   - Host Environment Sanitizer (GTK_MODULES, UBUNTU_MENUPROXY, QT_STYLE_OVERRIDE)                  |
|   - PyGObject / Gdk Introspection Namespace Locker (GTK 3.0 / 4.0 Version Binding)                 |
|   - StderrRedirector, Display Detector ($DISPLAY/$WAYLAND_DISPLAY), GTK->Textual Fallback Recovery |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                         +------------------------+------------------------+
                         |                                                 |
                         v                                                 v
+--------------------------------------------------+ +-----------------------------------------------+
|             toga_gtk (Desktop Engine)            | |       toga_textual_backend.py (TUI Engine)    |
| - Gtk.TextView (native_textview) Auto-Scroll     | | - ContextVar App Wrapping (_ensure_active_app)|
| - Gdk Pointer Motion / Leave 3s Dwell Tracking   | | - Custom TogaDataTable & Multi-Select Gutter  |
| - Native Modal Windows & Gtk.HeaderBar Binding   | | - Modals (Splash, RateLimit, Choice, Folder)  |
| - AppArmor NON_UNIQUE D-Bus Sandbox Patch        | | - TogaProgressBar, TogaLoadingIndicator,      |
| - weakref.finalize Idle Event-Loop Cleanup       | |   TextualWebView, TextualDivider, _Discarding |
+--------------------------------------------------+ +-----------------------------------------------+
                         |                                                 |
                         +------------------------+------------------------+
                                                  |
                                                  v
+----------------------------------------------------------------------------------------------------+
|                        twittui/ Modular Package + twittui_form.py Facade                           |
|   - twittui/shows.py: Single-source SHOW_REGISTRY (38 shows; derives ALL 7 lookup tables)          |
|   - twittui/rate_limiter.py: Sliding-Window ApiRateLimiter (5 req / rolling min, threading.Lock)   |
|   - twittui/cache.py: Normalized SQLite (WAL, twittui_episodes, FTS5, LIMIT/OFFSET, 24h TTL, 0600) |
|   - twittui/config.py: Debounced .env persistence & owner-only 0o600 write_restricted_file()       |
|   - twittui/catalog.py & rss.py: Paginated API/RSS/archive ingestion & Tier 4b SQLite FTS5 search  |
|   - twittui/media.py: Safe XML (defusedxml), single-pass redirect resolution, shell=False launcher |
|   - twittui/downloader.py: Single-flight chunked HTTP & yt-dlp downloader (atomic os.replace)      |
|   - twittui/viewer.py & resources/: importlib.resources assets, allowlist sanitizer, loopback HTTP |
|   - twittui/ui/{form,preferences,metadata}.py: TwitTUIForm composing all 8 domain & UI mixins      |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                         +------------------------+------------------------+
                         |                                                 |
                         v                                                 v
+--------------------------------------------------+ +-----------------------------------------------+
|     tiered_search.py / twittui/search/           | |       double_metaphone.py / twittui/search/   |
| - Tier 1: Exact Substring Matching (Score: 100)  | | - Pure Python Lawrence Philips Algorithm      |
| - Tier 2: Ranked Fuzzy & fzf Subsequence Score   | | - Primary & Alternate 4-Character Keys        |
| - Tier 3: Phonetic Double Metaphone (< 80.0)     | | - Silent Consonants, TH/TCH/SCH, Ç/Ñ,         |
| - Unified Field Extraction & Threshold (68.0)    | |   Italian/Germanic/Romance Sound-Shift Rules  |
| - Keyword-in-Context (KWIC) Snippet Generation   | |                                               |
+--------------------------------------------------+ +-----------------------------------------------+
```

---

## 2. Execution Bootstrap & Environment Stabilization (`main.py`)

The application entry point is `main.py` (also exposed via `twittui/cli.py`). Because BeeWare Toga relies on dynamic backend factories that bind to host system C libraries via GObject Introspection (`gi.repository`), startup requires strict pre-initialization checks to prevent library collisions, symbol mismatch crashes, and console noise.

### 2.1 Backend Discovery & Selection Flow
`main.py` processes command-line arguments using `parse_backend_args()`, running `resolve_toga_backend()` before emitting terminal banners so `--help`, `--install`, and `--clean` never print loading/closing splashes:
- `--gtk` / `--gui` / `-b gtk`: Forces the GTK desktop graphical backend (`toga_gtk`).
- `--textual` / `--tui` / `-b textual`: Forces the terminal user interface backend (`toga_textual`).
- `-i` / `--install`: Delegates execution directly to `installer.py` to compile and install a standalone binary (supporting `--install-dir`, `--python-executable`, `--no-clean`, `--strip`, and `--uninstall-pyinstaller`).
- `-c` / `--clean`: Delegates execution to `installer.py` to purge build artifacts (`build/`, `dist/`, `.spec`).
- `--log-file <path>` / `--log-level <level>`: Enables structured diagnostic file logging (`twittui/logging_config.py`, created with `0o600` + `O_CLOEXEC` permissions; also configurable via `TWITTUI_LOG_FILE` / `TWITTUI_LOG_LEVEL`) without polluting TUI stdout. Logged URLs are redacted to `scheme://host` via `safe_url_for_log()` so credentials, paths, and signed query strings never enter logs. All core modules emit structured `_logger` diagnostics with zero `print` shadowing and zero unlogged broad `except` handlers.

When no command-line switch is provided, `resolve_toga_backend()` inspects installed packages via `importlib.util.find_spec()`:
1. **Interactive TTY Selection**: If both `toga_gtk` and `toga_textual` are installed, and standard input is connected to an interactive terminal (`sys.stdin.isatty()`), TwitTUI presents an interactive prompt asking the user to choose [1] GTK or [2] Textual (cleanly aborting with exit code `130` on `KeyboardInterrupt`). The default choice adapts dynamically: GTK is preferred if `$DISPLAY` or `$WAYLAND_DISPLAY` is present; otherwise, Textual is preferred.
2. **Non-Interactive Fallback**: If running in non-interactive pipelines (e.g., cron jobs, background daemons, or standard input redirects), it immediately selects GTK if display variables exist, or Textual if no display exists.
3. **Runtime Fallback Recovery**: If GTK fails during initialization (due to missing X11/Wayland displays, GDK Pixbuf loader faults, AppArmor denial, or D-Bus registration errors), `main()` catches the failure, closes any stale idle GTK event loop, resets `toga.App.app = None`, clears Toga's backend/factory caches via `toga.platform.get_backend.cache_clear()` and `get_factory.cache_clear()`, configures Textual warning filters, redirects stdout to a zero-allocation `_NullTextIO` sink, rebinds `TOGA_BACKEND=toga_textual`, and automatically relaunches in Textual TUI mode.

### 2.2 Environment Sanitization & GTK Namespace Locking
Host desktop environments (such as Cinnamon, MATE, or GNOME) frequently inject environment variables pointing to host themes and windowing modules that crash or emit warnings when loaded inside isolated Python virtualenvs or Snap containers.

1. **`sanitize_gtk_module_env()`**:
   - Strips problematic variables: `GTK_MODULES`, `GTK_PATH`, `GTK3_MODULES`, `UBUNTU_MENUPROXY`, `QT_STYLE_OVERRIDE`, and `QT_QPA_PLATFORMTHEME`.
   - Uses `ctypes.CDLL(None).unsetenv` to invoke libc's native `unsetenv` directly, ensuring child C libraries and GObject runtimes do not read unmanaged host pointers.
2. **`StderrRedirector`**:
   - Intercepts `sys.stderr.write()` (returning the integer character count per Python's `TextIO` contract) to filter out spurious host GTK module errors, specifically: `Failed to load module "xapp-gtk3-module"`.
3. **`configure_gtk_environment()`**:
   - Disables AT-SPI accessibility D-Bus bridge overhead by setting `NO_AT_BRIDGE = '1'`.
   - Purges `GTK_DEBUG` to avoid assertion aborts on release GTK builds.
   - Binds `GDK_BACKEND = 'x11'` if `$DISPLAY` is set and `$WAYLAND_DISPLAY` is absent.
   - **Namespace Version Locking**: Before any UI module is imported, it calls `gi.require_version()` for `Gtk` ("3.0" or "4.0" if `TOGA_GTK=4`), `Gdk`, `GdkX11`, `GdkWayland`, `Pango` ("1.0"), `PangoCairo`, `GLib` ("2.0"), `GObject` ("2.0"), and `Gio` ("2.0"). This prevents PyInstaller or host libraries from accidentally binding Gdk 4.0 when Toga GTK expects Gdk 3.0.

---

## 3. Textual TUI Backend & Adapter Architecture (`toga_textual_backend.py`)

The standard `toga-textual` package provides rudimentary terminal implementations for basic Toga widgets. To deliver complete feature parity with the GTK desktop interface, `toga_textual_backend.py` (2,463 lines, also re-exported from `twittui/ui/textual_backend.py`) monkey-patches and extends Toga's Textual platform factory via `patch_toga_textual()`.

### 3.1 ContextVar Stabilization & Event-Loop Hygiene
Textual depends on an internal `active_app` `ContextVar` to resolve the current terminal application instance. In an asynchronous event-driven architecture, background network worker threads and timer threads schedule UI updates using `loop.call_soon_threadsafe()`. Outside of Textual's core event loop task, this context variable is unset, which causes standard Textual widget calls to raise a `LookupError`.

`toga_textual_backend.py` introduces:
- `_ensure_active_app(app_native)`: A context manager that enters the application context if unset.
- `_AppContextScreenMixin`: A mixin applied to all modal screens that overrides `_context` to guarantee child screens retain the active Textual app handle.
- Monkey-patches on `TogaApp._register_child`, `push_screen`, `pop_screen`, and `loop.call_soon_threadsafe` (using `weakref.ref(self)` to avoid reference cycles and `weakref.finalize(..., _close_idle_event_loop, loop)` to close idle event loops) plus a zero-allocation `_DiscardingTextIO` stdout sink during TUI execution. Finalization is not guaranteed when the loop retains references to the app.

### 3.2 Key Custom Widgets and Adapters

| Class / Component | Base Type | Architectural Functionality & Implementation Details |
| :--- | :--- | :--- |
| `TogaDataTable` / `TextualTable` | `DataTable` / `Widget` | Advanced table widget supporting single and multiple row selection. Intercepts `Space`, `Shift+Up/Down`, `Ctrl+A`, `Escape`, and `u` to toggle selections, implements incremental `source_insert()`, `source_remove()` (re-syncing shifted `_marked_rows`), and `source_change()` (`update_cell(..., update_width=True)`), displays a visual checkbox gutter (`☐` / `☑`), updates a live selection count header, forwards the explicitly activated row on `Enter`, and tracks mouse pointer hover events with a 3-second dwell timer. |
| `TogaSelect` / `TextualSelection` | `Select` / `Widget` | Custom selection adapter wrapping Textual's native `Select`. Maps Toga item schemas, handles change events, and supports formatted display strings with air dates. |
| `SplashScreen` | `ModalScreen` | Centered modal screen displaying a Textual `LoadingIndicator` and dynamic status label. Displayed during application boot and dismissed immediately once the show catalog and initial selected show's Page 1 episodes complete (without blocking on background archive date scraping). |
| `RateLimitScreen` | `ModalScreen` | Centered modal wait dialog triggered during API rate-limiting or catalog refresh. Displays a static status label (`Waiting for the TWiT API. Please wait.`) and a Textual `LoadingIndicator` spinner until the in-flight request settles. |
| `TextualSelectFolderScreen` | `ModalScreen` | Terminal directory browser combining a direct path `Input`, an `Up` parent-directory button, `_FoldersOnlyDirectoryTree`, and `Select Folder` / `Cancel` confirmation controls with idempotent `_finish()` resolution without leaving the TUI. |
| `TextualDialogScreen` / `ChoiceDialog` / `OpenFileDialog` / `SaveFileDialog` | `ModalScreen` / `Dialog` | Modal dialog abstractions implementing Toga 0.5's `Dialog` / `AsyncResult` protocol (`InfoDialog`, `ErrorDialog`, `QuestionDialog`, `ConfirmDialog`, `ChoiceDialog`, `OpenFileDialog`, `SaveFileDialog`) with idempotent `_resolve_dialog_future()` resolution. |
| `TogaProgressBar` / `TogaLoadingIndicator` / `TextualDivider` | `ProgressBar` / `LoadingIndicator` / `Widget` | Full Toga 0.5 widget adapters: `TogaProgressBar` handles indeterminate (`max=None` -> `value=None`), clamping, and post-mount sync; `TogaLoadingIndicator` gates Textual's 16 FPS `auto_refresh` timer on running state and mount lifecycle; `TextualDivider` implements `get_direction`/`set_direction` and orientation-aware `rehint`. |
| `TextualWebView` | `Widget` | Scrollable terminal document viewer (`VerticalScroll` + `Static(..., markup=False)`) that converts HTML to readable text and implements Toga 0.5's full WebView contract (`get_user_agent`, `set_user_agent`, `set_on_webview_load`, `get_cookies`, `evaluate_javascript`, `set_url`, `set_content`) without misinterpreting Rich markup brackets. |
| `Secondary Window Lifecycle` | `TogaWindow` | Patches `toga_textual.window.Window` (`hide()`, `close()`, `set_app()`) to support multi-window management (e.g., Preferences and Metadata dialogs). Mounts custom `TitleBar` widgets with close buttons (`✕`), resolves any stacked modal futures cleanly via `dismiss()` + loop guards on `hide()`, binds `Escape` to close secondary windows without terminating the app, and restores focus to parent windows upon dismissal. |

### 3.3 Command Palette & Keyboard Bindings
`patch_toga_textual()` intercepts `TogaApp.get_system_commands` to expose all Toga application commands inside Textual's native Command Palette (`Ctrl+P`). It explicitly binds `F2` and `Ctrl+O` across all screens to open the Preferences window.

---

## 4. Application Controller & Modular Package (`twittui/`, `twittui_form.py`)

`TwitTUIForm(toga.App)` lives in `twittui/ui/form.py` and composes eight cohesive domain and UI mixins: `PreferencesMixin` (`twittui/ui/preferences.py`), `MetadataMixin` (`twittui/ui/metadata.py`), `ViewerMixin` (`twittui/viewer.py`), `DownloaderMixin` (`twittui/downloader.py`), `MediaMixin` (`twittui/media.py`), `RssMixin` (`twittui/rss.py`), `CatalogMixin` (`twittui/catalog.py`), and `ConfigMixin` (`twittui/config.py`), supported by leaf modules (`twittui/shows.py`, `twittui/cache.py`, `twittui/rate_limiter.py`, `twittui/logging_config.py`, `twittui/_compat.py`, and `twittui/resources/__init__.py`). The top-level `twittui_form.py` (182 lines) acts strictly as a thin backward-compatibility facade re-exporting all historical public symbols and monkeypatch targets.

### 4.1 Widget Hierarchy & Layout Tree
The UI is constructed inside `startup()` (`twittui/ui/form.py`) using a responsive flexbox layout defined via `travertino` / `toga.style.Pack`:

```
toga.MainWindow (title='TWIT.tv TUI')
└── toga.Box (direction=COLUMN, margin=5) [main_box]
    ├── toga.Box (direction=ROW, margin=5) [show_box]
    │   ├── toga.Label ('Show:')
    │   ├── toga.Selection [show_combo] (items=shows, on_change=on_show_select)
    │   ├── toga.Button ('Fetch', on_press=on_fetch_press)
    │   └── toga.Button ('Next', on_press=on_next_press)
    ├── toga.Label ('') [api_status_label]
    ├── toga.Box (direction=ROW, margin=5) [search_box]
    │   ├── toga.Label ('Search:')
    │   ├── toga.TextInput [search_input] (placeholder=..., on_confirm=on_search_press)
    │   ├── toga.Button ('Search', on_press=on_search_press)
    │   └── toga.Button ('Clear', on_press=on_clear_search_press)
    ├── toga.Box (direction=ROW, margin=5) [sort_box]
    │   ├── toga.Label ('Sort by:')
    │   ├── toga.Button ('☑ Date', on_press=on_sort_button_press) [date_radio]
    │   ├── toga.Button ('☐ Episode Number', on_press=on_sort_button_press) [episode_radio]
    │   ├── toga.Button ('☐ Episode Title', on_press=on_sort_button_press) [title_radio]
    │   ├── toga.Button ('☐ Length', on_press=on_sort_button_press) [length_radio]
    │   ├── toga.Button ('☐ Size', on_press=on_sort_button_press) [size_radio]
    │   ├── toga.Button ('▼ Descending', on_press=on_sort_order_toggle) [sort_order_button]
    │   └── toga.Button ('☐ Audio Only', on_press=on_audio_only_toggle) [audio_only_checkbox]
    ├── toga.Label ('Episodes:') [episodes_label]
    ├── toga.Table [episodes_list] (columns=['Episode', 'Title', 'Date', 'Length', 'Size'], multiple_select=True)
    ├── toga.Box (direction=ROW, margin=5) [button_box]
    │   ├── toga.Button ('Download', on_press=on_download_press)
    │   ├── toga.Button ('Stream', on_press=on_stream_press)
    │   ├── toga.Button ('Preferences', on_press=on_preferences_press)  # shown in Textual TUI mode
    │   ├── toga.Button ('Cancel', on_press=on_cancel_press)
    │   └── toga.Button ('Close', on_press=on_close_press)
    └── toga.ProgressBar [progress_bar] (max=100.0, value=0.0)

toga.Window (title='Preferences', modal and transient to main_window)
└── toga.Box (direction=COLUMN, margin=5) [settings_box]
    ├── API Application ID input [app_id_input]
    ├── API Application Key input [app_key_input] & 'Test API' Button
    ├── Club TWiT Memberful URL/Key input [url_input] & 'Show' Button
    ├── Download Destination [dest_input], 'Browse' Button, 'Open' Button, & 'Show Folders' Switch
    ├── Stream Block Size input [block_input] & API Rate Limit input [rate_limit_input]
    ├── Streamer Command Template input [streamer_input]
    ├── Search Matching Switches (Fuzzy Match & Phonetic Match switches)
    ├── Cache Management ('Clear Cache' Button)
    └── 'Close' Button
```

### 4.2 Tooltip Injection Engine
Standard Toga widgets do not uniformly expose tooltip properties across all native backends. `patch_toga_tooltips()` monkey-patches `toga.Widget.__init__` to accept an optional `tooltip` keyword argument:
- **GTK Implementation**: Maps tooltips directly to GTK widgets using `native.set_tooltip_text(tooltip_text)`.
- **Textual Implementation**: Maps tooltips to Textual widget instances via `native.tooltip = tooltip_text`.
- `set_widget_tooltip()` and `get_widget_tooltip()` provide programmatic access across all interactive controls (buttons, inputs, radios, checkboxes, and table headers).

### 4.3 Icon Pipeline, `importlib.resources` Assets & Sandbox Window Lifecycle
`resolve_app_icon()` (`twittui/ui/form.py`) resolves the application icon base path by checking overrides first and falling back to packaged data:
1. `sys._MEIPASS/resources/twittui` (when bundled into a PyInstaller standalone executable).
2. `$SNAP/resources/twittui` (when executing inside a Snap package).
3. `<project_root>/resources/twittui` and the current working directory.
4. `twittui.resources.resolve_icon_base()` via `importlib.resources.files("twittui.resources")` (materializing archive-backed icon resources into a private process-lifetime temporary directory when executing from a zip/wheel archive).

`patch_toga_icons()` hardens `toga.icons.CachedIcon` and `toga_gtk.icons.Icon` against recursive lookup failures by falling back to generated blank `GdkPixbuf` surfaces when loaders fail. `patch_toga_gtk_app()` temporarily sets `interface._app_id = None` during GTK app instantiation, applies `Gio.ApplicationFlags.NON_UNIQUE` to prevent AppArmor D-Bus name ownership denials in strict sandboxes, and registers `weakref.finalize(..., _close_idle_event_loop, loop)`.

### 4.4 Documentation & RSS Viewer with Ephemeral HTTP Server (`twittui/viewer.py`)
TwitTUI embeds an offline documentation viewer accessible via the application menu (**Help -> View README Documentation** or **View API Specification**):
1. **Packaged Asset Resolution (`twittui/resources/__init__.py`)**: `show_document_viewer()` and `render_rss_feed_to_html()` check `$SNAP`, `PROJECT_ROOT`, and `cwd` overrides first, then fall back cleanly to `importlib.resources` (`read_resource_text()` / `read_resource_bytes()` / `locate_resource_file()`) for `README.md`, `twittv.apib`, `feed-style.css`, and `feed-style.xsl` (using `about:blank` as the WebView base URL when documentation is loaded from an archive).
2. **Markdown & RSS XSLT Pipeline (`render_markdown_to_html`, `render_rss_feed_to_html`)**: Converts Markdown to styled HTML with heading anchors (`_ensure_heading_ids`), and transforms RSS XML using a hardened `lxml` parser (`resolve_entities=False`, `no_network=True`, `dtd_validation=False`, `load_dtd=False`), sanitizing untrusted RSS body content *before* wrapping it in the trusted local `feed-style.css` `<style>` shell so visual styling is preserved safely.
3. **HTML Sanitization (`sanitize_html` / `sanitize_html_content`)**: Pre-strips nested dangerous container tags (`<script>`, `<style>`, `<iframe>`, `<object>`, `<embed>`, `<svg>`, `<math>`, `<form>`, including whitespace before `>`), delegates to `bleach` or `nh3` when installed, and otherwise applies a strict pure-Python allowlist `html.parser.HTMLParser` (`_AllowlistHTMLSanitizer`) that drops unknown tags, `style`/`srcdoc`/`formaction`/event attributes and decodes HTML entities and ASCII control characters before allowing only `http://`, `https://`, `mailto:`, and relative/anchor URIs.
4. **Local Ephemeral HTTP Server (`_LocalHTMLServer`, `_LocalHTMLHandler`)**:
   - Binds strictly to `127.0.0.1` on an ephemeral OS-assigned port to avoid `file://` CORS and cross-origin anchor blocks.
   - Generates a cryptographically random URL-safe session token via `secrets.token_urlsafe(24)` (`generate_local_server_token()`).
   - Serves requested documentation and styled RSS feeds only when the exact session token is supplied as the **first URL path segment** (`/<token>/<page>`), verified with `secrets.compare_digest()`, returning HTTP 403 Forbidden otherwise.
   - Shuts down cleanly on application exit via `_cleanup_resources_for_exit()` (`server.shutdown()` and `server.server_close()` on a bounded helper thread).
5. **Hybrid Resilient Viewer & Quiet Browser Launches**: In GTK desktop mode, documentation opens inside an integrated `toga.WebView` window. If WebView is unavailable or browser fallback is invoked, `_open_browser_quietly()` opens the URL (writing temporary HTML previews with `os.fchmod(..., 0o600)` inside a context manager and pruning stale previews); in POSIX Textual TUI mode it spawns `open` (macOS) or `xdg-open` / `gio open` / `sensible-browser` (Linux/Unix) with `stdin`/`stdout`/`stderr=subprocess.DEVNULL` and `start_new_session=True` instead of mutating process-global stdio.

---

## 5. Networking Architecture & Rate Limiter (`ApiRateLimiter`)

The TWiT.tv REST API (v1.0), hosted via 3Scale, enforces strict consumption limits: applications must not exceed **5 API requests per rolling minute**. Exceeding this quota results in HTTP 500 (`usage limits are exceeded`) or HTTP 403 (`request blocked`) errors.

### 5.1 Process-Wide Sliding-Window Algorithm
To prevent quota exhaustion across multiple threads, TwitTUI implements a process-wide rate limiter in `twittui/rate_limiter.py`:

```
               [ Worker Thread Requests API Call ]
                               │
                               ▼
                   [ Acquire api_rate_limiter.lock ]
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ Purge timestamps older than 60s from deque   │
        └──────────────────────────────────────────────┘
                               │
                               ▼
                Is deque length >= rate_limit (5)?
                      /                 \
                    Yes                  No
                    /                     \
       ┌────────────────────────┐   ┌──────────────────────────┐
       │ delay = 60s -          │   │ delay = max(0, 1.0s -    │
       │ (now - timestamps[0])  │   │ (now - timestamps[-1]))  │
       └────────────────────────┘   └──────────────────────────┘
                    \                     /
                     ▼                   ▼
                     Calculate required delay
                               │
                               ▼
                        Is delay > 0?
                      /               \
                    Yes                No
                    /                   \
        ┌─────────────────────────┐  ┌─────────────────────────┐
        │ Trigger UI Wait Dialog  │  │ Append now to timestamps│
        │ sleep(delay)            │  │ Execute requests.get()  │
        │ Re-evaluate window      │  └─────────────────────────┘
        └─────────────────────────┘               │
                                                  ▼
                                     Did server return 500/403
                                     with 'usage limits exceeded'?
                                           /             \
                                         Yes              No
                                         /                 \
                          ┌────────────────────────┐   ┌───────────────────────┐
                          │ retried = True         │   │ Return HTTP Response  │
                          │ sleep(10.0s)           │   └───────────────────────┘
                          │ Retry request once     │
                          └────────────────────────┘
```

1. **Sliding Deque (`twittui/rate_limiter.py`)**: Maintains a `collections.deque` of monotonic request start timestamps protected by a non-reentrant `threading.Lock()`.
2. **Spacing Constraint**: Enforces a minimum interval of 1.0 second between consecutive request starts.
3. **Rolling Quota**: If `rate_limit` timestamps exist within the last 60 seconds, the next call sleeps for `60.0 - (now - timestamps[0])` seconds.
4. **Automated Retry**: If the API returns HTTP 500 containing `"usage limits are exceeded"` or HTTP 403 containing `"request blocked"`, the limiter sleeps for 10.0 seconds and retries the request once before propagating errors.
5. **UI Synchronization & Background Suppression**: Foreground waits invoke `_rate_limit_wait_changed(True)` to display a modal wait screen (`RateLimitScreen` in Textual or a centered GTK dialog with `toga.ActivityIndicator`). Background multi-page episode backfills enter `api_rate_limiter.suppress_wait_notifications()` so rate-limit pacing continues silently without locking the UI.

### 5.2 Thread Isolation & Guaranteed Cleanup (`_network_snapshot`, `_run_network`)
Toga widgets are not thread-safe and must only be modified on the main GUI thread. When a background operation begins:
1. `_network_snapshot()` creates a decoupled clone of application state under `self._cache_lock` (`threading.RLock`), copying live widget values into `types.SimpleNamespace` instances and snapshotting caches (`_episodes_cache`, `_show_date_cache`, `_show_date_cache_ts`, etc.).
2. `_run_network(work, done, on_error=None, on_finally=None)` (wrapped by `_call_run_network()` for backward compatibility with 2-argument test stubs) runs `work` off-thread via `asyncio.to_thread()` and guarantees that `on_finally` executes **exactly once** on the UI event loop inside a `finally:` block (and via `task.add_done_callback()` on pre-start `CancelledError`, or directly after `coro.close()` if `loop.create_task()` fails), ensuring `SplashScreen` and `RateLimitScreen` can never freeze stuck on error.
3. `_show_dialog_threadsafe(..., prefer_main=...)` and `update_progress()` marshal background UI notifications strictly via `loop.call_soon_threadsafe()`, never touching real native GTK/Textual widgets from worker threads, and present Toga 0.5 `InfoDialog`/`ErrorDialog` instances via `_present_window_dialog()`.

---

## 6. Data Ingestion, Multi-Tier Fallbacks & Persistent Caching

TwitTUI uses a resilient data ingestion pipeline designed to provide fast cold-start responsiveness and full browsing functionality even when API credentials are absent, network limits are reached, or the user is offline.

```
+----------------------------------------------------------------------------------------------------+
|                                    Show Catalog Ingestion                                          |
|                                                                                                    |
|  1. Check in-memory self._shows_cache                                                              |
|  2. Check SQLite twittui_cache (category='shows', key=SHA-256(app_id + '\0' + app_key))            |
|  3. Execute GET /shows?page=1&range=1000 via ApiRateLimiter                                        |
|  4. Extract Start Dates from API 'created' timestamp; immediately start Page 1 episodes            |
|  5. Dismiss SplashScreen & RateLimitScreen once show catalog + initial Page 1 episodes complete    |
|  6. Scrape End Dates asynchronously in background (max 4 in-flight, startup + runtime 24h TTL)     |
|  7. Fallback: Load 26 built-in DEFAULT_SHOWS derived from SHOW_REGISTRY if API unavailable         |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                                      Episode Ingestion                                             |
|                                                                                                    |
|  1. Check _LazySQLiteEpisodesCache (normalized twittui_episodes + SQL LIMIT/OFFSET pagination)     |
|  2. Phase 1: Fetch Page 1 canonical newest-first (-airingDate), display & release modal wait       |
|  3. Phase 2: Background backfill of pages 2+ under suppress_wait_notifications(), 1 deferred write |
|  4. Deduplicate into normalized twittui_episodes rows + synchronized twittui_episodes_fts (FTS5)   |
|  5. Fallback 1: Public Show RSS feed resolved via get_show_entry() (feeds.twit.tv/{slug}_*.xml)    |
|  6. Fallback 2: Club TWiT Memberful subscriber RSS feed (twit.memberfulcontent.com/rss/{feed_id})  |
|  7. Fallback 3: Triangulation public web archive scraping                                          |
+----------------------------------------------------------------------------------------------------+
```

### 6.1 Show Catalog Ingestion, Unified Show Registry & Non-Blocking Date Resolution
1. **Single-Source Show Registry (`twittui/shows.py`)**: `SHOW_REGISTRY` maps 38 canonical show keys to frozen `ShowEntry` dataclasses (`key`, `display_name`, `default_show_id`, `public_feeds`, `memberful_feeds`, `search_slugs`, `transcript_slugs`, `aliases`, `include_in_default_shows`, `is_host_feed`). **All 7 derived tables** are computed strictly from `SHOW_REGISTRY` with zero hand-maintained duplicates: `KNOWN_SHOW_FEEDS`, `MEMBERFUL_SHOW_FEEDS`, `MEMBERFUL_HOST_FEEDS`, `SHOW_SEARCH_SLUGS`, `TRANSCRIPT_SLUG_MAP`, `SHOW_ABBREVIATIONS`, and `DEFAULT_SHOWS`. `get_show_entry()` resolves exact names, punctuation/hyphen/ellipsis variants (e.g., `"Security Now!"`, `"Know How..."`, `"Hands On Tech"`), explicit aliases, and unambiguous slugs (`"twiet"`, `"floss"`, `"hop"`, `"aaa"`, `"im"`).
2. **Catalog Pagination**: Queries `https://twit.tv/api/v1.0/shows?page=1&range=1000` in a single request and traverses validated `https://twit.tv/api/v1.0/shows` next links.
3. **Non-Blocking Cold-Start Date Scraping**:
   - **Show Start Dates**: Extracted directly from the show object's `created` timestamp in the API payload.
   - **Immediate Splash Dismissal**: `_refresh_catalog()` dismisses `SplashScreen` and releases `_catalog_wait_held` / `RateLimitScreen` as soon as the show catalog and initial selected show's Page 1 episodes complete.
   - **Background Show End Dates (`fetch_show_date_bounds` / `_refresh_show_dates`)**: Scrapes missing or expired end dates asynchronously in the background from `https://twit.tv/episodes?filter[shows]={show_id}&page=1` with bounded concurrency (`max_concurrent=4`), enforcing a **24-hour TTL** (`SHOW_DATE_BOUNDS_TTL_SECONDS = 86400`) both at startup (purging stale SQLite rows) and at runtime via `_show_date_cache_ts`.
   - **Status Label Formatting**: Formats show selector entries with fixed-width columns:
     - `YYYY-MM-DD - YYYY-MM-DD  Active   Show Title`
     - `YYYY-MM-DD - YYYY-MM-DD  Ended    Show Title`

### 6.2 Two-Phase Episode Ingestion & Cache Reconciliation
1. **Canonical Pagination & Client-Side Sorting**: `fetch_episodes()` fetches canonical newest-first (`-airingDate`) pages (`range=50`) by default and applies UI sort selections (`Date`, `Episode Number`, `Title`, `Length`, `Size`, asc/desc) in memory, tracking `fetched_pages` so cache reconciliation never double-fetches pages or drops gap episodes.
2. **Two-Phase Loading & Deferred Persistence**: `load_episodes_for_selected_show()` displays Page 1 immediately and unlocks the UI, then backfills pages 2+ asynchronously under `api_rate_limiter.suppress_wait_notifications()` with a single deferred SQLite write on completion. Deferred first-page loads bypass full-cache reconciliation so partial archives cannot block startup; incomplete backfills preserve existing cache entries, and `clear_cache()` invalidates active workers via cache-generation counters so stale results cannot repopulate memory or SQLite.
3. **SQL Pagination & Fallback Cascade**: Cached pages (`page > 1`) are served directly via SQL `LIMIT/OFFSET` (`_LazySQLiteEpisodesCache.get_page()` / `count_episodes()`) without hydrating entire show catalogs into RAM. When API credentials are missing or API requests fail, ingestion falls back to public show RSS (`fetch_show_rss_items()`), Club TWiT Memberful RSS (`fetch_club_twit_rss_items()`), and Triangulation HTML archive scraping (`fetch_triangulation_archive()`).

### 6.3 Persistent SQLite Caching & `FTS5` Full-Text Search (`twittui/cache.py`, `twittui_cache.db`)
Persistent data is stored in a WAL-mode SQLite 3 database with owner-only permissions (`0o600` on the DB and `-wal`/`-shm` sidecars; `0o700` on the parent directory) located at `~/.cache/twittui/twittui_cache.db` (or `$SNAP_USER_DATA/twittui_cache.db` under Snap confinement).

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS twittui_cache (
    category TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (category, cache_key)
);
CREATE INDEX IF NOT EXISTS idx_twittui_cache_category ON twittui_cache(category);

CREATE TABLE IF NOT EXISTS twittui_episodes (
    show_id TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    airing_date TEXT,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (show_id, episode_key)
);
CREATE INDEX IF NOT EXISTS idx_twittui_episodes_show_pos ON twittui_episodes(show_id, position);
CREATE INDEX IF NOT EXISTS idx_twittui_episodes_show_date ON twittui_episodes(show_id, airing_date);

CREATE VIRTUAL TABLE IF NOT EXISTS twittui_episodes_fts USING fts5(
    show_id UNINDEXED,
    episode_key UNINDEXED,
    title,
    description,
    hosts,
    topics,
    episode_number,
    tokenize='unicode61 remove_diacritics 2'
);
```

#### Categories, Operations & Space Compaction:
- `twittui_episodes`: Normalized per-episode rows keyed by `(show_id, episode_key)` with canonical SQL-level deduplication (`save_normalized_episodes()` and incremental `upsert_normalized_episodes()`), instant SQL pagination (`load_episodes_page()` and `count_normalized_episodes()`), and lazy on-first-read migration of legacy monolithic `twittui_cache` episode blobs.
- `twittui_episodes_fts`: Indexed `FTS5` virtual table synchronized automatically on episode saves/upserts/clears (with lazy backfill via `ensure_fts_indexed()` and safe prefix-AND query escaping in `_build_fts5_match_query()`). `search_episodes_fts()` ranks results via `bm25(twittui_episodes_fts)` and powers Tier 4b offline/cross-show local cache search in `CatalogMixin.search_episodes()`.
- `shows`: Aggregated show catalogs keyed by SHA-256 hash (`_shows_cache_key_hash(app_id, app_key)`) so API credentials are never stored in plaintext (legacy `app_id:app_key` rows are auto-migrated with `PRAGMA secure_delete = ON`).
- `show_date_bounds`: Start and end date bounds keyed by `show_id`, enforced with a **24-hour TTL** (`SHOW_DATE_BOUNDS_TTL_SECONDS = 86400`); expired rows are purged on startup and evicted at runtime.
- `episode_detail`, `media_webpage`, `triangulation_archive`, `api_search`: Keyed detail, scraped stream URL, archive page, and API search caches.
- Clearing either `category='episodes'` or the full cache clears both `twittui_episodes` and `twittui_episodes_fts`, runs `VACUUM` + `PRAGMA wal_checkpoint(TRUNCATE)` to reclaim disk space, and re-enforces `0o600` permissions.

#### Transparent On-Demand Cache Loading (`_LazySQLiteEpisodesCache`):
- `_LazySQLiteEpisodesCache` subclasses Python's `dict` and implements full mapping semantics (`__contains__`, `__getitem__`, `get`, `setdefault`, `pop`, `update`, `__iter__`, `keys`, `values`, `items`, `|`, `|=`, `copy`, `clear`) alongside direct SQL helpers (`get_page()`, `count_episodes()`, `search_fts()`).
- At startup, it queries only `SELECT DISTINCT show_id FROM twittui_episodes` (plus any unmigrated legacy `cache_key`s), populating `_unloaded_keys` with zero `json.loads()` calls.
- Paginated queries (`get_page()`), episode counts (`count_episodes()`), and full-text searches (`search_fts()`) execute directly in SQLite without hydrating full show archives into RAM.

---

## 7. Tiered Search Engine & Phonetic Matching (`tiered_search.py`, `double_metaphone.py`)

To eliminate the frustration of misspelled queries, partial abbreviations, and guest name mispronunciations, TwitTUI implements a three-tiered search engine in `tiered_search.py` and `double_metaphone.py` (also re-exported under `twittui/search/`).

```
                              [ User Query String ]
                                        │
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │ Tokenize & Normalize Query into Words    │
                  └──────────────────────────────────────────┘
                                        │
                                        ▼
+-----------------------------------------------------------------------------------+
| Tier 1: Exact Substring Matching                                                  |
| - Scans: Title, Hosts/Guests, Topics, Description/Show Notes, Summary/Teaser,     |
|          Episode Number, Length, Size                                             |
| - If all query tokens appear verbatim in text -> Score = 100.0                    |
+-----------------------------------------------------------------------------------+
                                        │ (If Score < 100.0)
                                        ▼
+-----------------------------------------------------------------------------------+
| Tier 2: Ranked Fuzzy & fzf-Style Subsequence Scoring                              |
| - fzf_subsequence_score: Smith-Waterman alignment checking character order         |
|   Bonuses: +10 word start, +5*consecutive runs                                    |
| - fuzzy_ratio: Levenshtein edit distance normalized by string length              |
| - Matches typos & abbreviations (e.g. 'secruity' -> 'security', 'macbrk')         |
| - Score Range: 60.0 - 99.0                                                        |
+-----------------------------------------------------------------------------------+
                                        │ (If Word Score < 80.0)
                                        ▼
+-----------------------------------------------------------------------------------+
| Tier 3: Pure Python Double Metaphone Phonetic Correlation                         |
| - Lawrence Philips Double Metaphone Algorithm (double_metaphone.py)               |
| - Generates Primary and Alternate 4-character phonetic keys                       |
| - Primary phonetic match: Score 80.0; Secondary phonetic match: Score 72.0        |
| - Matches sound-alikes: 'ballacer' -> 'Ballecer' (PLSR == PLSR)                   |
| - Matches 'algorhtm' -> 'algorithms' (ALKR == ALKR)                               |
+-----------------------------------------------------------------------------------+
                                        │
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │ Enforce per-word minimum threshold:      │
                  │ - 68.0 for tokens >= 4 characters        │
                  │ - 80.0 for short tokens (< 4 characters) │
                  │ Average matched word scores (capped 99.0)│
                  └──────────────────────────────────────────┘
                                        │
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │ Sort descending by match score (100.0 -> │
                  │ 60.0); find_match_context breaks ties by │
                  │ Description (3) > Hosts (2) > Title (1)  │
                  └──────────────────────────────────────────┘
```

### 7.1 Tier 1: Exact Substring Matching
`extract_searchable_text()` derives its searchable corpus directly from `get_episode_fields()` (HTML-stripped `Title`, `Hosts / Guests`, `Topics`, `Description / Show Notes`, `Summary / Teaser`, `Episode Number`, `Length`, and `Size`) so filtering and match-context inspection always evaluate the exact same fields. If every query word is present as a case-insensitive substring within the target metadata, `compute_match_score()` assigns an exact match score of `100.0`.

### 7.2 Tier 2: Ranked Fuzzy & `fzf` Subsequence Scoring
When exact matching fails:
1. **`fzf_subsequence_score(query, target)`**: Implements local sequence alignment. It checks if query characters appear sequentially within candidate tokens, awarding score bonuses for:
   - Matches at word start boundaries (`is_word_start = t_idx == 0 or not t[t_idx - 1].isalnum()`): `+10.0`.
   - Contiguous consecutive character matches: `+5.0 * consecutive_count`.
2. **`fuzzy_ratio(s1, s2)` / `levenshtein_distance(s1, s2)`**: Computes minimum character edits (insertions, deletions, substitutions):
   $$\text{ratio} = \frac{(|s_1| + |s_2|) - d_{\text{Lev}}(s_1, s_2)}{|s_1| + |s_2|} \times 100$$
3. Uses `rapidfuzz.fuzz.ratio` and `partial_ratio` when the C-accelerated library is available, falling back to pure Python Levenshtein implementations seamlessly.
4. Normalizes Tier 2 & Tier 3 scores into the range `60.0`–`99.0`, ranking them strictly below exact (`100.0`) matches, with a default `min_word_threshold` of `68.0` (`80.0` for tokens shorter than 4 characters).

### 7.3 Tier 3: Pure Python Double Metaphone Phonetic Engine (`double_metaphone.py`)
`double_metaphone.py` is a pure Python implementation of Lawrence Philips' **Double Metaphone** algorithm. It converts strings into primary and secondary 4-character phonetic encoding codes:
- Preserves Unicode Latin characters (`Ç`, `Ñ`) and word-boundary spacing prior to encoding.
- Handles silent initial consonants (`GN`, `KN`, `PN`, `WR`, `PS`), `CHAE`, `DG`, `GLI`, Italian `AGGI`/`OGGI`, `J`/`L`/`R`/`S`/`Z` Slavo-Germanic guards, `SCH` secondary (`SK`), `TION`/`TIA`/`TCH` vs. `TH`/`TTH`, and initial `W` / `WICZ` / `WITZ`.
- Evaluates Tier 3 whenever a word's Tier 2 score is below `80.0`, awarding `80.0` for primary phonetic equivalence and `72.0` for secondary equivalence (e.g., `ballacer` -> `Ballecer` (`PLSR`), `algorhtm` -> `algorithms` (`ALKR`)).

### 7.4 Search Match Inspection & KWIC Snippets
When an episode matches a query, `find_match_context()` requires every query word to match at least one episode field and builds a `MatchContext` object capturing provenance (breaking equal-score ties by field priority: `Description / Show Notes` (3) > `Hosts / Guests` (2) > `Title` (1)):
- `field_name`: The matched field (`Description / Show Notes`, `Summary / Teaser`, `Title`, `Hosts / Guests`, `Topics`, etc.).
- `matched_token`: The exact token found in the metadata (e.g., `Ballecer`).
- `query_token`: The user's query token (e.g., `ballacer`).
- `match_tier`: Formatted classification label (`Exact Match`, `Fuzzy Match (92% similarity)`, or `Phonetic Match ("ballacer" ≈ "Ballecer")`).
- `char_offset`: Character index of the match within the cleaned text (aligned identically with `MetadataMixin.clean_html_text()`).
- `snippet`: Keyword-in-Context (KWIC) excerpt generated by `extract_snippet()`. Extracts a 100-character window centered on the match, scanning up to 15 characters in either direction to align cleanly to whitespace word boundaries.

---

## 8. Episode Metadata Hover Preview & Inspection System (`twittui/ui/metadata.py`)

TwitTUI provides immediate metadata inspection without requiring network queries or row clicks.

### 8.1 3-Second Hover Dwell Engine
1. **GTK Implementation (`_setup_table_hover_events`)**: Connects to the native `GtkTreeView`'s `motion-notify-event` and `leave-notify-event` signals with `Gdk.EventMask.POINTER_MOTION_MASK` and `LEAVE_NOTIFY_MASK`.
   - `_on_table_motion_notify`: Calls `widget.get_path_at_pos(x, y)` to resolve the hovered row index.
   - If the cursor stays on the same row, it starts a daemon `threading.Timer(3.0, self._trigger_hover_metadata, args=(row_idx,))`.
   - Any motion to a different row or out of the table immediately cancels the active timer under `_hover_lock`.
2. **Textual Implementation (`_on_textual_table_hover_row`)**: `TextualTable` captures mouse enter/hover events over table rows and dispatches them to `_on_textual_table_hover_row`, running identical 3-second timer logic.

### 8.2 Popup Metadata Dialog, Transcript Resolution & GTK Auto-Scroll
When the 3-second timer triggers, `show_episode_metadata_dialog()` displays the episode inspection window:
- **Search Match Banner**: If an active search query matched the episode, it renders a `🔍 Search Match` callout banner displaying the matched field, tier description, and KWIC snippet.
- **Metadata Fields & Registry-Driven Parsing**: Formats Title, Show Name, Episode Number (extracted via `_EPISODE_NUMBER_RE` compiled from `SHOW_ABBREVIATIONS`), Air Date, Duration, File Size, Formats, Hosts/Guests, and Topics. `resolve_transcript_url()` returns verified transcript URLs by default (`allow_guess=False`) and uses exact `get_show_entry()` lookup in `generate_transcript_slug_candidates()` to prevent substring collisions (such as `"the tech guy"` colliding with `"Ask The Tech Guy"`).
- **Clickable Action Links**: Renders dynamically aligned clickable buttons for the Web Link, Transcript Link, and Direct Media URL that launch quietly in the system browser when pressed.
- **GTK Cursor Auto-Scroll**: If the search match occurred within the Description/Show Notes, `_show_episode_metadata()` schedules `_scroll_desc_to_match()` via `GLib.idle_add` after `win.show()`, guards against stale callbacks after window close/replacement, resolves the underlying `Gtk.TextView` via `desc_input._impl.native_textview` (falling back to `impl.native` or its child if wrapped in a `Gtk.ScrolledWindow`), clamps `char_offset` to `buf.get_char_count()`, places the cursor at `buf.get_iter_at_offset(clamped)`, invokes `textview.scroll_to_iter(iter_pos, 0.1, True, 0.0, 0.2)`, and falls back to `textview.scroll_to_mark(buf.get_insert(), 0.1, True, 0.0, 0.2)` when GTK 3 defers line-height layout.

---

## 9. Media Resolution & Streaming Engine (`twittui/media.py`)

Resolving a playable media stream URL across TWiT's heterogeneous API schemas and RSS syndication formats is handled by `resolve_media_url()`, `extract_media_url()`, and `get_available_resolutions()`.

### 9.1 Resolution Hierarchy
Media resolution adjusts dynamically based on the **Audio Only** setting (`is_audio_only()`):

```python
# Video preference order (Audio Only unchecked)
VIDEO_PREFERENCE = ['video_hd', 'video_large', 'video_small', 'video_audio', 'video_youtube']

# Audio preference order (Audio Only checked)
AUDIO_PREFERENCE = ['video_audio', 'audio', 'video_hd', 'video_large', 'video_small', 'video_youtube']
```

#### Multi-Source Resolution Cascade (`resolve_media_url` & `get_available_resolutions`):
1. **Club TWiT Memberful Feeds**: Checks configured subscriber RSS feeds (`MEMBERFUL_SHOW_FEEDS`, `MEMBERFUL_HOST_FEEDS`, and network feeds). Subscriber enclosures take precedence to provide ad-free streams.
2. **Direct API Fields**: Evaluates standard API objects (`video_hd`, `video_large`, etc.), direct URL fields (`mediaUrl`, `downloadUrl`), files dictionaries, and `_links` enclosures.
3. **Public Show RSS Feeds**: Queries public feeds via `get_show_entry()` (`https://feeds.twit.tv/{show_slug}_{video_hd|audio}.xml`), matching items via clean path slugs, episode numbers, or episode titles (`_match_rss_item`). `get_available_resolutions()` inspects the live mode-ordered `{show_key}_video` / `{show_key}_audio` cache keys under `self._cache_lock`.
4. **Episode Webpage Scraping**: Fetches public episode HTML (`https://twit.tv{cleanPath}`) and extracts embedded `.mp4`, `.mp3`, or `.m4a` stream links.
5. **REST API Detail Endpoint**: Fetches full episode records via `GET /episodes/{episode_id}`.
6. **YouTube Fallback**: Resolves YouTube stream identifiers (including `youtube-nocookie.com` and `yt.be`).

### 9.2 Validation Filter (`is_valid_media_url`)
To prevent passing API metadata endpoints or HTML error documents to media players, every URL must pass `is_valid_media_url()`:
- Verifies protocol: Must begin with `http://`, `https://`, `rtsp://`, or `mms://` and contain no whitespace.
- Rejects API endpoints containing `/api/` or `twit.tv/api`.
- Rejects TWiT website navigation paths (`/shows`, `/episodes`, `/node`, `/people`) unless a recognizable media extension (`.mp4`, `.mp3`, `.m4a`, `.webm`, `.ogg`) is present.

### 9.3 Secure Stream Subprocess Execution & Activation Targeting
Streaming is handled without blocking the UI or corrupting TUI output:
1. **Row Targeting & Request Superseding**: `on_episode_activate(widget, row)` passes the explicitly activated `target_row` into `on_stream_press()` so pressing `Enter` or double-clicking streams the activated episode even when other rows are marked (`☑`), while monotonic `self._stream_request` counters supersede stale overlapping activations.
2. **Single-Pass Redirect Resolution (`resolve_stream_url`)**: Resolves podcast tracking redirects (always closing `head_resp`) once prior to launching and passes `resolve=False` into `launch_stream_safe()` to prevent redundant network hops.
3. **Argument Tokenization (`build_stream_args`)**: Parses streamer templates (`_default_streamer_template()` selects `mpv %f` in strict Snaps with bundled `mpv`, else `env LC_ALL=C vlc %f`) using `shlex.split()`, replacing `%f`, `{url}`, `%s`, `{file}`, or `{media_url}` safely without invoking a shell.
4. **Detached TUI-Safe Spawning (`launch_stream_safe`)**: Executes media players via `subprocess.Popen(args, shell=False)`. In live Textual TUI mode, it attaches `stdin`/`stdout`/`stderr=subprocess.DEVNULL`, sets `start_new_session=True` (or `DETACHED_PROCESS` on Windows), and appends `-I dummy` for headless Unix VLC launches when `$DISPLAY` and `$WAYLAND_DISPLAY` are absent.
5. **YouTube Redirection**: YouTube streams launch through `_open_browser_quietly()`, preventing browser console noise from corrupting the TUI.

---

## 10. Multi-Threaded Batch Downloader & Deduplication (`twittui/downloader.py`)

Batch downloading is managed asynchronously in background daemon threads via `download_episodes_batch()`, protected against overlapping starts by `self._download_starting`, `self._is_downloading`, and non-blocking `self._download_lock`.

### 10.1 Deduplication & File Verification (`is_existing_file_identical`)
To conserve bandwidth and avoid redundant writes, TwitTUI verifies existing target files before starting transfers:
1. **Byte-Size Separation (`_extract_expected_byte_size`)**: Separates episode duration (`length`) from true byte sizes (`file_size`, `fileSize`, `enclosure_length`, `bytes`, `size`, and explicit RSS `enclosure`/`enclosures` sub-dicts), matching per-format byte sizes against the selected `media_url`.
2. **Cryptographic ETag Checksum**: If the remote server returns an HTTP `ETag` containing a 32-character hexadecimal string, TwitTUI computes the local file's MD5 checksum in 64 KB chunks (`hashlib.md5()`). If the checksums match, the download is skipped.
3. **YouTube Heuristic**: Existing valid binary YouTube downloads exceeding 1 MB (including aligned sibling container extensions when `ffmpeg` is absent) are recognized and skipped.

### 10.2 Chunked Streaming, Safe Staging & Subprocess Lifecycle
`download_episode_file()` and `download_youtube_video()` perform safe staging and cleanup:
1. **Staging File**: Streams HTTP content into `<dest_path>.part` using configurable chunk buffers (default: 8192 bytes / `twitclubblocksize`).
2. **Cancellation & Exit Termination**: Checks `self._cancel_download` during iteration and tracks any active `yt-dlp` subprocess (`self._active_download_proc`) so Cancel or Close (`_terminate_active_download_proc()`) terminates/kills child processes cleanly, closes `proc.stdout`, and removes partial `.part` files.
3. **MIME & Binary Validation**: Rejects HTML error documents before promotion via `is_valid_media_file()` and atomically promotes validated files via `os.replace()`.
4. **Specialized YouTube Pipeline (`download_youtube_video`)**: Uses `yt-dlp` / `youtube-dl`, wraps temporary path patterns with `glob.escape()` and escapes literal `%` in `outtmpl` (handling bracketed `[...]` titles safely), filters `.part`/`.ytdl` sidecars, aligns extensions to actual downloaded audio/video containers when `ffmpeg` is absent, and validates output before atomic `os.replace()`.

### 10.3 Path Sanitization & Show Folders
`_sanitize_fs_component()` and `determine_download_filename()` sanitize file and directory components across POSIX, NTFS, and FAT32 filesystems:
- Strips invalid characters (`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`), control characters, and leading/trailing dots/spaces.
- Escapes Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, even with extensions) and clamps components to POSIX's 255-byte `NAME_MAX`.
- Constructs standardized names: `<Show Name> <Episode Number> <Episode Title>.<ext>`, routing into `<Destination>/<Show Name>/<Filename>` when `TWITCLUBSHOWFOLDERS=1`.

---

## 11. Configuration Architecture & Preferences Synchronization (`twittui/config.py`)

TwitTUI centralizes configuration inside `.env` files and manages live state updates across sessions.

### 11.1 Configuration Schema

| Key | Default | Description |
| :--- | :--- | :--- |
| `TWITAPI_APPLICATIONID` | *None* | 3Scale Application ID for TWiT.tv REST API access. |
| `TWITAPI_APPLICATIONKEYS` | *None* | 3Scale Application Key for TWiT.tv REST API access. |
| `twitcluburl` | `""` | Memberful RSS feed URL (preserving custom feed IDs such as `/rss/9055?auth=...`) or auth key. |
| `twitclubdestination` | `~/Downloads` | Target download directory. |
| `twitclubblocksize` | `8192` | Stream buffer chunk size in bytes (8 KB; validated numerically). |
| `twitclubstreamer` | `mpv %f` (strict Snap) / `env LC_ALL=C vlc %f` | Subprocess command template for launching media players (`_default_streamer_template()`). |
| `TWITAUDIOONLY` | `0` | Prefers audio feeds and formats when enabled (`1`). |
| `TWITCLUBSHOWFOLDERS` | `0` | Organizes downloads into per-show subdirectories (`1`). |
| `TWITFUZZYSEARCH` | `1` | Enables Tier 2 ranked fuzzy / subsequence search matching (`1`). |
| `TWITPHONETICSEARCH` | `1` | Enables Tier 3 Double Metaphone phonetic sound-alike search (`1`). |
| `twitapiratelimit` | `5` | API sliding window request limit per rolling minute (validated numerically). |
| `TWITTUI_LOG_FILE` | *None* | Optional diagnostic log file path (created with `0o600` + `O_CLOEXEC`; overridden by `--log-file`). |
| `TWITTUI_LOG_LEVEL` | `DEBUG` | Diagnostic log verbosity when file logging is active (overridden by `--log-level`). |

### 11.2 Environment Resolution & Persistence (`twittui/config.py`)
1. **Loading (`load_twittui_dotenv`)**: Under Snap confinement, resolves `$SNAP_USER_DATA/.env` (or `$SNAP_USER_COMMON/.env`) first; otherwise resolves `.env` via `find_dotenv(usecwd=True)` and the project root directory. Calls `load_dotenv(..., override=True)` so disk settings take precedence over inherited environment variables.
2. **Saving (`save_env_setting`, `_schedule_env_save`, `write_restricted_file`)**: Interactive preference edits are debounced (`0.35s`) on the UI loop (cancelling stale pending writes when reverted) and flushed immediately on Preferences close or exit (`_flush_pending_env_saves()`). Isolated test app IDs (`org.twit.test*`) skip real `.env` writes unless `SNAP_USER_DATA`/`SNAP_USER_COMMON` is explicitly configured. Settings are written via `python-dotenv`'s `set_key` (locking permissions to `0o600`), with a `write_restricted_file()` fallback that opens with `O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC`, enforces `0o600` directly on the open FD via `os.fchmod()`, and uses `fd_owned` tracking in `finally:` to prevent FD double-close hazards.

---

## 12. Packaging, CI & Sandboxing Infrastructure

### 12.1 Unified Python Packaging (`pyproject.toml`, `requirements.txt`, `uv.lock`)
`pyproject.toml` (`setuptools.build_meta`) is the single authoritative PEP 621 / PEP 517 package manifest (redundant `setup.py` has been removed); `requirements.txt` contains only `.` so pip resolves runtime dependencies from package metadata, and `uv.lock` records the resolved graph for reproducible `uv` installs:
- Distributes the `twittui`, `twittui.resources`, `twittui.search`, and `twittui.ui` packages, top-level compatibility modules (`py-modules`), and package-local runtime assets in `twittui/resources/` (`*.md`, `*.apib`, `*.css`, `*.xsl`, `*.png`, `*.ico`, `*.svg`).
- Uses `toga-core`, `toga-textual`, `textual`, `requests`, `python-dotenv`, and `yt-dlp` as headless-Linux/macOS/Windows-safe core dependencies; GTK (`toga-gtk`, `PyGObject`, `pycairo` with `sys_platform == 'linux'`) lives under `[project.optional-dependencies].gtk`.
- Declares optional extras `gtk`, `textual`, `youtube`, `security` (`defusedxml`, `nh3`), `fast-search` (`rapidfuzz`), `xml` (`lxml`), `dev` (`PyYAML`, `ruff`, `mypy`, plus `tomli` on Python < 3.11), and `all`, alongside `[tool.ruff]` and `[tool.mypy]` configurations.

### 12.2 Standalone Binary Packaging Engine (`installer.py`)
`installer.py` compiles standalone, self-contained binaries using PyInstaller:
1. **Shared Library Verification (`check_python_shared_library`)**: Verifies that the target Python interpreter was compiled with shared library support (`--enable-shared` / `libpython3.X.so`).
2. **Cross-Interpreter Probing & Asset Bundling**: Packages icons (`resources/`), stylesheets (`feed-style.css`, `feed-style.xsl`), documentation (`README.md`), API specifications (`twittv.apib`), and collects `twittui`, `toga`, `toga_textual`, `textual`, `dotenv`, `requests`, plus optional `toga_gtk`, `gi`, `yt_dlp`, `defusedxml`, and `nh3` probed inside the target `--python-executable` via `_probe_packages_in_interpreter()` (scoping `gi.overrides.Gtk`/`Pango` hidden imports to non-Windows/non-macOS Linux builds; `--strip` is opt-in on POSIX).
3. **Atomic PATH Installation (`install_twittui`)**: Locates writable user binary directories (`~/.local/bin`, `~/bin`, `/usr/local/bin`) while excluding virtualenvs (`VIRTUAL_ENV`, `CONDA_PREFIX`, `sys.prefix`), relative `.`, `/tmp`, and language-toolchain paths; writes the binary into an exclusive `tempfile.mkstemp()` staging file in the target directory, applies umask-respecting executable permissions (`(0o755 & ~umask) | 0o700`), and atomically promotes it via `os.replace()` so failed promotions preserve any existing binary.
4. **Hygiene Engine (`clean_build_artifacts`)**: Cleans up `build/`, `dist/`, and `.spec` files, with an option to uninstall PyInstaller (`--uninstall-pyinstaller`).

### 12.3 Ubuntu Core 24 Snap Packaging (`snap/`)
TwitTUI includes production Snap packaging configurations supporting cross-distribution deployment:
- **`snap/snapcraft.yaml`**: Built on Ubuntu Core 24 (`core24`) with strict confinement (`confinement: strict`). Uses `override-pull:` to strip developer `.env`/`*.env` and build artifacts, exposes `${SNAP}/bin:${SNAP}/usr/bin` on `PATH`, installs pinned dependencies from `requirements-snap.txt` followed by `pip install --no-deps .`, and stages `shared-mime-info` (running `update-mime-database`), `mpv`, `ffmpeg`, and `.env.example` (never copying `test_*.py` or developer `.env` files). Declares desktop plugs (`desktop`, `desktop-legacy`, `wayland`, `x11`, `opengl`, `audio-playback`, `network`, `network-bind`, `home`, `removable-media`).
- **Dual Snap Entry Points**:
  - `twittui`: Launches GTK graphical desktop UI (`bin/twittui-launcher --gtk`).
  - `twittui.tui`: Launches Textual terminal interface (`bin/twittui-launcher --textual`).
- **Runtime Sandbox Launcher (`snap/local/launcher.sh`)**:
  - Prepends `$SNAP/bin:$SNAP/usr/bin` on `PATH` and sanitizes incompatible host theme variables (`GTK_MODULES`, `UBUNTU_MENUPROXY`).
  - Configures library paths (`LD_LIBRARY_PATH`), GObject typelibs (`GI_TYPELIB_PATH`), and schema directories (`GSETTINGS_SCHEMA_DIR`).
  - Atomically seeds `$SNAP_USER_DATA/.env` from `.env.example` via `install -m 600`, defaults `TWITCLUBSTREAMER="mpv %f"` when bundled `mpv` is available, and generates the GDK Pixbuf loaders cache (`gdk-pixbuf-query-loaders > $SNAP_USER_DATA/.loaders.cache`).

### 12.4 Repository Hygiene & Continuous Integration (`.github/workflows/ci.yml`)
- **Repository Hygiene**: `.gitignore` ignores `*.egg-info/`, `*.log`, `*.spec`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `overlay/`, `parts/`, `prime/`, `stage/`, and `.env`; `twittui.egg-info/` is untracked, scratch build logs (`build.log`, `build_verbose.log`) are removed, and static API/scenario reference captures (`shows*.json`, `sn_ballecer.txt`, `scenarios.jsonl`) live cleanly under `docs/fixtures/`.
- **GitHub Actions CI**: Runs on pushes and pull requests across Python 3.11 and 3.12 on `ubuntu-latest`:
  - Installs system GTK 3, PyGObject build headers, `shared-mime-info`, `xvfb`, and `openbox`, plus `pip install -e ".[gtk,security,fast-search,xml,dev]"` (including `PyYAML`, `ruff`, and `mypy`).
  - Runs `ruff check` across `twittui/` and all top-level source modules, `mypy` across core typed modules, and `python -m py_compile` across `*.py`, `twittui/*.py`, `twittui/resources/*.py`, `twittui/ui/*.py`, and `twittui/search/*.py`.
  - Runs a dedicated headless Textual smoke suite (`DISPLAY=""`, `TOGA_BACKEND=toga_textual`) followed by the full `xvfb-run -a python -W always::ResourceWarning -m unittest discover -s . -p "test_*.py" -v` suite with `SNAP_USER_DATA` isolated to `${{ runner.temp }}` (leaving per-test cache DB paths untouched).

---

## 13. Quality Assurance & Automated Test Suite

TwitTUI maintains an automated test suite comprising **336 unit and integration tests across 25 test modules**. The suite supports headless terminals and graphical sessions, with isolated application data to avoid mutating the developer's `.env`.

```
test_*.py Test Coverage Matrix:
├── test_api_rate_limiter.py          # Sliding window rate limiting, 5 req/min cap, 403/500 retry logic
├── test_architecture_suggestions.py  # twittui/ package, importlib.resources, PEP 517 wheel, SHOW_REGISTRY, WAL+FTS5 cache, logging, CI, docs
├── test_backend_factory.py           # Backend detection, CLI switches (--gtk, --textual), fallback recovery
├── test_caching.py                   # Persistent SQLite caching, incremental episode merge, gap recovery, clear cache
├── test_critical_fixes.py            # Credential hashing, HTML/XSLT XSS hardening, lazy cache completeness, worker error cleanup, WebView/Divider
├── test_double_metaphone.py          # Double Metaphone phonetic rules (TH/TCH/SCH, Ç/Ñ, silent consonants)
├── test_episode_activation.py        # Row selection, double-click streaming activation, keyboard events
├── test_episode_search.py            # Multi-tier search (Exact, Fuzzy, Double Metaphone), sorting stability
├── test_gtk_maximize_layout.py       # GTK window state events, table resizing, Xvfb+Openbox flexbox layout stability
├── test_hover_popup.py               # 3-second hover dwell timers, metadata dialog, KWIC snippet auto-scroll
├── test_install.py                   # PyInstaller packaging, shared library validation, PATH filtering, atomic staging, cleanup
├── test_low_fixes.py                 # Debounced .env writes, _LocalHTMLServer exit cleanup, Toga 0.5 dialogs, POSIX stdio isolation
├── test_medium_fixes.py              # GTK auto-scroll, glob escaping, length/size separation, row targeting, Snap MIME/YAML fallback
├── test_open_destination.py          # Cross-platform directory creation and file manager launching
├── test_preferences.py               # In-app settings dialog, search toggles, .env serialization
├── test_resolutions.py               # Multi-resolution format parsing, sorting, batch resolution modals
├── test_security.py                  # Stream argument safety, 0o600 files, local server token auth, HTML/XML sanitization
├── test_show_catalog.py              # Catalog pagination, non-blocking cold start, date scraping, deferred backfill & cache invalidation
├── test_show_folders.py              # Show folder directory creation, filename sanitization
├── test_snap.py                      # Snapcraft recipe, desktop entry validity, sandbox launcher script, pyproject.toml parity
├── test_splash_screen.py             # Terminal splash banner, Textual modal splash, GTK splash window
├── test_tooltips.py                  # Tooltip injection across GTK and Textual widgets
├── test_tui_multiselect.py           # Textual table multi-selection, space toggle, checkbox gutter
├── test_tui_streaming_and_stdout.py  # Stream launching, stdout redirection, lazy cache performance, Textual context safety
└── test_youtube_download.py          # YouTube format extraction and yt-dlp download handling
```

The test suite runs directly with Python's standard `unittest` runner:
```bash
python -W always::ResourceWarning -m unittest discover -s . -p "test_*.py" -v
```
In the latest isolated Xvfb run, all 336 tests passed with no `ResourceWarning`s and the developer's `.env` unchanged. The run did emit a shutdown `RuntimeWarning` for an unawaited network coroutine; passing tests do not establish that the codebase is regression-free.
