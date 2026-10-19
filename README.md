# TwitTUI: TWiT.tv Terminal & Desktop Media Browser

TwitTUI is an efficiency-focused, cross-platform media client for browsing, streaming, and batch-downloading podcast episodes from the [TWiT.tv](https://twit.tv) network. Built upon the [BeeWare Toga](https://beeware.org/) framework, TwitTUI operates seamlessly across terminal environments and graphical desktop environments with minimal resource overhead.

This document serves two primary audiences:
1. **[End-User Guide](#end-user-guide)**: Practical, step-by-step instructions for installing, configuring, and operating the application.
2. **[Developer & Technical Architecture Reference](#developer--technical-architecture-reference)**: Exhaustive architectural, algorithmic, and implementation documentation for software engineers maintaining or extending the codebase.

---

## Table of Contents

- [Core Capabilities](#core-capabilities)
- [End-User Guide](#end-user-guide)
  - [System Requirements](#system-requirements)
  - [Installation](#installation)
  - [Configuration (.env & UI)](#configuration-env--ui)
  - [User Interface & Usage Walkthrough](#user-interface--usage-walkthrough)
    - [Show Selection & Episode Browsing](#show-selection--episode-browsing)
    - [Searching Episodes](#searching-episodes)
    - [Sorting Episodes](#sorting-episodes)
    - [Streaming an Episode](#streaming-an-episode)
    - [Batch Downloading Episodes](#batch-downloading-episodes)
    - [Club TWiT Member Features](#club-twit-member-features)
- [Developer & Technical Architecture Reference](#developer--technical-architecture-reference)
  - [Project Structure](#project-structure)
  - [Execution Lifecycle & Runtime Sanitization (`main.py`)](#execution-lifecycle--runtime-sanitization-mainpy)
  - [UI Architecture & Widget Tree (`twittui_form.py`)](#ui-architecture--widget-tree-twittui_formpy)
  - [Data Ingestion & 5-Tier Fallback Cascade](#data-ingestion--5-tier-fallback-cascade)
  - [Media Resolution Engine & Extraction Heuristics](#media-resolution-engine--extraction-heuristics)
  - [Asynchronous Streaming & Multi-Threaded Batch Downloader](#asynchronous-streaming--multi-threaded-batch-downloader)
  - [Filesystem Sanitization & Naming Pipeline](#filesystem-sanitization--naming-pipeline)
  - [REST API Blueprint Integration (`twittv.apib`)](#rest-api-blueprint-integration-twittvapib)
  - [Environment Variables & Configuration Schema](#environment-variables--configuration-schema)
- [Known Issues & Troubleshooting](#known-issues--troubleshooting)
  - [GTK Module & Backend Warnings](#gtk-module--backend-warnings)
  - [Missing API Credentials Fallback](#missing-api-credentials-fallback)
  - [VLC / Streamer Path Resolution](#vlc--streamer-path-resolution)
- [License & Credits](#license--credits)

---

## Core Capabilities

- **Show Catalog Navigation**: Browse active and legacy TWiT.tv productions with automatic fallback to static show catalogs when offline or unauthenticated.
- **In-Show Episode & Topic Search**: Search episodes within the currently selected show by keywords or topics using the official TWiT REST API search endpoint (`/search/{keywords}`) with automatic fallback to Show and Club RSS feed matching.
- **Episode Metadata Hover Preview**: Hovering over any episode row for 3 seconds triggers a detailed metadata modal revealing complete show notes, guest and host lists, topics, duration, direct media stream links, and episode transcripts with clickable buttons for Web Link, Transcript, and Media URL that launch the default browser.
- **Resilient Episode Ingestion**: Automatic multi-tier failover across the official TWiT REST API v1.0, public XML/RSS feeds (`feeds.twit.tv`), authenticated Club TWiT Memberful RSS feeds, and webpage media scrapers.
- **Direct Video/Audio Streaming**: Spawn external media players (e.g., VLC, MPV) asynchronously using customizable command templates without stalling the UI.
- **Concurrent Batch Downloader**: Download single or multiple episodes in non-blocking background daemon threads with configurable byte buffers, duplicate file confirmation, and atomic file writes.
- **Smart Download Deduplication**: Automatically skips re-downloading files if a complete local copy already exists and is confirmed identical via HTTP HEAD `Content-Length` and MD5 cryptographic checksum verification (`ETag`).
- **Club TWiT Integration**: Native support for subscriber Memberful authentication keys, giving direct access to ad-free streams and subscriber-exclusive shows.
- **Cross-Platform Portability**: Developed on BeeWare's Toga widget toolkit, supporting terminal execution (`toga-textual`) and native desktop GUI backends (`toga-gtk`, `toga-cocoa`, `toga-winforms`).

---

## End-User Guide

### System Requirements

- **Python**: Version 3.10, 3.11, or 3.12+
- **Media Player**: [VLC Media Player](https://www.videolan.org/vlc/) (default) or any player that accepts stream URLs via CLI (such as `mpv` or `ffplay`).
- **Operating System**: Linux, macOS, or Windows.
  - *Linux note*: If running via GTK backend, ensure standard GTK libraries are installed (`libgirepository1.0-dev`, `gir1.2-gtk-3.0`).

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/twittui.git
   cd twittui
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install toga requests python-dotenv
   ```
   *(Install GTK desktop UI, Textual terminal UI, or both simultaneously)*:
   ```bash
   pip install toga-gtk toga-textual  # Both backends can be installed concurrently
   ```

4. **Launch the application**:
   ```bash
   python main.py
   ```
   - When both `toga-gtk` and `toga-textual` are installed, TwitTUI prompts you at startup to choose your preferred UI interface:
     ```text
     Multiple Toga UI backends detected:
       1) GTK (Graphical Desktop UI)
       2) Textual (Terminal User Interface)
     Select backend [1/2] (default: 1 - GTK):
     ```
   - You can also bypass the startup prompt using command line switches:
     ```bash
     python main.py --gtk        # Launch GTK desktop GUI
     python main.py --textual    # Launch Textual terminal UI (TUI)
     python main.py -b gtk       # Alternative syntax (-b gtk / -b textual)
     python main.py --help       # Display all backend options and switches
     ```

---

### Configuration (.env & UI)

TwitTUI reads default configuration values from a local `.env` file upon launch, which can also be modified in real time via the application settings panel.

Create a `.env` file in the project root directory:

```ini
# TWiT.tv API Credentials (Optional - app falls back to public RSS feeds if omitted)
TWITAPI_APPLICATIONID=your_3scale_app_id
TWITAPI_APPLICATIONKEYS=your_3scale_app_key

# Club TWiT Memberful Configuration
# Paste either your full RSS URL or just your unique authorization key
twitcluburl=https://twit.memberfulcontent.com/rss/9041?auth=YOUR_SECRET_AUTH_KEY

# Download Destination Directory
twitclubdestination=~/Downloads/TWiT

# Download Stream Read Buffer Size (Bytes)
twitclubblocksize=8192

# Media Player Streaming Command Template (%f or {url} will be replaced by stream URL)
twitclubstreamer=vlc %f
```

---

### User Interface & Usage Walkthrough

```
+---------------------------------------------------------------------------------+
| Show: [ This Week in Tech                  v ] [ Fetch ] [ Next ]               |
| Search: [ OpenAI                                ] [ Search ] [ Clear ]          |
| Sort by: [X Date]  [  Episode Number]  [  Episode Title] [v Desc]               |
| +-----------------------------------------------------------------------------+ |
| | Episode | Title                        | Date       | Length   | Size       | |
| |---------|------------------------------|------------|----------|------------| |
| | 1001    | TWiT 1001: AI in Fast Lane   | 2024-10-13 | 02:15:40 | 642.5 MB   | |
| | 1000    | TWiT 1000: The Milestone     | 2024-10-06 | 02:08:15 | 618.2 MB   | |
| +-----------------------------------------------------------------------------+ |
| [ Download ]  [ Stream ]  [ Cancel ]  [ Close ]                                 |
|                                                                                 |
| API Application ID:   [ 3edec74c                 ]                              |
| API Application Key:  [ 36a22e422f0f8773e03b8... ] [ Test API ]                |
| TWIT Club URL: https://twit.memberfulcontent.com/rss/9041?auth= [ KEY ] [ Show ]|
| Download Destination: [/home/user/Podcasts       ] [ Browse ] [ Open ]          |
| Block Size:           [8192                      ]                              |
| Streamer:             [vlc %f                    ]                              |
+---------------------------------------------------------------------------------+
```

#### Show Selection & Episode Browsing
- Click the **Show** dropdown menu to select a show.
- The episode list refreshes automatically upon selection.
- Click **Fetch** to force a catalog refresh against the TWiT API or fallback feeds.
- Click **Next** to fetch and append the next page of episodes for the active show.
- **Episode Metadata Inspection**: Hovering your mouse cursor over any episode row in the list for more than 3 seconds displays a modal dialog showing comprehensive episode metadata including show name, episode number, title, airing date, duration, episode ID, web links, transcript links, media stream URLs, available formats, hosts/guests, topics, and complete show notes. Web links, transcript links, and media URLs are clickable to open directly in your system's default web browser.

#### Searching Episodes
- Enter keywords or topics (e.g., `OpenAI`, `Surface`, `Security`) into the **Search** text box.
- Click **Search** or press `Enter` to query the TWiT REST API search endpoint and fallback RSS feeds scoped to the active show.
- The table populates immediately with all matching episodes across the selected show.
- Click **Clear** (or submit an empty search) to clear the search input and restore the complete episode list for the selected show.

#### Sorting Episodes
- Select one of the three sort mode buttons:
  - **☑ Date**: Sorts episodes by airing/publication date.
  - **☑ Episode Number**: Sorts numerically by episode number.
  - **☑ Episode Title**: Sorts alphabetically by episode title.
- Toggle the sort direction button:
  - **▼ Descending**: Queries the TWiT REST API with descending sort (`-airingDate`, `-episodeNumber`, `-label`) to display newest/highest first.
  - **▲ Ascending**: Queries the TWiT REST API with ascending sort (`airingDate`, `episodeNumber`, `label`) to fetch and display oldest/lowest first (e.g., Episode 1 forward).

#### Streaming an Episode
1. Click on an episode in the list table to highlight it.
2. Double-click the row or press the **Stream** button.
3. TwitTUI resolves the high-definition media stream and launches your configured media player in a detached process.

#### Batch Downloading Episodes
1. Highlight one or more episodes in the table (hold `Shift` or `Ctrl` for multiple selections).
2. Ensure **Download Destination** is set to your preferred folder (use **Browse** to select).
3. Click **Download**. Downloads execute concurrently in the background without freezing the UI.
4. Files are saved directly to your destination path with normalized, clean filenames (e.g., `This Week in Tech 1001 AI in the Fast Lane.mp4`).
5. When the batch completes, a modal dialog appears displaying the target download folder at the top and the list of downloaded filenames (one per line) with a **Close** button.

#### Club TWiT Member Features
- Paste your unique Memberful key into the **TWIT Club URL** box.
- When configured, TwitTUI automatically checks your Club TWiT feed for commercial-free and subscriber-exclusive episodes.
- Click the **Show** button next to the URL input to fetch, format, and view your Club TWiT feed as a styled webpage directly in your default web browser (styled with `feed-style.css`).

---

## Developer & Technical Architecture Reference

### Project Structure

```
twittui/
├── main.py                  # Process bootstrap, stderr filtering, and GTK environment patching
├── twittui_form.py          # Core application logic, Toga GUI/TUI layout, networking, and workers
├── twittv.apib              # Full API Blueprint documentation for TWiT.tv REST API v1.0
├── Layout_spec_for_AI.txt   # UI specification and control layout blueprint
├── feed-style.css           # Modern, responsive CSS stylesheet for podcast RSS feeds
├── feed-style.xsl           # Standalone XSLT 1.0 transformation template for podcast RSS feeds
├── .env                     # Local environment configuration file (ignored in VCS)
└── README.md                # System documentation and technical manual
```

---

### Execution Lifecycle & UI Backend Selection (`main.py`)

`main.py` is the execution entry point. Before importing GUI modules or initializing the main loop, it dynamically inspects available Toga backends (`toga-gtk`, `toga-textual`), processes command-line switches or interactive startup prompts, sets `TOGA_BACKEND`, and executes runtime environment stabilization:

```
[ Process Start ]
        │
        ▼
[ Parse CLI Switches & Inspect Backends ]
  ├── --gtk / --gui / -b gtk       ──► Force toga_gtk
  ├── --textual / --tui / -b textual ──► Force toga_textual
  └── (No Switch & Both Found)     ──► Interactive CLI prompt [1: GTK / 2: Textual]
        │
        ▼
[ Set TOGA_BACKEND & Configure Environment ]
  ├── If toga_gtk:
  │     ├── Instantiate StderrRedirector (Filter xapp-gtk3-module warnings)
  │     ├── GTK_MODULES = '' (Suppress external modules)
  │     ├── del GTK_DEBUG (Prevent assertion crashes in non-debug GTK)
  │     ├── NO_AT_BRIDGE = '1' (Bypass accessibility D-Bus bridge overhead)
  │     ├── GDK_BACKEND = 'x11' (Enforce stable X11 protocol)
  │     └── G_MESSAGES_DEBUG = '' (Mute Glib debug logging)
  └── If toga_textual:
        └── Initialize Textual terminal rendering loop
        │
        ▼
[ load_dotenv() ] ──► Ingest environment configurations
        │
        ▼
[ twittui_form.main() ] ──► Build Toga widget hierarchy & launch app.main_loop()
```

#### `StderrRedirector` Implementation
```python
class StderrRedirector:
    def __init__(self, original_stderr) -> None:
        self.original_stderr = original_stderr

    def write(self, message) -> None:
        if "Failed to load module" in message and "xapp-gtk3-module" in message:
            return
        self.original_stderr.write(message)

    def flush(self) -> None:
        self.original_stderr.flush()
```

---

### UI Architecture & Widget Tree (`twittui_form.py`)

`TwitTUIForm` extends `toga.App` and declares a declarative widget layout inside `startup()`. Layout geometry is managed through `travertino` / `toga.style.Pack` flexbox rules.

#### Application Menu Commands
- **Help Menu (`toga.Group.HELP`)**:
  - **View README Documentation**: Opens the integrated documentation viewer via the **Hybrid Resilient Pattern**. Converts Markdown to fully sanitized HTML (stripping malicious tags, event handlers, and dangerous URI schemes) and displays it in an in-app `toga.WebView` window with automatic fallback to the system default web browser. Features smooth Table of Contents anchor navigation and a persistent floating "↑ Table of Contents" button.
  - **View API Specification (twittv.apib)**: Opens the complete API Blueprint specification for the TWiT.tv REST API v1.0 formatted and rendered identically to the README documentation viewer with HTML sanitization, anchor navigation, and hybrid viewer fallback.
  - **Get TWiT API Key**: Opens the official TWiT 3Scale API developer portal (`https://twit-tv.3scale.net`) in the default system web browser to register applications and obtain API Application IDs and Keys.

#### Widget Hierarchy
```
toga.MainWindow (title='TWIT.tv TUI')
└── toga.Box (direction=COLUMN, margin=5) [main_box]
    ├── toga.Box (direction=ROW, margin=5) [show_box]
    │   ├── toga.Label ('Show:')
    │   ├── toga.Selection (items=shows, on_change=on_show_select) [show_combo]
    │   ├── toga.Button ('Fetch', on_press=on_fetch_press)
    │   └── toga.Button ('Next', on_press=on_next_press)
    ├── toga.Box (direction=ROW, margin=5) [search_box]
    │   ├── toga.Label ('Search:')
    │   ├── toga.TextInput (placeholder='Search episodes in selected show...', on_confirm=on_search_press) [search_input]
    │   ├── toga.Button ('Search', on_press=on_search_press)
    │   └── toga.Button ('Clear', on_press=on_clear_search_press)
    ├── toga.Box (direction=ROW, margin=5) [sort_box]
    │   ├── toga.Label ('Sort by:')
    │   ├── toga.Button ('☑ Date', on_press=on_sort_button_press) [date_radio]
    │   ├── toga.Button ('☐ Episode Number', on_press=on_sort_button_press) [episode_radio]
    │   ├── toga.Button ('☐ Episode Title', on_press=on_sort_button_press) [title_radio]
    │   ├── toga.Button ('▼ Descending', on_press=on_sort_order_toggle) [sort_order_button]
    │   └── toga.Button ('☐ Audio Only', on_press=on_audio_only_toggle) [audio_only_checkbox]
    ├── toga.Label ('Episodes:')
    ├── toga.Table (headings=['Episode', 'Title', 'Date', 'Length', 'Size'], multiple_select=True) [episodes_list with horizontal scrollbar & 3s hover metadata modal]
    ├── toga.Box (direction=ROW, margin=5) [button_box]
    │   ├── toga.Button ('Download', on_press=on_download_press)
    │   ├── toga.Button ('Stream', on_press=on_stream_press)
    │   ├── toga.Button ('Cancel', on_press=on_cancel_press)
    │   └── toga.Button ('Close', on_press=on_close_press)
    └── toga.Box (direction=COLUMN, margin=5) [settings_box]
        ├── toga.Box (direction=ROW) [app_id_box]
        │   ├── toga.Label ('API Application ID:')
        │   └── toga.TextInput (value=initial_app_id) [app_id_input]
        ├── toga.Box (direction=ROW) [app_key_box]
        │   ├── toga.Label ('API Application Key:')
        │   ├── toga.TextInput (value=initial_app_key) [app_key_input]
        │   └── toga.Button ('Test API', on_press=on_test_api_press)
        ├── toga.Box (direction=ROW) [url_box]
        │   ├── toga.Label ('TWIT Club URL:')
        │   ├── toga.Label ('https://twit.memberfulcontent.com/rss/9041?auth=')
        │   ├── toga.TextInput (value=initial_url_key) [url_input]
        │   └── toga.Button ('Show', on_press=on_show_club_url_press)
        ├── toga.Box (direction=ROW) [dest_box]
        │   ├── toga.Label ('Download Destination:')
        │   ├── toga.TextInput (value=initial_dest) [dest_input]
        │   ├── toga.Button ('Browse', on_press=on_browse_press)
        │   └── toga.Button ('Open', on_press=on_open_destination_press)
        ├── toga.Box (direction=ROW) [block_box]
        │   ├── toga.Label ('Block Size:')
        │   └── toga.TextInput (value='8192') [block_input]
        └── toga.Box (direction=ROW) [streamer_box]
            ├── toga.Label ('Streamer:')
            └── toga.TextInput (value='vlc %f') [streamer_input]
    └── toga.ProgressBar (max=100.0, value=0.0) [progress_bar]
```

---

### Data Ingestion & 5-Tier Fallback Cascade

To ensure continuous operation regardless of API authentication status, network outages, or rate limiting, `TwitTUIForm` executes a five-tier resolution cascade for shows, episodes, and direct media URLs:

```
[ Request Episode Data / Media URL ]
                │
                ▼
      ┌───────────────────┐
      │ Tier 1: REST API  │ ──► GET https://twit.tv/api/v1.0/episodes?filter[shows]={id}
      └─────────┬─────────┘     (Requires TWITAPI_APPLICATIONID / TWITAPI_APPLICATIONKEYS)
                │ (Fails or No Direct Media)
                ▼
      ┌───────────────────┐
      │ Tier 2: Show RSS  │ ──► GET https://feeds.twit.tv/{show_feed}.xml
      └─────────┬─────────┘     (Mapped via KNOWN_SHOW_FEEDS or show slug heuristic)
                │ (Fails or Not Found)
                ▼
      ┌───────────────────┐
      │ Tier 3: Club RSS  │ ──► GET https://twit.memberfulcontent.com/rss/9041?auth={key}
      └─────────┬─────────┘     (Parses XML enclosure tags & matches title/episode number)
                │ (Fails or Not Found)
                ▼
      ┌───────────────────┐
      │ Tier 4: Scrape Web│ ──► GET https://twit.tv/{cleanPath}
      └─────────┬─────────┘     (Regex extraction of .mp4/.mp3 URLs or YouTube links)
                │ (Fails or Not Found)
                ▼
      ┌───────────────────┐
      │ Tier 5: Ep Detail │ ──► GET https://twit.tv/api/v1.0/episodes/{episode_id}
      └───────────────────┘     (Deep HAL+JSON object graph traversal)
```

#### In-Memory Caching
To eliminate redundant HTTP traffic and improve responsiveness:
- `self._club_rss_cache`: Stores parsed Memberful XML items for the duration of the process lifecycle.
- `self._show_rss_cache`: Dict keyed by normalized show name (`show_name.lower().strip()`), caching parsed XML items from `feeds.twit.tv`.
- `self.show_ids`: Dict storing active show mappings with fallback to `DEFAULT_SHOWS` (containing 17 primary TWiT productions).

---

### Media Resolution Engine & Extraction Heuristics

The `extract_media_url(episode_dict, audio_only=...)` and `resolve_media_url(episode_dict, show_name, audio_only=...)` methods inspect heterogeneous data schemas returned by the API and RSS parsers, prioritizing either high-fidelity video streams or audio-only streams based on the **Audio Only** setting:

```python
# Video format priority order (when Audio Only is unchecked)
VIDEO_PREFERENCE = [
    'video_hd',       # 1080p / 720p HD Video
    'video_large',    # Large standard definition video
    'video_small',    # Mobile-optimized small video
    'video_audio',    # Audio-only stream fallback
    'video_youtube'   # YouTube hosted video stream
]

# Audio format priority order (when Audio Only is checked)
AUDIO_PREFERENCE = [
    'video_audio',    # Standard MP3 / M4A audio stream
    'audio',          # Direct audio enclosure
    'video_hd'        # Video fallback if no audio stream exists
]
```

When **Audio Only** is enabled:
- Club TWiT RSS queries prioritize subscriber audio feeds (`9040`, `9066`, `9054`, etc.) before video feeds.
- Public RSS queries check `.xml` audio feeds before `_video_hd.xml`.
- Webpage scraping extracts `.mp3` and `.m4a` URLs before `.mp4`.
- Download filenames automatically preserve `.mp3` / `.m4a` file extensions.
- State is persisted persistently across restarts via the `TWITAUDIOONLY` environment setting in `.env`.

#### Validation Filter (`is_valid_media_url`)
Every candidate URL passes through `is_valid_media_url(url)` to prevent opening API metadata endpoints or HTML web pages as media streams:
- Protocol check: Must start with `http://`, `https://`, `rtsp://`, or `mms://`.
- API blacklist: Rejects URLs containing `/api/` or `twit.tv/api`.
- Webpage blacklist: Rejects `twit.tv/shows/...`, `twit.tv/episodes/...`, `twit.tv/node/...` unless ending in an explicit media extension (`.mp4`, `.mp3`, `.m4a`, `.webm`, `.ogg`, `.m4v`, `.mov`, `.flv`, `.m3u8`, `.aac`).

---

### Asynchronous Streaming & Multi-Threaded Batch Downloader

#### Subprocess Stream Launcher
Streaming commands are formatted and safely tokenized via `build_stream_args(streamer_template, media_url)` and spawned via `launch_stream_safe(streamer_template, media_url)` supporting replacement tokens (`%f`, `{url}`, `%s`, `{file}`, `{media_url}`) without shell injection risks:
```python
args = build_stream_args(streamer_template, media_url)
subprocess.Popen(args, shell=False)  # Non-blocking, secure detached execution
```

#### Dynamic Multi-Resolution Selection
When streaming or downloading an episode that offers multiple media resolutions (e.g., HD Video 1080p/720p, Large Video 540p/480p, Small Video 360p, Audio Only MP3/M4A), TwitTUI presents an interactive modal prompt allowing the user to choose their preferred format:
- For single-episode downloads and streaming, the modal lists each available stream format along with its human-readable file size.
- For batch downloads with multiple selected episodes, users can pick a batch resolution preference (HD, Large, Small, or Audio) applied across all queued downloads.

#### Multi-Threaded Batch Download Architecture
Downloads run on background daemon threads (`threading.Thread`) to keep Toga's main event loop fully responsive.

```
[ on_download_press ]
         │
         ▼
[ Extract Selected Table Rows ]
         │
         ▼
[ Spawn threading.Thread(target=download_episodes_batch, daemon=True) ]
         │
         ▼
 ┌────────────────────────────────────────────────────────┐
 │ download_episodes_batch loop:                          │
 │   1. Initialize batch progress (0% to 100%)            │
 │   2. For each episode:                                 │
 │      a. Resolve Media URL via 5-tier cascade           │
 │      b. Determine sanitized target filename            │
 │      c. Verify existing file (is_existing_file_same): │
 │         • Compare local size against RSS / Content-Len │
 │         • Verify MD5 hash against remote ETag          │
 │         • If confirmed identical: SKIP download!       │
 │      d. Stream via requests.get(url, stream=True)      │
 │      e. Update progress bar with batch percentage      │
 │      f. Write chunks (size=block_size) to .part file   │
 │      g. Atomic rename: dest.part -> dest               │
 │   3. On batch completion:                              │
 │      Display modal dialog with destination folder &    │
 │      downloaded files list (one per line) + Close btn  │
 └────────────────────────────────────────────────────────┘
```

#### Smart File Verification & Deduplication
To conserve network bandwidth, prevent unnecessary disk wear, and avoid redundant transfers:
1. **Metadata & Size Check**: Verifies if the local target file exists and non-empty, matching expected RSS enclosure length or HTTP `Content-Length`.
2. **HTTP HEAD / Conditional Request**: Issues a lightweight `HEAD` request to inspect remote file size and `ETag`.
3. **Cryptographic MD5 Checksum**: When the remote server returns a hex `ETag`, computes the local file's MD5 checksum. If they match bit-for-bit, download is safely skipped.

#### Atomic Write Guarantee
To prevent corrupt files when a download is aborted or interrupted:
1. Chunks are written to `<filename>.part`.
2. Existing target files at the destination are removed upon completion.
3. `<filename>.part` is atomically renamed to `<filename>`.
4. If an exception occurs, `<filename>.part` is deleted automatically.

---

### Filesystem Sanitization & Naming Pipeline

The `determine_download_filename(target, media_url)` method sanitizes filenames for cross-platform filesystem compatibility (POSIX, NTFS, FAT32):

1. **Title & Show Normalization**:
   - Replaces illegal characters: `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|` with empty strings or spaces.
   - Cleans leading `TWiT+` prefixes into standard `TWiT`.
   - Collapses contiguous whitespace into single spaces.
2. **Naming Pattern**:
   - If the show name is general (`All TWiT.tv Shows`), uses: `<Episode Title>.<ext>`
   - If show title is already in episode name: `<Episode Title>.<ext>`
   - Standard format: `<Show Name> <Episode Number> <Episode Title>.<ext>`
3. **Extension Preservation**:
   - Extracts extension from media URL path; defaults to `.mp4` for video feeds.

---

### REST API Blueprint Integration (`twittv.apib`)

`twittv.apib` defines the complete API Blueprint specification for the TWiT.tv REST API v1.0 hosted via 3Scale.

#### Key Endpoints Used by TwitTUI:
- `GET /shows`: Fetches active show lists, identifiers, and media metadata.
- `GET /search/{keywords}`: Executes scoped full-text queries for in-show episode discovery across TWiT indexed archives.
- `GET /episodes?filter[shows]={show_id}`: Retrieves paginated episode lists for a specific show.
- `GET /episodes/{episode_id}`: Fetches detailed episode records including nested `video_hd`, `video_large`, and audio download nodes.

#### Authentication Headers:
- `Accept`: `application/json`
- `app-id`: Configured via `TWITAPI_APPLICATIONID`
- `app-key`: Configured via `TWITAPI_APPLICATIONKEYS`

---

### Environment Variables & Configuration Schema

| Variable Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `TWITAPI_APPLICATIONID` | String | *None* | 3Scale Application Identifier for TWiT.tv REST API access. |
| `TWITAPI_APPLICATIONKEYS` | String | *None* | 3Scale Application Secret Key for TWiT.tv REST API access. |
| `twitcluburl` / `TWITCLUBURL` | String | `""` | Full Memberful RSS feed URL or unique authorization key token. |
| `twitclubdestination` / `TWITCLUBDESTINATION` | String | `.` (Current dir) | Filesystem directory path for storing downloaded podcast files. |
| `twitclubblocksize` / `TWITCLUBBLOCKSIZE` | Integer | `8192` (8 KB) | Buffer chunk size in bytes for network download streaming. |
| `twitclubstreamer` / `TWITCLUBSTREAMER` | String | `vlc %f` | Command template string used to spawn the external streaming player. |
| `TWITAUDIOONLY` / `twitaudioonly` | Integer / Boolean | `0` (False) | Flag (`1`/`0`) persisting the Audio Only streaming/download preference across sessions. |

---

## Known Issues & Troubleshooting

### GTK Module & Backend Warnings
- **Symptom**: Console outputs `Failed to load module "xapp-gtk3-module"` or `Gtk-Message: Failed to load module "canberra-gtk-module"`.
- **Cause**: Linux systems with desktop environments like Cinnamon or MATE attempt to inject theme modules into GTK applications that lack matching runtime bindings.
- **Resolution**: TwitTUI automatically filters this specific warning through `main.py`'s `StderrRedirector` and enforces `GDK_BACKEND=x11` and `NO_AT_BRIDGE=1`. No user action is required.

### Missing API Credentials Fallback
- **Symptom**: Console logs `API credentials not found in .env file, using default shows`.
- **Impact**: TwitTUI operates without issue by loading its hardcoded list of TWiT shows and resolving all episode media directly through public RSS feeds (`feeds.twit.tv`) and Club TWiT RSS feeds.

### VLC / Streamer Path Resolution
- **Symptom**: Pressing **Stream** produces no visible media window.
- **Resolution**: Verify VLC is installed and available in your system `$PATH`. Alternatively, configure an absolute path in the **Streamer** box:
  - Linux/macOS: `/usr/bin/vlc %f` or `mpv %f`
  - Windows: `"C:\Program Files\VideoLAN\VLC\vlc.exe" %f`

---

## License & Credits

- **Framework**: Built with [BeeWare Toga](https://beeware.org/)
- **Media Content**: All podcast content, video streams, and audio files are copyrighted by [TWiT LLC](https://twit.tv/).
- **Author**: Mainmeister
