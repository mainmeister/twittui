"""Unit tests for opening download destination folder in the default file manager."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import tempfile

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from twittui_form import TwitTUIForm


class TestOpenDestinationFolder(unittest.TestCase):
    """Test destination directory opening across platforms."""

    def setUp(self) -> None:
        self.form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")

    def test_open_destination_folder_creates_directory_if_missing(self) -> None:
        """Verify that open_destination_folder creates the folder if it does not exist."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_folder = os.path.join(tmp_dir, "nested_downloads", "twit")
            self.assertFalse(os.path.exists(test_folder))

            with patch('subprocess.Popen') as mock_popen:
                success = self.form.open_destination_folder(test_folder)
                self.assertTrue(success)
                self.assertTrue(os.path.exists(test_folder))
                self.assertTrue(os.path.isdir(test_folder))

    def test_open_destination_folder_linux_xdg_open(self) -> None:
        """Verify on Linux / Unix xdg-open is invoked."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch('sys.platform', 'linux'):
                with patch('subprocess.Popen') as mock_popen:
                    success = self.form.open_destination_folder(tmp_dir)
                    self.assertTrue(success)
                    mock_popen.assert_called_once_with(['xdg-open', os.path.abspath(tmp_dir)])

    def test_open_destination_folder_macos_open(self) -> None:
        """Verify on macOS open command is invoked."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch('sys.platform', 'darwin'):
                with patch('subprocess.Popen') as mock_popen:
                    success = self.form.open_destination_folder(tmp_dir)
                    self.assertTrue(success)
                    mock_popen.assert_called_once_with(['open', os.path.abspath(tmp_dir)])

    def test_open_destination_folder_windows_startfile(self) -> None:
        """Verify on Windows os.startfile is invoked."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch('sys.platform', 'win32'):
                with patch('os.startfile', create=True) as mock_startfile:
                    success = self.form.open_destination_folder(tmp_dir)
                    self.assertTrue(success)
                    mock_startfile.assert_called_once_with(os.path.abspath(tmp_dir))

    def test_open_destination_folder_fallback_to_webbrowser(self) -> None:
        """Verify fallback to webbrowser.open with file URI if subprocess fails."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch('sys.platform', 'linux'):
                with patch('subprocess.Popen', side_effect=OSError("Command not found")):
                    with patch('webbrowser.open') as mock_browser:
                        success = self.form.open_destination_folder(tmp_dir)
                        self.assertTrue(success)
                        mock_browser.assert_called_once()
                        called_uri = mock_browser.call_args[0][0]
                        self.assertTrue(called_uri.startswith('file://'))

    def test_on_open_destination_press_triggers_thread(self) -> None:
        """Verify on_open_destination_press starts a background thread."""
        with patch.object(self.form, 'open_destination_folder') as mock_open:
            with patch('threading.Thread') as mock_thread_cls:
                mock_thread = MagicMock()
                mock_thread_cls.return_value = mock_thread
                self.form.on_open_destination_press()
                mock_thread_cls.assert_called_once_with(target=self.form.open_destination_folder, daemon=True)
                mock_thread.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
