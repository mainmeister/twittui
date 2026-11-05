import asyncio
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

from twittui_form import ApiRateLimiter, TwitTUIForm


class TestApiRateLimiter(unittest.TestCase):
    def test_request_notifications_surround_network_call(self):
        limiter = ApiRateLimiter()
        events = []
        limiter.wait_callback = events.append
        def request(*args, **kwargs):
            self.assertEqual(events, [True])
            return SimpleNamespace(status_code=200, text='')
        with patch('twittui_form.requests.get', side_effect=request):
            limiter.get('url')
        self.assertEqual(events, [True, False])

    def test_request_notification_cleared_on_network_error(self):
        limiter = ApiRateLimiter()
        events = []
        limiter.wait_callback = events.append
        with patch('twittui_form.requests.get', side_effect=ConnectionError):
            with self.assertRaises(ConnectionError):
                limiter.get('url')
        self.assertEqual(events, [True, False])

    def test_wait_notifications_cover_spacing_and_retry(self):
        limiter = ApiRateLimiter()
        events = []
        limiter.wait_callback = events.append
        clock = [0.0]
        limited = SimpleNamespace(status_code=500, text='usage limits are exceeded')
        success = SimpleNamespace(status_code=200, text='')
        with patch('twittui_form.time.monotonic', side_effect=lambda: clock[0]), \
                patch('twittui_form.time.sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                patch('twittui_form.requests.get', side_effect=[success, limited, success]):
            limiter.get('url')
            limiter.get('url')
        self.assertEqual(events, [True, False, True, False])

    def test_wait_notification_is_cleared_on_error(self):
        limiter = ApiRateLimiter()
        events = []
        limiter.wait_callback = events.append
        limiter.timestamps.append(0)
        with patch('twittui_form.time.monotonic', return_value=0), \
                patch('twittui_form.time.sleep', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                limiter.get('url')
        self.assertEqual(events, [True, False])

    def test_rolling_window_and_spacing(self):
        limiter = ApiRateLimiter()
        clock = [0.0]
        starts = []

        def sleep(seconds):
            clock[0] += seconds

        with patch('twittui_form.time.monotonic', side_effect=lambda: clock[0]), \
                patch('twittui_form.time.sleep', side_effect=sleep), \
                patch('twittui_form.requests.get', side_effect=lambda *a, **k: (starts.append(clock[0]), SimpleNamespace(status_code=200, text=''))[1]):
            for _ in range(7):
                limiter.get('https://twit.tv/api/v1.0/shows')

        self.assertEqual(starts, [0, 1, 2, 3, 4, 60, 61])
        self.assertEqual(list(limiter.timestamps), [2, 3, 4, 60, 61])

    def test_failed_requests_count(self):
        limiter = ApiRateLimiter()
        with patch('twittui_form.time.monotonic', return_value=0), \
                patch('twittui_form.requests.get', side_effect=ConnectionError):
            with self.assertRaises(ConnectionError):
                limiter.get('https://twit.tv/api/v1.0/shows')
        self.assertEqual(list(limiter.timestamps), [0])

    def test_usage_limit_response_waits_and_retries_once(self):
        limiter = ApiRateLimiter()
        clock = [0.0]
        starts = []
        limited = SimpleNamespace(status_code=500, text='Usage limits are exceeded')
        success = SimpleNamespace(status_code=200, text='')

        def request(*args, **kwargs):
            starts.append(clock[0])
            return limited if len(starts) == 1 else success

        with patch('twittui_form.time.monotonic', side_effect=lambda: clock[0]), \
                patch('twittui_form.time.sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                patch('twittui_form.requests.get', side_effect=request):
            self.assertIs(limiter.get('https://twit.tv/api/v1.0/shows'), success)
        self.assertEqual(starts, [0, 60])

    def test_usage_limit_retry_is_bounded(self):
        limiter = ApiRateLimiter()
        clock = [0.0]
        limited = SimpleNamespace(status_code=500, text='usage limits are exceeded')
        with patch('twittui_form.time.monotonic', side_effect=lambda: clock[0]), \
                patch('twittui_form.time.sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                patch('twittui_form.requests.get', return_value=limited) as get:
            self.assertIs(limiter.get('https://twit.tv/api/v1.0/shows'), limited)
        self.assertEqual(get.call_count, 2)

    def test_other_server_errors_are_not_retried(self):
        limiter = ApiRateLimiter()
        failure = SimpleNamespace(status_code=500, text='Internal Server Error')
        with patch('twittui_form.requests.get', return_value=failure) as get:
            self.assertIs(limiter.get('https://twit.tv/api/v1.0/shows'), failure)
        self.assertEqual(get.call_count, 1)

    def test_concurrent_callers_share_the_window(self):
        limiter = ApiRateLimiter()
        clock = [0.0]
        starts = []
        barrier = threading.Barrier(7)

        def call():
            barrier.wait()
            limiter.get('https://twit.tv/api/v1.0/episodes')

        def sleep(seconds):
            clock[0] += seconds

        with patch('twittui_form.time.monotonic', side_effect=lambda: clock[0]), \
                patch('twittui_form.time.sleep', side_effect=sleep), \
                patch('twittui_form.requests.get', side_effect=lambda *a, **k: (starts.append(clock[0]), SimpleNamespace(status_code=200, text=''))[1]):
            threads = [threading.Thread(target=call) for _ in range(6)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

        self.assertEqual(starts, [0, 1, 2, 3, 4, 60])


class TestBackgroundEpisodes(unittest.TestCase):
    def test_old_selection_result_is_discarded(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.show_combo = SimpleNamespace(value='First')
        form.show_ids = {'First': 1, 'Second': 2}
        form.current_episodes = []
        form._cancel_hover_timer = MagicMock()
        form.update_episodes_display = MagicMock()
        jobs = []
        form._run_network = lambda work, done: jobs.append((work, done))

        form.load_episodes_for_selected_show()
        form.show_combo.value = 'Second'
        form.load_episodes_for_selected_show()
        jobs[1][1](([{'title': 'Second'}], 1))
        jobs[0][1](([{'title': 'First'}], 1))
        self.assertEqual(form.current_episodes, [{'title': 'Second'}])


class TestRateLimitModal(unittest.TestCase):
    def test_desktop_wait_window_is_centered_on_main_window(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form._main_window = MagicMock()
        form._main_window.position = (300, 200)
        form._main_window.size = (1000, 700)
        form._impl.native = SimpleNamespace()
        window = MagicMock()
        window.size = (440, 220)
        window._impl.native = SimpleNamespace(set_decorated=MagicMock())
        with patch('twittui_form.toga.Window', return_value=window) as create, \
                patch('twittui_form.toga.Box'), patch('twittui_form.toga.Label'), \
                patch('twittui_form.toga.ActivityIndicator') as indicator:
            form._set_rate_limit_wait(True)
        self.assertFalse(create.call_args.kwargs['closable'])
        self.assertFalse(create.call_args.kwargs['resizable'])
        self.assertFalse(create.call_args.kwargs['minimizable'])
        self.assertEqual(window.position, (580, 440))
        style = indicator.call_args.kwargs['style']
        self.assertEqual((style.width, style.height), (128, 128))
        self.assertEqual(str(style.color), 'rgb(255 0 0 / 1.0)')
        window._impl.native.set_decorated.assert_called_once_with(True)
        window.show.assert_called_once()

    def test_gtk_wait_window_hides_title_buttons(self):
        for existing_header in (False, True):
            with self.subTest(existing_header=existing_header):
                form = TwitTUIForm('TestApp', 'org.twit.test')
                form._main_window = MagicMock()
                form._main_window.position = (0, 0)
                form._main_window.size = (800, 600)
                form._impl.native = SimpleNamespace()
                native = MagicMock()
                header = MagicMock()
                impl = type('GtkWindow', (), {'__module__': 'toga_gtk.window'})()
                impl.native = native
                if existing_header:
                    impl.headerbar = header
                window = MagicMock()
                window._impl = impl
                gtk = SimpleNamespace(HeaderBar=MagicMock(return_value=header))
                with patch.dict('sys.modules', {'toga_gtk.libs': SimpleNamespace(Gtk=gtk)}), \
                        patch('twittui_form.toga.Window', return_value=window), \
                        patch('twittui_form.toga.Box'), patch('twittui_form.toga.Label'), \
                        patch('twittui_form.toga.ActivityIndicator'):
                    form._set_rate_limit_wait(True)
                header.set_decoration_layout.assert_called_once_with(':')
                if existing_header:
                    native.set_titlebar.assert_not_called()
                else:
                    native.set_titlebar.assert_called_once_with(header)
                window.show.assert_called_once()

    def test_reentrant_show_creates_only_one_window(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form._main_window = MagicMock()
        form._main_window.position = (0, 0)
        form._main_window.size = (800, 600)
        form._impl.native = SimpleNamespace()
        window = MagicMock(spec=['_impl', 'content', 'show', 'hide', 'close'])
        window._impl = MagicMock()
        window.show.side_effect = lambda: form._set_rate_limit_wait(True)
        with patch('twittui_form.toga.Window', return_value=window) as create, \
                patch('twittui_form.toga.Box'), patch('twittui_form.toga.Label'), \
                patch('twittui_form.toga.ActivityIndicator'):
            form._set_rate_limit_wait(True)
            self.assertEqual(create.call_count, 1)
            form._set_rate_limit_wait(False)
            form._set_rate_limit_wait(False)
            self.assertEqual(window.method_calls[-2:], [unittest.mock.call.hide(), unittest.mock.call.close()])
            window.close.assert_called_once()

    def test_api_request_on_ui_thread_does_not_block_event_loop(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        limiter = ApiRateLimiter()
        limiter.wait_callback = form._rate_limit_wait_changed

        async def run():
            with patch.object(type(form), 'loop', new_callable=unittest.mock.PropertyMock, return_value=asyncio.get_running_loop()), \
                    patch('twittui_form.requests.get') as request:
                with self.assertRaises(RuntimeError):
                    limiter.get('url')
                request.assert_not_called()

        asyncio.run(run())

    def test_overlapping_requests_keep_modal_open(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        window = MagicMock()
        form._rate_limit_window = window
        form._api_wait_count = 1
        form._set_rate_limit_wait(True)
        form._set_rate_limit_wait(False)
        window.close_wait.assert_not_called()
        form._set_rate_limit_wait(False)
        window.close_wait.assert_called_once()

    def test_worker_waits_for_modal_before_request(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        events = []
        form._set_rate_limit_wait = events.append

        async def run():
            with patch.object(type(form), 'loop', new_callable=unittest.mock.PropertyMock, return_value=asyncio.get_running_loop()):
                await asyncio.to_thread(form._rate_limit_wait_changed, True)
                self.assertEqual(events, [True])
                await asyncio.to_thread(form._rate_limit_wait_changed, False)
                await asyncio.sleep(0)
                self.assertEqual(events, [True, False])

        asyncio.run(run())

    def test_textual_modal_displays_and_closes(self):
        from textual.app import App
        from textual.widgets import LoadingIndicator
        from toga_textual_backend import RateLimitScreen

        async def run():
            app = App()
            async with app.run_test() as pilot:
                screen = RateLimitScreen()
                await app.push_screen(screen)
                self.assertIs(app.screen, screen)
                self.assertEqual(len(screen.query(LoadingIndicator)), 1)
                self.assertIn('TWiT API', str(screen.query_one('Label').renderable))
                screen.close_wait()
                await pilot.pause()
                self.assertIsNot(app.screen, screen)

        asyncio.run(run())

    def test_textual_modal_closes_after_overlapping_dialog(self):
        from textual.app import App
        from textual.screen import ModalScreen
        from toga_textual_backend import RateLimitScreen

        async def run():
            app = App()
            async with app.run_test() as pilot:
                screen = RateLimitScreen()
                await app.push_screen(screen)
                other = ModalScreen()
                await app.push_screen(other)
                screen.close_wait()
                self.assertIs(app.screen, other)
                other.dismiss()
                await pilot.pause()
                self.assertIsNot(app.screen, screen)

        asyncio.run(run())

    def test_wait_notifications_are_dispatched_to_ui_loop(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form._set_rate_limit_wait = MagicMock()
        with patch.object(type(form), 'loop', new_callable=unittest.mock.PropertyMock) as loop:
            loop.return_value.is_running.return_value = False
            form._rate_limit_wait_changed(True)
            loop.return_value.call_soon_threadsafe.assert_called_once_with(form._set_rate_limit_wait, True)


if __name__ == '__main__':
    unittest.main()