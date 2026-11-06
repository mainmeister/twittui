import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

import twittui_form
from twittui_form import TwitTUIForm


class TestShowCatalog(unittest.TestCase):
    def setUp(self):
        self.form = TwitTUIForm('TestApp', 'org.twit.test')
        limiter = patch('twittui_form.api_rate_limiter.get', side_effect=lambda *args, **kwargs: twittui_form.requests.get(*args, **kwargs))
        limiter.start()
        self.addCleanup(limiter.stop)

    @patch('twittui_form.load_twittui_dotenv')
    def test_triangulation_in_fallback_catalog(self, _load):
        with patch.object(self.form, 'get_api_app_id', return_value=''):
            self.assertIn('Triangulation', self.form.fetch_shows())

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_triangulation_in_api_catalog(self, get, _load):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'shows': [{'label': 'Security Now', 'id': 1636}]}
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertIn('Triangulation', self.form.fetch_shows())
            self.assertEqual(self.form.show_ids['Security Now'], 1636)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_api_triangulation_keeps_its_id(self, get, _load):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'shows': [{'label': 'Triangulation', 'id': 42}]}
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertEqual(self.form.fetch_shows(), ['Triangulation'])
            self.assertEqual(self.form.show_ids['Triangulation'], 42)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_api_catalog_requests_all_shows_once(self, get, _load):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'shows': [{'label': 'Zebra', 'id': 1}, {'label': 'Alpha', 'id': 2}, {'label': 'No ID'}]}
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertEqual(self.form.fetch_shows(), ['Alpha', 'No ID', 'Triangulation', 'Zebra'])
        self.assertEqual(self.form.show_ids['Alpha'], 2)
        self.assertIsNone(self.form.show_ids['No ID'])
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], 'https://twit.tv/api/v1.0/shows?page=1&range=1000')

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_show_catalog_sorts_ignoring_case(self, get, _load):
        shows = [('zebra', 1), ('Alpha', 2), ('beta', 3)]
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'shows': [{'label': name, 'id': sid} for name, sid in shows]}
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertEqual(self.form.fetch_shows(), ['Alpha', 'beta', 'Triangulation', 'zebra'])
        with patch('twittui_form.DEFAULT_SHOWS', shows), patch.object(self.form, 'get_api_app_id', return_value=''):
            self.assertEqual(self.form.fetch_shows(), ['Alpha', 'beta', 'zebra'])

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_api_catalog_preserves_show_active_flags(self, get, _load):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            'shows': [
                {'label': 'Active Show', 'id': 1, 'active': True},
                {'label': 'Ended Show', 'id': 2, 'active': False},
                {'label': 'Unknown Show', 'id': 3},
            ]
        }
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.form.fetch_shows()
        self.assertEqual(self.form.show_active, {'Active Show': True, 'Ended Show': False, 'Unknown Show': None, 'Triangulation': None})

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_api_catalog_extracts_created_showdate_and_active(self, get, _load):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            'shows': [
                {
                    'label': 'Security Now',
                    'id': 1636,
                    'created': '2005-08-18T22:06:55Z',
                    'showDate': 'New episodes every Tuesday.',
                    'active': True,
                },
                {
                    'label': 'Abby\'s Road',
                    'id': 1652,
                    'created': '2009-07-08T06:58:29Z',
                    'showDate': 'Although the show is no longer in production, you can enjoy episodes from the TWiT Archives.',
                    'active': False,
                },
            ]
        }
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            names = self.form.fetch_shows()
        self.assertEqual(self.form.show_active['Security Now'], True)
        self.assertEqual(self.form.show_active['Abby\'s Road'], False)
        self.assertEqual(self.form.show_date_bounds['Security Now'], ('2005-08-18T22:06:55Z', None))
        self.assertEqual(self.form.show_date_bounds['Abby\'s Road'], ('2009-07-08T06:58:29Z', None))
        self.assertEqual(self.form.show_date_bounds['Triangulation'], (None, None))
        self.assertEqual(self.form._show_date_cache['1636'], ('2005-08-18T22:06:55Z', None))

    def test_show_option_formats_fixed_width_metadata_before_name(self):
        self.form.show_active = {'Running': True, 'Finished': False}
        self.form.show_date_bounds = {
            'Running': ('2020-01-02', '2025-03-04'),
            'Finished': (None, None),
        }
        active = self.form._format_show_option('Running')
        ended = self.form._format_show_option('Finished')
        self.assertEqual(active[:10], '2020-01-02')
        self.assertEqual(active[13:23], '2025-03-04')
        self.assertEqual(active[25:32], 'Active ')
        self.assertTrue(active.endswith('Running'))
        self.assertEqual(ended[:10], 'Unknown   ')
        self.assertEqual(ended[13:23], 'Unknown   ')
        self.assertEqual(ended[25:32], 'Ended  ')
        self.assertTrue(ended.endswith('Finished'))

    @patch('twittui_form.requests.get')
    def test_show_date_bounds_single_page_archive(self, get):
        page = MagicMock(status_code=200)
        page.text = ('<a href="/shows/example/episodes/1"><span class="date">Jan 02 2010</span><br /></a>'
                     '<a href="/shows/example/episodes/2"><span class="date">Mar 04 2025</span><br /></a>')
        get.return_value = page
        self.assertEqual(self.form.fetch_show_date_bounds(123), ('2010-01-02', '2025-03-04'))
        get.assert_called_once()

    @patch('twittui_form.requests.get')
    def test_show_date_bounds_use_oldest_and_newest_archive_pages(self, get):
        oldest = MagicMock(status_code=200)
        oldest.text = ('<input class="page-number-input" max="2">'
                       '<a href="/shows/example/episodes/1"><span class="date">Jan 02 2010</span> - Oldest<br /></a>')
        newest = MagicMock(status_code=200)
        newest.text = ('<input class="page-number-input" max="2">'
                       '<a href="/shows/example/episodes/2"><span class="date">Mar 04 2025</span> - Newest<br /></a>')
        get.side_effect = [newest, oldest]
        self.assertEqual(self.form.fetch_show_date_bounds(123), ('2010-01-02', '2025-03-04'))
        self.assertEqual([call.kwargs['params']['page'] for call in get.call_args_list], [1, 2])

    @patch('twittui_form.requests.get')
    def test_show_date_bounds_are_unknown_without_id_or_archive(self, get):
        self.assertIsNone(self.form.fetch_show_date_bounds(None))
        get.assert_not_called()
        get.return_value.raise_for_status.side_effect = twittui_form.requests.RequestException('offline')
        self.assertIsNone(self.form.fetch_show_date_bounds(123))

    def test_display_selection_resolves_back_to_real_show_name(self):
        self.form.show_ids = {'Security Now': 1636}
        self.form.show_active = {'Security Now': True}
        self.form.show_date_bounds = {'Security Now': ('2010-01-01', '2025-01-01')}
        self.form.show_combo = SimpleNamespace(value='Security Now', items=[])
        self.form._set_show_selector_items(['Security Now'], 'Security Now')
        self.assertNotEqual(self.form.show_combo.value, 'Security Now')
        self.assertEqual(self.form._selected_show_name(), 'Security Now')
        self.assertEqual(self.form.show_ids[self.form._selected_show_name()], 1636)

    def test_stale_show_date_refresh_does_not_update_catalog(self):
        self.form._catalog_request = 1
        self.form.show_ids = {'Show': 1}
        self.form.show_active = {'Show': True}
        self.form.show_date_bounds = {'Show': (None, None)}
        self.form.show_combo = SimpleNamespace(value='Show', items=[])
        worker = MagicMock()
        worker.fetch_show_date_bounds.return_value = ('2020-01-01', '2024-01-01')
        self.form._network_snapshot = MagicMock(return_value=worker)
        jobs = []
        self.form._run_network = lambda work, done: jobs.append((work, done))
        self.form._refresh_show_dates(1, ['Show'])
        self.form._catalog_request = 2
        jobs[0][1](jobs[0][0]())
        self.assertEqual(self.form.show_date_bounds['Show'], (None, None))

    def test_refresh_show_dates_preserves_created_start_and_populates_scraped_end(self):
        self.form._catalog_request = 1
        self.form.show_ids = {'Security Now': 1636}
        self.form.show_active = {'Security Now': True}
        self.form.show_date_bounds = {'Security Now': ('2005-08-18T22:06:55Z', None)}
        self.form.show_combo = SimpleNamespace(value='Security Now', items=[])
        worker = MagicMock()
        worker.fetch_show_date_bounds.return_value = ('2005-08-19', '2025-03-04')
        self.form._network_snapshot = MagicMock(return_value=worker)
        jobs = []
        self.form._run_network = lambda work, done: jobs.append((work, done))
        self.form._refresh_show_dates(1, ['Security Now'])
        jobs[0][1](jobs[0][0]())
        self.assertEqual(self.form.show_date_bounds['Security Now'], ('2005-08-18T22:06:55Z', '2025-03-04'))
        self.assertEqual(self.form._show_date_cache['1636'], ('2005-08-18T22:06:55Z', '2025-03-04'))

    def test_refresh_catalog_holds_wait_dialog_until_dates_and_episodes_finish(self):
        self.form.show_combo = SimpleNamespace(value='Security Now', items=[])
        self.form.show_ids = {'Security Now': 1636}
        self.form.show_active = {'Security Now': True}
        self.form.show_date_bounds = {'Security Now': ('2005-08-18', None)}
        self.form._set_rate_limit_wait = MagicMock()
        self.form.update_episodes_display = MagicMock()

        worker = MagicMock()
        worker.show_ids = {'Security Now': 1636}
        worker.show_active = {'Security Now': True}
        worker.show_date_bounds = {'Security Now': ('2005-08-18', None)}
        worker._show_date_cache = {}
        worker.fetch_shows.return_value = ['Security Now']
        worker.fetch_show_date_bounds.return_value = ('2005-08-18', '2025-03-04')
        worker.fetch_episodes.return_value = [{'title': 'SN 1'}]
        worker._episodes_all_loaded = True
        self.form._network_snapshot = MagicMock(return_value=worker)

        network_jobs = []
        self.form._run_network = lambda work, done: network_jobs.append((work, done))

        self.form._refresh_catalog()
        self.form._set_rate_limit_wait.assert_called_with(True)
        self.form._set_rate_limit_wait.reset_mock()

        # 1. Shows API finishes
        network_jobs[0][1](['Security Now'])

        # Verify dialog not closed yet
        self.form._set_rate_limit_wait.assert_not_called()

        episodes_job = [j for j in network_jobs[1:] if 'fetch_all' in getattr(j[0], '__name__', '')][0]
        dates_job = [j for j in network_jobs[1:] if j != episodes_job][0]

        # 2. Episode list finishes first
        episodes_job[1](([{'title': 'SN 1'}], 1))
        self.form._set_rate_limit_wait.assert_not_called()

        # 3. Show dates finish second
        dates_job[1](('2005-08-18', '2025-03-04'))
        self.form._set_rate_limit_wait.assert_called_once_with(False)

    def test_refresh_catalog_holds_wait_dialog_when_dates_finish_before_episodes(self):
        self.form.show_combo = SimpleNamespace(value='Security Now', items=[])
        self.form.show_ids = {'Security Now': 1636}
        self.form.show_active = {'Security Now': True}
        self.form.show_date_bounds = {'Security Now': ('2005-08-18', None)}
        self.form._set_rate_limit_wait = MagicMock()
        self.form.update_episodes_display = MagicMock()

        worker = MagicMock()
        worker.show_ids = {'Security Now': 1636}
        worker.show_active = {'Security Now': True}
        worker.show_date_bounds = {'Security Now': ('2005-08-18', None)}
        worker._show_date_cache = {}
        worker.fetch_shows.return_value = ['Security Now']
        worker.fetch_show_date_bounds.return_value = ('2005-08-18', '2025-03-04')
        worker.fetch_episodes.return_value = [{'title': 'SN 1'}]
        worker._episodes_all_loaded = True
        self.form._network_snapshot = MagicMock(return_value=worker)

        network_jobs = []
        self.form._run_network = lambda work, done: network_jobs.append((work, done))

        self.form._refresh_catalog()
        self.form._set_rate_limit_wait.assert_called_with(True)
        self.form._set_rate_limit_wait.reset_mock()

        # Shows API finishes
        network_jobs[0][1](['Security Now'])

        episodes_job = [j for j in network_jobs[1:] if 'fetch_all' in getattr(j[0], '__name__', '')][0]
        dates_job = [j for j in network_jobs[1:] if j != episodes_job][0]

        # Dates finish first
        dates_job[1](('2005-08-18', '2025-03-04'))
        self.form._set_rate_limit_wait.assert_not_called()

        # Episodes finish second
        episodes_job[1](([{'title': 'SN 1'}], 1))
        self.form._set_rate_limit_wait.assert_called_once_with(False)

    def test_show_list_display_and_selection_survive_date_refresh(self):
        import asyncio
        import toga
        import toga.platform
        from textual.app import App, ComposeResult
        from toga_textual_backend import patch_toga_textual

        os.environ['TOGA_BACKEND'] = 'toga_textual'
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()
        patch_toga_textual()

        self.form.show_ids = {'Alpha': 1, 'A Much Longer Name': 2, 'Zulu': 3}
        self.form.show_active = {'Alpha': True, 'A Much Longer Name': False}
        self.form.show_date_bounds = {
            'Alpha': ('2020-01-02', '2025-03-04'),
            'A Much Longer Name': (None, None),
            'Zulu': ('2018-05-06', '2024-07-08'),
        }
        shows = sorted(self.form.show_ids, key=str.casefold)
        self.form.show_combo = toga.Selection(items=[])
        self.form._set_show_selector_items(shows, 'Zulu')
        selection = self.form.show_combo

        class ShowListApp(App):
            def compose(self) -> ComposeResult:
                yield selection._impl.native

        async def run_show_list_test():
            async with ShowListApp().run_test() as pilot:
                labels = [title for title, _ in selection._impl._options]
                self.assertEqual(labels, [self.form._format_show_option(name) for name in shows])
                self.assertTrue(all(label.endswith(name) for label, name in zip(labels, shows)))
                self.assertTrue(all(label[10:13] == ' - ' for label in labels))
                self.assertTrue(all(label[23:25] == '  ' for label in labels))
                self.assertTrue(all(label[32:34] == '  ' for label in labels))

                by_name = dict(zip(shows, labels))
                self.assertEqual(by_name['Alpha'][25:32], 'Active ')
                self.assertEqual(by_name['A Much Longer Name'][:10], 'Unknown   ')
                self.assertEqual(by_name['A Much Longer Name'][13:23], 'Unknown   ')
                self.assertEqual(by_name['A Much Longer Name'][25:32], 'Ended  ')
                self.assertEqual(by_name['Zulu'][25:32], 'Unknown')

                selection._impl.native.value = str(shows.index('A Much Longer Name'))
                await pilot.pause()
                self.assertEqual(self.form._selected_show_name(), 'A Much Longer Name')

                self.form.show_date_bounds['A Much Longer Name'] = ('2012-03-04', '2023-04-05')
                selected_show = self.form._selected_show_name()
                self.form._set_show_selector_items(shows, selected_show)
                await pilot.pause()

                updated_labels = [title for title, _ in selection._impl._options]
                updated_by_name = dict(zip(shows, updated_labels))
                self.assertEqual(updated_by_name['A Much Longer Name'][:10], '2012-03-04')
                self.assertEqual(updated_by_name['A Much Longer Name'][13:23], '2023-04-05')
                self.assertEqual(self.form._selected_show_name(), 'A Much Longer Name')
                self.assertEqual(self.form.show_ids[self.form._selected_show_name()], 2)

        asyncio.run(run_show_list_test())


    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_catalog_loads_all_pages(self, get, _load):
        for page_count in (1, 2, 4, 6):
            with self.subTest(page_count=page_count):
                get.reset_mock()
                pages = []
                for page_number in range(1, page_count + 1):
                    shows = [{'label': f'Show {page_number}', 'id': page_number}]
                    links = {'next': {'href': f'https://twit.tv/api/v1.0/shows/?page={page_number + 1}'}} if page_number < page_count else {}
                    pages.append({'shows': shows, '_links': links})
                responses = [MagicMock(status_code=200) for _ in pages]
                for response, page in zip(responses, pages):
                    response.json.return_value = page
                get.side_effect = responses
                with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
                    names = self.form.fetch_shows()
                for page in pages:
                    for show in page['shows']:
                        self.assertIn(show['label'], names)
                        self.assertEqual(self.form.show_ids[show['label']], show['id'])
                self.assertEqual(get.call_count, page_count)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_invalid_or_repeated_next_link_uses_fallback(self, get, _load):
        self.form.api_status_label = MagicMock()
        for href in ('https://evil.example/shows?page=2', 'https://twit.tv/api/v1.0/shows'):
            with self.subTest(href=href):
                get.reset_mock()
                get.return_value.status_code = 200
                get.return_value.json.return_value = {'shows': [{'label': 'Partial', 'id': 1}], '_links': {'next': {'href': href}}}
                with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
                    self.assertNotIn('Partial', self.form.fetch_shows())
                get.assert_called_once()
                self.assertIn('fallback', self.form.api_status_label.text.lower())

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_later_catalog_page_failure_uses_fallback(self, get, _load):
        self.form.api_status_label = MagicMock()
        first, second = MagicMock(status_code=200), MagicMock(status_code=503)
        first.json.return_value = {'shows': [{'label': 'Partial', 'id': 1}], '_links': {'next': {'href': '?page=2'}}}
        get.side_effect = [first, second]
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertNotIn('Partial', self.form.fetch_shows())
        self.assertEqual(get.call_count, 2)
        self.assertIn('503', self.form.api_status_label.text)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_episode_catalog_requests_bounded_page(self, get, _load):
        self.form.show_combo = MagicMock(value='Test')
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'episodes': [{'label': 'First'}, {'label': 'Second'}]}
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            episodes = self.form.fetch_episodes(123, sort='-airingDate')
            self.assertEqual([e['title'] for e in episodes], ['First', 'Second'])
            self.assertEqual(self.form.fetch_episodes(123, page=2), [])
        get.assert_called_once()
        self.assertIn('page=1&range=50', get.call_args.args[0])
        self.assertIn('sort=-airingDate', get.call_args.args[0])

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_episode_next_page_is_loaded_on_demand(self, get, _load):
        self.form.show_combo = MagicMock(value='Test')
        first, second = MagicMock(status_code=200), MagicMock(status_code=200)
        first.json.return_value = {'episodes': [{'label': 'First'}], '_links': {'next': {'href': '?page=2'}}}
        second.json.return_value = {'episodes': [{'label': 'Second'}]}
        get.side_effect = [first, second]
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertEqual(self.form.fetch_episodes(123)[0]['title'], 'First')
            self.assertFalse(self.form._episodes_all_loaded)
            self.assertEqual(self.form.fetch_episodes(123, page=2)[0]['title'], 'Second')
            self.assertEqual(self.form.fetch_episodes(123, page=3), [])
        self.assertEqual(get.call_count, 2)
        self.assertIn('page=2', get.call_args.args[0])

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_api_failure_loads_all_available_rss_items_and_warns(self, get, _load):
        self.form.show_combo = MagicMock(value='Security Now')
        get.return_value.status_code = 500
        items = [{'title': f'Episode {i}'} for i in range(50)]
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'), patch.object(self.form, 'fetch_show_rss_items', return_value=items):
            episodes = self.form.fetch_episodes(1636)
            self.assertEqual(len(episodes), 50)
            self.assertEqual(self.form.fetch_episodes(1636, page=2), [])
        self.assertIn('500', self.form._episode_api_status)
        get.assert_called_once()

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_episode_count_detects_additional_pages_without_next_link(self, get, _load):
        self.form.show_combo = MagicMock(value='Security Now')
        get.return_value.status_code = 200
        get.return_value.json.return_value = {'count': 2500, 'episodes': [{'label': 'Partial'}]}
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertEqual(self.form.fetch_episodes(1636)[0]['title'], 'Partial')
        self.assertFalse(self.form._episodes_all_loaded)
        get.assert_called_once()

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_later_episode_page_failure_preserves_api_source(self, get, _load):
        self.form.show_combo = MagicMock(value='Test')
        first, second = MagicMock(status_code=200), MagicMock(status_code=500)
        first.json.return_value = {'episodes': [{'label': 'First'}], '_links': {'next': {'href': '?page=2'}}}
        get.side_effect = [first, second]
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'), patch.object(self.form, 'fetch_show_rss_items') as rss:
            self.form.fetch_episodes(123)
            self.assertEqual(self.form.fetch_episodes(123, page=2), [])
        rss.assert_not_called()
        self.assertIn('500', self.form._episode_api_status)

    def test_next_page_failure_is_displayed_without_losing_episodes(self):
        self.form.show_combo = MagicMock(value='Test')
        self.form.show_ids = {'Test': 123}
        self.form.current_page = 1
        self.form.current_episodes = [{'title': 'First'}]
        self.form.api_status_label = MagicMock(text='')
        worker = MagicMock()
        worker._episodes_all_loaded = False
        worker._episode_api_status = 'Episodes API failed (HTTP 500)'
        worker.fetch_episodes.return_value = []
        with patch.object(self.form, '_network_snapshot', return_value=worker), patch.object(self.form, '_run_network', side_effect=lambda work, done: done(work())):
            self.form.on_next_press(None)
        self.assertEqual(self.form.current_page, 1)
        self.assertEqual(self.form.current_episodes, [{'title': 'First'}])
        self.assertIn('500', self.form.api_status_label.text)

    def test_episode_source_propagates_from_worker(self):
        self.form.show_combo = MagicMock(value='Test')
        self.form.show_ids = {'Test': 123}
        worker = MagicMock()
        worker.fetch_episodes.side_effect = lambda *args, **kwargs: [{'title': 'First'}]
        worker._episodes_from_api = True
        worker._triangulation_rss_fallback = False
        with patch.object(self.form, '_network_snapshot', return_value=worker), patch.object(self.form, '_run_network', side_effect=lambda work, done: done(work())), patch.object(self.form, 'update_episodes_display'):
            self.form.load_episodes_for_selected_show()
        self.assertTrue(self.form._episodes_from_api)

    def test_selected_show_loads_all_pages(self):
        self.form.show_combo = MagicMock(value='Test')
        self.form.show_ids = {'Test': 123}
        self.form.search_input = MagicMock(value='')
        worker = MagicMock()
        worker._episodes_all_loaded = False
        def fetch(show_id, page):
            worker._episodes_all_loaded = page == 3
            return [{'title': f'Episode {page}'}]
        worker.fetch_episodes.side_effect = fetch
        with patch.object(self.form, '_network_snapshot', return_value=worker), patch.object(self.form, '_run_network', side_effect=lambda work, done: done(work())), patch.object(self.form, 'update_episodes_display'):
            self.form.load_episodes_for_selected_show()
        self.assertEqual([ep['title'] for ep in self.form.current_episodes], ['Episode 1', 'Episode 2', 'Episode 3'])
        self.assertEqual(self.form.current_page, 3)

    def test_selected_show_holds_modal_wait_dialog_until_complete(self):
        self.form.show_combo = MagicMock(value='Test')
        self.form.show_ids = {'Test': 123}
        self.form.search_input = MagicMock(value='')
        self.form._set_rate_limit_wait = MagicMock()
        worker = MagicMock()
        worker.fetch_episodes.return_value = [{'title': 'Episode 1'}]
        worker._episodes_all_loaded = True
        jobs = []
        with patch.object(self.form, '_network_snapshot', return_value=worker), patch.object(self.form, '_run_network', side_effect=lambda work, done: jobs.append((work, done))), patch.object(self.form, 'update_episodes_display'):
            self.form.load_episodes_for_selected_show()
            self.form._set_rate_limit_wait.assert_called_once_with(True)
            self.form._set_rate_limit_wait.reset_mock()
            jobs[0][1](jobs[0][0]())
            self.form._set_rate_limit_wait.assert_called_once_with(False)

    def test_select_show_with_search_loads_catalog(self):
        self.form.search_input = MagicMock(value='query')
        with patch.object(self.form, 'load_episodes_for_selected_show') as load:
            self.form.on_show_select(None)
        load.assert_called_once()

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_selected_show_preserves_pages_on_api_failure(self, get, _load):
        self.form.show_combo = MagicMock(value='Test')
        self.form.show_ids = {'Test': 123}
        self.form.search_input = MagicMock(value='first')
        self.form.api_status_label = MagicMock(text='')
        first, second = MagicMock(status_code=200), MagicMock(status_code=500)
        first.json.return_value = {'episodes': [{'label': 'First'}], '_links': {'next': {'href': '?page=2'}}}
        get.side_effect = [first, second]
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'), patch.object(self.form, '_run_network', side_effect=lambda work, done: done(work())), patch.object(self.form, 'update_episodes_display'):
            self.form.load_episodes_for_selected_show()
        self.assertEqual([ep['title'] for ep in self.form.current_episodes], ['First'])
        self.assertIn('500', self.form.api_status_label.text)
        self.assertEqual(get.call_count, 2)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_api_failure_message_and_recovery(self, get, _load):
        self.form.api_status_label = MagicMock()
        get.return_value.status_code = 403
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertIn('Triangulation', self.form.fetch_shows())
            self.assertIn('403', self.form.api_status_label.text)
            self.assertIn('fallback', self.form.api_status_label.text.lower())
            get.return_value.status_code = 200
            get.return_value.json.return_value = {'shows': [{'label': 'Security Now', 'id': 1636}]}
            self.form.fetch_shows()
            self.assertEqual(self.form.api_status_label.text, '')

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get', side_effect=ConnectionError('offline'))
    def test_api_exception_message(self, get, _load):
        self.form.api_status_label = MagicMock()
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'):
            self.assertIn('Triangulation', self.form.fetch_shows())
            self.assertIn('failed', self.form.api_status_label.text.lower())

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_rss_only_show_skips_unfiltered_api_request(self, get, _load):
        self.form.show_combo = MagicMock(value='Triangulation')
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'), patch.object(self.form, 'fetch_triangulation_archive', return_value=None), patch.object(self.form, 'fetch_show_rss_items', return_value=[]), patch.object(self.form, 'fetch_club_twit_rss_items', return_value=[]):
            self.form.fetch_episodes(None)
        get.assert_not_called()

    @patch('twittui_form.load_twittui_dotenv')
    def test_rss_only_show_loads_episodes(self, _load):
        self.form.show_combo = MagicMock(value='Triangulation')
        with patch.object(self.form, 'get_api_app_id', return_value='id'), patch.object(self.form, 'get_api_app_key', return_value='key'), patch.object(self.form, 'fetch_triangulation_archive', return_value=None), patch.object(self.form, 'fetch_show_rss_items', return_value=[{'title': 'Triangulation 421'}]) as feed:
            episodes = self.form.fetch_episodes(None)
        self.assertEqual(episodes[0]['title'], 'Triangulation 421')
        self.assertEqual(feed.call_args.args[0], 'Triangulation')

    @patch('twittui_form.requests.get')
    def test_archive_pagination_and_order(self, get):
        def response(page):
            result = MagicMock()
            result.text = (f'<input class="page-number-input" max="2">'
                           f'<a href="/shows/triangulation/episodes/{page}?autostart=false">'
                           f'<span class="date">Jan 19 2011</span> - Episode &amp; {page}<br /></a>')
            return result

        get.side_effect = lambda url, params, timeout: response(3 - params['page'])
        self.form.sort_order_button = MagicMock(text='Ascending')
        first = self.form.fetch_triangulation_archive(1)
        self.assertEqual(first[0]['number'], '1')
        self.assertEqual(first[0]['title'], 'Episode & 1')
        self.assertEqual(first[0]['date'], '2011-01-19')
        self.assertEqual(self.form.fetch_triangulation_archive(2)[0]['number'], '2')
        self.assertEqual(self.form.fetch_triangulation_archive(3), [])
        self.form.sort_order_button.text = 'Descending'
        self.assertEqual(self.form.fetch_triangulation_archive(1)[0]['number'], '2')

    @patch('twittui_form.load_twittui_dotenv')
    def test_archive_failure_does_not_mix_pagination_sources(self, _load):
        self.form.show_combo = MagicMock(value='Triangulation')
        with patch.object(self.form, 'get_api_app_id', return_value=''), patch.object(self.form, 'fetch_triangulation_archive', side_effect=[[{'number': '1'}], None]), patch.object(self.form, 'fetch_show_rss_items') as rss:
            self.assertEqual(self.form.fetch_episodes(None, 1)[0]['number'], '1')
            self.assertEqual(self.form.fetch_episodes(None, 2), [])
            rss.assert_not_called()


if __name__ == '__main__':
    unittest.main()