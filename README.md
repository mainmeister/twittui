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
  - [Snap Package (Cross-Distribution Linux)](#snap-package-cross-distribution-linux)
  - [Standalone Binary Packaging & Installation](#standalone-binary-packaging--installation)
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
  - [Application Icon & Branding Asset Pipeline](#application-icon--branding-asset-pipeline)
  - [Execution Lifecycle & GTK Namespace Locking (`main.py`)](#execution-lifecycle--gtk-namespace-locking-mainpy)
  - [Installer & Packaging Engine (`installer.py`)](#installer--packaging-engine-installerpy)
  - [Snap Packaging & Confinement Architecture (`snap/`)](#snap-packaging--confinement-architecture-snap)
  - [UI Architecture & Widget Tree (`twittui_form.py`)](#ui-architecture--widget-tree-twittui_formpy)
  - [Data Ingestion & 5-Tier Fallback Cascade](#data-ingestion--5-tier-fallback-cascade)
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

This compiles all dependencies, GLib schemas, GObject typelibs, and virtual environments, producing `twittui_1.0.0_<arch>.snap` (e.g., `twittui_1.0.0_amd64.snap`) in the project root directory.

#### 3. Installing the Snap

- **Install Local Build**:
  Install the locally compiled `.snap` package using the `--dangerous` flag (required for locally built, self-signed packages):
  ```bash
  sudo snap install --dangerous twittui_1.0.0_amd64.snap
  ```

- **Install for Development & Debugging** (Optional):
  To test without confinement restrictions during development:
  ```bash
  sudo snap install --dangerous --devmode twittui_1.0.0_amd64.snap
  ```

- **Install from Snap Store** (Once Published):
  ```bash
  sudo snap install twittui
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
  # Or pass backend switch to main command:
  twittui --textual
  ```

- **Command-Line Options & Help**:
  ```bash
  twittui --gtk        # Force GTK graphical desktop backend
  twittui --textual    # Force Textual terminal backend
  twittui --help       # Display all startup options
  ```

#### 5. Snap Permissions & Interface Plugs

TwitTUI operates under strict confinement (`confinement: strict`) and requests standard desktop interfaces:

| Plug Interface | Default Status | Purpose |
| :--- | :--- | :--- |
| `desktop`, `desktop-legacy` | Connected | Native windowing, GTK themes, and font rendering |
| `wayland`, `x11` | Connected | Wayland and X11 display server communication |
| `opengl` | Connected | Hardware-accelerated graphics rendering |
| `audio-playback` | Connected | PulseAudio / PipeWire audio playback for podcast streams |
| `network`, `network-bind` | Connected | REST API querying, RSS feed parsing, and media streaming/downloading |
| `home` | Connected | Accessing standard user directories (`~/Downloads`) |
| `removable-media` | Disconnected (Manual) | Accessing external USB drives and SD cards (`/media`, `/run/media`) |

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

- Upon first launch, TwitTUI automatically initializes this configuration file.
- If no custom download destination is set, TwitTUI defaults to `~/Downloads` (or `~/snap/twittui/current/` if `~/Downloads` is unavailable).
- You can edit `~/snap/twittui/current/.env` with any text editor or modify settings live via the in-app configuration panel.

---

5. **Install as a Standalone Command-Line / Desktop Executable**:
   TwitTUI features an automated packaging and installation pipeline using PyInstaller. It compiles the entry point into a single, optimized standalone executable (`twittui` on POSIX systems or `twittui.exe` on Windows), embeds the application icon set, bundles all backend libraries (`toga-gtk`, `toga-textual`, `gi`), and installs the binary to a directory on your system's executable `$PATH`:
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
   If your active virtual environment is based on a static Python build (e.g. without `--enable-shared`), you can compile the standalone binary using another Python interpreter on your system:
   ```bash
   python main.py --install --python-executable /usr/bin/python3
   ```

   **Automatic Cleanup & Build Artifact Management**:
   To preserve disk space and keep your workspace clean, the installation routine automatically removes intermediate PyInstaller `build/`, `dist/`, and `.spec` files after copying the binary.
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
   Once installed, run TwitTUI from any terminal or application launcher:
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
twitclubstreamer=env LC_ALL=C vlc %f
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
| Download Destination: [/home/user/Podcasts       ] [ Browse ] [ Open ] [X Show Folders] |
| Block Size:           [8192                      ]                              |
| Streamer:             [env LC_ALL=C vlc %f       ]                              |
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
3. Optionally toggle **Show Folders** if you want downloaded episodes organized into dedicated subfolders named after each show (e.g., `<Download Destination>/Security Now/Security Now 1000.mp4`).
4. Click **Download**. Downloads execute concurrently in the background without freezing the UI.
5. Files are saved directly to your destination path (or show subfolder) with normalized, clean filenames (e.g., `This Week in Tech 1001 AI in the Fast Lane.mp4`).
6. When the batch completes, a modal dialog appears displaying the target download folder at the top and the list of downloaded filenames (one per line) with a **Close** button.

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
├── test_snap.py             # Snapcraft recipe, desktop entry, launcher, and sandbox tests
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
  └── (No Switch & Both Found)        ──► Interactive CLI prompt [1: GTK / 2: Textual]
        │
        ▼
[ Set TOGA_BACKEND & Configure Environment ]
  ├── If toga_gtk:
  │     ├── configure_gtk_environment()
  │     │     ├── gi.require_version('Gtk', '3.0')
  │     │     ├── gi.require_version('Gdk', '3.0')
  │     │     ├── gi.require_version('GdkX11', '3.0')
  │     │     ├── gi.require_version('GdkWayland', '3.0')
  │     │     ├── gi.require_version('Pango', '1.0') / PangoCairo / GLib / GObject / Gio
  │     │     ├── Import gi.overrides.Gtk & gi.overrides.Pango
  │     │     └── Gtk.init_check()
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

#### `configure_gtk_environment()` Implementation
To prevent runtime crashes where external modules or PyInstaller dynamic loaders prematurely import GTK 4 (`gi.RepositoryError: Requiring namespace 'Gdk' version '4.0', but '3.0' is already loaded`), `main.py` explicitly locks all GObject introspection versions and pre-initializes GTK bindings before any UI code runs.

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

### Installer & Packaging Engine (`installer.py`)

`installer.py` provides standalone binary compilation, local `$PATH` discovery, and workspace hygiene management:

1. **PyInstaller Automated Compilation (`build_executable`)**:
   - Detects or installs `pyinstaller` dynamically within the active virtual environment.
   - Bundles required data assets: `feed-style.css`, `feed-style.xsl`, `twittv.apib`, and `resources/` (icon suite).
   - Embeds native platform application icons (`--icon=resources/twittui.ico` or `twittui.png`).
   - Collects all dependencies and hidden imports for `toga`, `toga_textual`, `toga_gtk`, `gi`, `gi.overrides.Gtk`, `gi.overrides.Pango`, `dotenv`, and `requests`.
   - Produces a single non-debug standalone executable in `dist/twittui` (or `dist/twittui.exe`).

2. **System PATH Resolution & Installation (`install_twittui`)**:
   - Queries standard user and system binary paths (`~/.local/bin`, `~/bin`, `/usr/local/bin`, etc.).
   - Copies the compiled binary using `shutil.copy2` and grants POSIX executable permissions (`0o755`).
   - Replaces pre-existing binary installations in place cleanly.

3. **Artifact Cleanup Engine (`clean_build_artifacts`)**:
   - Automatically purges temporary `build/`, distribution `dist/`, and PyInstaller `.spec` files.
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
[ Initialize User Config ($SNAP_USER_DATA/.env) ]
                 │
                 ▼
[ Set Default Download Path ($HOME/Downloads or $SNAP_USER_DATA) ]
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
        │   ├── toga.Button ('Open', on_press=on_open_destination_press)
        │   └── toga.Switch ('Show Folders', on_change=on_show_folders_change) [show_folders_checkbox]
        ├── toga.Box (direction=ROW) [block_box]
        │   ├── toga.Label ('Block Size:')
        │   └── toga.TextInput (value='8192') [block_input]
        └── toga.Box (direction=ROW) [streamer_box]
            ├── toga.Label ('Streamer:')
            └── toga.TextInput (value='env LC_ALL=C vlc %f') [streamer_input]
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
| `twitclubstreamer` / `TWITCLUBSTREAMER` | String | `env LC_ALL=C vlc %f` | Command template string used to spawn the external streaming player. |
| `TWITAUDIOONLY` / `twitaudioonly` | Integer / Boolean | `0` (False) | Flag (`1`/`0`) persisting the Audio Only streaming/download preference across sessions. |
| `TWITCLUBSHOWFOLDERS` / `twitclubshowfolders` | Integer / Boolean | `0` (False) | Flag (`1`/`0`) persisting the Show Folders organization preference across sessions. |

---

### Automated Testing & Quality Assurance

TwitTUI maintains a comprehensive automated unit test suite covering end-to-end functionality, GUI backend abstractions, packaging pipelines, security sanitization, and network operations:

- **Test Suite Structure**:
  - `test_install.py`: Tests for PyInstaller compilation, standalone executable installation, PATH discovery, artifact cleanup, and application icon generation.
  - `test_snap.py`: Tests for Snapcraft YAML structure, base core24 specification, strict confinement, plugs and slots, desktop entry Freedesktop validity, launcher shell script permissions and environment isolation logic, requirements/setup synchronization, SNAP_USER_DATA .env loading/saving, and runtime resource resolution.
  - `test_backend_factory.py`: Tests for backend detection, CLI flag routing (`--gtk`, `--textual`), and environment variable configuration.
  - `test_security.py`: Tests for markdown sanitization, HTML attribute stripping, and URI validation.
  - `test_resolutions.py`: Tests for multi-resolution media extraction, format sorting, and batch resolution selection modals.
  - `test_open_destination.py`: Tests for opening destination folders cross-platform.
  - `test_show_folders.py`: Tests for show folder sub-directory hierarchy creation and file path resolution.
  - `test_tooltips.py`: Tests for tooltip assignment across widgets.
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
- **Resolution**: TwitTUI automatically filters this specific warning through `main.py`'s `StderrRedirector` and enforces `GDK_BACKEND=x11` and `NO_AT_BRIDGE=1`. No user action is required.

### PyGObject & Gdk Introspection Namespace Collisions
- **Symptom**: Standalone binary or desktop run fails with `gi.RepositoryError: Requiring namespace 'Gdk' version '4.0', but '3.0' is already loaded` or `ImportError: Requiring namespace 'Gdk' version '4.0'`.
- **Cause**: PyInstaller binary hooks or system libraries may attempt to resolve the latest GTK 4.0 introspection typelibs when `toga-gtk` requires GTK 3.0 / Gdk 3.0.
- **Resolution**: TwitTUI's `configure_gtk_environment()` in `main.py` explicitly locks GObject introspection namespaces (`Gtk 3.0`, `Gdk 3.0`, `GdkX11 3.0`, `GdkWayland 3.0`, `Pango 1.0`, `GLib`, `GObject`, `Gio`) prior to initializing Toga backends, eliminating namespace collisions.

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
