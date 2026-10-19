"""Unit tests verifying multiple resolution detection and selection for TwitTUI."""

import os
import unittest
import asyncio

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from twittui_form import TwitTUIForm


class TestTwitTUIResolutions(unittest.TestCase):
    """Test resolution extraction and selection behavior."""

    def setUp(self) -> None:
        self.form = TwitTUIForm(formal_name="TwitTUI", app_id="org.twit.test")

    def test_get_available_resolutions_from_api_dict(self) -> None:
        """Verify extraction of multiple resolution options from TWiT API format fields."""
        ep_data = {
            'id': '12345',
            'number': '1000',
            'title': 'The Big Milestone',
            'video_hd': {
                'mediaUrl': 'https://twit.tv/ep1000_1080p.mp4',
                'fileSize': 1500000000,
            },
            'video_large': {
                'mediaUrl': 'https://twit.tv/ep1000_540p.mp4',
                'fileSize': 750000000,
            },
            'video_small': {
                'mediaUrl': 'https://twit.tv/ep1000_360p.mp4',
                'fileSize': 350000000,
            },
            'video_audio': {
                'mediaUrl': 'https://twit.tv/ep1000_audio.mp3',
                'fileSize': 70000000,
            },
        }

        resolutions = self.form.get_available_resolutions(ep_data)
        self.assertEqual(len(resolutions), 4)

        res_ids = [r['id'] for r in resolutions]
        self.assertIn('video_hd', res_ids)
        self.assertIn('video_large', res_ids)
        self.assertIn('video_small', res_ids)
        self.assertIn('video_audio', res_ids)

        hd_res = next(r for r in resolutions if r['id'] == 'video_hd')
        self.assertEqual(hd_res['url'], 'https://twit.tv/ep1000_1080p.mp4')
        self.assertIn('1.4', hd_res['label'])  # ~1.4 GB / 1.5 GB formatted

        audio_res = next(r for r in resolutions if r['id'] == 'video_audio')
        self.assertEqual(audio_res['url'], 'https://twit.tv/ep1000_audio.mp3')
        self.assertEqual(audio_res['type'], 'audio')

    def test_get_available_resolutions_from_files_list(self) -> None:
        """Verify extraction when episode contains a files array."""
        ep_data = {
            'title': 'Files List Episode',
            'files': [
                {
                    'format': 'hd',
                    'mediaUrl': 'https://twit.tv/files_hd.mp4',
                    'fileSize': 1200000000,
                },
                {
                    'format': 'sdl',
                    'mediaUrl': 'https://twit.tv/files_sdl.mp4',
                    'fileSize': 600000000,
                },
                {
                    'format': 'audio',
                    'mediaUrl': 'https://twit.tv/files_audio.mp3',
                    'fileSize': 50000000,
                },
            ]
        }

        resolutions = self.form.get_available_resolutions(ep_data)
        self.assertEqual(len(resolutions), 3)
        urls = [r['url'] for r in resolutions]
        self.assertIn('https://twit.tv/files_hd.mp4', urls)
        self.assertIn('https://twit.tv/files_sdl.mp4', urls)
        self.assertIn('https://twit.tv/files_audio.mp3', urls)

    def test_get_available_resolutions_deduplicates_same_urls(self) -> None:
        """Verify duplicate URLs across fields are deduplicated."""
        ep_data = {
            'video_hd': {'mediaUrl': 'https://twit.tv/same_url.mp4'},
            'video_large': {'mediaUrl': 'https://twit.tv/same_url.mp4'},
            'media_url': 'https://twit.tv/same_url.mp4',
        }
        resolutions = self.form.get_available_resolutions(ep_data)
        self.assertEqual(len(resolutions), 1)

    def test_single_resolution_returns_single_entry(self) -> None:
        """Verify single format episode returns exactly 1 resolution."""
        ep_data = {
            'media_url': 'https://twit.tv/single.mp4'
        }
        resolutions = self.form.get_available_resolutions(ep_data)
        self.assertEqual(len(resolutions), 1)
        self.assertEqual(resolutions[0]['url'], 'https://twit.tv/single.mp4')

    def test_prompt_resolution_choice_single_resolution_auto_resolves(self) -> None:
        """Verify prompt_resolution_choice directly returns single resolution without prompt."""
        single_res = [{'id': 'video_hd', 'name': 'HD Video', 'url': 'https://twit.tv/hd.mp4'}]
        result = asyncio.run(self.form.prompt_resolution_choice("Title", "Message", single_res))
        self.assertEqual(result, single_res[0])

    def test_prompt_resolution_choice_empty_returns_none(self) -> None:
        """Verify empty resolutions list returns None."""
        result = asyncio.run(self.form.prompt_resolution_choice("Title", "Message", []))
        self.assertIsNone(result)

    def test_batch_download_honors_preferred_resolution(self) -> None:
        """Verify batch download uses preferred resolution when available."""
        ep_data = {
            'id': '101',
            'number': '101',
            'title': 'Test Episode',
            'video_hd': {'mediaUrl': 'https://twit.tv/ep101_hd.mp4', 'fileSize': 1000000},
            'video_small': {'mediaUrl': 'https://twit.tv/ep101_small.mp4', 'fileSize': 300000},
        }

        class MockTarget:
            def __init__(self, data):
                self.title = data['title']
                self.episode = data['number']
                self.episode_data = data

        target = MockTarget(ep_data)
        downloaded_urls = []

        def mock_download_file(url, dest_path, block_size, progress_callback=None, expected_size=None):
            downloaded_urls.append(url)
            return True

        self.form.download_episode_file = mock_download_file
        self.form.get_destination_folder = lambda: "/tmp"
        self.form.determine_download_filename = lambda t, u: "test.mp4"

        self.form.download_episodes_batch([target], preferred_resolution='video_small')
        self.assertEqual(downloaded_urls, ['https://twit.tv/ep101_small.mp4'])

    def test_batch_download_honors_selected_media_url_override(self) -> None:
        """Verify target.selected_media_url overrides default resolution in batch worker."""
        ep_data = {
            'id': '102',
            'number': '102',
            'title': 'Test Override',
            'video_hd': {'mediaUrl': 'https://twit.tv/ep102_hd.mp4'},
            'video_small': {'mediaUrl': 'https://twit.tv/ep102_small.mp4'},
        }

        class MockTarget:
            def __init__(self, data):
                self.title = data['title']
                self.episode = data['number']
                self.episode_data = data
                self.selected_media_url = 'https://twit.tv/ep102_custom.mp4'

        target = MockTarget(ep_data)
        downloaded_urls = []

        self.form.download_episode_file = lambda u, d, b, progress_callback=None, expected_size=None: downloaded_urls.append(u) or True
        self.form.get_destination_folder = lambda: "/tmp"
        self.form.determine_download_filename = lambda t, u: "test.mp4"

        self.form.download_episodes_batch([target])
        self.assertEqual(downloaded_urls, ['https://twit.tv/ep102_custom.mp4'])


if __name__ == "__main__":
    unittest.main()
