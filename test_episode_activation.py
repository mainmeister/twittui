import asyncio
import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault('TOGA_BACKEND', 'toga_textual')

import toga
from twittui_form import TwitTUIForm


class TestEpisodeActivation(unittest.IsolatedAsyncioTestCase):
    async def test_table_activation_schedules_stream_handler(self):
        form = TwitTUIForm('TestApp', 'org.twit.test')
        form.on_stream_press = AsyncMock()
        table = toga.Table(columns=['Title'], on_activate=form.on_episode_activate)
        row = object()

        table.on_activate(row=row)
        await asyncio.sleep(0)

        form.on_stream_press.assert_awaited_once_with(table)