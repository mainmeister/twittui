import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import toga
from twittui_form import TwitTUIForm


class TestHoverPopup(unittest.TestCase):
    def setUp(self):
        os.environ['TOGA_BACKEND'] = 'toga_textual'
        from toga_textual_backend import patch_toga_textual
        patch_toga_textual()
        self.form = TwitTUIForm('TestApp', 'org.twit.test')
        self.form.episodes_list = MagicMock()
        self.form._main_window = MagicMock()
        self.form._loop = MagicMock()
        self.form._loop.is_running.return_value = False
        self.form._hover_timer = None
        self.form._hover_row_index = None
        self.form._dialog_open = False
        self.form._metadata_window = None

    def tearDown(self):
        self.form._cancel_hover_timer()

    def test_hover_trigger_shows_metadata_dialog_without_rate_limit_wait(self):
        sample_ep = {
            'number': '1049',
            'title': 'MacBreak Weekly 1049: Test Episode',
            'date': '2026-11-03',
            'length': '02:15:30',
            'size': '1500000000',
            'description': 'A comprehensive test episode description with notes.',
            'media_url': 'https://twit.tv/audio.mp3',
            'cleanPath': 'shows/macbreak-weekly/episodes/1049',
        }
        self.form.episodes_list.data = [
            SimpleNamespace(
                episode='1049',
                title='MacBreak Weekly 1049: Test Episode',
                date='2026-11-03',
                length='02:15:30',
                size='1.4 GB',
                media_url='https://twit.tv/audio.mp3',
                episode_data=sample_ep,
                show='MacBreak Weekly'
            )
        ]

        with patch.object(self.form, '_set_rate_limit_wait') as mock_wait:
            self.form._hover_row_index = 0
            self.form._trigger_hover_metadata(0)
            mock_wait.assert_not_called()
            self.form.main_window.info_dialog.assert_called_once()
            args, _ = self.form.main_window.info_dialog.call_args
            self.assertIn('MacBreak Weekly 1049: Test Episode', args[1])

    def test_hover_motion_starts_3_second_timer(self):
        with patch('twittui_form.threading.Timer') as mock_timer_cls:
            mock_timer = MagicMock()
            mock_timer_cls.return_value = mock_timer

            self.form._on_textual_table_hover_row(2)

            self.assertEqual(self.form._hover_row_index, 2)
            mock_timer_cls.assert_called_once_with(3.0, self.form._trigger_hover_metadata, args=(2,))
            mock_timer.start.assert_called_once()

    def test_hover_motion_to_new_row_cancels_previous_timer(self):
        with patch('twittui_form.threading.Timer') as mock_timer_cls:
            timer1 = MagicMock()
            timer2 = MagicMock()
            mock_timer_cls.side_effect = [timer1, timer2]

            self.form._on_textual_table_hover_row(1)
            self.assertEqual(self.form._hover_row_index, 1)
            timer1.start.assert_called_once()

            self.form._on_textual_table_hover_row(2)
            self.assertEqual(self.form._hover_row_index, 2)
            timer1.cancel.assert_called_once()
            timer2.start.assert_called_once()

    def test_hover_leave_cancels_timer(self):
        mock_timer = MagicMock()
        self.form._hover_timer = mock_timer
        self.form._hover_row_index = 1

        self.form._cancel_hover_timer()

        mock_timer.cancel.assert_called_once()
        self.assertIsNone(self.form._hover_timer)
        self.assertIsNone(self.form._hover_row_index)

    def test_metadata_extraction_formats_all_fields(self):
        ep_data = {
            'number': '42',
            'title': 'The Answer Episode',
            'date': '2026-05-15',
            'duration': 3600,
            'size': 500000000,
            'show_name': 'TWiT Tests',
            'hosts': [{'label': 'Leo Laporte'}],
            'topics': [{'name': 'Artificial Intelligence'}],
            'cleanPath': 'shows/twit/episodes/42',
            'description': 'Show notes discussing technology.'
        }
        target = SimpleNamespace(episode_data=ep_data, title=ep_data['title'], episode='42', show='TWiT Tests')
        meta = self.form.extract_episode_metadata_fields(target)

        self.assertEqual(meta['title'], 'The Answer Episode')
        self.assertEqual(meta['episode'], '42')
        self.assertEqual(meta['date'], '2026-05-15')
        self.assertEqual(meta['duration'], '01:00:00')
        self.assertIn('MB', meta['size'])
        self.assertIn('Leo Laporte', meta['people'])
        self.assertIn('Artificial Intelligence', meta['topics'])
        self.assertEqual(meta['link'], 'https://twit.tv/shows/twit/episodes/42')

    def test_textual_backend_uses_info_dialog_on_show_metadata(self):
        sample_ep = {
            'number': '100',
            'title': 'TUI Episode',
            'date': '2026-01-01',
            'show_name': 'TUI Show'
        }
        target = SimpleNamespace(episode_data=sample_ep, title='TUI Episode', episode='100', show='TUI Show')
        fake_textual_app = SimpleNamespace(__class__=SimpleNamespace(__module__='toga_textual.app'))
        self.form._impl = SimpleNamespace(native=fake_textual_app)

        self.form.show_episode_metadata_dialog(target)
        self.form.main_window.info_dialog.assert_called_once()
        args, kwargs = self.form.main_window.info_dialog.call_args
        self.assertIn('TUI Episode', args[1])


if __name__ == '__main__':
    unittest.main()
