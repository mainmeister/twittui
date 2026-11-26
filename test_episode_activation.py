import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

import toga
from toga.style import Pack
from toga_textual_backend import patch_toga_textual
from twittui_form import TwitTUIForm


class TestEpisodeActivation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        os.environ['TOGA_BACKEND'] = 'toga_textual'
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()
        patch_toga_textual()

    async def test_table_activation_schedules_stream_handler(self):
        form = TwitTUIForm('TestApp', 'org.twit.test', cache_db_path=':memory:')
        form.on_stream_press = AsyncMock()
        table = toga.Table(columns=['Title'], on_activate=form.on_episode_activate)
        row = object()

        table.on_activate(row=row)
        await asyncio.sleep(0)

        form.on_stream_press.assert_awaited_once_with(table, target_row=row)

    async def test_tui_enter_streams_activated_row_even_when_other_row_marked(self):
        """End-to-end Textual DataTable: marking row 0 with Space then pressing Enter on row 2 streams row 2."""
        from textual.app import App, ComposeResult

        form = TwitTUIForm('TestApp', 'org.twit.test', cache_db_path=':memory:')
        form.is_audio_only = lambda: False

        rows = [
            {
                'episode': str(i),
                'title': f'Episode {i}',
                'episode_data': {
                    'title': f'Episode {i}',
                    'number': str(i),
                    'video_hd': {'mediaUrl': f'https://cdn.twit.tv/ep{i}.mp4'},
                },
            }
            for i in range(4)
        ]
        table = toga.Table(
            headings=['Episode', 'Title'],
            accessors=['episode', 'title'],
            data=rows,
            multiple_select=True,
            on_activate=form.on_episode_activate,
            style=Pack(flex=1),
        )
        form.episodes_list = table

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield table._impl.native

        launched_cmds = []

        def fake_popen(cmd, *args, **kwargs):
            launched_cmds.append(cmd)
            return SimpleNamespace(pid=12345)

        with patch('twittui_form.resolve_stream_url', side_effect=lambda u: u), \
             patch('twittui_form.subprocess.Popen', side_effect=fake_popen):
            harness = _Harness()
            async with harness.run_test() as pilot:
                table._impl._sync_data_to_native(force=True)
                await pilot.pause()
                table._impl.native.focus()
                await pilot.pause()

                # Mark row 0 with Space, then move cursor down to row 2
                await pilot.press('space')
                await pilot.pause()
                await pilot.press('down')
                await pilot.press('down')
                await pilot.pause()

                # Selection holds marked row 0, while cursor sits on row 2
                self.assertEqual([r.episode for r in table.selection], ['0'])
                self.assertEqual(table._impl.native.cursor_row, 2)

                # Press Enter to activate row 2 -> must stream ep2.mp4, NOT marked ep0.mp4
                await pilot.press('enter')
                for _ in range(10):
                    if launched_cmds:
                        break
                    await asyncio.sleep(0.02)

        self.assertEqual(len(launched_cmds), 1)
        self.assertIn('https://cdn.twit.tv/ep2.mp4', launched_cmds[0])
        self.assertNotIn('https://cdn.twit.tv/ep0.mp4', launched_cmds[0])

    async def test_rapid_row_activation_supersedes_earlier_inflight_stream(self):
        """Activating row 3 while row 2 is still resolving cancels row 2 and only launches row 3."""
        form = TwitTUIForm('TestApp', 'org.twit.test', cache_db_path=':memory:')
        form.is_audio_only = lambda: False

        row2 = SimpleNamespace(
            title='Episode 2',
            episode='2',
            episode_data={'title': 'Episode 2', 'video_hd': {'mediaUrl': 'https://cdn.twit.tv/ep2.mp4'}},
        )
        row3 = SimpleNamespace(
            title='Episode 3',
            episode='3',
            episode_data={'title': 'Episode 3', 'video_hd': {'mediaUrl': 'https://cdn.twit.tv/ep3.mp4'}},
        )
        form.episodes_list = SimpleNamespace(selection=[row2])

        gate = asyncio.Event()
        first_started = asyncio.Event()
        orig_to_thread = asyncio.to_thread

        def fake_resolve(url):
            return url

        async def gated_to_thread(fn, *args, **kwargs):
            if fn is fake_resolve and args and 'ep2.mp4' in str(args[0]):
                first_started.set()
                await gate.wait()
            return await orig_to_thread(fn, *args, **kwargs)

        launched_cmds = []
        with patch('twittui_form.asyncio.to_thread', side_effect=gated_to_thread), \
             patch('twittui_form.resolve_stream_url', fake_resolve), \
             patch('twittui_form.subprocess.Popen', side_effect=lambda cmd, *a, **kw: launched_cmds.append(cmd)):
            t1 = asyncio.create_task(form.on_episode_activate(form.episodes_list, row=row2))
            await asyncio.wait_for(first_started.wait(), timeout=5.0)
            t2 = asyncio.create_task(form.on_episode_activate(form.episodes_list, row=row3))
            await asyncio.wait_for(t2, timeout=5.0)
            gate.set()
            await asyncio.wait_for(t1, timeout=5.0)

        self.assertEqual(len(launched_cmds), 1)
        self.assertIn('https://cdn.twit.tv/ep3.mp4', launched_cmds[0])
