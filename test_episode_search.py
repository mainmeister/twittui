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


if __name__ == '__main__':
    unittest.main()