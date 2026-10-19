"""Unit tests for Show Folders download organization feature."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from twittui_form import TwitTUIForm


class MockTarget:
    """Mock episode object representing a row in the table."""

    def __init__(self, data: dict) -> None:
        self.episode = data.get('number', '100')
        self.title = data.get('title', 'Test Episode')
        self.episode_data = data


class TestShowFolders(unittest.TestCase):
    """Test suite verifying Show Folders checkbox and destination path calculation."""

    def setUp(self) -> None:
        self.form = TwitTUIForm('TestApp', 'org.twit.test')
        self.form.show_combo = MagicMock()
        self.form.show_combo.value = 'Security Now'
        self.form.dest_input = MagicMock()
        self.form.dest_input.value = '/tmp/downloads'
        self.form.show_folders_checkbox = MagicMock()
        self.form.show_folders_checkbox.value = False

    def test_is_show_folders_enabled_from_checkbox(self) -> None:
        """Verify is_show_folders_enabled reflects checkbox value."""
        self.form.show_folders_checkbox.value = True
        self.assertTrue(self.form.is_show_folders_enabled())

        self.form.show_folders_checkbox.value = False
        self.assertFalse(self.form.is_show_folders_enabled())

    def test_is_show_folders_enabled_from_env_var(self) -> None:
        """Verify is_show_folders_enabled falls back to environment variable when checkbox is None."""
        self.form.show_folders_checkbox = None
        with patch.dict(os.environ, {'TWITCLUBSHOWFOLDERS': '1'}):
            self.assertTrue(self.form.is_show_folders_enabled())

        with patch.dict(os.environ, {'TWITCLUBSHOWFOLDERS': '0'}):
            self.assertFalse(self.form.is_show_folders_enabled())

    def test_on_show_folders_change_persists_env(self) -> None:
        """Verify toggling checkbox updates environment and saves setting."""
        saved_settings = {}
        self.form.save_env_setting = lambda k, v: saved_settings.update({k: v})

        self.form.show_folders_checkbox.value = True
        self.form.on_show_folders_change()
        self.assertEqual(os.environ.get('TWITCLUBSHOWFOLDERS'), '1')
        self.assertEqual(saved_settings.get('TWITCLUBSHOWFOLDERS'), '1')

        self.form.show_folders_checkbox.value = False
        self.form.on_show_folders_change()
        self.assertEqual(os.environ.get('TWITCLUBSHOWFOLDERS'), '0')
        self.assertEqual(saved_settings.get('TWITCLUBSHOWFOLDERS'), '0')

    def test_get_show_folder_name_from_episode_data(self) -> None:
        """Verify show folder name is extracted from episode data."""
        target = MockTarget({
            'show_name': 'This Week in Tech',
            'title': 'TWiT 1000',
            'number': '1000'
        })
        self.assertEqual(self.form.get_show_folder_name(target), 'This Week in Tech')

    def test_get_show_folder_name_from_show_combo(self) -> None:
        """Verify show folder name falls back to selected combo box show."""
        target = MockTarget({
            'title': 'Episode 50',
            'number': '50'
        })
        self.form.show_combo.value = 'MacBreak Weekly'
        self.assertEqual(self.form.get_show_folder_name(target), 'MacBreak Weekly')

    def test_get_show_folder_name_sanitizes_illegal_characters(self) -> None:
        """Verify illegal filesystem characters are removed from show folder names."""
        target = MockTarget({
            'show_name': 'TWiT: Live / Special <Show> & *Events*?',
            'title': 'Special Event'
        })
        folder_name = self.form.get_show_folder_name(target)
        self.assertNotIn(':', folder_name)
        self.assertNotIn('/', folder_name)
        self.assertNotIn('<', folder_name)
        self.assertNotIn('>', folder_name)
        self.assertNotIn('*', folder_name)
        self.assertNotIn('?', folder_name)

    def test_get_target_destination_folder_when_disabled(self) -> None:
        """When Show Folders is disabled, destination is the base folder."""
        self.form.show_folders_checkbox.value = False
        target = MockTarget({'show_name': 'Security Now'})
        self.assertEqual(self.form.get_target_destination_folder(target), '/tmp/downloads')

    def test_get_target_destination_folder_when_enabled(self) -> None:
        """When Show Folders is enabled, destination includes the show subfolder."""
        self.form.show_folders_checkbox.value = True
        target = MockTarget({'show_name': 'Security Now'})
        expected = os.path.join('/tmp/downloads', 'Security Now')
        self.assertEqual(self.form.get_target_destination_folder(target), expected)

    def test_download_episodes_batch_saves_into_show_folder(self) -> None:
        """Verify download_episodes_batch saves into show folder and creates it."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.form.dest_input.value = tmp_dir
            self.form.show_folders_checkbox.value = True

            target = MockTarget({
                'show_name': 'Ask The Tech Guys',
                'title': 'Episode 2000',
                'number': '2000',
                'media_url': 'https://twit.tv/ep2000.mp4'
            })
            target.selected_media_url = 'https://twit.tv/ep2000.mp4'

            downloaded_paths = []

            def mock_download(url, dest_path, block_size, progress_callback=None, expected_size=None):
                downloaded_paths.append(dest_path)
                with open(dest_path, 'wb') as f:
                    f.write(b"data")
                return True

            self.form.download_episode_file = mock_download
            self.form.determine_download_filename = lambda t, u: "Ask The Tech Guys 2000.mp4"

            self.form.download_episodes_batch([target])

            self.assertEqual(len(downloaded_paths), 1)
            expected_folder = os.path.join(tmp_dir, 'Ask The Tech Guys')
            expected_file = os.path.join(expected_folder, 'Ask The Tech Guys 2000.mp4')
            self.assertEqual(downloaded_paths[0], expected_file)
            self.assertTrue(os.path.isdir(expected_folder))
            self.assertTrue(os.path.isfile(expected_file))


if __name__ == '__main__':
    unittest.main()
