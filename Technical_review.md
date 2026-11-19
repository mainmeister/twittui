# TwitTUI: Comprehensive Technical Architecture & Code Review

## 1. Executive Summary & System Overview

TwitTUI is a dual-interface media browser, streaming client, and batch-download manager designed specifically for the [TWiT.tv](https://twit.tv) podcast network. Built on Python 3 (supporting versions 3.10 through 3.12+) and the [BeeWare Toga](https://beeware.org/) cross-platform GUI framework, the application delivers visual and functional parity across two distinct operational backends:
1. **GTK 3 Desktop GUI (`toga-gtk`)**: A graphical desktop application featuring GTK windowing, native header bars, mouse hover dwell detection, and clipboard integration.
2. **Textual Terminal User Interface (`toga-textual`)**: An interactive terminal user interface (TUI) rendered in standard virtual terminals with keyboard-driven multi-selection, custom modal screens, and an integrated directory picker.

The codebase encompasses approximately 18,600 lines of Python code, complete API specifications (`twittv.apib`, `openapi.json`), modern RSS transformation stylesheets (`feed-style.css`, `feed-style.xsl`), Cairo-based vector/raster icon asset pipelines, PyInstaller compilation routines, and an Ubuntu Core 24 strict-confinement Snap packaging configuration.

```
+----------------------------------------------------------------------------------------------------+
|                                             TwitTUI                                                |
+----------------------------------------------------------------------------------------------------+
|                                         main.py (Bootstrap)                                        |
|   - CLI Switch Parser (--gtk, --textual, --install, --clean)                                       |
|   - Host Environment Sanitizer (GTK_MODULES, UBUNTU_MENUPROXY, QT_STYLE_OVERRIDE)                 |
|   - PyGObject / Gdk Introspection Namespace Locker (GTK 3.0 / 4.0 Version Binding)                 |
|   - Stderr Warning Filter & Graphical Display Detector ($DISPLAY / $WAYLAND_DISPLAY)                |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                         +------------------------+------------------------+
                         |                                                 |
                         v                                                 v
+--------------------------------------------------+ +-----------------------------------------------+
|             toga_gtk (Desktop Engine)            | |       toga_textual_backend.py (TUI Engine)    |
| - GtkTextView Auto-Scroll to Search Match Iter   | | - ContextVar App Wrapping (_ensure_active_app)|
| - Gdk Pointer Motion / Leave 3s Dwell Tracking   | | - Custom TogaDataTable & Multi-Select Gutter  |
| - Native Modal Windows & Gtk.HeaderBar Binding   | | - Textual Modal Screens (Splash, RateLimit)   |
| - GdkPixbuf Multi-Resolution Application Icons   | | - DirectoryTree SelectFolderDialog Screen     |
+--------------------------------------------------+ +-----------------------------------------------+
                         |                                                 |
                         +------------------------+------------------------+
                                                  |
                                                  v
+----------------------------------------------------------------------------------------------------+
|                                    twittui_form.py (Core Logic)                                    |
|   - TwitTUIForm(toga.App) Lifecycle & Travertino Flexbox Layout Engine                             |
|   - Process-Wide Sliding-Window Rate Limiter (ApiRateLimiter: 5 req / rolling min)                |
|   - Detached Network Workers (_network_snapshot, asyncio.to_thread)                                |
|   - Resilient Multi-Tier Ingestion (REST API -> Public RSS -> Club RSS -> Web Scraping)           |
|   - Persistent SQLite Caching (twittui_cache.db & Lazy-Loaded _LazySQLiteEpisodesCache)            |
|   - Media Resolution Engine (HD, Large, Small, Audio-Only, YouTube)                                |
|   - Subprocess Stream Launcher (Tokenized args: %f, {url})                                         |
|   - Background Chunked Batch Downloader (Deduplication via Size/ETag/MD5, .part staging)          |
|   - In-App Document Viewer & Embedded Ephemeral HTTP Server (_LocalHTMLServer)                     |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                         +------------------------+------------------------+
                         |                                                 |
                         v                                                 v
+--------------------------------------------------+ +-----------------------------------------------+
|         tiered_search.py (Search Engine)         | |       double_metaphone.py (Phonetic Engine)   |
| - Tier 1: Exact Substring Matching (Score: 100)  | | - Pure Python Lawrence Philips Algorithm     |
| - Tier 2: Ranked Fuzzy & fzf Subsequence Score   | | - Primary & Alternate 4-Character Keys        |
| - Tier 3: Phonetic Double Metaphone Correlation  | | - Silent Consonants, Italian/Germanic/Romance |
| - Weighted Field Priority (Title > People > Desc)| |   Sound-Shift Rules                          |
| - Keyword-in-Context (KWIC) Snippet Generation   | |                                               |
+--------------------------------------------------+ +-----------------------------------------------+
```

---

## 2. Execution Bootstrap & Environment Stabilization (`main.py`)

The application entry point is `main.py`. Because BeeWare Toga relies on dynamic backend factories that bind to host system C libraries via GObject Introspection (`gi.repository`), startup requires strict pre-initialization checks to prevent library collisions, symbol mismatch crashes, and console noise.

### 2.1 Backend Discovery & Selection Flow
`main.py` processes command-line arguments using `parse_backend_args()`, identifying whether the user requested specific backends or installation actions:
- `--gtk` / `--gui` / `-b gtk`: Forces the GTK desktop graphical backend (`toga_gtk`).
- `--textual` / `--tui` / `-b textual`: Forces the terminal user interface backend (`toga_textual`).
- `-i` / `--install`: Delegates execution directly to `installer.py` to compile and install a standalone binary.
- `-c` / `--clean`: Delegates execution to `installer.py` to purge build artifacts (`build/`, `dist/`, `.spec`).

When no command-line switch is provided, `resolve_toga_backend()` inspects installed packages via `importlib.util.find_spec()`:
1. **Interactive TTY Selection**: If both `toga_gtk` and `toga_textual` are installed, and standard input is connected to an interactive terminal (`sys.stdin.isatty()`), TwitTUI presents an interactive prompt asking the user to choose [1] GTK or [2] Textual. The default choice adapts dynamically: GTK is preferred if a graphical display environment variable (`$DISPLAY` or `$WAYLAND_DISPLAY`) is present; otherwise, Textual is preferred.
2. **Non-Interactive Fallback**: If running in non-interactive pipelines (e.g., cron jobs, background daemons, or standard input redirects), it immediately selects GTK if display variables exist, or Textual if no display exists.
3. **Runtime Fallback Recovery**: If GTK fails during initialization (due to missing X11/Wayland displays, GDK Pixbuf loader faults, AppArmor denial, or D-Bus registration errors), `main()` catches the runtime exception, clears Toga's internal factory caches via `toga.platform.get_backend.cache_clear()`, rebinds `TOGA_BACKEND=toga_textual`, and automatically re-launches the application in Textual TUI mode without crashing.

### 2.2 Environment Sanitization & GTK Namespace Locking
Host desktop environments (such as Cinnamon, MATE, or GNOME) frequently inject environment variables pointing to host themes and windowing modules that crash or emit warnings when loaded inside isolated Python virtualenvs or Snap containers.

1. **`sanitize_gtk_module_env()`**:
   - Strips problematic variables: `GTK_MODULES`, `GTK_PATH`, `GTK3_MODULES`, `UBUNTU_MENUPROXY`, `QT_STYLE_OVERRIDE`, and `QT_QPA_PLATFORMTHEME`.
   - Uses `ctypes.CDLL(None).unsetenv` to invoke libc's native `unsetenv` directly, ensuring child C libraries and GObject runtimes do not read unmanaged host pointers.
2. **`StderrRedirector`**:
   - Intercepts `sys.stderr.write()` to filter out spurious host GTK module errors, specifically: `Failed to load module "xapp-gtk3-module"`.
3. **`configure_gtk_environment()`**:
   - Disables AT-SPI accessibility D-Bus bridge overhead by setting `NO_AT_BRIDGE = '1'`.
   - Purges `GTK_DEBUG` to avoid assertion aborts on release GTK builds.
   - Binds `GDK_BACKEND = 'x11'` if `$DISPLAY` is set and `$WAYLAND_DISPLAY` is absent.
   - **Namespace Version Locking**: Before any UI module is imported, it calls `gi.require_version()` for `Gtk` ("3.0" or "4.0" if `TOGA_GTK=4`), `Gdk`, `GdkX11`, `GdkWayland`, `Pango` ("1.0"), `PangoCairo`, `GLib` ("2.0"), `GObject` ("2.0"), and `Gio` ("2.0"). This prevents PyInstaller or host libraries from accidentally binding Gdk 4.0 when Toga GTK expects Gdk 3.0.

---

## 3. Textual TUI Backend & Adapter Architecture (`toga_textual_backend.py`)

The standard `toga-textual` package provides rudimentary terminal implementations for basic Toga widgets. To deliver complete feature parity with the GTK desktop interface, `toga_textual_backend.py` (2,122 lines) monkey-patches and extends Toga's Textual platform factory via `patch_toga_textual()`.

### 3.1 ContextVar Stabilization Across Thread Boundaries
Textual depends on an internal `active_app` `ContextVar` to resolve the current terminal application instance. In an asynchronous event-driven architecture, background network worker threads and timer threads schedule UI updates using `loop.call_soon_threadsafe()`. Outside of Textual's core event loop task, this context variable is unset, which causes standard Textual widget calls to raise a `LookupError`.

`toga_textual_backend.py` introduces:
- `_ensure_active_app(app_native)`: A context manager that enters the application context if unset.
- `_AppContextScreenMixin`: A mixin applied to all modal screens that overrides `_context` to guarantee child screens retain the active Textual app handle.
- Monkey-patches on `TogaApp._register_child`, `push_screen`, `pop_screen`, and `loop.call_soon_threadsafe` that wrap callbacks inside `_ensure_active_app()`.

### 3.2 Key Custom Widgets and Adapters

| Class / Component | Base Type | Architectural Functionality & Implementation Details |
| :--- | :--- | :--- |
| `TogaDataTable` / `TextualTable` | `DataTable` / `Widget` | Advanced table widget supporting single and multiple row selection. Intercepts `Space`, `Shift+Up/Down`, `Ctrl+A`, `Escape`, and `u` to toggle selections. Adds a visual checkbox column (`☐` / `☑`), highlights selected rows across their entire width, updates a live selection count header, and tracks mouse pointer hover events with a 3-second dwell timer. |
| `TogaSelect` / `TextualSelection` | `Select` / `Widget` | Custom selection adapter wrapping Textual's native `Select`. Maps Toga item schemas, handles change events, and supports formatted display strings with air dates. |
| `SplashScreen` | `ModalScreen` | Centered modal screen displaying a Textual `LoadingIndicator` and dynamic status label. Displayed during application boot and dismissed once show catalogs and episode archives are loaded. |
| `RateLimitScreen` | `ModalScreen` | Modal countdown dialog triggered when API quota limits are approached or exceeded. Displays a visual countdown and blocks UI input until the rate-limiter timer elapses. |
| `TextualSelectFolderScreen` | `ModalScreen` | Terminal directory browser featuring `_FoldersOnlyDirectoryTree`. Allows interactive navigation, directory creation, path breadcrumb tracking, and folder confirmation without leaving the TUI. |
| `TextualDialogScreen` / `ChoiceDialog` | `ModalScreen` | Modal dialog abstractions implementing Toga's `info_dialog`, `error_dialog`, `confirm_dialog`, `question_dialog`, and format selection dialogs (`ChoiceDialog`). Resolves asynchronous `asyncio.Future` promises upon button dismissal. |
| `TextualWebView` | `Widget` | Markdown and HTML text renderer for terminal environments. Strips markup and renders formatted plain text with scrollable containers when running without a graphical browser. |
| `Secondary Window Lifecycle` | `TogaWindow` | Patches `toga_textual.window.Window` to support multi-window management (e.g., Preferences and Metadata dialogs). Mounts custom `TitleBar` widgets with close buttons (`✕`), binds `Escape` to close secondary windows without terminating the app, and restores focus to parent windows upon dismissal. |

### 3.3 Command Palette & Keyboard Bindings
`patch_toga_textual()` intercepts `TogaApp.get_system_commands` to expose all Toga application commands inside Textual's native Command Palette (`Ctrl+P`). It explicitly binds `F2` and `Ctrl+O` across all screens to open the Preferences window.

---

## 4. Application Controller & UI Architecture (`twittui_form.py`)

`twittui_form.py` (7,691 lines) contains the primary application class, `TwitTUIForm`, which subclasses `toga.App`.

### 4.1 Widget Hierarchy & Layout Tree
The UI is constructed inside `startup()` using a responsive flexbox layout defined via `travertino` / `toga.style.Pack`.

```
toga.MainWindow (title='TWIT.tv TUI')
└── toga.Box (direction=COLUMN, margin=5) [main_box]
    ├── toga.Box (direction=ROW, margin=5) [show_box]
    │   ├── toga.Label ('Show:')
    │   ├── toga.Selection [show_combo] (items=shows, on_change=on_show_select)
    │   ├── toga.Button ('Fetch', on_press=on_fetch_press)
    │   └── toga.Button ('Next', on_press=on_next_press)
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
    │   ├── toga.Button ('▼ Descending', on_press=on_sort_order_toggle) [sort_order_button]
    │   └── toga.Button ('☐ Audio Only', on_press=on_audio_only_toggle) [audio_only_checkbox]
    ├── toga.Label ('Episodes:') [episodes_label]
    ├── toga.Table [episodes_list] (headings=['Episode', 'Title', 'Date', 'Length', 'Size'], multiple_select=True)
    ├── toga.Box (direction=ROW, margin=5) [button_box]
    │   ├── toga.Button ('Download', on_press=on_download_press)
    │   ├── toga.Button ('Stream', on_press=on_stream_press)
    │   ├── toga.Button ('Cancel', on_press=on_cancel_press)
    │   └── toga.Button ('Close', on_press=on_close_press)
    └── toga.ProgressBar [progress_bar] (max=100.0, value=0.0)

toga.Window (title='Preferences', modal and transient to main_window)
└── toga.Box (direction=COLUMN, margin=5) [settings_box]
    ├── API Application ID input [app_id_input]
    ├── API Application Key input [app_key_input] & 'Test API' Button
    ├── Club TWiT Memberful URL/Key input [url_input] & 'Show' Button
    ├── Download Destination [dest_input], 'Browse' Button, 'Open' Button, & 'Show Folders' Switch
    ├── Stream Block Size input [block_input]
    ├── Streamer Command Template input [streamer_input]
    ├── Search Matching Switches (Fuzzy Search & Phonetic Search switches)
    ├── Cache Management ('Clear Cache' Button)
    └── 'Close' Button
```

### 4.2 Tooltip Injection Engine
Standard Toga widgets do not uniformly expose tooltip properties across all native backends. `patch_toga_tooltips()` monkey-patches `toga.Widget.__init__` to accept an optional `tooltip` keyword argument:
- **GTK Implementation**: Maps tooltips directly to GTK widgets using `native.set_tooltip_text(tooltip_text)`.
- **Textual Implementation**: Maps tooltips to Textual widget instances via `native.tooltip = tooltip_text`.
- `set_widget_tooltip()` and `get_widget_tooltip()` provide programmatic access across all interactive controls (buttons, inputs, radios, checkboxes, and table headers).

### 4.3 Icon Pipeline & Window Branding
`resolve_app_icon()` determines the application icon path by inspecting:
1. `sys._MEIPASS/resources/twittui` (when bundled into a PyInstaller standalone executable).
2. `<project_root>/resources/twittui` (when executing directly from source).
3. System icon theme paths.

`patch_toga_icons()` hooks Toga's icon loader to automatically resolve `.png`, `.ico`, and `.svg` files, while `patch_toga_gtk_app()` binds the window icon directly to `Gtk.Window.set_default_icon_from_file()`.

### 4.4 Documentation & RSS Viewer with Ephemeral HTTP Server
TwitTUI embeds an offline documentation viewer accessible via the application menu (**Help -> View README Documentation** or **View API Specification**):
1. **Markdown to HTML Pipeline (`render_markdown_to_html`)**: Parses Markdown text, applies ID anchors to all headers (`_ensure_heading_ids`), and injects custom CSS styling matching TWiT's visual branding.
2. **HTML Sanitization (`sanitize_html`)**: Uses `html.parser.HTMLParser` to sanitize rendered markup. It removes dangerous tags (`<script>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, `<input>`), strips active inline attributes (`onclick`, `onload`, `onerror`), and verifies URI schemes to permit only `http://`, `https://`, and internal anchor links (`#`).
3. **Local Ephemeral HTTP Server (`_LocalHTMLServer`, `_LocalHTMLHandler`)**:
   - To bypass modern browser local file restrictions (`file://` CORS and cross-origin anchor blocks), `TwitTUIForm` launches a lightweight, local HTTP server bound strictly to `127.0.0.1` on an ephemeral OS-assigned port.
   - Generates a cryptographically random, 32-character hexadecimal token (`generate_local_server_token()`).
   - Serves requested documentation and styled RSS feeds only when the exact session token is supplied in the request query string (`?token=<token>`), returning HTTP 403 Forbidden otherwise.
   - Automatically shuts down when the application terminates.
4. **Hybrid Resilient Viewer**: In GTK desktop mode, documentation opens inside an integrated `toga.WebView` window. If the web view component fails to initialize or is running in Textual mode, it falls back to launching the user's default desktop browser via `webbrowser.open()`.

---

## 5. Networking Architecture & Rate Limiter (`ApiRateLimiter`)

The TWiT.tv REST API (v1.0), hosted via 3Scale, enforces strict consumption limits: applications must not exceed **5 API requests per rolling minute**. Exceeding this quota results in HTTP 500 (`usage limits are exceeded`) or HTTP 403 (`request blocked`) errors.

### 5.1 Process-Wide Sliding-Window Algorithm
To prevent quota exhaustion across multiple threads, TwitTUI implements a process-wide rate limiter in `ApiRateLimiter`:

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

1. **Sliding Deque**: Maintains a `collections.deque` of request start timestamps protected by a re-entrant `threading.Lock`.
2. **Spacing Constraint**: Enforces a minimum interval of 1.0 second between consecutive request starts.
3. **Rolling Quota**: If 5 timestamps exist within the last 60 seconds, the next call sleeps for `60.0 - (now - timestamps[0])` seconds.
4. **Automated Retry**: If the API returns HTTP 500 containing `"usage limits are exceeded"` or HTTP 403 containing `"request blocked"`, the limiter sleeps for 10.0 seconds and retries the request once before propagating errors.
5. **UI Synchronization (`wait_callback`)**: While the rate limiter is waiting, it invokes `_rate_limit_wait_changed(True)`. This displays a modal wait screen (`RateLimitScreen` in Textual or a centered dialog containing an active `toga.ActivityIndicator` in GTK) to prevent user interaction until the network pipe clears.

### 5.2 Thread Isolation via `_network_snapshot()`
Toga widgets are not thread-safe and must only be modified on the main GUI thread. When a background operation begins:
1. `_network_snapshot()` creates a decoupled clone of application state by instantiating an empty object and copying necessary values into `types.SimpleNamespace` instances (inputs, selected show, sort settings, and cache references).
2. `_run_network(work_fn, done_fn)` schedules `work_fn` onto a background thread using `asyncio.to_thread()`.
3. When the background thread finishes, `done_fn` is dispatched back onto Toga's main event loop via `loop.call_soon_threadsafe()`.

---

## 6. Data Ingestion, Multi-Tier Fallbacks & Persistent Caching

TwitTUI uses a resilient data ingestion pipeline designed to provide full browsing functionality even when API credentials are absent, network limits are reached, or the user is offline.

```
+----------------------------------------------------------------------------------------------------+
|                                    Show Catalog Ingestion                                          |
|                                                                                                    |
|  1. Check in-memory self._shows_cache                                                              |
|  2. Check SQLite twittui_cache (category='shows', key='app_id:app_key')                            |
|  3. Execute GET /shows?page=1&range=1000 via ApiRateLimiter                                        |
|  4. Extract Start Dates from API 'created' timestamp                                               |
|  5. Scrape End Dates from public web archives: /episodes?filter[shows]={id} (Conserves API quota)  |
|  6. Fallback: Load 26 built-in DEFAULT_SHOWS if API credentials are missing or network fails       |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                                      Episode Ingestion                                             |
|                                                                                                    |
|  1. Check _LazySQLiteEpisodesCache (SQLite category='episodes', key=show_id)                      |
|  2. Execute GET /episodes?filter[shows]={id}&page={page}&range=50 via ApiRateLimiter               |
|  3. Deduplicate and merge newly fetched episodes into SQLite persistent store                      |
|  4. Fallback 1: Public Show RSS feed at feeds.twit.tv/{show_slug}_{video_hd|audio}.xml             |
|  5. Fallback 2: Club TWiT Memberful subscriber RSS feed at twit.memberfulcontent.com/rss/{feed_id} |
|  6. Fallback 3: Triangulation public web archive scraping                                          |
+----------------------------------------------------------------------------------------------------+
```

### 6.1 Show Catalog Ingestion & Date Bound Resolution
1. **Catalog Pagination**: Queries `https://twit.tv/api/v1.0/shows?page=1&range=1000` in a single request. If next links exist, it traverses them sequentially.
2. **Date Extraction Strategy**:
   - **Show Start Dates**: Extracted directly from the show object's `created` timestamp in the API payload.
   - **Show End Dates (`fetch_show_date_bounds`)**: To avoid consuming the strict 5 call/minute API limit, TwitTUI scrapes end dates from the public web archive: `https://twit.tv/episodes?filter[shows]={show_id}&page=1`. It extracts the maximum page number via regex (`class="page-number-input".*max="(\d+)"`), reads the newest date from page 1, and reads the oldest date from the last page.
   - **Status Label Formatting**: Formats show selector entries with fixed-width tags:
     - `[Active YYYY-MM-DD - YYYY-MM-DD] Show Title`
     - `[Ended  YYYY-MM-DD - YYYY-MM-DD] Show Title`

### 6.2 Episode Ingestion & Cache Reconciliation
1. **Iterative Block Pagination**: Episodes are retrieved via `GET /episodes?filter[shows]={show_id}&page={page}&range=50`.
2. **Incremental Cache Merge**: If cached episodes exist in SQLite, `fetch_episodes` checks if newly retrieved items match known episode keys (`_episode_cache_key`). When a match occurs, it merges new items with the existing cache and avoids refetching the full historical archive.
3. **Fallback Cascade**:
   - If API credentials are missing or the API returns non-200 responses, the system falls back to `fetch_show_rss_items()`, querying `https://feeds.twit.tv/{show_slug}_video_hd.xml` (or `_audio.xml`).
   - If public RSS fails, it checks Club TWiT Memberful subscriber feeds via `fetch_club_twit_rss_items()`.
   - For legacy productions like *Triangulation*, it scrapes episode lists from HTML archives (`fetch_triangulation_archive`).

### 6.3 Persistent SQLite Caching (`twittui_cache.db`)
Persistent data is stored in an SQLite 3 database located at `~/.cache/twittui/twittui_cache.db` (or `$SNAP_USER_DATA/.cache/twittui/twittui_cache.db` under Snap confinement).

```sql
CREATE TABLE IF NOT EXISTS twittui_cache (
    category TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (category, cache_key)
);
CREATE INDEX IF NOT EXISTS idx_twittui_cache_category ON twittui_cache(category);
```

#### Categories Stored:
- `shows`: Aggregated show catalogs keyed by `app_id:app_key`.
- `show_date_bounds`: Start and end date bounds keyed by `show_id`.
- `episodes`: Complete episode archives keyed by `show_id`.
- `episode_detail`: Detailed single-episode payloads keyed by `episode_id`.
- `media_webpage`: Scraped media URLs keyed by `clean_path|||audio_flag`.
- `triangulation_archive`: Triangulation archive pages keyed by `page_num|||sort_flag`.
- `api_search`: Full-text API search responses keyed by query string.

#### Transparent On-Demand Cache Loading (`_LazySQLiteEpisodesCache`):
Because historical episode archives for long-running shows (like *This Week in Tech* or *Security Now*) contain thousands of records, loading every show's episode archive into RAM at startup would degrade performance.
- `_LazySQLiteEpisodesCache` subclasses Python's standard `dict`.
- At startup, it queries only `SELECT cache_key FROM twittui_cache WHERE category = 'episodes'`, populating an in-memory set of available keys (`_unloaded_keys`).
- When a show's episodes are accessed via `__getitem__`, `get()`, or `in`, it intercepts the call, executes `SELECT data_json FROM twittui_cache WHERE category = 'episodes' AND cache_key = ?`, parses the JSON payload into memory, and removes the key from `_unloaded_keys`.
- This ensures zero deserialization overhead for unviewed shows while preserving standard dictionary semantics.

---

## 7. Tiered Search Engine & Phonetic Matching (`tiered_search.py`, `double_metaphone.py`)

To eliminate the frustration of misspelled queries, partial abbreviations, and guest name mispronunciations, TwitTUI implements a three-tiered search engine in `tiered_search.py` and `double_metaphone.py`.

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
| - Scans: Title, Hosts/Guests, Topics, Description/Show Notes, Episode Number      |
| - If all query tokens appear verbatim in text -> Score = 100.0                    |
+-----------------------------------------------------------------------------------+
                                        │ (If Score < 100.0)
                                        ▼
+-----------------------------------------------------------------------------------+
| Tier 2: Ranked Fuzzy & fzf-Style Subsequence Scoring                              |
| - fzf_subsequence_score: Smith-Waterman alignment checking character order         |
|   Bonuses: +10 word start, +5*consecutive runs, camelCase transitions             |
| - fuzzy_ratio: Levenshtein edit distance normalized by string length              |
| - Matches typos & abbreviations (e.g. 'secruity' -> 'security', 'macbrk')         |
| - Score Range: 60.0 - 99.0                                                        |
+-----------------------------------------------------------------------------------+
                                        │ (If Score < 75.0)
                                        ▼
+-----------------------------------------------------------------------------------+
| Tier 3: Pure Python Double Metaphone Phonetic Correlation                         |
| - Lawrence Philips Double Metaphone Algorithm (double_metaphone.py)               |
| - Generates Primary and Alternate 4-character phonetic keys                       |
| - Matches sound-alikes: 'ballacer' -> 'Ballecer' (PLSR == PLSR -> Score: 95.0)    |
| - Matches 'algorhtm' -> 'algorithms' (ALKR == ALKR -> Score: 95.0)                |
+-----------------------------------------------------------------------------------+
                                        │
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │ Apply Domain-Specific Field Multipliers: │
                  │ Title: 1.3x                              │
                  │ Hosts/Guests: 1.25x                      │
                  │ Topics/Tags: 1.2x                        │
                  │ Episode Number: 1.1x                     │
                  │ Description/Notes: 1.0x                  │
                  └──────────────────────────────────────────┘
                                        │
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │ Filter results below threshold (65.0)    │
                  │ Sort descending by weighted match score  │
                  └──────────────────────────────────────────┘
```

### 7.1 Tier 1: Exact Substring Matching
Evaluates all whitespace-delimited query tokens against candidate episode fields (`Title`, `Hosts / Guests`, `Topics`, `Description / Show Notes`, `Episode Number`). If every query word is present as a case-insensitive substring within the target metadata, it assigns an exact match score of `100.0`.

### 7.2 Tier 2: Ranked Fuzzy & `fzf` Subsequence Scoring
When exact matching fails:
1. **`fzf_subsequence_score(query, target)`**: Implements local sequence alignment. It checks if query characters appear sequentially within candidate tokens, awarding score bonuses for:
   - Matches at word start boundaries (`is_word_start = t_idx == 0 or not t[t_idx - 1].isalnum()`): `+10.0`.
   - Contiguous consecutive character matches: `+5.0 * consecutive_count`.
2. **`fuzzy_ratio(s1, s2)` / `levenshtein_distance(s1, s2)`**: Computes minimum character edits (insertions, deletions, substitutions):
   $$\text{ratio} = \frac{(|s_1| + |s_2|) - d_{\text{Lev}}(s_1, s_2)}{|s_1| + |s_2|} \times 100$$
3. Uses `rapidfuzz.fuzz.ratio` and `partial_ratio` when the C-accelerated library is available, falling back to pure Python Levenshtein implementations seamlessly.
4. Normalizes Tier 2 scores into the range `60.0`–`99.0`, ranking them just below exact matches.

### 7.3 Tier 3: Pure Python Double Metaphone Phonetic Engine (`double_metaphone.py`)
`double_metaphone.py` (648 lines) is a pure Python implementation of Lawrence Philips' **Double Metaphone** algorithm (published in 2000). It converts strings into primary and secondary 4-character phonetic encoding codes:
- Handles silent initial consonants (`GN`, `KN`, `PN`, `WR`, `PS`).
- Contextual `C` rules (soft `/S/` before `E`/`I`/`Y`, hard `/K/`, Germanic `CH` as `/K/`, Italian `CCIA`).
- Spanish and Romance sound shifts (`LL` to `/L/` or silent vowel glides).
- Vowel dropping and consonant classification.

#### Phonetic Equivalence Examples:
- Query `ballacer` generates `(PLSR, PLSR)`. Candidate token `Ballecer` generates `(PLSR, PLSR)`. Since their primary keys match, it awards a phonetic score of `95.0`.
- Query `algorhtm` generates `(ALKR, ALKR)`. Candidate token `algorithms` generates `(ALKR, ALKR)`, resulting in a `95.0` match.

### 7.4 Search Match Inspection & KWIC Snippets
When an episode matches a query, `find_match_context()` builds a `MatchContext` object capturing provenance:
- `field_name`: The matched field (`Description / Show Notes`, `Title`, `Hosts / Guests`).
- `matched_token`: The exact token found in the metadata (e.g., `Ballecer`).
- `query_token`: The user's query token (e.g., `ballacer`).
- `match_tier`: Formatted classification label (`Exact Match`, `Fuzzy Match (92% similarity)`, or `Phonetic Match ("ballacer" ≈ "Ballecer")`).
- `char_offset`: Character index of the match within the text.
- `snippet`: Keyword-in-Context (KWIC) excerpt generated by `extract_snippet()`. Extracts a 100-character window centered on the match, scanning up to 15 characters in either direction to align cleanly to whitespace word boundaries.

---

## 8. Episode Metadata Hover Preview & Inspection System

TwitTUI provides immediate metadata inspection without requiring network queries or row clicks.

### 8.1 3-Second Hover Dwell Engine
1. **GTK Implementation (`_setup_table_hover_events`)**: Connects to the native `GtkTreeView`'s `motion-notify-event` and `leave-notify-event` signals with `Gdk.EventMask.POINTER_MOTION_MASK` and `LEAVE_NOTIFY_MASK`.
   - `_on_table_motion_notify`: Calls `widget.get_path_at_pos(x, y)` to resolve the hovered row index.
   - If the cursor stays on the same row, it starts a daemon `threading.Timer(3.0, self._trigger_hover_metadata, args=(row_idx,))`.
   - Any motion to a different row or out of the table immediately cancels the active timer under `_hover_lock`.
2. **Textual Implementation (`_on_textual_table_hover_row`)**: `TextualTable` captures mouse enter/hover events over table rows and dispatches them to `_on_textual_table_hover_row`, running identical 3-second timer logic.

### 8.2 Popup Metadata Dialog & Auto-Scroll
When the 3-second timer triggers, `show_episode_metadata_dialog()` displays the episode inspection window:
- **Search Match Banner**: If an active search query matched the episode, it renders a `🔍 Search Match` callout banner displaying the matched field, tier description, and KWIC snippet.
- **Metadata Fields**: Formats Title, Show Name, Episode Number, Air Date, Duration, File Size, Formats, Hosts/Guests, and Topics.
- **Clickable Action Links**: Renders clickable buttons for the Web Link, Transcript Link, and Direct Media URL that launch in the system browser when pressed.
- **GTK Cursor Auto-Scroll**: If the search match occurred within the Description/Show Notes, `_show_episode_metadata()` obtains the native `GtkTextBuffer` from the multiline text view, calls `buf.get_iter_at_offset(char_offset)`, places the insertion cursor at the match position, and executes `native.scroll_to_iter(iter_pos, 0.1, True, 0.0, 0.2)` to scroll the text view directly to the matched term.

---

## 9. Media Resolution & Streaming Engine

Resolving a playable media stream URL across TWiT's heterogeneous API schemas and RSS syndication formats is handled by `resolve_media_url()` and `extract_media_url()`.

### 9.1 Resolution Hierarchy
Media resolution adjusts dynamically based on the **Audio Only** setting (`is_audio_only()`):

```python
# Video preference order (Audio Only unchecked)
VIDEO_PREFERENCE = ['video_hd', 'video_large', 'video_small', 'video_audio', 'video_youtube']

# Audio preference order (Audio Only checked)
AUDIO_PREFERENCE = ['video_audio', 'audio', 'video_hd', 'video_large', 'video_small', 'video_youtube']
```

#### Multi-Source Resolution Cascade (`resolve_media_url`):
1. **Club TWiT Memberful Feeds**: Checks configured subscriber RSS feeds (`MEMBERFUL_SHOW_FEEDS`, `MEMBERFUL_HOST_FEEDS`, and network feeds). Subscriber enclosures take precedence to provide ad-free streams.
2. **Direct API Fields**: Evaluates standard API objects (`video_hd`, `video_large`, etc.), direct URL fields (`mediaUrl`, `downloadUrl`), files dictionaries, and `_links` enclosures.
3. **Public Show RSS Feeds**: Queries public feeds at `https://feeds.twit.tv/{show_slug}_{video_hd|audio}.xml`, matching items via clean path slugs, episode numbers, or episode titles (`_match_rss_item`).
4. **Episode Webpage Scraping**: Fetches public episode HTML (`https://twit.tv{cleanPath}`) and uses regex to extract embedded `.mp4`, `.mp3`, or `.m4a` stream links.
5. **REST API Detail Endpoint**: Fetches full episode records via `GET /episodes/{episode_id}`.
6. **YouTube Fallback**: Resolves YouTube stream identifiers.

### 9.2 Validation Filter (`is_valid_media_url`)
To prevent passing API metadata endpoints or HTML error documents to media players, every URL must pass `is_valid_media_url()`:
- Verifies protocol: Must begin with `http://`, `https://`, `rtsp://`, or `mms://`.
- Rejects API endpoints containing `/api/` or `twit.tv/api`.
- Rejects TWiT website navigation paths (`/shows`, `/episodes`, `/node`, `/people`) unless a recognizable media extension (`.mp4`, `.mp3`, `.m4a`, `.webm`, `.ogg`) is present.

### 9.3 Secure Stream Subprocess Execution
Streaming is handled without blocking the UI:
1. **Argument Tokenization (`build_stream_args`)**: Parses streamer templates (default: `env LC_ALL=C vlc %f`) using `shlex.split()`. It safely replaces `%f`, `{url}`, `%s`, `{file}`, or `{media_url}` with the resolved media stream URL without invoking a shell.
2. **Detached Spawning (`launch_stream_safe`)**: Executes media players via `subprocess.Popen(args, shell=False)`. This prevents shell injection vulnerabilities and keeps the player independent of TwitTUI's process lifecycle.
3. **YouTube Redirection**: If a user streams a YouTube video format, TwitTUI opens the video directly in their default web browser for native playback.

---

## 10. Multi-Threaded Batch Downloader & Deduplication

Batch downloading is managed asynchronously in background daemon threads via `download_episodes_batch()`.

### 10.1 Deduplication & File Verification (`is_existing_file_identical`)
To conserve bandwidth and avoid redundant writes, TwitTUI verifies existing target files before starting transfers:
1. **Size Verification**: Compares local file size against expected RSS enclosure lengths or remote HTTP `Content-Length` headers.
2. **Cryptographic ETag Checksum**: If the remote server returns an HTTP `ETag` containing a 32-character hexadecimal string, TwitTUI computes the local file's MD5 checksum in 64 KB chunks (`hashlib.md5()`). If the checksums match, the download is skipped.
3. **YouTube Heuristic**: Existing YouTube downloads exceeding 1 MB are considered downloaded and skipped.

### 10.2 Chunked Streaming & Safe Staging
`download_episode_file()` performs robust chunked streaming:
1. **Staging File**: Streams content into `<dest_path>.part` using configurable chunk buffers (default: 8192 bytes / `twitclubblocksize`).
2. **Cancellation Support**: Checks `self._cancel_download` during iteration. When cancelled, it breaks the loop and deletes the partial `.part` file.
3. **MIME Verification**: Reads incoming `Content-Type` headers. If the server returns HTML instead of binary media, it parses the HTML to extract embedded media links rather than saving an HTML error page.
4. **Final Promotion**: Once downloaded and verified via `is_valid_media_file()`, any existing target file is unlinked, and `<dest_path>.part` is renamed to `<dest_path>`.
5. **Specialized YouTube Pipeline (`download_youtube_video`)**: Uses `yt-dlp` or `youtube-dl` via Python APIs, falling back to CLI subprocess execution.

### 10.3 Path Sanitization & Show Folders
`determine_download_filename()` sanitizes file names across POSIX, NTFS, and FAT32 filesystems:
- Strips invalid characters: `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`.
- Normalizes `TWiT+` prefixes and collapses multiple whitespace characters.
- Constructs standardized names: `<Show Name> <Episode Number> <Episode Title>.<ext>`.
- **Show Folders (`is_show_folders_enabled`)**: When enabled via UI or `TWITCLUBSHOWFOLDERS=1`, downloads are routed into dedicated show subfolders: `<Destination>/<Show Name>/<Filename>`.

---

## 11. Configuration Architecture & Preferences Synchronization

TwitTUI centralizes configuration inside `.env` files and manages live state updates across sessions.

### 11.1 Configuration Schema

| Key | Default | Description |
| :--- | :--- | :--- |
| `TWITAPI_APPLICATIONID` | *None* | 3Scale Application ID for TWiT.tv REST API access. |
| `TWITAPI_APPLICATIONKEYS` | *None* | 3Scale Application Key for TWiT.tv REST API access. |
| `twitcluburl` | `""` | Memberful RSS feed URL or unique authentication key. |
| `twitclubdestination` | `~/Downloads` | Target download directory. |
| `twitclubblocksize` | `8192` | Stream buffer chunk size in bytes (8 KB). |
| `twitclubstreamer` | `env LC_ALL=C vlc %f` | Subprocess command template for launching media players. |
| `TWITAUDIOONLY` | `0` | Prefers audio feeds and formats when enabled (`1`). |
| `TWITCLUBSHOWFOLDERS` | `0` | Organizes downloads into per-show subdirectories (`1`). |
| `TWITFUZZYSEARCH` | `1` | Enables Tier 2 ranked fuzzy / subsequence search matching (`1`). |
| `TWITPHONETICSEARCH` | `1` | Enables Tier 3 Double Metaphone phonetic sound-alike search (`1`). |
| `twitapiratelimit` | `5` | API sliding window request limit per rolling minute. |

### 11.2 Environment Resolution & Persistence
1. **Loading (`load_twittui_dotenv`)**: In standard execution, it resolves `.env` in the current working directory, falling back to the module directory. Under Snap confinement, it isolates settings inside `$SNAP_USER_DATA/.env`. It calls `load_dotenv(..., override=True)` so disk settings take precedence over inherited environment variables.
2. **Saving (`save_env_setting`)**: Serializes modified preferences back to `.env` using atomic file replacements, preserving existing comments and ordering.

---

## 12. Packaging & Sandboxing Infrastructure

### 12.1 Standalone Binary Packaging Engine (`installer.py`)
`installer.py` compiles standalone, self-contained binaries using PyInstaller:
1. **Shared Library Verification (`check_python_shared_library`)**: Verifies that the Python interpreter was compiled with shared library support (`--enable-shared` / `libpython3.X.so`). PyInstaller on Linux cannot bundle statically linked Python binaries.
2. **Asset Bundling**: Packages icons (`resources/`), stylesheets (`feed-style.css`, `feed-style.xsl`), documentation (`README.md`), and API specifications (`twittv.apib`).
3. **Hidden Import Collection**: Collects dynamic imports including `tiered_search`, `double_metaphone`, `toga_gtk`, `toga_textual`, `textual`, and GObject overrides.
4. **PATH Installation (`install_twittui`)**: Locates writable user binary directories (`~/.local/bin`, `~/bin`, `/usr/local/bin`), copies the binary via `shutil.copy2`, and sets executable permissions (`0o755`).
5. **Hygiene Engine (`clean_build_artifacts`)**: Cleans up build directories (`build/`, `dist/`) and `.spec` files, with an option to uninstall PyInstaller (`--uninstall-pyinstaller`).

### 12.2 Ubuntu Core 24 Snap Packaging (`snap/`)
TwitTUI includes production Snap packaging configurations supporting cross-distribution deployment on Ubuntu, Debian, Fedora, Arch, and openSUSE:
- **`snap/snapcraft.yaml`**: Built on Ubuntu Core 24 (`core24`) with strict confinement (`confinement: strict`). Declares desktop plugs (`desktop`, `desktop-legacy`, `wayland`, `x11`, `opengl`, `audio-playback`, `network`, `home`, `removable-media`).
- **Dual Snap Entry Points**:
  - `twittui`: Launches GTK graphical desktop UI (`bin/twittui-launcher --gtk`).
  - `twittui.tui`: Launches Textual terminal interface (`bin/twittui-launcher --textual`).
- **Runtime Sandbox Launcher (`snap/local/launcher.sh`)**:
  - Sanitizes incompatible host theme variables (`GTK_MODULES`, `UBUNTU_MENUPROXY`).
  - Sets up library paths (`LD_LIBRARY_PATH`), GObject typelibs (`GI_TYPELIB_PATH`), and schema directories (`GSETTINGS_SCHEMA_DIR`).
  - Automatically queries and builds the GDK Pixbuf loaders cache (`gdk-pixbuf-query-loaders > $SNAP_USER_DATA/.loaders.cache`) to ensure image and icon rendering functions across all desktop environments.

---

## 13. Quality Assurance & Automated Test Suite

TwitTUI maintains an automated test suite comprising 263 unit and integration tests across 20 test modules.

```
test_*.py Test Coverage Matrix:
├── test_api_rate_limiter.py       # Sliding window rate limiting, 5 req/min cap, 403/500 retry logic
├── test_backend_factory.py        # Backend detection, CLI switches (--gtk, --textual), fallback recovery
├── test_caching.py                # SQLite cache initialization, TTL expiration, LazyEpisodesCache proxy
├── test_episode_activation.py     # Row selection, double-click streaming activation, keyboard events
├── test_episode_search.py         # Multi-tier search (Exact, Fuzzy, Double Metaphone), sorting stability
├── test_gtk_maximize_layout.py    # GTK window state events, table resizing, flexbox layout stability
├── test_hover_popup.py            # 3-second hover dwell timers, metadata dialog, KWIC snippet auto-scroll
├── test_install.py                # PyInstaller packaging, shared library validation, artifact cleanup
├── test_open_destination.py       # Cross-platform directory creation and file manager launching
├── test_preferences.py            # In-app settings dialog, search toggles, .env serialization
├── test_resolutions.py            # Multi-resolution format parsing, sorting, batch resolution modals
├── test_security.py               # Markdown and HTML sanitization, dangerous URI scheme filtering
├── test_show_catalog.py           # Catalog pagination, date scraping, rate-limit wait modal sync
├── test_show_folders.py           # Show folder directory creation, filename sanitization
├── test_snap.py                   # Snapcraft recipe, desktop entry validity, sandbox launcher script
├── test_splash_screen.py          # Terminal splash banner, Textual modal splash, GTK splash window
├── test_tooltips.py               # Tooltip injection across GTK and Textual widgets
├── test_tui_multiselect.py        # Textual table multi-selection, space toggle, checkbox gutter
├── test_tui_streaming_and_stdout.py# Stream launching, stdout redirection, Textual context safety
└── test_youtube_download.py       # YouTube format extraction and yt-dlp download handling
```

The test suite runs with Python's standard `unittest` runner:
```bash
GDK_BACKEND=x11 DISPLAY=:0 WAYLAND_DISPLAY="" python -m unittest discover
```
All 263 tests execute in under 30 seconds, confirming regression-free operation across the entire codebase.
