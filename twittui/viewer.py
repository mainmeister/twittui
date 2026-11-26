"""HTML sanitization and authenticated loopback viewer server for TwitTUI."""

from __future__ import annotations

import glob
import html
import html.parser
import http.server
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import webbrowser

import requests
import toga
from toga.style import Pack

from twittui._compat import (
    PACKAGE_ROOT,
    PROJECT_ROOT,
    _is_textual_tui_running,
    compat_attr,
)
from twittui.config import TWIT_API_KEY_URL, TWITTUI_HOMEPAGE_URL
from twittui.logging_config import get_logger, safe_url_for_log
from twittui.media import is_safe_http_url, safe_xml_fromstring

_logger = get_logger("viewer")


def generate_local_server_token() -> str:
    """Generate a cryptographically random URL-safe token for local server requests."""
    return secrets.token_urlsafe(24)


class _LocalHTMLServer(http.server.HTTPServer):
    """Loopback-only HTTP server storing in-memory rendered documentation pages."""

    def __init__(self, server_address, RequestHandlerClass) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.pages: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self.secret_token: str = generate_local_server_token()


class _LocalHTMLHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler enforcing path-segment session token authentication."""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]

        # Require secret session token as the first path segment
        expected_token = getattr(self.server, "secret_token", "")
        if not path_parts or not secrets.compare_digest(path_parts[0], expected_token):
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"403 Forbidden: Invalid or missing session token")
            return

        path_key = path_parts[1] if len(path_parts) > 1 else "index.html"

        with self.server.lock:
            content_bytes = self.server.pages.get(path_key) or self.server.pages.get("index.html")

        if content_bytes:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content_bytes)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(content_bytes)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def log_message(self, format: str, *args) -> None:
        # Mute server request logging to preserve clean console/TUI output
        pass


_DANGEROUS_TAGS = (
    "script", "style", "iframe", "object", "embed", "applet",
    "form", "input", "button", "link", "meta", "svg", "math", "base",
)

_ALLOWED_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
    "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "blockquote", "strong", "b", "em", "i", "u", "s", "del",
    "a", "hr", "br", "span", "div", "img", "dl", "dt", "dd", "sup", "sub",
})

_VOID_TAGS = frozenset({"br", "hr", "img"})

_DROP_CONTENT_TAGS = frozenset({
    "script", "style", "iframe", "object", "applet",
    "svg", "math", "template", "noscript", "title", "head",
})

_ALLOWED_ATTRS = {
    "a": frozenset({"href", "title", "id", "name", "target", "rel"}),
    "img": frozenset({"src", "alt", "title", "width", "height"}),
    "th": frozenset({"align", "colspan", "rowspan"}),
    "td": frozenset({"align", "colspan", "rowspan"}),
    "*": frozenset({"class", "id"}),
}

_SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto"})


def _clean_url_attr(val: str, is_src: bool = False) -> str | None:
    unescaped = val
    for _ in range(3):
        nxt = html.unescape(unescaped)
        if nxt == unescaped:
            break
        unescaped = nxt
    normalized = re.sub(r"[\x00-\x20\x7f]+", "", unescaped).lower()
    if not normalized:
        return None if is_src else ""
    if normalized.startswith(("#", "./", "../")) or (
        normalized.startswith("/") and not normalized.startswith("//")
    ):
        return val.strip()
    scheme_match = re.match(r"^([a-z][a-z0-9+.\-]*):", normalized)
    if scheme_match:
        if scheme_match.group(1) in _SAFE_URL_SCHEMES:
            return val.strip()
        return None if is_src else "#"
    prefix = re.split(r"[/?#]", normalized, maxsplit=1)[0]
    if ":" in prefix or normalized.startswith("//"):
        return None if is_src else "#"
    return val.strip()


class _AllowlistHTMLSanitizer(html.parser.HTMLParser):
    """Pure-Python allowlist HTML sanitizer immune to regex/entity bypasses."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._drop_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in _DROP_CONTENT_TAGS:
            self._drop_stack.append(t)
            return
        if self._drop_stack or t not in _ALLOWED_TAGS:
            return
        tag_allowed = _ALLOWED_ATTRS.get(t, frozenset()) | _ALLOWED_ATTRS["*"]
        rendered_attrs: list[str] = []
        for k, v in attrs:
            if not k:
                continue
            attr_name = k.lower()
            if attr_name not in tag_allowed:
                continue
            val_str = "" if v is None else str(v)
            if attr_name in ("href", "src"):
                safe_url = _clean_url_attr(val_str, is_src=(attr_name == "src"))
                if safe_url is None:
                    continue
                val_str = safe_url
            rendered_attrs.append(f'{attr_name}="{html.escape(val_str, quote=True)}"')
        attr_suffix = (" " + " ".join(rendered_attrs)) if rendered_attrs else ""
        if t in _VOID_TAGS:
            self.parts.append(f"<{t}{attr_suffix} />")
        else:
            self.parts.append(f"<{t}{attr_suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in _DROP_CONTENT_TAGS or self._drop_stack or t not in _ALLOWED_TAGS:
            return
        self.handle_starttag(tag, attrs)
        if t not in _VOID_TAGS:
            self.parts.append(f"</{t}>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if self._drop_stack:
            if t in self._drop_stack:
                while self._drop_stack:
                    if self._drop_stack.pop() == t:
                        break
            return
        if t in _ALLOWED_TAGS and t not in _VOID_TAGS:
            self.parts.append(f"</{t}>")

    def handle_data(self, data: str) -> None:
        if not self._drop_stack:
            self.parts.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        pass

    def handle_pi(self, data: str) -> None:
        pass

    def handle_decl(self, decl: str) -> None:
        pass


def sanitize_html_content(html_str: str) -> str:
    """Sanitize untrusted HTML to prevent script injection and dangerous URI schemes."""
    if not html_str:
        return ""

    sanitized = html_str
    for _ in range(5):
        prev = sanitized
        for tag in _DANGEROUS_TAGS:
            sanitized = re.sub(
                rf"<{tag}\b[^>]*>.*?</{tag}\s*>", "", sanitized, flags=re.IGNORECASE | re.DOTALL
            )
            sanitized = re.sub(rf"<{tag}\b[^>]*/>", "", sanitized, flags=re.IGNORECASE)
        if sanitized == prev:
            break

    try:
        import bleach

        return bleach.clean(
            sanitized,
            tags=[
                "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
                "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                "blockquote", "strong", "em", "a", "hr", "br", "span", "div", "img",
            ],
            attributes={
                "a": ["href", "title", "id", "name", "target", "rel"],
                "img": ["src", "alt", "title", "width", "height"],
                "th": ["align"],
                "td": ["align"],
                "*": ["class", "id"],
            },
            protocols=["http", "https", "mailto"],
            strip=True,
            strip_comments=True,
        )
    except ImportError:
        pass

    try:
        import nh3

        return nh3.clean(
            sanitized,
            tags={
                "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
                "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                "blockquote", "strong", "em", "a", "hr", "br", "span", "div", "img",
            },
            attributes={
                "a": {"href", "title", "id", "name", "target", "rel"},
                "img": {"src", "alt", "title", "width", "height"},
                "th": {"align"},
                "td": {"align"},
                "*": {"class", "id"},
            },
            url_schemes={"http", "https", "mailto"},
        )
    except ImportError:
        pass

    parser = _AllowlistHTMLSanitizer()
    parser.feed(sanitized)
    parser.close()
    return "".join(parser.parts)


class ViewerMixin:
    """Markdown/RSS HTML rendering, local HTTP viewer, browser, and folder opener mixin."""

    def _open_browser_quietly(self, url: str) -> bool:
        """Open a URL in the default browser while silencing child OS stdio in live TUI mode.

        In live Textual TUI mode on POSIX, launches the OS URL opener directly with
        stdin/stdout/stderr redirected to DEVNULL instead of mutating process-global
        sys.stdout/sys.stderr (which is neither thread-safe nor effective for child FDs).
        """
        if not url or not isinstance(url, str):
            return False
        clean_url = url.strip()
        if not clean_url or clean_url.startswith('-'):
            return False

        if compat_attr('_is_textual_tui_running', _is_textual_tui_running)(self):
            if sys.platform != 'win32':
                opener_cmds: list[list[str]] = []
                if sys.platform == 'darwin':
                    open_bin = shutil.which('open')
                    if open_bin:
                        opener_cmds.append([open_bin, clean_url])
                else:
                    xdg_bin = shutil.which('xdg-open')
                    if xdg_bin:
                        opener_cmds.append([xdg_bin, clean_url])
                    gio_bin = shutil.which('gio')
                    if gio_bin:
                        opener_cmds.append([gio_bin, 'open', clean_url])
                    sensible_bin = shutil.which('sensible-browser')
                    if sensible_bin:
                        opener_cmds.append([sensible_bin, clean_url])

                for cmd in opener_cmds:
                    try:
                        subprocess.Popen(
                            cmd,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                        return True
                    except OSError:
                        _logger.debug("POSIX browser opener %s failed; trying fallback", cmd[0], exc_info=True)
            return bool(webbrowser.open(clean_url))
        return bool(webbrowser.open(clean_url))

    def sanitize_html(self, html_str: str) -> str:
        """Sanitize HTML content to prevent script injection and malicious payloads."""
        return sanitize_html_content(html_str)

    @staticmethod
    def _slugify(text: str) -> str:
        """Generate a GitHub-compatible URL slug from a heading text string."""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.lower().strip()
        clean = re.sub(r"[^\w\s-]", "", clean)
        clean = re.sub(r"\s", "-", clean)
        return clean

    def _ensure_heading_ids(self, html_content: str) -> str:
        """Ensure all <h1-6> headings have unique id attributes matching standard slug format."""
        slug_counts = {}

        def replace_heading(match):
            level = match.group(1)
            attrs = match.group(2)
            inner_text = match.group(3)
            # If id attribute already exists, track it and keep
            id_match = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
            if id_match:
                existing_id = id_match.group(1)
                slug_counts[existing_id] = slug_counts.get(existing_id, 0) + 1
                return match.group(0)

            # Generate slug from inner heading text
            clean_text = re.sub(r'<[^>]+>', '', inner_text).strip()
            slug = self._slugify(clean_text)
            if not slug:
                slug = f"heading-{level}"

            count = slug_counts.get(slug, 0)
            slug_counts[slug] = count + 1
            final_id = slug if count == 0 else f"{slug}-{count}"

            return f'<h{level}{attrs} id="{final_id}">{inner_text}</h{level}>'

        return re.sub(r'<h([1-6])([^>]*)>(.*?)</h\1>', replace_heading, html_content, flags=re.IGNORECASE | re.DOTALL)

    def render_markdown_to_html(self, md_text: str, title: str = "TwitTUI Documentation") -> str:
        """Convert Markdown text to fully sanitized and styled HTML with anchor navigation."""
        body_html = ""

        # Try markdown-it-py (with raw HTML disabled) and anchors plugin
        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt("gfm-like", {"html": False})
            try:
                from mdit_py_plugins.anchors import anchors_plugin
                md.use(anchors_plugin, min_level=1, max_level=6)
            except ImportError:
                pass
            body_html = md.render(md_text)
        except ImportError:
            pass

        # Try standard python markdown library if markdown-it-py unavailable
        if not body_html:
            try:
                import markdown
                body_html = markdown.markdown(md_text, extensions=["extra", "tables", "toc"])
            except ImportError:
                pass

        # Fallback to escaped preformatted text
        if not body_html:
            body_html = f"<pre><code>{html.escape(md_text)}</code></pre>"

        # Guarantee heading IDs are present for Table of Contents navigation
        body_html = self._ensure_heading_ids(body_html)

        # Enforce sanitization on the generated HTML
        safe_body_html = self.sanitize_html(body_html)

        # Detect Table of Contents presence for navigation button
        has_toc = 'id="table-of-contents"' in safe_body_html or 'id="toc"' in safe_body_html
        toc_target = "#table-of-contents" if has_toc else "#top"
        toc_label = "↑ Table of Contents" if has_toc else "↑ Top"
        toc_title = "Jump to Table of Contents" if has_toc else "Return to top of document"

        # Wrap in clean, readable stylesheet
        styled_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
  html {{
    scroll-behavior: smooth;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.6;
    padding: 24px 32px;
    color: #24292e;
    background-color: #ffffff;
    max-width: 960px;
    margin: 0 auto;
  }}
  h1, h2, h3, h4, h5, h6 {{
    border-bottom: 1px solid #eaecef;
    padding-bottom: 0.3em;
    margin-top: 24px;
    margin-bottom: 16px;
    font-weight: 600;
    scroll-margin-top: 16px;
  }}
  h1 {{ font-size: 2em; }}
  h2 {{ font-size: 1.5em; }}
  h3 {{ font-size: 1.25em; }}
  code {{
    background-color: #f6f8fa;
    padding: 0.2em 0.4em;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    font-size: 85%;
  }}
  pre {{
    background-color: #f6f8fa;
    padding: 16px;
    overflow: auto;
    border-radius: 6px;
    line-height: 1.45;
  }}
  pre code {{
    background-color: transparent;
    padding: 0;
    font-size: 100%;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
    display: block;
    overflow-x: auto;
  }}
  table th, table td {{
    border: 1px solid #dfe2e5;
    padding: 8px 14px;
    text-align: left;
  }}
  table th {{
    background-color: #f2f4f8;
    font-weight: 600;
  }}
  table tr:nth-child(2n) {{
    background-color: #f8f9fa;
  }}
  blockquote {{
    border-left: 0.25em solid #dfe2e5;
    color: #6a737d;
    padding: 0 1em;
    margin: 16px 0;
  }}
  a {{
    color: #0366d6;
    text-decoration: none;
  }}
  a:hover {{
    text-decoration: underline;
  }}
  hr {{
    height: 0.25em;
    padding: 0;
    margin: 24px 0;
    background-color: #e1e4e8;
    border: 0;
  }}
  .back-to-toc {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    background-color: #0366d6;
    color: #ffffff;
    padding: 8px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
    opacity: 0.85;
    transition: opacity 0.2s ease, transform 0.2s ease, background-color 0.2s ease;
    z-index: 1000;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    user-select: none;
    cursor: pointer;
  }}
  .back-to-toc:hover {{
    opacity: 1.0;
    color: #ffffff;
    background-color: #0255b5;
    text-decoration: none;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
  }}
  .back-to-toc:active {{
    transform: translateY(0);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
  }}
</style>
</head>
<body>
<div id="top"></div>
{safe_body_html}
<a href="{toc_target}" class="back-to-toc" title="{toc_title}" aria-label="{toc_label}">{toc_label}</a>
</body>
</html>"""
        return styled_html

    def _ensure_local_server(self) -> _LocalHTMLServer | None:
        """Ensure local background HTTP server is running on 127.0.0.1 for displaying HTML in browsers."""
        if not hasattr(self, '_local_server') or self._local_server is None:
            try:
                self._local_server = _LocalHTMLServer(('127.0.0.1', 0), _LocalHTMLHandler)
                server_thread = threading.Thread(target=self._local_server.serve_forever, daemon=True)
                server_thread.start()
            except Exception as e:
                _logger.warning(f"Warning: Could not start local HTTP server ({e})")
                self._local_server = None
        return self._local_server

    def open_html_in_browser(self, html_content: str, page_name: str = "index.html") -> None:
        """Open rendered HTML in web browser via local HTTP server with file fallback."""
        html_bytes = html_content.encode('utf-8')
        server = self._ensure_local_server()
        if server:
            with server.lock:
                server.pages[page_name] = html_bytes
                server.pages['index.html'] = html_bytes
            port = server.server_address[1]
            token = getattr(server, 'secret_token', '')
            self._open_browser_quietly(f"http://127.0.0.1:{port}/{token}/{page_name}")
            return

        # Fallback to local HTML file in cache directory if local HTTP server unavailable.
        # Prune older fallback previews so ~/.cache/twittui never grows unboundedly.
        cache_dir = self.get_app_cache_dir()
        try:
            existing_previews = sorted(
                glob.glob(os.path.join(glob.escape(cache_dir), "twittui_preview_*.html")),
                key=os.path.getmtime,
                reverse=True,
            )
            for stale_preview in existing_previews[4:]:
                try:
                    os.remove(stale_preview)
                except OSError:
                    pass
        except Exception:
            _logger.debug("Ignored exception in %s", 'TwitTUIForm.open_html_in_browser', exc_info=True)
        with tempfile.NamedTemporaryFile(
            "w",
            dir=cache_dir,
            prefix="twittui_preview_",
            delete=False,
            suffix=".html",
            encoding="utf-8",
        ) as temp_file:
            temp_path = temp_file.name
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(temp_file.fileno(), 0o600)
                else:
                    os.chmod(temp_path, 0o600)
            except Exception:
                _logger.debug("Ignored exception in %s", 'TwitTUIForm.open_html_in_browser', exc_info=True)
            temp_file.write(html_content)
        file_uri = pathlib.Path(os.path.abspath(temp_path)).as_uri()
        self._open_browser_quietly(file_uri)

    def show_document_viewer(self, filename: str, doc_title: str) -> None:
        """Display a Markdown/APIB document using the Hybrid Resilient Pattern (WebView with Browser fallback)."""
        candidate_paths = [
            os.path.join(os.environ["SNAP"], filename) if os.environ.get("SNAP") else None,
            os.path.join(PROJECT_ROOT, filename),
            os.path.join(PACKAGE_ROOT, "resources", filename),
            os.path.join(os.getcwd(), filename),
            os.path.abspath(filename)
        ]
        candidate_paths = [p for p in candidate_paths if p]

        doc_path = None
        for path in candidate_paths:
            if os.path.isfile(path):
                doc_path = path
                break

        if not doc_path:
            err_msg = f"Could not locate {filename} file in the application directory."
            _logger.warning(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                self._show_dialog_threadsafe("error", "Documentation Not Found", err_msg, host_win=self.main_window)
            return

        try:
            with open(doc_path, "r", encoding="utf-8", errors="replace") as f:
                md_text = f.read()
        except Exception as e:
            err_msg = f"Failed to read {filename}: {e}"
            _logger.warning(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                self._show_dialog_threadsafe("error", "Read Error", err_msg, host_win=self.main_window)
            return

        styled_html = self.render_markdown_to_html(md_text, title=doc_title)

        # Primary Tier: In-App toga.WebView window
        try:
            help_window = toga.Window(title=doc_title, size=(900, 700))
            web_view = toga.WebView(style=Pack(flex=1))
            web_view.set_content(f"file://{doc_path}", styled_html)
            help_window.content = web_view
            help_window.show()
            return
        except Exception as webview_err:
            _logger.info(f"In-app WebView viewer unavailable ({webview_err}), falling back to system browser.")

        # Fallback Tier: System default web browser
        try:
            doc_slug = os.path.splitext(filename)[0].lower().replace('_', '-').replace('.', '-')
            self.open_html_in_browser(styled_html, page_name=f"{doc_slug}.html")
        except Exception as browser_err:
            err_msg = f"Unable to display documentation: {browser_err}"
            _logger.warning(f"Error: {err_msg}")
            if hasattr(self, 'main_window') and self.main_window:
                self._show_dialog_threadsafe("error", "Documentation Viewer Error", err_msg, host_win=self.main_window)

    def show_readme_viewer(self) -> None:
        """Display README.md using the Hybrid Resilient Pattern (WebView with Browser fallback)."""
        self.show_document_viewer("README.md", "TwitTUI Documentation")

    def show_apib_viewer(self) -> None:
        """Display twittv.apib using the Hybrid Resilient Pattern (WebView with Browser fallback)."""
        self.show_document_viewer("twittv.apib", "TWiT API Specification (twittv.apib)")

    def visit_homepage(self) -> None:
        """Open the TwitTUI project homepage URL in the default browser."""
        self.open_homepage_url()

    def open_homepage_url(self) -> None:
        """Open the TwitTUI project homepage URL in the default browser."""
        try:
            target_url = getattr(self, 'home_page', None) or TWITTUI_HOMEPAGE_URL
            self._open_browser_quietly(target_url)
        except Exception as e:
            err_msg = f"Failed to open project homepage URL: {e}"
            _logger.warning(f"Error: {err_msg}")
            self._show_dialog_threadsafe("error", "Browser Error", err_msg)

    def on_open_homepage(self, widget=None) -> None:
        """Handler for Help menu command to visit project homepage."""
        self.open_homepage_url()

    def on_open_readme(self, widget=None) -> None:
        """Handler for Help menu command to view README documentation."""
        self.show_readme_viewer()

    def on_open_apib(self, widget=None) -> None:
        """Handler for Help menu command to view twittv.apib API specification."""
        self.show_apib_viewer()

    def open_api_key_url(self) -> None:
        """Open the TWiT API documentation URL in the default browser."""
        try:
            self._open_browser_quietly(TWIT_API_KEY_URL)
        except Exception as e:
            err_msg = f"Failed to open API key registration URL: {e}"
            _logger.warning(f"Error: {err_msg}")
            self._show_dialog_threadsafe("error", "Browser Error", err_msg)

    def on_open_api_key_url(self, widget=None) -> None:
        """Handler for Help menu command to open the TWiT API key registration / documentation URL."""
        self.open_api_key_url()

    def open_api_docs_url(self) -> None:
        """Open the TWiT API documentation URL in the default browser."""
        self.open_api_key_url()

    def on_open_api_docs(self, widget=None) -> None:
        """Handler for Help menu command to open the TWiT API documentation URL."""
        self.open_api_docs_url()

    def render_rss_feed_to_html(self, xml_content: str | bytes) -> str:
        """Render RSS 2.0 XML podcast feed content into styled HTML using CSS/XSL styling."""
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode('utf-8', errors='replace')
        else:
            xml_bytes = xml_content

        # Load CSS file if available
        css_content = ""
        candidate_css_paths = [
            os.path.join(os.environ["SNAP"], "feed-style.css") if os.environ.get("SNAP") else None,
            os.path.join(PROJECT_ROOT, "feed-style.css"),
            os.path.join(PACKAGE_ROOT, "resources", "feed-style.css"),
            os.path.join(os.getcwd(), "feed-style.css"),
            os.path.abspath("feed-style.css")
        ]
        candidate_css_paths = [p for p in candidate_css_paths if p]
        for cpath in candidate_css_paths:
            if os.path.isfile(cpath):
                try:
                    with open(cpath, "r", encoding="utf-8") as f:
                        css_content = f.read()
                        break
                except Exception:
                    _logger.debug("Ignored exception in %s", 'TwitTUIForm.render_rss_feed_to_html', exc_info=True)

        # If lxml and feed-style.xsl are available, attempt XSLT transformation with hardened parser
        candidate_xsl_paths = [
            os.path.join(os.environ["SNAP"], "feed-style.xsl") if os.environ.get("SNAP") else None,
            os.path.join(PROJECT_ROOT, "feed-style.xsl"),
            os.path.join(PACKAGE_ROOT, "resources", "feed-style.xsl"),
            os.path.join(os.getcwd(), "feed-style.xsl"),
            os.path.abspath("feed-style.xsl")
        ]
        candidate_xsl_paths = [p for p in candidate_xsl_paths if p]
        xsl_path = None
        for xpath in candidate_xsl_paths:
            if os.path.isfile(xpath):
                xsl_path = xpath
                break

        if xsl_path:
            try:
                import lxml.etree as etree
                safe_parser = etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    dtd_validation=False,
                    load_dtd=False
                )
                with open(xsl_path, "rb") as xf:
                    xslt_doc = etree.XML(xf.read(), parser=safe_parser)
                transform = etree.XSLT(xslt_doc)
                src_doc = etree.fromstring(xml_bytes, parser=safe_parser)
                result_tree = transform(src_doc)
                html_out = str(result_tree)
                # Extract trusted local stylesheet and document title before sanitizing untrusted body HTML
                # so sanitize_html() does not strip the trusted <style> block or HTML document shell.
                title_match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html_out, flags=re.IGNORECASE | re.DOTALL)
                doc_title = html.unescape(title_match.group(1)).strip() if title_match else "Podcast RSS Feed"
                if css_content:
                    trusted_css = css_content
                else:
                    style_match = re.search(r"<style\b[^>]*>(.*?)</style\s*>", html_out, flags=re.IGNORECASE | re.DOTALL)
                    trusted_css = style_match.group(1) if style_match else ""
                trusted_css = re.sub(r"</style", r"<\/style", trusted_css, flags=re.IGNORECASE)
                body_match = re.search(r"<body\b[^>]*>(.*?)</body\s*>", html_out, flags=re.IGNORECASE | re.DOTALL)
                body_raw = body_match.group(1) if body_match else html_out
                safe_body = self.sanitize_html(body_raw)
                return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(doc_title)}</title>
  <style>
{trusted_css}
  </style>
</head>
<body>
{safe_body}
</body>
</html>"""
            except Exception as xslt_err:
                _logger.info(f"XSLT rendering fallback ({xslt_err}), using Python RSS renderer.")

        # ElementTree parser fallback
        try:
            root = safe_xml_fromstring(xml_bytes)
            channel = root.find('channel')
            if channel is None:
                channel = root.find('.//channel')

            ch_title = channel.findtext('title', 'Podcast RSS Feed') if channel is not None else 'Podcast RSS Feed'
            ch_desc = channel.findtext('description', '') if channel is not None else ''
            ch_link = channel.findtext('link', '') if channel is not None else ''
            ch_author = ''
            ch_lang = ''
            ch_image = ''

            if channel is not None:
                for elem in channel:
                    tag = elem.tag.lower()
                    if tag.endswith('author'):
                        ch_author = elem.text or ''
                    elif tag.endswith('language'):
                        ch_lang = elem.text or ''
                    elif tag.endswith('image'):
                        if elem.attrib.get('href'):
                            ch_image = elem.attrib['href']
                        else:
                            url_sub = elem.find('url')
                            if url_sub is not None and url_sub.text:
                                ch_image = url_sub.text.strip()

            items_html = []
            raw_items = channel.findall('.//item') if channel is not None else root.findall('.//item')
            for item in raw_items:
                title = item.findtext('title', 'Untitled Episode')
                link = item.findtext('link', '')
                pub_date = item.findtext('pubDate', '')

                desc = ''
                duration = ''
                episode_no = ''
                for elem in item:
                    tag = elem.tag.lower()
                    if tag.endswith('encoded'):
                        desc = elem.text or ''
                    elif tag.endswith('description') and not desc:
                        desc = elem.text or ''
                    elif tag.endswith('summary') and not desc:
                        desc = elem.text or ''
                    elif tag.endswith('duration'):
                        duration = elem.text or ''
                    elif tag.endswith('episode'):
                        episode_no = elem.text or ''

                enclosure = item.find('enclosure')
                enc_url = enclosure.attrib.get('url', '') if enclosure is not None else ''
                enc_type = enclosure.attrib.get('type', '') if enclosure is not None else ''
                enc_length = enclosure.attrib.get('length', '') if enclosure is not None else ''

                size_str = ''
                if enc_length:
                    try:
                        mb = round(int(enc_length) / 1048576)
                        if mb > 0:
                            size_str = f" • {mb} MB"
                    except Exception:
                        _logger.debug("Ignored exception in %s", 'TwitTUIForm.render_rss_feed_to_html', exc_info=True)

                title_html = f'<a href="{html.escape(link)}" target="_blank" rel="noopener noreferrer">{html.escape(title)}</a>' if (link and is_safe_http_url(link)) else html.escape(title)

                meta_parts = []
                if pub_date:
                    meta_parts.append(f'<span>Published: {html.escape(pub_date)}</span>')
                if duration:
                    meta_parts.append(f'<span>Duration: {html.escape(duration)}</span>')
                if episode_no:
                    meta_parts.append(f'<span>Episode #{html.escape(episode_no)}</span>')
                meta_html = f'<div class="episode-meta">{" ".join(meta_parts)}</div>' if meta_parts else ''

                media_html = ''
                if enc_url and is_safe_http_url(enc_url):
                    media_html = f"""<div class="media-controls">
  <a class="media-link" href="{html.escape(enc_url)}" target="_blank" rel="noopener noreferrer">&#9654; Stream / Download Media</a>
  <span class="media-type">{html.escape(enc_type)}{size_str}</span>
</div>"""

                safe_desc = self.sanitize_html(desc) if hasattr(self, 'sanitize_html') else desc

                card_html = f"""<div class="episode-card">
  <h2 class="episode-title">{title_html}</h2>
  {meta_html}
  <div class="episode-description">{safe_desc}</div>
  {media_html}
</div>"""
                items_html.append(card_html)

            image_html = f'<img class="channel-image" src="{html.escape(ch_image)}" alt="Podcast Cover Art" />' if (ch_image and is_safe_http_url(ch_image)) else ''
            author_html = f'<span>Author: {html.escape(ch_author)}</span>' if ch_author else ''
            lang_html = f'<span>Language: {html.escape(ch_lang)}</span>' if ch_lang else ''
            link_html = f'<a href="{html.escape(ch_link)}" target="_blank" rel="noopener noreferrer">Visit Website</a>' if (ch_link and is_safe_http_url(ch_link)) else ''

            return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(ch_title)} - RSS Feed</title>
  <style>
{css_content}
  </style>
</head>
<body>
  <div class="container">
    <div class="notice-banner">
      <strong>Podcast RSS Feed View:</strong> Formatted with <code>feed-style.css</code>. You can copy this URL into your podcast client.
    </div>
    <div class="header">
      {image_html}
      <div class="header-info">
        <h1>{html.escape(ch_title)}</h1>
        <p class="channel-desc">{html.escape(ch_desc)}</p>
        <div class="header-meta">
          {link_html}
          {author_html}
          {lang_html}
        </div>
      </div>
    </div>
    <div class="episodes-heading">
      Episodes ({len(items_html)})
    </div>
    <div class="episodes-list">
      {"".join(items_html)}
    </div>
  </div>
</body>
</html>"""
        except Exception as parse_err:
            _logger.warning(f"Error parsing RSS XML: {parse_err}")
            return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>RSS Feed Error</title><style>{css_content}</style></head>
<body><div class="container"><h1>Unable to parse RSS feed</h1><p>{html.escape(str(parse_err))}</p></div></body></html>"""

    def open_club_twit_url(self, target_url: str | None = None) -> None:
        """Fetch and render the Club TWiT RSS feed with CSS styling and open in default web browser."""
        if not target_url:
            target_url = self.get_full_club_twit_url()
        try:
            resp = requests.get(target_url, headers={'User-Agent': 'Mozilla/5.0 (compatible; TwitTUI/1.0)'}, timeout=15)
            if resp.status_code == 200 and resp.content:
                styled_html = self.render_rss_feed_to_html(resp.content)
                self.open_html_in_browser(styled_html, page_name="club-twit-feed.html")
                return
            else:
                _logger.warning(f"Warning: HTTP {resp.status_code} while fetching Club TWiT feed, opening direct URL.")
        except Exception as e:
            _logger.warning(
                "Error fetching Club TWiT RSS feed at %s (%s), opening direct URL.",
                safe_url_for_log(target_url), type(e).__name__,
            )

        try:
            self._open_browser_quietly(target_url)
        except Exception as e:
            err_msg = f"Failed to open Club TWiT URL: {e}"
            _logger.warning("Could not open Club TWiT URL in browser (%s)", type(e).__name__)
            self._show_dialog_threadsafe("error", "Browser Error", err_msg)

    def on_show_club_url_press(self, widget=None) -> None:
        """Handler for Show button press next to the Club TWiT URL field."""
        target_url = self.get_full_club_twit_url()
        threading.Thread(target=self.open_club_twit_url, args=(target_url,), daemon=True).start()

    def open_destination_folder(self, folder_path: str = None) -> bool:
        """Open the configured or specified download destination folder in the system file manager."""
        if not folder_path:
            folder_path = self.get_destination_folder()

        target_dir = os.path.abspath(os.path.expanduser(folder_path or '.'))
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            _logger.warning(f"Could not create destination directory '{target_dir}': {e}")

        try:
            if sys.platform == 'win32':
                os.startfile(target_dir)
                return True
            elif sys.platform == 'darwin':
                if compat_attr('_is_textual_tui_running', _is_textual_tui_running)(self):
                    subprocess.Popen(
                        ['open', target_dir],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                else:
                    subprocess.Popen(['open', target_dir])
                return True
            else:
                # Linux and other Unix/BSD systems
                if compat_attr('_is_textual_tui_running', _is_textual_tui_running)(self):
                    subprocess.Popen(
                        ['xdg-open', target_dir],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                else:
                    subprocess.Popen(['xdg-open', target_dir])
                return True
        except Exception as e:
            _logger.warning(f"Failed to launch file manager for '{target_dir}': {e}")
            try:
                file_uri = pathlib.Path(target_dir).as_uri()
                self._open_browser_quietly(file_uri)
                return True
            except Exception as e2:
                _logger.warning(f"Fallback to browser for folder URI failed: {e2}")
                self._show_dialog_threadsafe(
                    "error",
                    "File Manager Error",
                    f"Could not open download folder:\n{target_dir}\n\nError: {e}",
                )
                return False

    def on_open_destination_press(self, widget=None) -> None:
        """Handler for Open button press next to Download Destination."""
        folder_path = self.get_destination_folder()
        threading.Thread(target=self.open_destination_folder, args=(folder_path,), daemon=True).start()

    def open_url_in_browser(self, url: str) -> None:
        """Open the specified URL in the system default web browser."""
        if not url:
            return
        target_url = str(url).strip()
        if not target_url.startswith('http://') and not target_url.startswith('https://'):
            target_url = f"https://{target_url}"
        try:
            self._open_browser_quietly(target_url)
        except Exception as e:
            err_msg = f"Failed to open URL in browser: {e}"
            _logger.warning(
                "Could not open URL in browser %s (%s)",
                safe_url_for_log(target_url), type(e).__name__,
            )
            self._show_dialog_threadsafe("error", "Browser Error", err_msg)
