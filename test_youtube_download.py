"""Unit tests for YouTube stream downloading and fallback handling."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import tempfile

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from twittui_form import TwitTUIForm


class TestYouTubeDownload(unittest.TestCase):
    """Test YouTube URL detection and downloader routing."""

    def setUp(self) -> None:
        self.form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")

    def test_is_youtube_url(self) -> None:
        """Verify accurate detection of various YouTube URL formats."""
        self.assertTrue(self.form.is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(self.form.is_youtube_url("http://youtube.com/watch?v=12345"))
        self.assertTrue(self.form.is_youtube_url("https://youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(self.form.is_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ"))

        self.assertFalse(self.form.is_youtube_url("https://twit.tv/episodes/twit-1000"))
        self.assertFalse(self.form.is_youtube_url("https://media.twit.tv/twit1000.mp4"))
        self.assertFalse(self.form.is_youtube_url(""))
        self.assertFalse(self.form.is_youtube_url(None))

    def test_download_episode_file_routes_youtube_to_specialized_downloader(self) -> None:
        """Ensure YouTube URLs are dispatched to download_youtube_video instead of raw HTTP GET."""
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        dest_path = "/tmp/test_twit_yt.mp4"

        with patch.object(self.form, 'download_youtube_video', return_value=True) as mock_yt_dl:
            with patch('requests.get') as mock_requests_get:
                success = self.form.download_episode_file(yt_url, dest_path)
                self.assertTrue(success)
                mock_yt_dl.assert_called_once()
                mock_requests_get.assert_not_called()

    def test_download_youtube_video_missing_downloader_shows_error(self) -> None:
        """When yt-dlp is not installed and module unavailable, report clear error and return False."""
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        with tempfile.TemporaryDirectory() as tmp_dir:
            dest_path = os.path.join(tmp_dir, "test.mp4")
            with patch('shutil.which', return_value=None):
                with patch.dict('sys.modules', {'yt_dlp': None}):
                    success = self.form.download_youtube_video(yt_url, dest_path)
                    self.assertFalse(success)
                    self.assertFalse(os.path.exists(dest_path))

    def test_download_youtube_video_invokes_ytdlp_process(self) -> None:
        """Verify yt-dlp command structure and file finalization."""
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        with tempfile.TemporaryDirectory() as tmp_dir:
            dest_path = os.path.join(tmp_dir, "test.mp4")
            temp_part = dest_path + '.part'

            def mock_popen(cmd, **kwargs):
                # Simulate yt-dlp creating temp part file
                with open(temp_part, 'wb') as f:
                    f.write(b'video_bytes_test')
                mock_proc = MagicMock()
                lines = [
                    "[download]  50.0% of 10.00MiB\n",
                    "[download] 100.0% of 10.00MiB\n",
                    ""
                ]
                line_iter = iter(lines)
                mock_proc.stdout.readline.side_effect = lambda: next(line_iter, "")
                mock_proc.poll.return_value = 0
                mock_proc.wait.return_value = 0
                return mock_proc

            progress_updates = []

            with patch('shutil.which', return_value='/usr/bin/yt-dlp'):
                with patch('subprocess.Popen', side_effect=mock_popen) as mock_p:
                    success = self.form.download_youtube_video(
                        yt_url,
                        dest_path,
                        progress_callback=lambda cur, tot: progress_updates.append((cur, tot))
                    )
                    self.assertTrue(success)
                    self.assertTrue(os.path.exists(dest_path))
                    self.assertFalse(os.path.exists(temp_part))
                    self.assertTrue(any(cur == 50.0 for cur, tot in progress_updates))

    def test_is_existing_file_identical_for_youtube(self) -> None:
        """Verify identical check recognizes substantial existing YouTube downloads."""
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Write 2MB of binary data (non-HTML) to simulate a downloaded video file
            f.write(b'\x00\x00\x00\x1cftypisom' + (b'\x00' * (2 * 1024 * 1024)))
            temp_name = f.name

        try:
            self.assertTrue(self.form.is_existing_file_identical(temp_name, yt_url))
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)

    def test_is_valid_media_file(self) -> None:
        """Verify HTML files are detected as invalid and binary media files as valid."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"<!DOCTYPE html><html><body><h1>Error</h1></body></html>" + (b" " * 1000))
            html_file = f.name

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42" + (b"\x00" * 1000))
            binary_file = f.name

        try:
            self.assertFalse(self.form.is_valid_media_file(html_file))
            self.assertTrue(self.form.is_valid_media_file(binary_file))
        finally:
            if os.path.exists(html_file):
                os.remove(html_file)
            if os.path.exists(binary_file):
                os.remove(binary_file)

    def test_is_existing_file_identical_rejects_corrupted_html_file(self) -> None:
        """Ensure an existing .mp4 file that contains HTML is rejected and not marked identical."""
        url = "https://twit.tv/shows/twit/episodes/1000"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            f.write(b"<!DOCTYPE html><html><head><title>Twit Episode</title></head></html>")
            temp_name = f.name

        try:
            self.assertFalse(self.form.is_existing_file_identical(temp_name, url))
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)

    def test_download_episode_file_blocks_html_content_and_cleans_up(self) -> None:
        """Ensure requests returning HTML without media links do not create corrupt .mp4 files."""
        url = "https://twit.tv/invalid-episode"
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest_path = os.path.join(tmp_dir, "episode.mp4")

            mock_resp = MagicMock()
            mock_resp.headers = {'content-type': 'text/html; charset=utf-8'}
            mock_resp.text = "<html><body>Page without media links</body></html>"
            mock_resp.url = url
            mock_resp.__enter__.return_value = mock_resp

            with patch('requests.get', return_value=mock_resp):
                success = self.form.download_episode_file(url, dest_path)
                self.assertFalse(success)
                self.assertFalse(os.path.exists(dest_path))

    def test_get_available_resolutions_expands_youtube_id(self) -> None:
        """Verify video_youtube ID or slug is converted into a standard watch URL."""
        target = MagicMock()
        target.episode_data = {
            'video_youtube': {'id': 'dQw4w9WgXcQ'},
            'title': 'Test Show 100'
        }
        res = self.form.get_available_resolutions(target)
        yt_res = next((r for r in res if r['id'] == 'video_youtube'), None)
        self.assertIsNotNone(yt_res)
        self.assertEqual(yt_res['url'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')


if __name__ == "__main__":
    unittest.main()
