"""Unit and integration tests verifying cybersecurity hardening implementations."""

import os
import tempfile
import unittest
import urllib.request
import urllib.error
import threading
import http.server
from twittui_form import (
    build_stream_args,
    write_restricted_file,
    generate_local_server_token,
    safe_xml_fromstring,
    TwitTUIForm,
    _LocalHTMLServer,
    _LocalHTMLHandler,
)


class TestTwitTUISecurity(unittest.TestCase):
    """Unit tests verifying security remediations across TwitTUI."""

    def test_build_stream_args_prevents_shell_injection(self) -> None:
        """Ensure shell metacharacters remain a single literal argument."""
        malicious_url = "https://twit.tv/ep.mp4;touch_pwned;.mp4"
        args = build_stream_args("vlc %f", malicious_url)
        self.assertEqual(args, ["vlc", malicious_url])

    def test_build_stream_args_appends_when_no_placeholder(self) -> None:
        """Ensure URL is appended safely when no placeholder is present."""
        url = "https://twit.tv/stream.mp4"
        args = build_stream_args("mpv --fs", url)
        self.assertEqual(args, ["mpv", "--fs", url])

    def test_build_stream_args_replaces_all_placeholder_variants(self) -> None:
        """Ensure various placeholder styles are replaced correctly."""
        url = "https://twit.tv/stream.mp4"
        for ph in ["%f", "%s", "%u", "{url}", "{URL}", "{stream_url}", "{media_url}", "{file}", "{}"]:
            template = f"player --play {ph}"
            args = build_stream_args(template, url)
            self.assertEqual(args, ["player", "--play", url])

    def test_build_stream_args_rejects_invalid_scheme(self) -> None:
        """Reject non-media schemes such as file:// or javascript:."""
        with self.assertRaises(ValueError):
            build_stream_args("vlc %f", "file:///etc/passwd")

    def test_build_stream_args_rejects_whitespace_in_url(self) -> None:
        """Reject URLs containing spaces or newlines."""
        with self.assertRaises(ValueError):
            build_stream_args("vlc %f", "https://twit.tv/ep.mp4 --flag")

    def test_write_restricted_file_sets_0600_mode(self) -> None:
        """Verify sensitive files are created with 0o600 permissions."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = os.path.join(tmp_dir, ".env")
            write_restricted_file(target, "TWITAPI_APPLICATIONKEYS=secret\n")
            mode = os.stat(target).st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_get_app_cache_dir_sets_0700_mode(self) -> None:
        """Verify application cache directory is restricted to owner."""
        form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")
        cache_dir = form.get_app_cache_dir()
        if os.path.exists(cache_dir):
            mode = os.stat(cache_dir).st_mode & 0o777
            self.assertEqual(mode, 0o700)

    def test_local_server_token_enforcement(self) -> None:
        """Verify that local HTML server rejects requests without session token."""
        server = _LocalHTMLServer(('127.0.0.1', 0), _LocalHTMLHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]

        try:
            with server.lock:
                server.pages['test.html'] = b"<html><body>Test Page</body></html>"

            # 1. Request without token -> Should return 403 Forbidden
            unauth_url = f"http://127.0.0.1:{port}/test.html"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(unauth_url)
            self.assertEqual(ctx.exception.code, 403)

            # 2. Request with invalid token -> Should return 403 Forbidden
            bad_token_url = f"http://127.0.0.1:{port}/invalid_token/test.html"
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(bad_token_url)
            self.assertEqual(ctx.exception.code, 403)

            # 3. Request with valid token -> Should return 200 OK
            valid_url = f"http://127.0.0.1:{port}/{server.secret_token}/test.html"
            resp = urllib.request.urlopen(valid_url)
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"<html><body>Test Page</body></html>")
        finally:
            server.shutdown()
            server.server_close()

    def test_sanitize_html_removes_dangerous_tags_and_handlers(self) -> None:
        """Verify script tags, event handlers, and iframes are stripped."""
        form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")
        dirty = '<p>Hello <script>alert(1)</script><img src="x" onerror="alert(2)"> World</p>'
        clean = form.sanitize_html(dirty)
        self.assertNotIn('<script>', clean)
        self.assertNotIn('alert(1)', clean)
        self.assertNotIn('onerror', clean)

    def test_sanitize_html_neutralizes_javascript_schemes(self) -> None:
        """Verify javascript: schemes in href and src attributes are neutralized."""
        form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")
        dirty = '<a href="javascript:alert(1)">Click</a><img src="javascript:alert(2)">'
        clean = form.sanitize_html(dirty)
        self.assertNotIn('javascript:', clean)
        self.assertNotIn('alert(1)', clean)

    def test_sanitize_html_handles_nested_tags_bypass(self) -> None:
        """Verify multi-pass tag stripping handles nested dangerous tags."""
        form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")
        dirty = '<scr<script>ipt>alert(1)</script>'
        clean = form.sanitize_html(dirty)
        self.assertNotIn('<script>', clean)
        self.assertNotIn('alert(1)', clean)

    def test_safe_xml_fromstring(self) -> None:
        """Verify safe XML parsing of standard RSS feeds."""
        rss_xml = b"""<?xml version="1.0"?>
        <rss version="2.0">
            <channel>
                <title>Test Show</title>
                <item>
                    <title>Episode 1</title>
                </item>
            </channel>
        </rss>"""
        root = safe_xml_fromstring(rss_xml)
        self.assertEqual(root.find('.//channel/title').text, 'Test Show')
        self.assertEqual(root.find('.//item/title').text, 'Episode 1')

    def test_get_full_club_twit_url_enforces_https(self) -> None:
        """Verify Memberful URLs upgrade http to https."""
        form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")
        import toga
        form.url_input = toga.PasswordInput(value="http://twit.memberfulcontent.com/rss/9041?auth=test")
        url = form.get_full_club_twit_url()
        self.assertTrue(url.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
