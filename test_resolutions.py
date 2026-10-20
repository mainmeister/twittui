"""Unit tests verifying multiple resolution detection and selection for TwitTUI."""

import os
import unittest
import unittest.mock
import asyncio

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from twittui_form import TwitTUIForm


class TestTwitTUIResolutions(unittest.TestCase):
    """Test resolution extraction and selection behavior."""

    def setUp(self) -> None:
        os.environ['TWITAUDIOONLY'] = '0'
        os.environ['TWITCLUBSHOWFOLDERS'] = '0'
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

    def test_get_available_resolutions_when_audio_only_enabled(self) -> None:
        """Verify only audio options are returned when audio_only is True or enabled."""
        ep_data = {
            'id': '12345',
            'video_hd': {
                'mediaUrl': 'https://twit.tv/ep1000_1080p.mp4',
                'fileSize': 1500000000,
            },
            'video_large': {
                'mediaUrl': 'https://twit.tv/ep1000_540p.mp4',
                'fileSize': 750000000,
            },
            'video_audio': {
                'mediaUrl': 'https://twit.tv/ep1000_audio.mp3',
                'fileSize': 70000000,
            },
        }

        resolutions = self.form.get_available_resolutions(ep_data, audio_only=True)
        self.assertEqual(len(resolutions), 1)
        self.assertEqual(resolutions[0]['id'], 'video_audio')
        self.assertEqual(resolutions[0]['url'], 'https://twit.tv/ep1000_audio.mp3')
        self.assertEqual(resolutions[0]['type'], 'audio')

    def test_get_available_resolutions_multiple_audio_options_when_audio_only(self) -> None:
        """Verify multiple audio formats are returned when episode has multiple audio sources."""
        ep_data = {
            'video_hd': {'mediaUrl': 'https://twit.tv/ep1000_1080p.mp4'},
            'files': [
                {'format': 'audio', 'label': 'MP3 Audio (High)', 'mediaUrl': 'https://twit.tv/audio_hq.mp3', 'fileSize': 80000000},
                {'format': 'audio', 'label': 'M4A Audio (AAC)', 'mediaUrl': 'https://twit.tv/audio.m4a', 'fileSize': 40000000},
            ]
        }

        self.form.is_audio_only = lambda: True
        resolutions = self.form.get_available_resolutions(ep_data)
        self.assertEqual(len(resolutions), 2)
        urls = [r['url'] for r in resolutions]
        self.assertIn('https://twit.tv/audio_hq.mp3', urls)
        self.assertIn('https://twit.tv/audio.m4a', urls)
        self.assertTrue(all(r['type'] == 'audio' for r in resolutions))

    def test_on_stream_press_audio_only_with_multiple_audio_prompts_audio_options(self) -> None:
        """Verify on_stream_press prompts user with only audio options when audio only is enabled."""
        ep_data = {
            'title': 'Test Episode',
            'video_hd': {'mediaUrl': 'https://twit.tv/video_hd.mp4'},
            'files': [
                {'format': 'audio', 'label': 'MP3 Audio', 'mediaUrl': 'https://twit.tv/stream_audio.mp3'},
                {'format': 'audio', 'label': 'AAC Audio', 'mediaUrl': 'https://twit.tv/stream_audio.m4a'},
            ]
        }

        class MockTarget:
            def __init__(self, data):
                self.title = data['title']
                self.episode_data = data

        self.form.is_audio_only = lambda: True
        self.form.episodes_list = type('MockList', (), {'selection': [MockTarget(ep_data)]})()

        prompted_resolutions = []

        async def mock_prompt(title, message, resolutions):
            prompted_resolutions.extend(resolutions)
            return resolutions[1]  # Choose AAC Audio

        self.form.prompt_resolution_choice = mock_prompt

        launched_streams = []
        with unittest.mock.patch('twittui_form.launch_stream_safe', side_effect=lambda template, url: launched_streams.append(url)):
            asyncio.run(self.form.on_stream_press())

        self.assertEqual(len(prompted_resolutions), 2)
        self.assertTrue(all(r['type'] == 'audio' for r in prompted_resolutions))
        self.assertEqual(launched_streams, ['https://twit.tv/stream_audio.m4a'])

    def test_on_stream_press_audio_only_with_single_audio_option_plays_without_prompt(self) -> None:
        """Verify on_stream_press directly streams audio without prompt when only 1 audio option is available."""
        ep_data = {
            'title': 'Test Single Audio Ep',
            'video_hd': {'mediaUrl': 'https://twit.tv/video_hd.mp4'},
            'video_large': {'mediaUrl': 'https://twit.tv/video_large.mp4'},
            'video_audio': {'mediaUrl': 'https://twit.tv/stream_single.mp3'},
        }

        class MockTarget:
            def __init__(self, data):
                self.title = data['title']
                self.episode_data = data

        self.form.is_audio_only = lambda: True
        self.form.episodes_list = type('MockList', (), {'selection': [MockTarget(ep_data)]})()

        mock_prompt_called = False

        async def mock_prompt(title, message, resolutions):
            nonlocal mock_prompt_called
            mock_prompt_called = True
            return resolutions[0]

        self.form.prompt_resolution_choice = mock_prompt

        launched_streams = []
        with unittest.mock.patch('twittui_form.launch_stream_safe', side_effect=lambda template, url: launched_streams.append(url)):
            asyncio.run(self.form.on_stream_press())

        self.assertFalse(mock_prompt_called)
        self.assertEqual(launched_streams, ['https://twit.tv/stream_single.mp3'])

    def test_on_download_press_audio_only_with_multiple_audio_prompts_audio_options(self) -> None:
        """Verify on_download_press prompts user with only audio options when audio only is enabled."""
        ep_data = {
            'title': 'Test Download Ep',
            'video_hd': {'mediaUrl': 'https://twit.tv/video_hd.mp4'},
            'files': [
                {'format': 'audio', 'label': 'MP3 Audio', 'mediaUrl': 'https://twit.tv/dl_audio.mp3'},
                {'format': 'audio', 'label': 'AAC Audio', 'mediaUrl': 'https://twit.tv/dl_audio.m4a'},
            ]
        }

        class MockTarget:
            def __init__(self, data):
                self.title = data['title']
                self.episode = '101'
                self.episode_data = data

        target = MockTarget(ep_data)
        self.form.is_audio_only = lambda: True
        self.form.episodes_list = type('MockList', (), {'selection': [target]})()

        prompted_resolutions = []

        async def mock_prompt(title, message, resolutions):
            prompted_resolutions.extend(resolutions)
            return resolutions[0]

        self.form.prompt_resolution_choice = mock_prompt

        with unittest.mock.patch('threading.Thread'):
            asyncio.run(self.form.on_download_press())

        self.assertEqual(len(prompted_resolutions), 2)
        self.assertTrue(all(r['type'] == 'audio' for r in prompted_resolutions))
        self.assertEqual(target.selected_media_url, 'https://twit.tv/dl_audio.mp3')

    def test_on_download_press_audio_only_single_audio_option_downloads_without_prompt(self) -> None:
        """Verify on_download_press directly selects audio without prompt when only 1 audio option is available."""
        ep_data = {
            'title': 'Test Single Audio DL',
            'video_hd': {'mediaUrl': 'https://twit.tv/video_hd.mp4'},
            'video_large': {'mediaUrl': 'https://twit.tv/video_large.mp4'},
            'video_audio': {'mediaUrl': 'https://twit.tv/dl_single.mp3'},
        }

        class MockTarget:
            def __init__(self, data):
                self.title = data['title']
                self.episode = '102'
                self.episode_data = data

        target = MockTarget(ep_data)
        self.form.is_audio_only = lambda: True
        self.form.episodes_list = type('MockList', (), {'selection': [target]})()

        mock_prompt_called = False

        async def mock_prompt(title, message, resolutions):
            nonlocal mock_prompt_called
            mock_prompt_called = True
            return resolutions[0]

        self.form.prompt_resolution_choice = mock_prompt

        with unittest.mock.patch('threading.Thread'):
            asyncio.run(self.form.on_download_press())

        self.assertFalse(mock_prompt_called)
        self.assertEqual(target.selected_media_url, 'https://twit.tv/dl_single.mp3')

    def test_batch_download_audio_only_prompts_only_audio_options(self) -> None:
        """Verify batch download with multiple audio formats prompts user with audio options only."""
        ep1_data = {
            'title': 'Batch Ep 1',
            'video_hd': {'mediaUrl': 'https://twit.tv/ep1_hd.mp4'},
            'files': [
                {'format': 'audio', 'label': 'MP3 Audio', 'mediaUrl': 'https://twit.tv/ep1.mp3'},
                {'format': 'audio', 'label': 'AAC Audio', 'mediaUrl': 'https://twit.tv/ep1.m4a'},
            ]
        }
        ep2_data = {
            'title': 'Batch Ep 2',
            'video_hd': {'mediaUrl': 'https://twit.tv/ep2_hd.mp4'},
            'files': [
                {'format': 'audio', 'label': 'MP3 Audio', 'mediaUrl': 'https://twit.tv/ep2.mp3'},
                {'format': 'audio', 'label': 'AAC Audio', 'mediaUrl': 'https://twit.tv/ep2.m4a'},
            ]
        }

        class MockTarget:
            def __init__(self, data, ep_num):
                self.title = data['title']
                self.episode = ep_num
                self.episode_data = data

        targets = [MockTarget(ep1_data, '1'), MockTarget(ep2_data, '2')]
        self.form.is_audio_only = lambda: True
        self.form.episodes_list = type('MockList', (), {'selection': targets})()

        prompted_resolutions = []

        async def mock_prompt(title, message, resolutions):
            prompted_resolutions.extend(resolutions)
            return resolutions[0]

        self.form.prompt_resolution_choice = mock_prompt

        with unittest.mock.patch('threading.Thread'):
            asyncio.run(self.form.on_download_press())

        self.assertTrue(len(prompted_resolutions) >= 1)
        self.assertTrue(all(r.get('type') == 'audio' for r in prompted_resolutions))
        self.assertNotIn('video_hd', [r.get('id') for r in prompted_resolutions])
        self.assertNotIn('video_large', [r.get('id') for r in prompted_resolutions])


if __name__ == "__main__":
    unittest.main()
