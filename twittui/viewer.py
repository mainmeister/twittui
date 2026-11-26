"""HTML sanitization and authenticated loopback viewer server for TwitTUI."""

from __future__ import annotations

import html
import html.parser
import http.server
import re
import secrets
import threading
import urllib.parse


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
