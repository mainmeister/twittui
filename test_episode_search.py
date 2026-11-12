import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from twittui_form import TwitTUIForm


class TestEpisodeSearch(unittest.TestCase):
    def test_search_filters_full_catalog_and_reuses_it_for_new_queries(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.show_combo = SimpleNamespace(value='TWIT+ Club Shows')
        form.search_input = SimpleNamespace(value='AI User Group')
        episodes = [
            {'title': 'AI User Group: Getting Started', 'number': '1'},
            {'title': 'Club event', 'description': 'Another event', 'number': '2'},
        ]
        form._search_catalog = episodes
        form._search_catalog_show = 'TWIT+ Club Shows'
        form.current_episodes = episodes
        form.update_episodes_display = MagicMock()
        form._cancel_hover_timer = MagicMock()
        form._run_network = MagicMock()

        form.on_search_press()
        self.assertEqual(form.current_episodes, episodes[:1])
        form.search_input.value = 'another event'
        form.on_search_press()
        self.assertEqual(form.current_episodes, episodes[1:])
        form.search_input.value = 'no matches'
        form.on_search_press()
        self.assertEqual(form.current_episodes, [])
        form._run_network.assert_not_called()
        form.on_clear_search_press()
        self.assertEqual(form.current_episodes, episodes)

    def test_loading_complete_catalog_enables_local_search(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.show_combo = SimpleNamespace(value='TWIT+ Club Shows')
        form.show_ids = {'TWIT+ Club Shows': 1}
        form.search_input = SimpleNamespace(value='AI User Group')
        form._cancel_hover_timer = MagicMock()
        form.update_episodes_display = MagicMock()
        worker = SimpleNamespace(_episodes_from_api=True, _episodes_all_loaded=True,
                                 fetch_episodes=lambda *args, **kwargs: [
                                     {'title': 'AI User Group'}, {'title': 'Other'}])
        form._network_snapshot = MagicMock(return_value=worker)
        form._run_network = lambda work, done: done(work())
        form.load_episodes_for_selected_show()
        form.on_search_press()
        self.assertEqual(form.current_episodes, [{'title': 'AI User Group'}])

    def test_search_does_not_use_catalog_for_another_show(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.show_combo = SimpleNamespace(value='Another Show')
        form.show_ids = {'Another Show': 1}
        form.search_input = SimpleNamespace(value='AI User Group')
        form._search_catalog = [{'title': 'AI User Group'}]
        form._search_catalog_show = 'TWIT+ Club Shows'
        form._cancel_hover_timer = MagicMock()
        form._run_network = MagicMock()
        form.on_search_press()
        form._run_network.assert_called_once()

    def test_tiered_search_exact_fuzzy_and_phonetic_ranking(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.show_combo = SimpleNamespace(value='Security Now')
        form._search_catalog_show = 'Security Now'
        episodes = [
            {'title': 'Security Now 661', 'description': 'Leo is away, Father Robert Ballecer guest hosts.', 'number': '661'},
            {'title': 'Security Now 600', 'description': 'Leo Laporte and Steve Gibson discuss cryptography.', 'number': '600'},
            {'title': 'Security Now 462', 'description': 'Father Robert Ballecer hosts Cloud Storage Solutions.', 'number': '462'},
        ]
        form._search_catalog = episodes
        form.current_episodes = episodes
        form.update_episodes_display = MagicMock()
        form._cancel_hover_timer = MagicMock()
        form._run_network = MagicMock()

        # 1. Fuzzy search with typo 'ballacer' matches 'ballecer'
        form.search_input = SimpleNamespace(value='ballacer')
        form.on_search_press()
        self.assertEqual(len(form.current_episodes), 2)
        self.assertEqual([ep['number'] for ep in form.current_episodes], ['661', '462'])

        # 2. Exact match 'ballecer' yields exact matches at top priority
        form.search_input = SimpleNamespace(value='ballecer')
        form.on_search_press()
        self.assertEqual(len(form.current_episodes), 2)

        # 3. Disabling fuzzy and phonetic requires strict exact match
        os.environ['TWITFUZZYSEARCH'] = '0'
        os.environ['TWITPHONETICSEARCH'] = '0'
        form.search_input = SimpleNamespace(value='ballacer')
        form.on_search_press()
        self.assertEqual(form.current_episodes, [])

        form.search_input = SimpleNamespace(value='ballecer')
        form.on_search_press()
        self.assertEqual(len(form.current_episodes), 2)

        # Re-enable defaults
        os.environ['TWITFUZZYSEARCH'] = '1'
        os.environ['TWITPHONETICSEARCH'] = '1'

    def test_preferences_search_toggles(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        self.assertTrue(form.is_fuzzy_search_enabled())
        self.assertTrue(form.is_phonetic_search_enabled())

        form.on_fuzzy_search_toggle()
        self.assertFalse(form.is_fuzzy_search_enabled())

        form.on_fuzzy_search_toggle()
        self.assertTrue(form.is_fuzzy_search_enabled())

        form.on_phonetic_search_toggle()
        self.assertFalse(form.is_phonetic_search_enabled())

        form.on_phonetic_search_toggle()
        self.assertTrue(form.is_phonetic_search_enabled())

    def test_search_by_length_and_size(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.show_combo = SimpleNamespace(value='Security Now')
        form._search_catalog_show = 'Security Now'
        episodes = [
            {'title': 'Security Now 661', 'number': '661', 'length': '01:45:00', 'size': 524288000},
            {'title': 'Security Now 600', 'number': '600', 'length': '00:30:00', 'size': 104857600},
            {'title': 'Security Now 462', 'number': '462', 'duration': '02:15:30', 'file_size': '250.5 MB'},
        ]
        form._search_catalog = episodes
        form.current_episodes = episodes
        form.update_episodes_display = MagicMock()
        form._cancel_hover_timer = MagicMock()
        form._run_network = MagicMock()

        # Strict exact search by duration / length in time
        os.environ['TWITFUZZYSEARCH'] = '0'
        os.environ['TWITPHONETICSEARCH'] = '0'

        form.search_input = SimpleNamespace(value='01:45:00')
        form.on_search_press()
        self.assertEqual(len(form.current_episodes), 1)
        self.assertEqual(form.current_episodes[0]['number'], '661')

        form.search_input = SimpleNamespace(value='02:15:30')
        form.on_search_press()
        self.assertEqual(len(form.current_episodes), 1)
        self.assertEqual(form.current_episodes[0]['number'], '462')

        # Strict exact search by size in bytes / human-readable size
        form.search_input = SimpleNamespace(value='250.5 MB')
        form.on_search_press()
        self.assertEqual(len(form.current_episodes), 1)
        self.assertEqual(form.current_episodes[0]['number'], '462')

        form.search_input = SimpleNamespace(value='524288000')
        form.on_search_press()
        self.assertEqual(len(form.current_episodes), 1)
        self.assertEqual(form.current_episodes[0]['number'], '661')

        # Re-enable defaults
        os.environ['TWITFUZZYSEARCH'] = '1'
        os.environ['TWITPHONETICSEARCH'] = '1'

        # Ranked search places exact match first
        form.search_input = SimpleNamespace(value='01:45:00')
        form.on_search_press()
        self.assertEqual(form.current_episodes[0]['number'], '661')

    def test_sort_by_length_and_size_display(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.episodes_list = MagicMock()
        episodes = [
            {'number': '1', 'title': 'Short', 'length': '00:15:00', 'size': 10485760},   # 900s, 10MB
            {'number': '2', 'title': 'Long', 'length': '02:00:00', 'size': 524288000},   # 7200s, 500MB
            {'number': '3', 'title': 'Medium', 'length': '01:00:00', 'size': 104857600}, # 3600s, 100MB
        ]
        form.current_episodes = list(episodes)
        form.date_radio = SimpleNamespace(text='☐ Date', tooltip='')
        form.episode_radio = SimpleNamespace(text='☐ Episode Number', tooltip='')
        form.title_radio = SimpleNamespace(text='☐ Episode Title', tooltip='')
        form.length_radio = SimpleNamespace(text='☐ Length', tooltip='')
        form.size_radio = SimpleNamespace(text='☐ Size', tooltip='')
        form.sort_order_button = SimpleNamespace(text='▼ Descending', tooltip='')

        # 1. Sort by Length - Descending (longest first)
        form.length_radio.text = '☑ Length'
        form.update_episodes_display()
        numbers = [row['episode'] for row in form.episodes_list.data]
        self.assertEqual(numbers, ['2', '3', '1'])

        # 2. Sort by Length - Ascending (shortest first)
        form.sort_order_button.text = '▲ Ascending'
        form.update_episodes_display()
        numbers = [row['episode'] for row in form.episodes_list.data]
        self.assertEqual(numbers, ['1', '3', '2'])

        # 3. Sort by Size - Descending (largest first)
        form.length_radio.text = '☐ Length'
        form.size_radio.text = '☑ Size'
        form.sort_order_button.text = '▼ Descending'
        form.update_episodes_display()
        numbers = [row['episode'] for row in form.episodes_list.data]
        self.assertEqual(numbers, ['2', '3', '1'])

        # 4. Sort by Size - Ascending (smallest first)
        form.sort_order_button.text = '▲ Ascending'
        form.update_episodes_display()
        numbers = [row['episode'] for row in form.episodes_list.data]
        self.assertEqual(numbers, ['1', '3', '2'])

    def test_api_sort_params_for_length_and_size(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.date_radio = SimpleNamespace(text='☐ Date', tooltip='')
        form.episode_radio = SimpleNamespace(text='☐ Episode Number', tooltip='')
        form.title_radio = SimpleNamespace(text='☐ Episode Title', tooltip='')
        form.length_radio = SimpleNamespace(text='☐ Length', tooltip='')
        form.size_radio = SimpleNamespace(text='☐ Size', tooltip='')
        form.sort_order_button = SimpleNamespace(text='▼ Descending', tooltip='')

        # Length descending & ascending (TWiT API does not support runningTime; returns None so API uses default full archive)
        form.length_radio.text = '☑ Length'
        self.assertIsNone(form.get_current_sort_param())
        form.sort_order_button.text = '▲ Ascending'
        self.assertIsNone(form.get_current_sort_param())

        # Size descending & ascending (TWiT API does not support fileSize; returns None so API uses default full archive)
        form.length_radio.text = '☐ Length'
        form.size_radio.text = '☑ Size'
        form.sort_order_button.text = '▼ Descending'
        self.assertIsNone(form.get_current_sort_param())
        form.sort_order_button.text = '▲ Ascending'
        self.assertIsNone(form.get_current_sort_param())

    def test_sort_by_length_and_size_does_not_truncate_episodes(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.episodes_list = MagicMock()
        episodes = [
            {'number': str(i), 'title': f'Episode {i}', 'length': f'0{i % 3 + 1}:00:00', 'size': (i + 1) * 10485760}
            for i in range(1, 101)
        ]
        form.current_episodes = list(episodes)
        form._episodes_all_loaded = True
        form.date_radio = SimpleNamespace(text='☐ Date', tooltip='')
        form.episode_radio = SimpleNamespace(text='☐ Episode Number', tooltip='')
        form.title_radio = SimpleNamespace(text='☐ Episode Title', tooltip='')
        form.length_radio = SimpleNamespace(text='☐ Length', tooltip='')
        form.size_radio = SimpleNamespace(text='☐ Size', tooltip='')
        form.sort_order_button = SimpleNamespace(text='▼ Descending', tooltip='')

        # Press Length sort button
        form.on_sort_button_press(form.length_radio)
        self.assertEqual(len(form.episodes_list.data), 100)
        self.assertEqual(len(form.current_episodes), 100)

        # Press Size sort button
        form.on_sort_button_press(form.size_radio)
        self.assertEqual(len(form.episodes_list.data), 100)
        self.assertEqual(len(form.current_episodes), 100)

        # Toggle sort order
        form.on_sort_order_toggle()
        self.assertEqual(len(form.episodes_list.data), 100)
        self.assertEqual(len(form.current_episodes), 100)


if __name__ == '__main__':
    unittest.main()