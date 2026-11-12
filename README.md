# TwitTUI: TWiT.tv Terminal & Desktop Media Browser

TwitTUI is a media client for browsing, streaming, and batch-downloading podcast episodes from the [TWiT.tv](https://twit.tv) network. Built on [BeeWare Toga](https://beeware.org/), it offers terminal and GTK desktop interfaces.

This document serves two primary audiences:
1. **[End-User Guide](#end-user-guide)**: Practical, step-by-step instructions for installing, configuring, and operating the application.
2. **[Developer & Technical Architecture Reference](#developer--technical-architecture-reference)**: Exhaustive architectural, algorithmic, and implementation documentation for software engineers maintaining or extending the codebase.

---

## Table of Contents

- [Core Capabilities](#core-capabilities)
- [End-User Guide](#end-user-guide)
  - [System Requirements](#system-requirements)
  - [Installation](#installation)
  - [Snap Package (Cross-Distribution Linux)](#snap-package-cross-distribution-linux)
  - [Standalone Binary Packaging & Installation](#standalone-binary-packaging--installation)
  - [Configuration (.env & UI)](#configuration-env--ui)
  - [User Interface & Usage Walkthrough](#user-interface--usage-walkthrough)
    - [Show Selection & Episode Browsing](#show-selection--episode-browsing)
    - [Searching Episodes & Tiered Matching Engine](#searching-episodes--tiered-matching-engine)
    - [Sorting Episodes](#sorting-episodes)
    - [Streaming an Episode](#streaming-an-episode)
    - [Batch Downloading Episodes](#batch-downloading-episodes)
    - [Club TWiT Member Features](#club-twit-member-features)
- [Developer & Technical Architecture Reference](#developer--technical-architecture-reference)
  - [Project Structure](#project-structure)
  - [Application Icon & Branding Asset Pipeline](#application-icon--branding-asset-pipeline)
  - [Execution Lifecycle & GTK Namespace Locking (`main.py`)](#execution-lifecycle--gtk-namespace-locking-mainpy)
  - [Startup & Shutdown Splash Screen Lifecycle](#startup--shutdown-splash-screen-lifecycle)
  - [Installer & Packaging Engine (`installer.py`)](#installer--packaging-engine-installerpy)
  - [Snap Packaging & Confinement Architecture (`snap/`)](#snap-packaging--confinement-architecture-snap)
  - [UI Architecture & Widget Tree (`twittui_form.py`)](#ui-architecture--widget-tree-twittui_formpy)
  - [Tiered Search Engine & Phonetic Matching Architecture (`tiered_search.py`, `double_metaphone.py`)](#tiered-search-engine--phonetic-matching-architecture-tiered_searchpy-double_metaphonepy)
  - [Search Match Inspection & KWIC Snippet Pipeline](#search-match-inspection--kwic-snippet-pipeline)
  - [Data Ingestion, Persistent SQLite Caching & Fallbacks](#data-ingestion-persistent-sqlite-caching--fallbacks)
  - [Media Resolution Engine & Extraction Heuristics](#media-resolution-engine--extraction-heuristics)
  - [Asynchronous Streaming & Multi-Threaded Batch Downloader](#asynchronous-streaming--multi-threaded-batch-downloader)
  - [Filesystem Sanitization & Naming Pipeline](#filesystem-sanitization--naming-pipeline)
  - [REST API Blueprint Integration (`twittv.apib`)](#rest-api-blueprint-integration-twittvapib)
  - [Environment Variables & Configuration Schema](#environment-variables--configuration-schema)
  - [Automated Testing & Quality Assurance](#automated-testing--quality-assurance)
- [Known Issues & Troubleshooting](#known-issues--troubleshooting)
  - [GTK Module & Backend Warnings](#gtk-module--backend-warnings)
  - [PyGObject & Gdk Introspection Namespace Collisions](#pygobject--gdk-introspection-namespace-collisions)
  - [Python Built Without Shared Library (`--enable-shared`)](#python-built-without-shared-library---enable-shared)
  - [Missing API Credentials Fallback](#missing-api-credentials-fallback)
  - [VLC / Streamer Path Resolution](#vlc--streamer-path-resolution)
- [License & Credits](#license--credits)

---

## Core Capabilities

- **Show Catalog Navigation**: Browse active and legacy TWiT.tv productions with automatic fallback to static show catalogs when offline or unauthenticated. Displays formatted status tags (`[Active ...]` / `[Ended ...]`) with start and end date bounds.
- **High-Efficiency API Pagination**: Retrieves the complete show catalog in a single request (`page=1&range=1000`) and episodes in reliable blocks of 50 (`range=50`) iteratively until all episodes have been loaded, maintaining a strict rate limit of 5 API calls per rolling minute.
- **Tiered Multi-Engine Search Pipeline**: Combines exact substring matching, ranked fuzzy subsequence scoring (`fzf`-style local sequence alignment and Levenshtein edit distance), and Double Metaphone phonetic matching in pure Python. Delivers precise results for accurate terms while transparently resolving typos and phonetic misspellings (e.g., `ballacer` → `ballecer`, `secruity` → `security`).
- **Interactive Search Match Preview & KWIC Snippets**: Displays an instant search match summary banner inside episode hover popup dialogs. Communicates the matched field (Title, Hosts/Guests, Topics, Description/Show Notes), match classification (Exact, Fuzzy similarity %, or Phonetic correlation), and an auto-aligned Keyword-in-Context (KWIC) excerpt with automated GTK cursor positioning.
- **Episode Metadata Hover Preview**: Hovering over an episode row for 3 seconds displays comprehensive episode metadata, show notes, and links in a dedicated popup dialog (across both GTK and Textual interfaces) without network delays.
- **Startup & Shutdown Splash Screens**: Provides clear, immediate visual feedback during application initialization (show catalog and episode archive hydration) and during application exit across Textual modal screens, GTK desktop windows, and interactive terminal banners.
- **Client-Side & In-Memory Sorting**: Instantly re-sorts loaded episode collections by Date, Episode Number, Title, Length, or Size without redundant network round-trips or episode list truncation.
- **Persistent SQLite & In-Memory Caching**: Leverages a local SQLite persistent cache (`twittui_cache.db`) alongside in-memory caches to store show metadata, RSS feeds, and episode entries, accelerating app launch and enabling responsive offline browsing.
- **Resilient Episode Ingestion**: Show and episode fetching and media resolution use different API, RSS and webpage fallbacks. End dates are scraped from public web archives without consuming API quota.
- **Synchronized UI Lifecycle**: Modal wait dialogs remain active until catalog dates and episode lists finish loading, ensuring stable UI scrolling and selection.
- **Direct Video/Audio Streaming**: Spawn external media players (e.g., VLC, MPV) asynchronously using customizable command templates without stalling the UI.
- **Background Batch Downloader**: Download selected episodes sequentially in a background worker with configurable byte buffers. Existing non-identical files can be overwritten without confirmation.
- **Download Deduplication**: Uses available size and ETag information as heuristics to skip existing files; identity is not guaranteed.
- **Club TWiT Integration**: Supports Memberful authentication keys for configured subscriber feeds; available episodes depend on the feed and network.
- **Backend Choices**: Uses BeeWare Toga with GTK and Textual backend selection. Native macOS and Windows operation is not guaranteed.

---

## End-User Guide

### System Requirements

- **Python**: Version 3.10, 3.11, or 3.12+
- **Media Player**: [VLC Media Player](https://www.videolan.org/vlc/) (default) or any player that accepts stream URLs via CLI (such as `mpv` or `ffplay`).
- **Operating System**: Linux is the primary target. Native macOS and Windows support is not guaranteed; the supplied requirements include Linux GTK dependencies.
- **Linux prerequisites**: Install GTK 3 and its introspection typelibs, GObject introspection development headers, Cairo development headers, Python development headers, `pkg-config`, and a C compiler. Package names vary by distribution and PyGObject version (for example, Debian/Ubuntu packages include `gir1.2-gtk-3.0`, `libgirepository1.0-dev`, `libcairo2-dev`, `python3-dev`, and `pkg-config`).
- **YouTube downloads**: `yt-dlp` or `youtube-dl` is required; `requirements.txt` includes `yt-dlp`. Optional `ffmpeg` enables merging video/audio and audio conversion.

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/mainmeister/twittui.git
   cd twittui
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   This installs both backends and dependencies including `yt-dlp`, PyGObject, and pycairo; their native prerequisites must be installed separately.

4. **Launch the application**:
   ```bash
   python main.py
   ```
   - When both backends are installed and stdin is interactive, TwitTUI prompts for a backend. The default is GTK when a graphical display is detected and Textual otherwise; non-interactive startup uses that default without prompting. For example, with a display:
     ```text
     Multiple Toga UI backends detected:
       1) GTK (Graphical Desktop UI)
       2) Textual (Terminal User Interface)
     Select backend [1/2] (default: 1 - GTK):
     ```
   - You can also bypass the startup prompt using command line switches. Certain GTK startup failures fall back to Textual if it is installed:
     ```bash
     python main.py --gtk        # Launch GTK desktop GUI
     python main.py --textual    # Launch Textual terminal UI (TUI)
     python main.py -b gtk       # Alternative syntax (-b gtk / -b textual)
     python main.py --help       # Display all backend options and switches
     ```

### Snap Package (Cross-Distribution Linux)

TwitTUI provides official Snap packaging support for universal installation on Ubuntu, Debian, Fedora, Arch Linux, openSUSE, and any Linux distribution with `snapd` enabled. Built on Ubuntu Core 24 (`core24`), the Snap package bundles Python, PyGObject, GTK 3, BeeWare Toga, Textual, audio subsystems, and desktop icons in a strictly confined, secure sandbox.

#### 1. Prerequisites & Build Tools

To build the Snap locally, install `snapcraft` from the Snap Store:

```bash
# Install snapcraft with classic confinement
sudo snap install snapcraft --classic

# (Optional) Install LXD container manager if using LXD as build provider
sudo snap install lxd
sudo lxd init --auto
```

#### 2. Building the Snap Package

Execute `snapcraft` from the repository root directory:

```bash
# Standard containerized build (using Multipass or LXD container provider)
snapcraft

# Alternatively, force LXD container build provider
snapcraft --use-lxd

# Alternatively, build directly on the host (e.g. in dedicated CI/CD build environments)
snapcraft --destructive-mode

# Clean previous build artifacts and virtual parts when rebuilding
snapcraft clean
```

This compiles all dependencies, GLib schemas, GObject typelibs, and virtual environments, producing `twittui_1.0.2_<arch>.snap` (e.g., `twittui_1.0.2_amd64.snap`) in the project root directory.

#### 3. Installing the Snap

- **Install Local Build**:
  Install the locally compiled `.snap` package using the `--dangerous` flag (required for locally built, self-signed packages):
  ```bash
  sudo snap install --dangerous twittui_1.0.2_amd64.snap
  ```

- **Install for Development & Debugging** (Optional):
  To test without confinement restrictions during development:
  ```bash
  sudo snap install --dangerous --devmode twittui_1.0.2_amd64.snap
  ```


#### 4. Running the Application

TwitTUI exposes two entry points within the Snap package:

- **Launch Graphical Desktop UI (GTK 3)**:
  ```bash
  twittui
  ```
  Or select **TwitTUI** from your desktop environment's application menu (GNOME, KDE Plasma, XFCE, Cinnamon, etc.).

- **Launch Terminal User Interface (TUI)**:
  ```bash
  twittui.tui
  ```

The Snap entry points supply their own backend switches; use `twittui.tui` for the terminal UI.
The Snap does not bundle VLC; streaming requires an accessible external player, which may be restricted by confinement. Verify the configured player works in your installation.

#### 5. Snap Permissions & Interface Plugs

TwitTUI operates under strict confinement (`confinement: strict`) and requests standard desktop interfaces:

| Plug Interface | Purpose |
| :--- | :--- |
| `desktop`, `desktop-legacy` | Native windowing, GTK themes, and font rendering |
| `wayland`, `x11` | Wayland and X11 display server communication |
| `opengl` | Hardware-accelerated graphics rendering |
| `audio-playback` | Audio playback |
| `network`, `network-bind` | Network access |
| `home` | Access to permitted user files |
| `removable-media` | Access to external drives |

Connections depend on snapd policy and the local installation; inspect them with `snap connections twittui`.

To allow downloading podcast episodes directly to external USB hard drives or SD cards, connect the `removable-media` interface:

```bash
sudo snap connect twittui:removable-media
```

To verify active interface connections:
```bash
snap connections twittui
```

#### 6. Snap Configuration File (.env) & Persistence

In strict Snap confinement, user settings, API credentials, and download preferences are saved inside the application's isolated writable user data directory:
```text
~/snap/twittui/current/.env
```
*(corresponds to `$SNAP_USER_DATA/.env`)*

- The launcher copies `$SNAP/.env.example` only if it is bundled and no user `.env` exists. Settings saved by the application may override the launcher's destination environment value.
- The launcher suggests `$HOME/Downloads` if it exists, otherwise `$SNAP_USER_DATA`; Snap's `$HOME` need not be the host home directory. Check the in-app destination rather than assuming host Downloads.
- You can edit `~/snap/twittui/current/.env` with any text editor or modify settings live via the in-app configuration panel.

---

### Standalone Binary Packaging & Installation

   The PyInstaller pipeline builds a single executable (`twittui` on POSIX or `twittui.exe` on Windows). GTK and assets are included conditionally when available; the selected installation directory may not be on `PATH`:
   ```bash
   python main.py --install
   ```
   Or use the dedicated installer script:
   ```bash
   python installer.py --install
   ```

   **Targeting a Custom Installation Directory (`--install-dir`)**:
   By default, the installer queries system directories (`~/.local/bin`, `~/bin`, `/usr/local/bin`, or Windows Apps paths) and selects the best writable path. You can explicitly override the target destination:
   ```bash
   python main.py --install --install-dir ~/.local/bin
   # Or for system-wide installation (requires appropriate permissions):
   sudo python main.py --install --install-dir /usr/local/bin
   ```

   **Specifying an Alternative Python Interpreter (`--python-executable`)**:
   If your active virtual environment is based on a static Python build (e.g. without `--enable-shared`), you can compile using another interpreter. That interpreter must have the application dependencies and PyInstaller available:
   ```bash
   python main.py --install --python-executable /usr/bin/python3
   ```

   **Automatic Cleanup & Build Artifact Management**:
   After copying the binary, the installation routine recursively removes the project's entire `build/` and `dist/` directories and all root-level `.spec` files, including unrelated content. The manual cleanup command removes the same paths; move anything you need elsewhere first.
   - To preserve build artifacts during installation, pass `--no-clean`:
     ```bash
     python main.py --install --no-clean
     ```
   - To manually clean build artifacts at any time:
     ```bash
     python main.py --clean
     # Or:
     python installer.py --clean
     ```
   - To clean artifacts and also remove the PyInstaller package from your virtual environment:
     ```bash
     python main.py --clean --uninstall-pyinstaller
     ```

   **Execution & PATH Precedence**:
   If the installation directory is on `PATH`, run TwitTUI from a terminal; otherwise add it to `PATH` or invoke the executable by its full path:
   ```bash
   twittui
   ```
   If a binary named `twittui` already exists on your system:
   - **In the target install directory**: The installer replaces the existing executable in place and re-applies executable permissions (`chmod +x`).
   - **Across multiple PATH folders**: Operating systems execute the first match found in `$PATH`. To verify which executable takes precedence, run:
     - Linux / macOS: `which -a twittui`
     - Windows: `where twittui`

---

### Configuration (.env & UI)

TwitTUI reads configuration from `.env` on launch; values in that file override existing process environment values. Outside Snap, discovery starts from the working directory, while saving settings prefers a writable `.env` beside the application module, so the file read and file saved can differ. The application settings panel can also modify settings.

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
twitclubstreamer=env LC_ALL=C vlc %f

# Prefer audio when available (1 or 0)
TWITAUDIOONLY=0

# Search Sensitivity & Matching Controls (1 or 0, default: 1)
TWITFUZZYSEARCH=1
TWITPHONETICSEARCH=1
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
| API Application Key:  [ *********************** ] [ Test API ]                |
| TWIT Club URL: https://twit.memberfulcontent.com/rss/9041?auth= [ *** ] [ Show ]|
| Download Destination: [/home/user/Podcasts       ] [ Browse ] [ Open ] [X Show Folders] |
| Block Size:           [8192                      ]                              |
| Streamer:             [env LC_ALL=C vlc %f       ]                              |
+---------------------------------------------------------------------------------+
```

#### Show Selection & Episode Browsing
- Click the **Show** dropdown menu to select a show. Shows display fixed-width metadata tags indicating status and air dates (e.g., `[Active 2005-08-18 - 2025-03-04] Security Now` or `[Ended  2009-07-08 - 2012-04-18] Abby's Road`).
- The episode list refreshes automatically upon selection.
- Click **Fetch** to refresh the show catalog and episodes. The catalog queries all shows in a single request (`page=1&range=1000`) and falls back to built-in shows if the API is unavailable.
- Show start dates are parsed from API `created` timestamps, while show end dates are scraped from public web archives asynchronously to conserve API quota under strict rate limits.
- The wait modal dialog remains displayed during catalog refresh until both show metadata dates and the initial episode list have completed loading, ensuring smooth navigation without list resets.
- **Next** fetches another page when additional episodes exist beyond the currently loaded catalog.
- The API status message reports loading and credential status; requests may display a wait dialog while the API rate limiter is active (5 calls per minute).
- **Episode Metadata Inspection**: Hovering over any episode row for 3 seconds displays a popup with complete metadata, show notes, and links for that episode.

#### Searching Episodes & Tiered Matching Engine
- Enter keywords, topics, host names, or episode numbers (e.g., `Ballecer`, `OpenAI`, `Security`, `Stagefright`, `1001`) into the **Search** text box.
- Click **Search** or press `Enter`.
- **Tiered Multi-Engine Processing**:
  - **Tier 1 (Exact Matches)**: Matches exact case-insensitive substrings across Title, Hosts/Guests, Topics, Description/Show Notes, and Episode Numbers with highest priority (Score: `100.0`).
  - **Tier 2 (Ranked Fuzzy & Subsequence)**: Catches typos, transposed letters, and partial abbreviations (e.g., typing `secruity` or `macbrk`) using `fzf`-style subsequence scoring and Levenshtein edit distance ratios. Results are ranked by match confidence (Scores: `60.0`–`99.0`).
  - **Tier 3 (Double Metaphone Phonetic Fallback)**: Resolves phonetic and pronunciation variations (e.g., typing `ballacer` matches `Ballecer`, `algorhtm` matches `algorithms`).
- **Configurable Search Sensitivity**:
  - Fuzzy and phonetic matching are enabled by default for maximum discovery.
  - To restrict searches strictly to exact matches, set `TWITFUZZYSEARCH=0` and `TWITPHONETICSEARCH=0` in `.env` or adjust search preferences in the configuration settings.
- Click **Clear** (or submit an empty search) to restore the full episode list.

#### Episode Metadata Inspection & Search Match Preview
- **3-Second Hover Preview**: Hovering over any episode row for 3 seconds opens a comprehensive metadata dialog displaying title, air date, duration, file size, direct links, and show notes across both GTK desktop and Textual terminal backends.
- **Search Match Summary Callout (`[🔍 Search Match]`)**:
  - When an episode is inspected while a search filter is active, the dialog displays a dedicated callout banner at the top of the popup.
  - **Field Indicator**: Clearly indicates where the match occurred (e.g., `Field: Description / Show Notes`, `Title`, `Hosts / Guests`).
  - **Match Type Indicator**: Explains the matching tier (e.g., `Match Type: Exact Match`, `Match Type: Fuzzy Match (92% similarity)`, or `Match Type: Phonetic Match ("ballacer" ≈ "Ballecer")`).
  - **Contextual KWIC Snippet**: Displays a 100-character Keyword-in-Context excerpt centered around the matched token.
  - **Auto-Scroll Positioning**: In the GTK desktop interface, the description text view automatically scrolls and positions the cursor at the exact character offset of the match.

#### Sorting Episodes
- Select one of the sort mode buttons:
  - **☑ Date**: Sorts episodes by airing/publication date.
  - **☑ Episode Number**: Sorts numerically by episode number.
  - **☑ Episode Title**: Sorts alphabetically by episode title.
- Toggle the sort direction button:
  - **▼ Descending**: Displays newer or higher values first.
  - **▲ Ascending**: Displays older or lower values first.
  - Loaded episode archives are sorted instantly in-memory, preserving the complete episode list without extra API requests or truncation. Sorting by duration (Length) or file size (Size) leverages local client-side sorting algorithms.

#### Streaming an Episode
1. Click on an episode in the list table to highlight it.
2. Double-click the row or press the **Stream** button.
3. If prompted, choose an available format or resolution. Choosing **YouTube Stream** opens the episode video directly in your default web browser for native playback. For direct video and audio streams, TwitTUI resolves the stream and launches your configured media player (e.g., VLC) in a separate process. **Audio Only** refreshes the episode list and prefers audio for streaming and downloads; the preference is saved as `TWITAUDIOONLY`.

#### Batch Downloading Episodes
1. Highlight one or more episodes in the table (hold `Shift` or `Ctrl` for multiple selections).
2. Ensure **Download Destination** is set to your preferred folder (use **Browse** to select). **Open** creates the destination if necessary and opens it in your file manager.
3. Optionally toggle **Show Folders** if you want downloaded episodes organized into dedicated subfolders named after each show (e.g., `<Download Destination>/Security Now/Security Now 1000.mp4`).
4. Click **Download**. If prompted, choose a format for a single episode or a resolution preference for the batch. The batch runs sequentially in a background worker. Existing non-identical files may be overwritten without confirmation.
5. Files are saved directly to your destination path (or show subfolder) with normalized, clean filenames (e.g., `This Week in Tech 1001 AI in the Fast Lane.mp4`).
6. A completion dialog appears if at least one item succeeded, including skipped existing files; it may appear after partial cancellation. **Cancel** requests cancellation of an active download, or exits the app if none is active.

#### Club TWiT Member Features
- Paste your unique Memberful key into the **TWIT Club URL** box.
- When configured, TwitTUI can check Club TWiT feeds for available subscriber episodes.
- Click **Show** next to the URL to view the feed in your browser. TwitTUI attempts to fetch and format it with `feed-style.css`; if fetching fails, it opens the direct feed URL instead.
- Use **Test API** to test the entered API credentials asynchronously and display the result.

---

## Developer & Technical Architecture Reference

### Project Structure

```
twittui/
├── main.py                  # Process bootstrap, stderr filtering, and GTK environment patching
├── twittui_form.py          # Core application logic, Toga GUI/TUI layout, networking, and workers
├── toga_textual_backend.py  # Textual TUI backend adapters, modal dialogs, and splash screen widgets
├── tiered_search.py         # Multi-tiered search engine (Exact, Ranked Fuzzy / fzf, Double Metaphone)
├── double_metaphone.py      # Pure Python implementation of Lawrence Philips' Double Metaphone algorithm
├── installer.py             # Packaging, executable installation, and artifact cleanup engine
├── generate_icon.py         # Icon asset generator (PNG multi-size, Windows ICO, SVG)
├── resources/               # Application icons and branding assets (PNG, ICO, SVG)
│   ├── twittui.png          # Master 512x512 application icon
│   ├── twittui.ico          # Multi-resolution Windows application icon
│   ├── twittui.svg          # Scalable vector graphics icon
│   └── twittui-*.png        # Sized raster icon variants (512, 256, 128, 72, 64, 48, 32, 16)
├── snap/                    # Ubuntu Snapcraft packaging recipes, desktop assets, and launchers
│   ├── snapcraft.yaml       # Core24 strict confinement build recipe and part definitions
│   ├── gui/                 # Desktop integration and Freedesktop menu entry
│   │   ├── twittui.desktop  # Desktop entry launcher specification
│   │   └── twittui.png      # Application branding icon for snap package (256x256)
│   └── local/               # Runtime sandboxing and environment isolation
│       └── launcher.sh      # Subprocess launcher, GTK module filter, and cache initializer
├── test_api_rate_limiter.py # 5 req/min rate limiter and retry logic tests
├── test_backend_factory.py  # Toga backend detection and CLI switch tests
├── test_caching.py          # SQLite database persistent caching and TTL expiration tests
├── test_episode_activation.py# Row selection and streaming activation tests
├── test_episode_search.py   # Multi-tier search verification and typo resilience tests
├── test_hover_popup.py      # Episode metadata dialog and search match preview tests
├── test_install.py          # PyInstaller packaging, standalone binary, and cleanup tests
├── test_open_destination.py # Destination directory opening and creation tests
├── test_preferences.py      # In-app configuration, search toggle, and .env persistence tests
├── test_resolutions.py      # Multi-resolution format parsing and selection tests
├── test_security.py         # Markdown sanitization and URL security tests
├── test_show_catalog.py     # Show catalog pagination, archive scraping, and rate limiting tests
├── test_show_folders.py     # Show subfolder structure creation and filename routing tests
├── test_snap.py             # Snapcraft recipe, desktop entry, launcher, and sandbox tests
├── test_splash_screen.py    # Startup/shutdown splash screens and terminal banner tests
├── test_tooltips.py         # UI widget tooltip bindings and accessibility tests
├── test_youtube_download.py # YouTube video stream resolution and download tests
├── setup.py                 # Standard Python package setup and metadata definition
├── pyproject.toml           # Modern Python build-system configuration
├── twittv.apib              # Full API Blueprint documentation for TWiT.tv REST API v1.0
├── Layout_spec_for_AI.txt   # UI specification and control layout blueprint
├── feed-style.css           # Modern, responsive CSS stylesheet for podcast RSS feeds
├── feed-style.xsl           # Standalone XSLT 1.0 transformation template for podcast RSS feeds
├── .env                     # Local environment configuration file (ignored in VCS)
└── README.md                # System documentation and technical manual
```

---

### Application Icon & Branding Asset Pipeline

TwitTUI incorporates a custom, multi-layered visual emblem that unites TWiT's media broadcasting heritage with terminal aesthetic cues:
- **Visual Composition**:
  - Dark midnight squircle background badge framed by a TWiT Red-to-Cyan cyber rim gradient.
  - Inset CRT terminal monitor featuring macOS/TUI traffic light status dots (Red, Amber, Green) and a title pill header.
  - Dual broadcast signal wave arcs radiating outward representing audio/video podcast transmissions.
  - Central TWiT Red/Orange media play beacon (`▶`).
  - Vibrant phosphor cyan terminal prompt chevron (`>`) and blinking cyber cursor (`_`).

- **Asset Generation Engine (`generate_icon.py`)**:
  - **Vector Master**: Generates `resources/twittui.svg` (scalable vector graphics).
  - **Raster Master & Sized Variants**: Renders high-resolution Cairo graphics at sizes `512`, `256`, `128`, `72`, `64`, `48`, `32`, and `16` pixels (`resources/twittui-*.png` and master `resources/twittui.png`).
  - **Windows Icon Package**: Combines raster imagery into `resources/twittui.ico` via `GdkPixbuf`.

- **Runtime Icon Resolution (`resolve_app_icon()`)**:
  `twittui_form.py` dynamically resolves the application icon at runtime across all environments:
  - Inside PyInstaller standalone bundles via `sys._MEIPASS/resources/twittui`.
  - In direct Python interpreter execution via `<project_root>/resources/twittui`.
  - Automatically binds icons into Toga application metadata during `TwitTUIForm.__init__()`.

---

### Execution Lifecycle & GTK Namespace Locking (`main.py`)

`main.py` is the execution entry point. Before importing GUI modules or initializing the main loop, it dynamically inspects available Toga backends (`toga-gtk`, `toga-textual`), processes command-line switches or interactive startup prompts, locks GObject introspection namespaces to prevent version conflicts, sets `TOGA_BACKEND`, and executes runtime environment stabilization:

```
[ Process Start ]
        │
        ▼
[ Parse CLI Switches & Inspect Backends ]
  ├── --gtk / --gui / -b gtk          ──► Force toga_gtk
  ├── --textual / --tui / -b textual  ──► Force toga_textual
  ├── --install / -i                  ──► Delegate to installer.py packaging pipeline
  ├── --clean / -c                    ──► Delegate to installer.py artifact cleanup
  └── (No Switch & Both Found)        ──► Prompt only on interactive stdin; otherwise use display-based default
        │
        ▼
[ Set TOGA_BACKEND & Configure Environment ]
  ├── If toga_gtk:
  │     ├── configure_gtk_environment()
  │     │     ├── Attempt Gtk, Gdk, GdkX11 and GdkWayland 3.0
  │     │     │   (4.0 when TOGA_GTK=4)
  │     │     ├── gi.require_version('Pango', '1.0') / PangoCairo / GLib / GObject / Gio
  │     │     ├── Import gi.overrides.Gtk & gi.overrides.Pango
  │     │     └── Gtk.init_check()
  │     ├── Instantiate StderrRedirector (Filter xapp-gtk3-module warnings)
  │     ├── Unset GTK_MODULES and other conflicting host overrides
  │     ├── del GTK_DEBUG (Prevent assertion crashes in non-debug GTK)
  │     ├── NO_AT_BRIDGE = '1' (Bypass accessibility D-Bus bridge overhead)
  │     ├── GDK_BACKEND = 'x11' only with DISPLAY and without WAYLAND_DISPLAY
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

#### `configure_gtk_environment()` Implementation
To reduce namespace conflicts, `main.py` attempts to bind GObject introspection versions and initialize GTK before UI startup. It uses GTK 3 by default or GTK 4 when `TOGA_GTK=4`; namespace and initialization failures are swallowed, so this is not a guarantee against collisions. Certain GTK startup errors can fall back to Textual when installed.

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

### Startup & Shutdown Splash Screen Lifecycle

TwitTUI provides dedicated visual feedback to keep users informed during startup and application exit:

1. **Terminal Banner (`show_terminal_splash` in `main.py`)**:
   - Prints an ASCII splash header when launching in interactive TTY sessions before backend initialization.
   - Outputs a clean shutdown confirmation banner upon process termination.

2. **Textual TUI Modal Splash (`SplashScreen` in `toga_textual_backend.py`)**:
   - Implements a centered modal overlay utilizing Textual's `LoadingIndicator` and reactive message labels.
   - Pushed onto the screen stack during application initialization and updated dynamically via `update_message()`.
   - Dismissed automatically via `close_splash()` once initial show catalogs and episode lists are hydrated, or closed gracefully on shutdown.

3. **Desktop GUI Splash Window (`show_splash_screen()` in `twittui_form.py`)**:
   - For graphical desktop environments (e.g. GTK), displays an undecorated, centered modal window containing an active `toga.ActivityIndicator` and dynamic progress text.
   - Positioned relative to the parent application window and automatically closed once background hydration finishes.

---

### Installer & Packaging Engine (`installer.py`)

`installer.py` provides standalone binary compilation, local `$PATH` discovery, and workspace hygiene management:

1. **PyInstaller Automated Compilation (`build_executable`)**:
   - Detects or installs `pyinstaller` dynamically within the active virtual environment.
   - Adds `feed-style.css`, `feed-style.xsl`, `twittv.apib`, `README.md`, and `resources/` when present; icon generation is attempted if needed.
   - Embeds a platform application icon if available.
   - Collects `toga`, `toga_textual`, `textual`, `dotenv`, and `requests`; `toga_gtk` and `gi` are collected when detected. GTK override imports are also specified.
   - Produces a single non-debug standalone executable in `dist/twittui` (or `dist/twittui.exe`).

2. **System PATH Resolution & Installation (`install_twittui`)**:
   - Queries standard user and system binary paths (`~/.local/bin`, `~/bin`, `/usr/local/bin`, etc.).
   - Copies the compiled binary using `shutil.copy2` and grants POSIX executable permissions (`0o755`).
   - Replaces pre-existing binary installations in place cleanly.

3. **Artifact Cleanup Engine (`clean_build_artifacts`)**:
   - Recursively removes the project `build/` and `dist/` directories and all root-level `.spec` files, including unrelated content.
   - Supports optional package uninstallation (`--uninstall-pyinstaller`) to return the development environment to its pre-build state.

---

### Snap Packaging & Confinement Architecture (`snap/`)

TwitTUI's Snap package provides containerized, cross-distribution deployment on Ubuntu Core 24 (`core24`) with strict sandboxing and complete environment isolation.

#### 1. Snapcraft Recipe Specification (`snap/snapcraft.yaml`)

- **Base Runtime**: Ubuntu 24.04 LTS (`core24`), ensuring modern Python 3.12, GTK 3.24, and PulseAudio/PipeWire runtimes.
- **Strict Confinement**: Isolates application execution from host system files while granting controlled access through explicit interface plugs (`desktop`, `wayland`, `x11`, `audio-playback`, `network`, `home`, `removable-media`).
- **Dual Application Definitions**:
  - `twittui`: GTK graphical desktop application executing `bin/twittui-launcher --gtk`, associated with `snap/gui/twittui.desktop` and registering D-Bus session slot `org.beeware.twittui`.
  - `tui`: Textual terminal application executing `bin/twittui-launcher --textual` directly in the user's terminal.
- **System Stage Packages**:
  Bundles native shared libraries and typelib introspections: `gir1.2-gtk-3.0`, `gir1.2-pango-1.0`, `gir1.2-glib-2.0`, `gir1.2-gdkpixbuf-2.0`, `libgtk-3-0`, `libgdk-pixbuf-2.0-0`, `librsvg2-common`, `shared-mime-info`, `libgirepository-1.0-1`, `libpulse0`.
- **Custom Build Lifecycle (`override-build`)**:
  - Initializes a standalone Python virtual environment inside `$CRAFT_PART_INSTALL`.
  - Upgrades `pip` and installs dependencies from `requirements.txt` and `setup.py`.
  - Compiles GLib schemas via `glib-compile-schemas` and generates MIME type index via `update-mime-database`.
  - Copies launcher script (`launcher.sh` -> `bin/twittui-launcher`), desktop entry, application icons, stylesheets, and API blueprint assets.

#### 2. Sandboxed Runtime Launcher (`snap/local/launcher.sh`)

When the application launches inside Snap confinement, `launcher.sh` configures runtime environment variables and sanitizes host desktop overrides:

```
[ snap run twittui / twittui.tui ]
                 │
                 ▼
[ Ensure SNAP_USER_DATA Directory Exists ]
                 │
                 ▼
[ Copy bundled .env.example to $SNAP_USER_DATA/.env if available and missing ]
                 │
                 ▼
[ Suggest Download Path ($HOME/Downloads or $SNAP_USER_DATA) if unset ]
                 │
                 ▼
[ Sanitize Incompatible Host Theme Variables ]
  ├── unset GTK_MODULES / GTK3_MODULES / GTK_PATH
  ├── unset UBUNTU_MENUPROXY
  └── unset QT_STYLE_OVERRIDE / QT_QPA_PLATFORMTHEME
                 │
                 ▼
[ Architecture Detection (x86_64, aarch64, armhf) ]
                 │
                 ▼
[ Export Library, Schema, Typelib & Python Paths ]
  ├── LD_LIBRARY_PATH (usr/lib/$ARCH, pulseaudio)
  ├── GI_TYPELIB_PATH (girepository-1.0)
  ├── GSETTINGS_SCHEMA_DIR (usr/share/glib-2.0/schemas)
  ├── XDG_DATA_DIRS (usr/share)
  └── PYTHONPATH ($SNAP/lib/python3.12/site-packages, $SNAP)
                 │
                 ▼
[ Dynamic GDK Pixbuf Loaders Cache Generation ]
  └── $SNAP/usr/lib/$ARCH/gdk-pixbuf-query-loaders > $SNAP_USER_DATA/.loaders.cache
                 │
                 ▼
[ Execute Application: python3 $SNAP/main.py "$@" ]
```

#### 3. Desktop Entry & Freedesktop Metadata (`snap/gui/twittui.desktop`)

The desktop launcher file registers TwitTUI in system application menus:
- Sets `Categories=AudioVideo;Audio;Video;Player;Network;` for standard audio/video and podcast indexing.
- Declares `StartupWMClass=twittui` ensuring application windows correctly map to the application icon in GNOME Shell and KDE taskbars.
- Provides standard search keywords for podcast discovery.

---

### UI Architecture & Widget Tree (`twittui_form.py`)

`TwitTUIForm` extends `toga.App` and declares a declarative widget layout inside `startup()`. Layout geometry is managed through `travertino` / `toga.style.Pack` flexbox rules.

#### Application Menu Commands
- **Application Menu (`toga.Group.APP`)**:
  - **Preferences**: Opens the modal Preferences window containing the API credentials, Club TWiT URL, download destination, block size, rate limit, and streamer settings.
- **Help Menu (`toga.Group.HELP`)**:
  - **View README Documentation**: Opens the integrated documentation viewer via the **Hybrid Resilient Pattern**. Converts Markdown to fully sanitized HTML (stripping malicious tags, event handlers, and dangerous URI schemes) and displays it in an in-app `toga.WebView` window with automatic fallback to the system default web browser. Features smooth Table of Contents anchor navigation and a persistent floating "↑ Table of Contents" button.
  - **View API Specification (twittv.apib)**: Opens the complete API Blueprint specification for the TWiT.tv REST API v1.0 formatted and rendered identically to the README documentation viewer with HTML sanitization, anchor navigation, and hybrid viewer fallback.
  - **Get TWiT API Key**: Opens the official TWiT API documentation and developer portal (`https://apidocs.twit.tv/`) in the default system web browser to register applications and obtain API Application IDs and Keys.

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
    └── toga.ProgressBar (max=100.0, value=0.0) [progress_bar]

toga.Window (title='Preferences', modal and transient to the main window)
└── toga.Box (direction=COLUMN, margin=5) [settings_box]
    ├── toga.Box (direction=ROW) [app_id_box]
    │   ├── toga.Label ('API Application ID:')
    │   └── toga.TextInput (value=initial_app_id) [app_id_input]
    ├── toga.Box (direction=ROW) [app_key_box]
    │   ├── toga.Label ('API Application Key:')
    │   ├── toga.PasswordInput (value=initial_app_key) [app_key_input]
    │   └── toga.Button ('Test API', on_press=on_test_api_press)
    ├── toga.Box (direction=ROW) [url_box]
    │   ├── toga.Label ('TWIT Club URL:')
    │   ├── toga.Label ('https://twit.memberfulcontent.com/rss/9041?auth=')
    │   ├── toga.PasswordInput (value=initial_url_key) [url_input]
    │   └── toga.Button ('Show', on_press=on_show_club_url_press)
    ├── toga.Box (direction=ROW) [dest_box]
    │   ├── toga.Label ('Download Destination:')
    │   ├── toga.TextInput (value=initial_dest) [dest_input]
    │   ├── toga.Button ('Browse', on_press=on_browse_press)
    │   ├── toga.Button ('Open', on_press=on_open_destination_press)
    │   └── toga.Switch ('Show Folders', on_change=on_show_folders_change) [show_folders_checkbox]
    ├── toga.Box (direction=ROW) [block_box]
    │   ├── toga.Label ('Block Size:')
    │   └── toga.TextInput (value='8192') [block_input]
    ├── toga.Box (direction=ROW) [streamer_box]
    │   ├── toga.Label ('Streamer:')
    │   └── toga.TextInput (value='env LC_ALL=C vlc %f') [streamer_input]
    └── toga.Button ('Close', on_press=on_preferences_close_press) [preferences_close_button]
```

---

### Tiered Search Engine & Phonetic Matching Architecture (`tiered_search.py`, `double_metaphone.py`)

To maximize query recall and precision while eliminating the cognitive friction of misspelled searches, TwitTUI employs a weighted, multi-tiered matching pipeline:

```
[User Query]
     │
     ├── 1. Exact Substring Match (Score: 100.0) ──► Highest Priority Display
     │      (Scans Title, Hosts/Guests, Topics, Show Notes, Episode Number)
     │
     ├── 2. Ranked Fuzzy / fzf Subsequence Score (Score: 60.0 - 99.0) ──► Sorted by Match Quality
     │      (Catches typos & abbreviations via Levenshtein & Smith-Waterman alignment)
     │
     └── 3. Double Metaphone Phonetic Fallback (Score: 88.0 - 95.0) ──► Phonetic Equivalence
            (Resolves sound-alike spellings: 'ballacer' ≈ 'Ballecer', 'secruity' ≈ 'security')
```

#### 1. Tier 1: Exact Substring Matching
- Evaluates candidate episode fields (`Title`, `Hosts / Guests`, `Topics`, `Description / Show Notes`, `Episode Number`).
- Yields a perfect score (`100.0`) when the entire query string or all individual whitespace-delimited tokens appear within the field metadata.

#### 2. Tier 2: Ranked Fuzzy & Subsequence Scoring (`fzf_subsequence_score` & `fuzzy_ratio`)
- **`fzf_subsequence_score(query, candidate)`**: Implements a modified Smith-Waterman local sequence alignment algorithm designed for interactive search:
  - Verifies that all query characters appear in sequential order within candidate strings.
  - Grants bonus multipliers for contiguous character matches, start-of-word boundaries (following spaces, underscores, hyphens, or slashes), and camelCase transitions.
  - Normalizes scores into a `0.0`–`100.0` floating-point range.
- **`fuzzy_ratio(s1, s2)` / `levenshtein_distance(s1, s2)`**: Computes the minimum single-character edit operations (insertions, deletions, substitutions) normalized by string length:
  $$\text{ratio} = \frac{(|s_1| + |s_2|) - d_{\text{Lev}}(s_1, s_2)}{|s_1| + |s_2|} \times 100$$
- Allows partial abbreviations and character transpositions (e.g., `macbrk` → `MacBreak Weekly`, `secruity` → `Security`).

#### 3. Tier 3: Pure Python Double Metaphone Phonetic Engine (`double_metaphone.py`)
- Provides an exhaustive, zero-dependency Python implementation of Lawrence Philips' **Double Metaphone** phonetic encoding algorithm.
- Generates primary and alternate phonetic keys up to 4 characters in length, handling complex phonetic transformations:
  - Silent letters (`GN`, `KN`, `PN`, `WR`, `PS`).
  - Contextual consonants (soft/hard `C`, `CH` as `/K/` vs `/SH/`, Italian `CCIA`, Germanic `SCH`).
  - Spanish and Romance sound shifts (e.g., `LL` to `/L/` or vowel glide).
  - Vowel dropping and consonant classification.
- Matches tokens sharing identical primary or alternate keys:
  - `ballacer` (`PLSR`, `PLSR`) $\leftrightarrow$ `ballecer` (`PLSR`, `PLSR`) $\rightarrow$ Primary Match (Score: `95.0`).
  - `algorhtm` (`ALKR`, `ALKR`) $\leftrightarrow$ `algorithms` (`ALKR`, `ALKR`) $\rightarrow$ Primary Match (Score: `95.0`).

#### 4. Weighted Scoring & Dynamic Field Prioritization
When scoring an episode against multiple query terms, `compute_match_score()` computes individual word scores and applies domain-specific field weights:
- **Field Weights**:
  - `Title`: $1.3\times$
  - `Hosts / Guests / People`: $1.25\times$
  - `Topics / Tags`: $1.2\times$
  - `Episode Number`: $1.1\times$
  - `Description / Show Notes`: $1.0\times$
- Episodes are ranked in descending score order. A match threshold of `65.0` filters out low-confidence noise, and search settings (`is_fuzzy_search_enabled()`, `is_phonetic_search_enabled()`) allow users to selectively toggle fuzzy and phonetic tiers.

---

### Search Match Inspection & KWIC Snippet Pipeline

To ensure transparency and allow instant verification of search results, TwitTUI extracts structured match provenance using `MatchContext` and `extract_snippet()`:

```python
@dataclass
class MatchContext:
    field_name: str = ""       # e.g., 'Description / Show Notes', 'Title', 'Hosts / Guests'
    matched_token: str = ""    # e.g., 'Ballecer'
    query_token: str = ""      # e.g., 'ballacer'
    match_tier: str = ""       # 'Exact Match', 'Fuzzy Match (92% similarity)', or 'Phonetic Match ("ballacer" ≈ "Ballecer")'
    snippet: str = ""          # '...Steve is away this week, so Fr. Robert Ballecer joins Leo Laporte...'
    char_offset: int = 0       # Character index offset within matched field
    score: float = 0.0
```

#### Keyword-in-Context (KWIC) Snippet Extraction (`extract_snippet`)
- Extracts a 100-character window centered around the match location.
- **Word-Boundary Alignment**: Scans up to 15 characters backward and forward for whitespace boundaries, preventing truncated words at snippet borders.
- Wraps snippets with leading and trailing ellipses (`...`) when boundary text extends beyond the window.

#### Desktop & Terminal Preview Integration
- **Textual TUI & Info Dialogs**: Injects the formatted `[🔍 Search Match]` header into metadata text views with explicit field and tier indicators.
- **GTK Desktop GUI Auto-Scroll**: In the desktop interface, `_show_episode_metadata()` detects `char_offset` within the show notes. It queries the native `GtkTextView` text buffer (`GtkTextBuffer.get_iter_at_offset()`), places the insertion cursor at the match position, and scrolls the text buffer (`scroll_to_iter()`) directly to the match location.

---

### Data Ingestion, Persistent SQLite Caching & Fallbacks

There is no single fallback cascade for every operation:
- **Show catalog**: Fetches the show catalog in a single API query (`GET /shows?page=1&range=1000`) when credentials are available, falling back to 26 built-in default shows if unavailable or offline. Show start dates (`created`) and active statuses (`active`) are parsed directly from the API response, while show end dates are discovered asynchronously via public web archive scraping (`/episodes?filter[shows]={show_id}`) to conserve API quotas under strict rate limits (5 calls/min).
- **Episodes and search**: Fetches show episodes iteratively in blocks of 50 (`GET /episodes?filter[shows]={show_id}&page={page}&range=50`) until the complete show catalog is loaded, throttled to a strict 5 calls per rolling minute. Public show RSS and configured Club RSS feeds provide resilient fallbacks. A fully loaded catalog can be searched locally; incomplete or unavailable sources need not produce complete results.
- **Media resolution**: Examines available episode formats and links, RSS enclosures, webpage media or YouTube links, and potentially API episode details. The path depends on the data and requested format rather than a universal tier order.
- **UI Initialization & Rate Limit Synchronization**: During catalog refreshes, the rate limit wait modal dialog is held open until both show date resolution and the selected show's initial episode list have finished loading, preventing UI jumping or focus loss while background operations complete.

API requests share a process-wide limiter: at least one second between request starts and at most five starts per rolling minute. An HTTP 500 response containing `usage limits are exceeded` triggers one retry after 60 seconds.

#### Persistent SQLite Caching & In-Memory Storage
To eliminate redundant HTTP traffic, minimize latency, and enable offline browsing:
- **Persistent SQLite Database (`twittui_cache.db`)**:
  - Saved to the platform cache directory (`~/.cache/twittui/twittui_cache.db` on Linux/POSIX or within `$SNAP_USER_DATA/.cache` under Snap confinement).
  - Maintains tables for show listings, show archive dates, public RSS feeds, Memberful subscriber feeds, and episode metadata.
  - Implements configurable TTL (time-to-live) expiration to balance freshness with network economy.
- **In-Memory Caches**:
  - `self._memberful_feeds_cache`: Caches parsed Memberful items per feed.
  - `self._club_rss_cache`: Holds aggregated Club items when fetched without a specific show.
  - `self._show_rss_cache`: Caches public feed items by normalized show name plus an `_audio` or `_video` suffix.
  - `self.show_ids`: Stores active show mappings with fallback to `DEFAULT_SHOWS` (26 entries).
  - Network workers use snapshots containing copies of caches rather than a single shared mutable cache.

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
    'video_hd',       # Video fallbacks if no audio stream exists
    'video_large',
    'video_small',
    'video_youtube'
]
```

When **Audio Only** is enabled:
- Club TWiT RSS queries prioritize subscriber audio feeds (`9040`, `9066`, `9054`, etc.) before video feeds.
- Public RSS queries check `.xml` audio feeds before `_video_hd.xml`.
- Webpage scraping extracts `.mp3` and `.m4a` URLs before `.mp4`.
- Download filenames automatically preserve `.mp3` / `.m4a` file extensions.
- State is persisted across restarts via the `TWITAUDIOONLY` setting in `.env`.

#### Validation Filter (`is_valid_media_url`)
Every candidate URL passes through `is_valid_media_url(url)` to prevent opening API metadata endpoints or HTML web pages as media streams:
- Protocol check: Must start with `http://`, `https://`, `rtsp://`, or `mms://`.
- API blacklist: Rejects URLs containing `/api/` or `twit.tv/api`.
- Webpage blacklist: Rejects matching TWiT page paths such as `shows`, `episodes`, `node`, `credits`, and `people` unless a media extension is recognized. Query strings are not categorically rejected; webpage scraping uses a regex that extracts the extension portion and may omit a URL's query string.

---

### Asynchronous Streaming & Multi-Threaded Batch Downloader

#### Subprocess Stream Launcher
Streaming commands are formatted and safely tokenized via `build_stream_args(streamer_template, media_url)` and spawned via `launch_stream_safe(streamer_template, media_url)` supporting replacement tokens (`%f`, `{url}`, `%s`, `{file}`, `{media_url}`) without shell injection risks:
```python
args = build_stream_args(streamer_template, media_url)
subprocess.Popen(args, shell=False)  # Non-blocking, secure detached execution
```

#### Dynamic Multi-Resolution Selection
When multiple media resolutions are available (e.g., HD, large, small, or audio), TwitTUI can present a modal prompt to choose a format:
- For single-episode downloads and streaming, the modal lists each available stream format along with its human-readable file size.
- For batch downloads with multiple selected episodes, users can pick a batch resolution preference (HD, Large, Small, or Audio) applied across all queued downloads.

#### Multi-Threaded Batch Download Architecture
Each batch runs sequentially in a background daemon thread (`threading.Thread`), keeping transfers off Toga's main event loop.

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
 │      a. Resolve an available Media URL                  │
 │      b. Determine sanitized target filename            │
 │      c. Verify existing file (is_existing_file_same): │
 │         • Compare local size against RSS / Content-Len │
 │         • Sometimes compare MD5 against remote ETag    │
 │         • If heuristic matches: SKIP download         │
 │      d. Stream via requests.get(url, stream=True)      │
 │      e. Update progress bar with batch percentage      │
 │      f. Write chunks (size=block_size) to .part file   │
 │      g. Remove existing destination, rename .part      │
 │   3. On batch completion:                              │
 │      Show dialog only if at least one item succeeded   │
 └────────────────────────────────────────────────────────┘
```

#### Smart File Verification & Deduplication
To conserve network bandwidth, prevent unnecessary disk wear, and avoid redundant transfers:
1. **Metadata & Size Check**: A matching expected enclosure size or HTTP `Content-Length` can be enough to skip a file, without proving identical content.
2. **HTTP HEAD / Conditional Request**: May inspect remote size and `ETag`, or accept a not-modified response.
3. **ETag Check**: A 32-hex-character ETag may be interpreted as an MD5 checksum and compared with the local file, but servers do not guarantee that ETags are MD5 hashes.
4. **YouTube**: An existing file over 1 MiB can be treated as already downloaded without proving identity.

#### Direct Download Writes
For direct downloads:
1. Chunks are written to `<filename>.part`.
2. Existing target files at the destination are removed upon completion.
3. `<filename>.part` is renamed to `<filename>`. Removing the destination first means replacement is not guaranteed atomic, and an existing non-identical file can be overwritten without confirmation.
4. On cancellation or exceptions, cleanup of `<filename>.part` is attempted. YouTube downloads use a separate downloader path.

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
- `GET /shows?page=1&range=1000`: Fetches active and legacy show lists, identifiers, start dates (`created`), and active status (`active`) in a single query.
- `GET /search/{keywords}`: Executes scoped full-text queries for in-show episode discovery across TWiT indexed archives.
- `GET /episodes?filter[shows]={show_id}&page={page}&range=50`: Retrieves episodes in sequential blocks of 50 per page until all episodes have been fetched.
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
| `twitcluburl` / `TWITCLUBURL` / `TWIT_CLUB_URL` | String | `""` | Full Memberful RSS feed URL or unique authorization key token. |
| `twitclubdestination` / `TWITCLUBDESTINATION` / `TWIT_CLUB_DESTINATION` | String | See below | Filesystem directory path for storing downloaded podcast files. |
| `twitclubblocksize` / `TWITCLUBBLOCKSIZE` | Integer | `8192` (8 KB) | Buffer chunk size in bytes for network download streaming. |
| `twitclubstreamer` / `TWITCLUBSTREAMER` / `TWIT_CLUB_STREAMER` | String | `env LC_ALL=C vlc %f` | Command template string used to spawn the external streaming player. |
| `TWITAUDIOONLY` / `twitaudioonly` / `TWIT_AUDIO_ONLY` | Integer / Boolean | `0` (False) | Flag (`1`/`0`) persisting the Audio Only streaming/download preference across sessions. |
| `TWITCLUBSHOWFOLDERS` / `twitclubshowfolders` | Integer / Boolean | `0` (False) | Flag (`1`/`0`) persisting the Show Folders organization preference across sessions. |
| `TWITFUZZYSEARCH` / `twitfuzzysearch` | Integer / Boolean | `1` (True) | Flag (`1`/`0`) enabling ranked fuzzy and `fzf` subsequence search matching. |
| `TWITPHONETICSEARCH` / `twitphoneticsearch` | Integer / Boolean | `1` (True) | Flag (`1`/`0`) enabling Double Metaphone phonetic sound-alike search matching. |

Without a configured destination, the application prefers a writable `~/Downloads`, then the current working directory, then `SNAP_USER_DATA` or the home directory. Snap's launcher can supply its own default as described above; saved settings may override it.

---

### Automated Testing & Quality Assurance

TwitTUI maintains a comprehensive automated unit test suite covering end-to-end functionality, GUI backend abstractions, packaging pipelines, security sanitization, search algorithms, and network operations:

- **Test Suite Structure**:
  - `test_api_rate_limiter.py`: Tests for 5 requests/minute sliding window rate limiting and automatic retry on API limit responses.
  - `test_backend_factory.py`: Tests for backend detection, CLI flag routing (`--gtk`, `--textual`), and environment variable configuration.
  - `test_caching.py`: Tests for persistent SQLite database caching (`twittui_cache.db`), schema creation, cache TTL expiration, and cache hits/misses.
  - `test_episode_activation.py`: Tests for table row selection, double-click streaming activation, keyboard shortcuts, and table focus interactions.
  - `test_episode_search.py`: Tests for the three-tiered search pipeline, exact substring priority, `fzf` subsequence ranking, typo resilience, Double Metaphone phonetic matching (`double_metaphone.py`), and non-truncating in-memory sorting.
  - `test_hover_popup.py`: Tests for 3-second hover metadata extraction, popup dialog formatting, search match provenance classification, KWIC snippet generation, and auto-scroll cursor placement.
  - `test_install.py`: Tests for PyInstaller compilation, standalone executable installation, PATH discovery, artifact cleanup, hidden module import bundling (`tiered_search`, `double_metaphone`), and application icon generation.
  - `test_open_destination.py`: Tests for opening and auto-creating download destination folders cross-platform.
  - `test_preferences.py`: Tests for in-app preference dialogs, live configuration binding, search toggle persistence, and `.env` serialization.
  - `test_resolutions.py`: Tests for multi-resolution media extraction, format sorting, and batch resolution selection modals.
  - `test_security.py`: Tests for markdown sanitization, HTML attribute stripping, and URI validation.
  - `test_show_catalog.py`: Tests for show catalog single-request pagination (`range=1000`), active/ended status parsing, start date (`created`) extraction, public web archive scraping, rate-limit wait modal synchronization, episode iterative fetching in blocks of 50 (`range=50`), and local catalog search.
  - `test_show_folders.py`: Tests for show folder sub-directory hierarchy creation and file path resolution.
  - `test_snap.py`: Tests for Snapcraft YAML structure, base core24 specification, strict confinement, plugs and slots, desktop entry Freedesktop validity, launcher shell script permissions and environment isolation logic, requirements/setup synchronization, SNAP_USER_DATA .env loading/saving, and runtime resource resolution.
  - `test_splash_screen.py`: Tests for Textual modal splash screens, desktop modal splash windows, message update reactivity, and CLI terminal splash banners.
  - `test_tooltips.py`: Tests for tooltip assignment and accessibility across all interactive widgets.
  - `test_youtube_download.py`: Tests for YouTube fallback extraction and download helpers.

- **Running Tests**:
  Execute the complete test suite using Python's standard `unittest` test discovery:
  ```bash
  python -m unittest discover
  ```

---

## Known Issues & Troubleshooting

### GTK Module & Backend Warnings
- **Symptom**: Console outputs `Failed to load module "xapp-gtk3-module"` or `Gtk-Message: Failed to load module "canberra-gtk-module"`.
- **Cause**: Linux systems with desktop environments like Cinnamon or MATE attempt to inject theme modules into GTK applications that lack matching runtime bindings.
- **Handling**: `main.py` filters only the `xapp-gtk3-module` failed-load warning, not the `canberra-gtk-module` warning. It sets `NO_AT_BRIDGE=1` and sets `GDK_BACKEND=x11` only when `DISPLAY` is set and `WAYLAND_DISPLAY` is not.

### PyGObject & Gdk Introspection Namespace Collisions
- **Symptom**: Standalone binary or desktop run fails with `gi.RepositoryError: Requiring namespace 'Gdk' version '4.0', but '3.0' is already loaded` or `ImportError: Requiring namespace 'Gdk' version '4.0'`.
- **Cause**: PyInstaller binary hooks or system libraries may attempt to resolve the latest GTK 4.0 introspection typelibs when `toga-gtk` requires GTK 3.0 / Gdk 3.0.
- **Handling**: `configure_gtk_environment()` attempts to select compatible introspection namespaces (GTK 3 by default, GTK 4 with `TOGA_GTK=4`). Failures are swallowed and collisions remain possible; check installed libraries and backend versions. Some GTK startup failures fall back to Textual if installed.

### Python Built Without Shared Library (`--enable-shared`)
- **Symptom**: `python main.py --install` or `python installer.py --install` fails with `ERROR: Python was built without a shared library, which is required by PyInstaller. If you built Python from source, rebuild it with the '--enable-shared' option.`
- **Cause**: On Linux, PyInstaller's bootloader requires dynamic link support via Python's shared library (`libpythonX.Y.so`). If Python was built statically from source or without shared libraries, PyInstaller cannot bundle the runtime.
- **Resolution**:
  1. **Source Builds**: Recompile Python with `./configure --enable-shared --enable-optimizations && make -j$(nproc) && sudo make altinstall && sudo ldconfig`.
  2. **pyenv**: Reinstall your Python version with shared libraries enabled: `env PYTHON_CONFIGURE_OPTS="--enable-shared" pyenv install <version>`.
  3. **Ubuntu/Debian**: Ensure development headers are installed: `sudo apt update && sudo apt install -y python3-dev libpython3-dev`.
  4. **Target Alternative Python**: Pass `--python-executable` pointing to an interpreter with shared libraries: `python main.py --install --python-executable /usr/bin/python3`.

### Missing API Credentials Fallback
- **Symptom**: Console logs `API credentials not found in .env file, using default shows`.
- **Impact**: TwitTUI loads its built-in show list and can try public RSS and configured Club RSS feeds. Episode and media availability depends on those sources; offline operation does not provide an episode catalog.

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
