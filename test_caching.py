import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

import twittui_form
from twittui_form import TwitTUIForm


class TestCaching(unittest.TestCase):
    def setUp(self):
        self.form = TwitTUIForm('TestApp', 'org.twit.test')
        limiter = patch('twittui_form.api_rate_limiter.get', side_effect=lambda *args, **kwargs: twittui_form.requests.get(*args, **kwargs))
        limiter.start()
        self.addCleanup(limiter.stop)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_shows_caching_and_clear_cache(self, mock_get, _load):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            'shows': [
                {'label': 'Security Now', 'id': 1636, 'active': True},
                {'label': 'This Week in Tech', 'id': 1634, 'active': True}
            ]
        }
        mock_get.return_value = resp

        with patch.object(self.form, 'get_api_app_id', return_value='test_id'), \
             patch.object(self.form, 'get_api_app_key', return_value='test_key'):
            # First call fetches from API
            shows_1 = self.form.fetch_shows()
            self.assertIn('Security Now', shows_1)
            self.assertIn('This Week in Tech', shows_1)
            self.assertEqual(mock_get.call_count, 1)

            # Second call uses cache
            shows_2 = self.form.fetch_shows()
            self.assertEqual(shows_1, shows_2)
            self.assertEqual(mock_get.call_count, 1)

            # Clearing cache causes next fetch to query API again
            self.form.clear_cache()
            shows_3 = self.form.fetch_shows()
            self.assertEqual(shows_1, shows_3)
            self.assertEqual(mock_get.call_count, 2)

    @patch('twittui_form.requests.get')
    def test_show_date_bounds_caching_and_clear_cache(self, mock_get):
        resp = MagicMock(status_code=200)
        resp.text = (
            '<input class="page-number-input" max="1">'
            '<a href="/shows/sn/episodes/1"><span class="date">Aug 18 2005</span> - ep 1<br /></a>'
            '<a href="/shows/sn/episodes/1000"><span class="date">Jan 01 2025</span> - ep 1000<br /></a>'
        )
        mock_get.return_value = resp

        # First call fetches from web
        bounds_1 = self.form.fetch_show_date_bounds(1636)
        self.assertEqual(bounds_1, ('2005-08-18', '2025-01-01'))
        self.assertEqual(mock_get.call_count, 1)

        # Second call returns cached bounds without network call
        bounds_2 = self.form.fetch_show_date_bounds(1636)
        self.assertEqual(bounds_2, bounds_1)
        self.assertEqual(mock_get.call_count, 1)

        # Clear cache and verify refetch
        self.form.clear_cache()
        bounds_3 = self.form.fetch_show_date_bounds(1636)
        self.assertEqual(bounds_3, bounds_1)
        self.assertEqual(mock_get.call_count, 2)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_episodes_incremental_api_querying(self, mock_get, _load):
        self.form.show_combo = MagicMock(value='Security Now')
        self.form.show_ids = {'Security Now': 1636}

        # Initial fetch of page 1 (episodes 100 and 99)
        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            'count': 2,
            'episodes': [
                {'id': 100, 'label': 'Security Now 100', 'episodeNumber': 100, 'airingDate': '2025-01-10'},
                {'id': 99, 'label': 'Security Now 99', 'episodeNumber': 99, 'airingDate': '2025-01-03'}
            ],
            '_links': {}
        }
        mock_get.return_value = resp1

        with patch.object(self.form, 'get_api_app_id', return_value='test_id'), \
             patch.object(self.form, 'get_api_app_key', return_value='test_key'):
            eps1 = self.form.fetch_episodes(1636, page=1)
            self.assertEqual(len(eps1), 2)
            self.assertEqual(eps1[0]['id'], 100)
            self.assertEqual(mock_get.call_count, 1)

            # Subsequent fetch where 1 new episode has been released (101)
            resp2 = MagicMock(status_code=200)
            resp2.json.return_value = {
                'count': 3,
                'episodes': [
                    {'id': 101, 'label': 'Security Now 101', 'episodeNumber': 101, 'airingDate': '2025-01-17'},
                    {'id': 100, 'label': 'Security Now 100', 'episodeNumber': 100, 'airingDate': '2025-01-10'}
                ],
                '_links': {}
            }
            mock_get.return_value = resp2

            eps2 = self.form.fetch_episodes(1636, page=1)
            # The new episode 101 is prepended to the cached list [100, 99]
            self.assertEqual([e['id'] for e in eps2], [101, 100, 99])
            # Only 1 API request was needed because episode 100 was recognized in the cache!
            self.assertEqual(mock_get.call_count, 2)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_episodes_page_greater_than_one_served_from_cache(self, mock_get, _load):
        self.form.show_combo = MagicMock(value='Security Now')
        self.form.show_ids = {'Security Now': 1636}

        # Populate cache with 60 episodes
        cached_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i} for i in range(60, 0, -1)]
        self.form._episodes_cache['1636'] = list(cached_eps)
        self.form._episodes_all_loaded = True

        with patch.object(self.form, 'get_api_app_id', return_value='test_id'), \
             patch.object(self.form, 'get_api_app_key', return_value='test_key'):
            # Page 2 should be served directly from cache without hitting network
            eps_page_2 = self.form.fetch_episodes(1636, page=2)
            self.assertEqual(len(eps_page_2), 10)
            self.assertEqual(eps_page_2[0]['id'], 10)
            self.assertEqual(mock_get.call_count, 0)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_fetch_episode_detail_caching_and_clear_cache(self, mock_get, _load):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            'episodes': [{'id': 500, 'label': 'Detail Episode', 'body': 'Episode show notes'}]
        }
        mock_get.return_value = resp

        with patch.object(self.form, 'get_api_app_id', return_value='test_id'), \
             patch.object(self.form, 'get_api_app_key', return_value='test_key'):
            detail1 = self.form.fetch_episode_detail(500)
            self.assertEqual(detail1['id'], 500)
            self.assertEqual(mock_get.call_count, 1)

            # Cached
            detail2 = self.form.fetch_episode_detail(500)
            self.assertEqual(detail2['id'], 500)
            self.assertEqual(mock_get.call_count, 1)

            # Clear cache
            self.form.clear_cache()
            detail3 = self.form.fetch_episode_detail(500)
            self.assertEqual(detail3['id'], 500)
            self.assertEqual(mock_get.call_count, 2)

    @patch('twittui_form.requests.get')
    def test_triangulation_archive_caching_and_clear_cache(self, mock_get):
        resp = MagicMock(status_code=200)
        resp.text = (
            '<input class="page-number-input" max="1">'
            '<a href="/shows/triangulation/episodes/1?autostart=false">'
            '<span class="date">Jan 19 2011</span> - Triangulation 1<br /></a>'
        )
        mock_get.return_value = resp
        self.form.sort_order_button = MagicMock(text='Ascending')

        arch1 = self.form.fetch_triangulation_archive(1)
        self.assertEqual(arch1[0]['number'], '1')
        self.assertEqual(mock_get.call_count, 1)

        # Cached call
        arch2 = self.form.fetch_triangulation_archive(1)
        self.assertEqual(arch2[0]['number'], '1')
        self.assertEqual(mock_get.call_count, 1)

        # Clear cache
        self.form.clear_cache()
        arch3 = self.form.fetch_triangulation_archive(1)
        self.assertEqual(arch3[0]['number'], '1')
        self.assertEqual(mock_get.call_count, 2)

    @patch('twittui_form.requests.get')
    def test_media_from_webpage_caching_and_clear_cache(self, mock_get):
        resp = MagicMock(status_code=200)
        resp.text = '<html><video src="https://twit.tv/media/sn1000.mp4"></video></html>'
        mock_get.return_value = resp

        media1 = self.form.fetch_media_from_webpage('/shows/security-now/episodes/1000', audio_only=False)
        self.assertEqual(media1, 'https://twit.tv/media/sn1000.mp4')
        self.assertEqual(mock_get.call_count, 1)

        # Cached call
        media2 = self.form.fetch_media_from_webpage('/shows/security-now/episodes/1000', audio_only=False)
        self.assertEqual(media2, 'https://twit.tv/media/sn1000.mp4')
        self.assertEqual(mock_get.call_count, 1)

        # Clear cache
        self.form.clear_cache()
        media3 = self.form.fetch_media_from_webpage('/shows/security-now/episodes/1000', audio_only=False)
        self.assertEqual(media3, 'https://twit.tv/media/sn1000.mp4')
        self.assertEqual(mock_get.call_count, 2)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_api_search_caching_and_clear_cache(self, mock_get, _load):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            'search': [
                {'id': 100, 'label': 'Steve Gibson AI', 'type': 'episode', 'cleanPath': '/shows/security-now/episodes/100', 'body': 'Discussing AI'}
            ]
        }
        mock_get.return_value = resp

        with patch.object(self.form, 'get_api_app_id', return_value='test_id'), \
             patch.object(self.form, 'get_api_app_key', return_value='test_key'), \
             patch.object(self.form, 'fetch_show_rss_items', return_value=[]), \
             patch.object(self.form, 'fetch_club_twit_rss_items', return_value=[]):
            res1 = self.form.search_episodes('Steve Gibson AI', show_name='All twit.tv Shows')
            self.assertEqual(len(res1), 1)
            self.assertEqual(res1[0]['id'], '100')
            self.assertEqual(mock_get.call_count, 1)

            # Repeated search queries cache
            res2 = self.form.search_episodes('Steve Gibson AI', show_name='All twit.tv Shows')
            self.assertEqual(len(res2), 1)
            self.assertEqual(mock_get.call_count, 1)

            # Clear cache
            self.form.clear_cache()
            res3 = self.form.search_episodes('Steve Gibson AI', show_name='All twit.tv Shows')
            self.assertEqual(len(res3), 1)
            self.assertEqual(mock_get.call_count, 2)

    def test_clear_cache_button_in_preferences(self):
        self.form.app_id_input = SimpleNamespace(value='app_id')
        self.form.app_key_input = SimpleNamespace(value='app_key')
        self.form.url_input = SimpleNamespace(value='')
        self.form.dest_input = SimpleNamespace(value='')
        self.form.block_input = SimpleNamespace(value='65535')
        self.form.rate_limit_input = SimpleNamespace(value='2.0')
        self.form.streamer_input = SimpleNamespace(value='vlc %f')
        box = self.form._build_preferences_box()
        self.assertIsNotNone(self.form.clear_cache_button)
        self.assertEqual(self.form.clear_cache_button.text, 'Clear Cache')

        # Test pressing clear cache
        self.form._shows_cache = {'dummy': 1}
        self.form.on_clear_cache_press(None)
        self.assertIsNone(self.form._shows_cache)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_persistent_sqlite_storage_across_runs(self, mock_get, _load):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        # Run 1: Form 1 fetches shows, episode details, date bounds, media links, and searches
        form1 = TwitTUIForm('App1', 'org.twit.test', cache_db_path=db_path)

        # 1. Shows
        resp_shows = MagicMock(status_code=200)
        resp_shows.json.return_value = {
            'shows': [
                {'label': 'Security Now', 'id': 1636, 'active': True}
            ]
        }
        mock_get.return_value = resp_shows
        with patch.object(form1, 'get_api_app_id', return_value='test_id'), \
             patch.object(form1, 'get_api_app_key', return_value='test_key'):
            shows1 = form1.fetch_shows()
            self.assertIn('Security Now', shows1)
            self.assertEqual(mock_get.call_count, 1)

        # 2. Episode details
        resp_detail = MagicMock(status_code=200)
        resp_detail.json.return_value = {'episodes': [{'id': 42, 'label': 'Episode 42'}]}
        mock_get.return_value = resp_detail
        with patch.object(form1, 'get_api_app_id', return_value='test_id'), \
             patch.object(form1, 'get_api_app_key', return_value='test_key'):
            det1 = form1.fetch_episode_detail(42)
            self.assertEqual(det1['id'], 42)

        # 3. Scraped date bounds
        resp_dates = MagicMock(status_code=200)
        resp_dates.text = '<input class="page-number-input" max="1"><a href="/shows/sn/episodes/1"><span class="date">Aug 18 2005</span></a>'
        mock_get.return_value = resp_dates
        bounds1 = form1.fetch_show_date_bounds(1636)
        self.assertEqual(bounds1, ('2005-08-18', '2005-08-18'))

        # 4. Scraped media link
        resp_media = MagicMock(status_code=200)
        resp_media.text = '<video src="https://twit.tv/media/sn42.mp4"></video>'
        mock_get.return_value = resp_media
        media1 = form1.fetch_media_from_webpage('/shows/security-now/episodes/42', audio_only=False)
        self.assertEqual(media1, 'https://twit.tv/media/sn42.mp4')

        # 5. Scraped triangulation archive
        resp_tri = MagicMock(status_code=200)
        resp_tri.text = '<input class="page-number-input" max="1"><a href="/shows/triangulation/episodes/1"><span class="date">Jan 19 2011</span> - Triangulation 1<br /></a>'
        mock_get.return_value = resp_tri
        form1.sort_order_button = MagicMock(text='Ascending')
        tri1 = form1.fetch_triangulation_archive(1)
        self.assertEqual(tri1[0]['number'], '1')

        # 6. API Search
        resp_search = MagicMock(status_code=200)
        resp_search.json.return_value = {
            'search': [{'id': 42, 'label': 'Search 42', 'type': 'episode', 'cleanPath': '/shows/security-now/episodes/42', 'body': 'Search notes'}]
        }
        mock_get.return_value = resp_search
        with patch.object(form1, 'get_api_app_id', return_value='test_id'), \
             patch.object(form1, 'get_api_app_key', return_value='test_key'), \
             patch.object(form1, 'fetch_show_rss_items', return_value=[]), \
             patch.object(form1, 'fetch_club_twit_rss_items', return_value=[]):
            s1 = form1.search_episodes('Search 42', show_name='All twit.tv Shows')
            self.assertEqual(len(s1), 1)

        # Reset mock call count to verify Form 2 makes 0 network requests
        mock_get.reset_mock()

        # Run 2: Fresh instance connecting to same SQLite DB
        form2 = TwitTUIForm('App2', 'org.twit.test', cache_db_path=db_path)
        with patch.object(form2, 'get_api_app_id', return_value='test_id'), \
             patch.object(form2, 'get_api_app_key', return_value='test_key'):
            shows2 = form2.fetch_shows()
            self.assertEqual(shows2, shows1)
            self.assertEqual(mock_get.call_count, 0)

            det2 = form2.fetch_episode_detail(42)
            self.assertEqual(det2['id'], 42)
            self.assertEqual(mock_get.call_count, 0)

            bounds2 = form2.fetch_show_date_bounds(1636)
            self.assertEqual(bounds2, bounds1)
            self.assertEqual(mock_get.call_count, 0)

            media2 = form2.fetch_media_from_webpage('/shows/security-now/episodes/42', audio_only=False)
            self.assertEqual(media2, media1)
            self.assertEqual(mock_get.call_count, 0)

            form2.sort_order_button = MagicMock(text='Ascending')
            tri2 = form2.fetch_triangulation_archive(1)
            self.assertEqual(tri2, tri1)
            self.assertEqual(mock_get.call_count, 0)

            with patch.object(form2, 'fetch_show_rss_items', return_value=[]), \
                 patch.object(form2, 'fetch_club_twit_rss_items', return_value=[]):
                s2 = form2.search_episodes('Search 42', show_name='All twit.tv Shows')
                self.assertEqual(len(s2), 1)
                self.assertEqual(mock_get.call_count, 0)

        # Run 3: Clear cache on form2, verify form3 starts with empty DB
        form2.clear_cache()
        form3 = TwitTUIForm('App3', 'org.twit.test', cache_db_path=db_path)
        mock_get.return_value = resp_shows
        with patch.object(form3, 'get_api_app_id', return_value='test_id'), \
             patch.object(form3, 'get_api_app_key', return_value='test_key'):
            form3.fetch_shows()
            self.assertEqual(mock_get.call_count, 1)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_persistent_sqlite_incremental_episodes(self, mock_get, _load):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        # Run 1: Fetch initial page 1
        form1 = TwitTUIForm('App1', 'org.twit.test', cache_db_path=db_path)
        form1.show_combo = MagicMock(value='Security Now')
        form1.show_ids = {'Security Now': 1636}

        resp1 = MagicMock(status_code=200)
        resp1.json.return_value = {
            'count': 2,
            'episodes': [
                {'id': 100, 'label': 'Security Now 100', 'episodeNumber': 100, 'airingDate': '2025-01-10'},
                {'id': 99, 'label': 'Security Now 99', 'episodeNumber': 99, 'airingDate': '2025-01-03'}
            ],
            '_links': {}
        }
        mock_get.return_value = resp1

        with patch.object(form1, 'get_api_app_id', return_value='test_id'), \
             patch.object(form1, 'get_api_app_key', return_value='test_key'):
            eps1 = form1.fetch_episodes(1636, page=1)
            self.assertEqual(len(eps1), 2)
            self.assertEqual(eps1[0]['id'], 100)
            self.assertEqual(mock_get.call_count, 1)

        # Run 2: New program run using the same SQLite database
        form2 = TwitTUIForm('App2', 'org.twit.test', cache_db_path=db_path)
        form2.show_combo = MagicMock(value='Security Now')
        form2.show_ids = {'Security Now': 1636}

        # API returns new episode 101 followed by already-cached 100
        resp2 = MagicMock(status_code=200)
        resp2.json.return_value = {
            'count': 3,
            'episodes': [
                {'id': 101, 'label': 'Security Now 101', 'episodeNumber': 101, 'airingDate': '2025-01-17'},
                {'id': 100, 'label': 'Security Now 100', 'episodeNumber': 100, 'airingDate': '2025-01-10'}
            ],
            '_links': {}
        }
        mock_get.return_value = resp2

        with patch.object(form2, 'get_api_app_id', return_value='test_id'), \
             patch.object(form2, 'get_api_app_key', return_value='test_key'):
            eps2 = form2.fetch_episodes(1636, page=1)
            # Should have merged new episode 101 with cached 100 and 99
            self.assertEqual(len(eps2), 3)
            self.assertEqual(eps2[0]['id'], 101)
            self.assertEqual(eps2[1]['id'], 100)
            self.assertEqual(eps2[2]['id'], 99)
            # Only 1 additional request for page 1 made
            self.assertEqual(mock_get.call_count, 2)

        # Run 3: Third program run verifies merged list persisted to DB
        form3 = TwitTUIForm('App3', 'org.twit.test', cache_db_path=db_path)
        cached_show_eps = form3._episodes_cache.get('1636', [])
        self.assertEqual(len(cached_show_eps), 3)
        self.assertEqual([e['id'] for e in cached_show_eps], [101, 100, 99])

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_relaunch_loads_full_cached_catalog_over_50_items(self, mock_get, _load):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        # Run 1: User loads show with 120 episodes (across 3 pages)
        form1 = TwitTUIForm('App1', 'org.twit.test', cache_db_path=db_path)
        form1.show_combo = MagicMock(value='Security Now')
        form1.show_ids = {'Security Now': 1636}

        page1_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2025-01-{i%28+1:02d}'} for i in range(120, 70, -1)]
        page2_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2024-01-{i%28+1:02d}'} for i in range(70, 20, -1)]
        page3_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2023-01-{i%28+1:02d}'} for i in range(20, 0, -1)]

        def get_side_effect(url, headers=None, timeout=None):
            resp = MagicMock(status_code=200)
            if 'page=1' in url:
                resp.json.return_value = {'count': 120, 'episodes': page1_eps, '_links': {'next': {'href': '...page=2'}}}
            elif 'page=2' in url:
                resp.json.return_value = {'count': 120, 'episodes': page2_eps, '_links': {'next': {'href': '...page=3'}}}
            elif 'page=3' in url:
                resp.json.return_value = {'count': 120, 'episodes': page3_eps, '_links': {}}
            return resp

        mock_get.side_effect = get_side_effect

        with patch.object(form1, 'get_api_app_id', return_value='test_id'), \
             patch.object(form1, 'get_api_app_key', return_value='test_key'):
            eps_p1 = form1.fetch_episodes(1636, page=1)
            self.assertEqual(len(eps_p1), 50)
            self.assertFalse(form1._episodes_all_loaded)

            eps_p2 = form1.fetch_episodes(1636, page=2)
            self.assertEqual(len(eps_p2), 50)
            self.assertFalse(form1._episodes_all_loaded)

            eps_p3 = form1.fetch_episodes(1636, page=3)
            self.assertEqual(len(eps_p3), 20)
            self.assertTrue(form1._episodes_all_loaded)

        # Run 2: App relaunches with persistent DB containing all 120 episodes
        form2 = TwitTUIForm('App2', 'org.twit.test', cache_db_path=db_path)
        form2.show_combo = MagicMock(value='Security Now')
        form2.show_ids = {'Security Now': 1636}

        # Reset mock; only page 1 will be fetched from API
        mock_get.reset_mock()
        mock_get.side_effect = None
        resp_p1 = MagicMock(status_code=200)
        resp_p1.json.return_value = {'count': 120, 'episodes': page1_eps, '_links': {'next': {'href': '...page=2'}}}
        mock_get.return_value = resp_p1

        with patch.object(form2, 'get_api_app_id', return_value='test_id'), \
             patch.object(form2, 'get_api_app_key', return_value='test_key'):
            # Fetching page 1 hits cache and returns ALL 120 episodes
            relaunch_eps = form2.fetch_episodes(1636, page=1)
            self.assertEqual(len(relaunch_eps), 120)
            self.assertTrue(form2._episodes_all_loaded)
            self.assertEqual(relaunch_eps[0]['id'], 120)
            self.assertEqual(relaunch_eps[-1]['id'], 1)
            # Only 1 API request made
            self.assertEqual(mock_get.call_count, 1)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_detects_and_retrieves_missing_cached_pages(self, mock_get, _load):
        """When only page 1 is in cache but total count is 120 (3 pages), fetching retrieves missing pages 2 and 3."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        page1_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2025-01-{i%28+1:02d}'} for i in range(120, 70, -1)]
        page2_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2024-01-{i%28+1:02d}'} for i in range(70, 20, -1)]
        page3_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2023-01-{i%28+1:02d}'} for i in range(20, 0, -1)]

        # Pre-seed SQLite cache with only page 1 (50 episodes)
        form1 = TwitTUIForm('App1', 'org.twit.test', cache_db_path=db_path)
        form1._episodes_cache['1636'] = list(page1_eps)
        form1._save_to_persistent_cache('episodes', '1636', form1._episodes_cache['1636'])

        # Now launch new instance with only 50 cached items
        form2 = TwitTUIForm('App2', 'org.twit.test', cache_db_path=db_path)
        form2.show_combo = MagicMock(value='Security Now')
        form2.show_ids = {'Security Now': 1636}

        def get_side_effect(url, headers=None, timeout=None):
            resp = MagicMock(status_code=200)
            if 'page=1' in url:
                resp.json.return_value = {'count': 120, 'episodes': page1_eps, '_links': {'next': {'href': '...page=2'}}}
            elif 'page=2' in url:
                resp.json.return_value = {'count': 120, 'episodes': page2_eps, '_links': {'next': {'href': '...page=3'}}}
            elif 'page=3' in url:
                resp.json.return_value = {'count': 120, 'episodes': page3_eps, '_links': {}}
            return resp

        mock_get.side_effect = get_side_effect

        with patch.object(form2, 'get_api_app_id', return_value='test_id'), \
             patch.object(form2, 'get_api_app_key', return_value='test_key'):
            eps = form2.fetch_episodes(1636, page=1)
            # Detected missing pages 2 and 3, retrieved them, and merged to 120 episodes
            self.assertEqual(len(eps), 120)
            self.assertTrue(form2._episodes_all_loaded)
            self.assertEqual(eps[0]['id'], 120)
            self.assertEqual(eps[-1]['id'], 1)
            # Page 1, Page 2, Page 3 requested
            self.assertEqual(mock_get.call_count, 3)

        # Verify full 120 episodes persisted to SQLite
        form3 = TwitTUIForm('App3', 'org.twit.test', cache_db_path=db_path)
        cached_eps = form3._episodes_cache.get('1636', [])
        self.assertEqual(len(cached_eps), 120)
        self.assertEqual(cached_eps[0]['id'], 120)
        self.assertEqual(cached_eps[-1]['id'], 1)

    @patch('twittui_form.load_twittui_dotenv')
    @patch('twittui_form.requests.get')
    def test_detects_and_retrieves_gap_in_cached_pages(self, mock_get, _load):
        """When pages 1 and 3 are cached but page 2 is missing, page 2 is retrieved without duplicate items."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        page1_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2025-01-{i%28+1:02d}'} for i in range(120, 70, -1)]
        page2_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2024-01-{i%28+1:02d}'} for i in range(70, 20, -1)]
        page3_eps = [{'id': i, 'label': f'SN {i}', 'episodeNumber': i, 'airingDate': f'2023-01-{i%28+1:02d}'} for i in range(20, 0, -1)]

        # Pre-seed cache with page 1 + page 3 (70 episodes total, page 2 missing)
        form1 = TwitTUIForm('App1', 'org.twit.test', cache_db_path=db_path)
        form1._episodes_cache['1636'] = list(page1_eps) + list(page3_eps)
        form1._save_to_persistent_cache('episodes', '1636', form1._episodes_cache['1636'])

        form2 = TwitTUIForm('App2', 'org.twit.test', cache_db_path=db_path)
        form2.show_combo = MagicMock(value='Security Now')
        form2.show_ids = {'Security Now': 1636}

        def get_side_effect(url, headers=None, timeout=None):
            resp = MagicMock(status_code=200)
            if 'page=1' in url:
                resp.json.return_value = {'count': 120, 'episodes': page1_eps, '_links': {'next': {'href': '...page=2'}}}
            elif 'page=2' in url:
                resp.json.return_value = {'count': 120, 'episodes': page2_eps, '_links': {'next': {'href': '...page=3'}}}
            elif 'page=3' in url:
                resp.json.return_value = {'count': 120, 'episodes': page3_eps, '_links': {}}
            return resp

        mock_get.side_effect = get_side_effect

        with patch.object(form2, 'get_api_app_id', return_value='test_id'), \
             patch.object(form2, 'get_api_app_key', return_value='test_key'):
            eps = form2.fetch_episodes(1636, page=1)
            self.assertEqual(len(eps), 120)
            self.assertTrue(form2._episodes_all_loaded)
            # Ensure unique IDs and no duplicates
            ep_ids = [e['id'] for e in eps]
            self.assertEqual(len(ep_ids), len(set(ep_ids)))
            self.assertEqual(set(ep_ids), set(range(1, 121)))


if __name__ == '__main__':
    unittest.main()
