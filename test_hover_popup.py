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

    def test_hover_popup_with_phonetic_search_match_shows_phonetic_summary(self):
        ep_data = {
            'number': '520',
            'title': 'Security Now 520',
            'date': '2015-08-11',
            'show_name': 'Security Now',
            'description': 'Steve is away this week, so Fr. Robert Ballecer joins Leo Laporte to discuss security vulnerabilities.'
        }
        target = SimpleNamespace(episode_data=ep_data, title='Security Now 520', episode='520', show='Security Now')
        self.form.search_input = MagicMock(value='ballacer')

        meta = self.form.extract_episode_metadata_fields(target)
        self.assertIsNotNone(meta.get('match_context'))
        self.assertEqual(meta['match_context'].field_name, 'Description / Show Notes')
        self.assertIn('Phonetic Match', meta['match_context'].match_tier)
        self.assertIn('Ballecer', meta['match_context'].snippet)

        _, message = self.form.format_episode_metadata(target, meta=meta)
        self.assertIn('[🔍 Search Match]', message)
        self.assertIn('• Field: Description / Show Notes', message)
        self.assertIn('• Match Type: Phonetic Match ("ballacer" ≈ "Ballecer")', message)
        self.assertIn('Robert Ballecer', message)

    def test_hover_popup_with_exact_search_match_shows_exact_summary(self):
        ep_data = {
            'number': '1049',
            'title': 'MacBreak Weekly 1049: Stagefright Alert',
            'date': '2026-11-03',
            'show_name': 'MacBreak Weekly',
            'description': 'Discussion of Apple silicon updates and new MacBooks.'
        }
        target = SimpleNamespace(episode_data=ep_data, title=ep_data['title'], episode='1049', show='MacBreak Weekly')
        self.form.search_input = MagicMock(value='Stagefright')

        meta = self.form.extract_episode_metadata_fields(target)
        self.assertIsNotNone(meta.get('match_context'))
        self.assertEqual(meta['match_context'].field_name, 'Title')
        self.assertEqual(meta['match_context'].match_tier, 'Exact Match')

        _, message = self.form.format_episode_metadata(target, meta=meta)
        self.assertIn('[🔍 Search Match]', message)
        self.assertIn('• Field: Title', message)
        self.assertIn('• Match Type: Exact Match', message)
        self.assertIn('Stagefright', message)

    def test_hover_popup_with_fuzzy_search_match_shows_fuzzy_similarity(self):
        ep_data = {
            'number': '800',
            'title': 'This Week in Tech 800: Network Security Update',
            'date': '2021-04-12',
            'show_name': 'This Week in Tech',
            'description': 'Exploring computer security and firewall architectures.'
        }
        target = SimpleNamespace(episode_data=ep_data, title=ep_data['title'], episode='800', show='This Week in Tech')
        self.form.search_input = MagicMock(value='aecurity')

        meta = self.form.extract_episode_metadata_fields(target)
        self.assertIsNotNone(meta.get('match_context'))
        self.assertIn('Fuzzy Match', meta['match_context'].match_tier)
        self.assertIn('security', meta['match_context'].snippet.lower())

        _, message = self.form.format_episode_metadata(target, meta=meta)
        self.assertIn('[🔍 Search Match]', message)
        self.assertIn('• Match Type: Fuzzy Match', message)

    def test_hover_popup_without_search_does_not_show_match_summary(self):
        ep_data = {
            'number': '100',
            'title': 'Standard Episode',
            'date': '2026-01-01',
            'show_name': 'Standard Show',
            'description': 'Normal description without active search.'
        }
        target = SimpleNamespace(episode_data=ep_data, title=ep_data['title'], episode='100', show='Standard Show')
        self.form.search_input = MagicMock(value='')

        meta = self.form.extract_episode_metadata_fields(target)
        self.assertIsNone(meta.get('match_context'))

        _, message = self.form.format_episode_metadata(target, meta=meta)
        self.assertNotIn('[🔍 Search Match]', message)

    def test_gtk_custom_window_includes_search_match_callout_box(self):
        ep_data = {
            'number': '520',
            'title': 'Security Now 520',
            'date': '2015-08-11',
            'show_name': 'Security Now',
            'description': 'Steve is away this week, so Fr. Robert Ballecer joins Leo Laporte.'
        }
        target = SimpleNamespace(episode_data=ep_data, title='Security Now 520', episode='520', show='Security Now')
        self.form.search_input = MagicMock(value='ballacer')
        fake_gtk_app = SimpleNamespace(__class__=SimpleNamespace(__module__='toga_gtk.app'))
        self.form._impl = SimpleNamespace(native=fake_gtk_app)
        os.environ['TOGA_BACKEND'] = 'toga_gtk'

        with patch('twittui_form.toga.Window') as mock_win_cls:
            mock_win = MagicMock()
            mock_win_cls.return_value = mock_win

            self.form.show_episode_metadata_dialog(target)

            self.assertIsNotNone(self.form._metadata_window)
            mock_win.show.assert_called_once()
            content = mock_win.content
            self.assertIsNotNone(content)
            labels = [c.text for c in content.children if isinstance(c, toga.Label)]
            box_labels = []
            for c in content.children:
                if isinstance(c, toga.Box):
                    box_labels.extend([child.text for child in c.children if isinstance(child, toga.Label)])
            all_labels = labels + box_labels
            self.assertTrue(any('🔍 Search Match' in l for l in all_labels))
            self.assertTrue(any('Phonetic Match' in l for l in all_labels))

    def test_metadata_link_labels_not_hardcoded_below_natural_width(self):
        ep_data = {
            'number': '1049',
            'title': 'MacBreak Weekly 1049',
            'date': '2026-11-03',
            'show_name': 'MacBreak Weekly',
            'cleanPath': 'shows/macbreak-weekly/episodes/1049',
            'transcript_url': 'https://twit.tv/posts/transcripts/macbreak-weekly-1049-transcript',
            'media_url': 'https://cdn.twit.tv/video/mbw/mbw1049/mbw1049_h264m_1280x720_1872.mp4',
            'description': 'Episode notes.',
        }
        target = SimpleNamespace(
            episode_data=ep_data,
            title=ep_data['title'],
            episode='1049',
            show='MacBreak Weekly',
            media_url=ep_data['media_url'],
        )
        fake_gtk_app = SimpleNamespace(__class__=SimpleNamespace(__module__='toga_gtk.app'))
        self.form._impl = SimpleNamespace(native=fake_gtk_app)
        os.environ['TOGA_BACKEND'] = 'toga_gtk'

        with patch('twittui_form.toga.Window') as mock_win_cls:
            mock_win = MagicMock()
            mock_win_cls.return_value = mock_win
            self.form.show_episode_metadata_dialog(target)

            content = mock_win.content
            link_rows = {}
            for child in content.children:
                if isinstance(child, toga.Box) and len(child.children) == 2:
                    first, second = child.children
                    if isinstance(first, toga.Label) and isinstance(second, toga.Button):
                        link_rows[first.text] = (first, second)

            self.assertEqual(set(link_rows.keys()), {'Web Link:', 'Transcript:', 'Media URL:'})
            for label_text, (lbl, _btn) in link_rows.items():
                lbl_width = lbl.style.width
                if lbl_width not in (None, 'none'):
                    self.assertGreaterEqual(
                        int(lbl_width),
                        144,
                        f"{label_text} width ({lbl_width}) is too narrow and will be overwritten by the field",
                    )

    def test_configure_metadata_link_rows_aligns_gtk_labels_and_ellipsizes_buttons(self):
        FakeGtkLabelImpl = type('FakeGtkLabelImpl', (), {'__module__': 'toga_gtk.widgets.label'})
        FakeGtkButtonImpl = type('FakeGtkButtonImpl', (), {'__module__': 'toga_gtk.widgets.button'})

        rows = []
        for pref_w in (125, 138, 190):
            lbl_impl = FakeGtkLabelImpl()
            lbl_impl.rehint = MagicMock()
            lbl_impl.native = MagicMock()
            lbl_impl.native.get_preferred_width.return_value = (pref_w, pref_w)
            lbl = SimpleNamespace(
                _impl=lbl_impl,
                intrinsic=SimpleNamespace(width=pref_w),
                style=SimpleNamespace(width=None),
            )

            btn_child = MagicMock()
            btn_impl = FakeGtkButtonImpl()
            btn_impl.rehint = MagicMock()
            btn_impl.native = MagicMock()
            btn_impl.native.get_child.return_value = btn_child
            btn = SimpleNamespace(_impl=btn_impl)

            rows.append((lbl, btn))

        content_box = MagicMock()
        self.form._configure_metadata_link_rows(rows, content_box)

        for lbl, btn in rows:
            self.assertEqual(lbl.style.width, 198)  # max(125, 138, 190) + 8
            btn._impl.native.get_child.return_value.set_xalign.assert_called_once_with(0.0)
            self.assertTrue(btn._impl.native.get_child.return_value.set_ellipsize.called)
            btn._impl.rehint.assert_called_once()
        content_box.refresh.assert_called_once()


class TestHoverPopupGtkLayout(unittest.TestCase):
    """Live GTK layout test verifying link labels are never overwritten by URL fields on Episode Details."""

    def test_gtk_episode_details_link_labels_not_overwritten_by_fields(self):
        import json
        import shutil
        import subprocess
        import sys
        import textwrap

        if not shutil.which('xvfb-run'):
            self.skipTest('Requires xvfb-run for live GTK layout verification')

        probe_script = textwrap.dedent(
            """
            import json
            import os
            import tempfile
            from types import SimpleNamespace

            os.environ["TOGA_BACKEND"] = "toga_gtk"
            import toga
            from toga_gtk.libs import GLib
            from twittui_form import TwitTUIForm

            TwitTUIForm._refresh_catalog = lambda self: None
            TwitTUIForm.show_splash_screen = lambda self, *a, **kw: None

            db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            db.close()
            app = TwitTUIForm("TWIT.tv TUI", "org.twit.metapopup", cache_db_path=db.name)
            rows_report = []

            orig_startup = app.startup
            def wrapped_startup():
                orig_startup()
                ep_data = {
                    "number": "1049",
                    "title": "MacBreak Weekly 1049: Test Episode",
                    "date": "2026-11-03",
                    "duration": 7200,
                    "size": 1500000000,
                    "show_name": "MacBreak Weekly",
                    "cleanPath": "shows/macbreak-weekly/episodes/1049",
                    "transcript_url": "https://twit.tv/posts/transcripts/macbreak-weekly-1049-transcript",
                    "media_url": "https://cdn.twit.tv/video/mbw/mbw1049/mbw1049_h264m_1280x720_1872.mp4?token=verylongtoken1234567890",
                    "description": "Show notes.",
                }
                target = SimpleNamespace(
                    episode_data=ep_data,
                    title=ep_data["title"],
                    episode="1049",
                    show="MacBreak Weekly",
                    media_url=ep_data["media_url"],
                )
                app.show_episode_metadata_dialog(target)

                def inspect_popup():
                    win = app._metadata_window
                    cont = win._impl.container
                    for child in win.content.children:
                        if isinstance(child, toga.Box) and len(child.children) == 2:
                            lbl, btn = child.children
                            if isinstance(lbl, toga.Label) and isinstance(btn, toga.Button):
                                lbl_nat = lbl._impl.native
                                btn_nat = btn._impl.native
                                min_w, nat_w = lbl_nat.get_preferred_width()
                                lbl_pos = lbl_nat.translate_coordinates(cont, 0, 0)
                                btn_pos = btn_nat.translate_coordinates(cont, 0, 0)
                                rows_report.append({
                                    "label": lbl.text,
                                    "lbl_layout_left": lbl.layout.absolute_content_left,
                                    "lbl_layout_width": lbl.layout.content_width,
                                    "lbl_alloc_width": lbl_nat.get_allocated_width(),
                                    "lbl_min_width": min_w,
                                    "lbl_nat_width": nat_w,
                                    "lbl_x": lbl_pos[0] if lbl_pos else lbl.layout.absolute_content_left,
                                    "btn_layout_left": btn.layout.absolute_content_left,
                                    "btn_x": btn_pos[0] if btn_pos else btn.layout.absolute_content_left,
                                    "btn_alloc_width": btn_nat.get_allocated_width(),
                                    "win_width": cont.get_allocated_width(),
                                })
                    app._impl.native.quit()
                    return False

                GLib.timeout_add(300, inspect_popup)

            app.startup = wrapped_startup
            app.main_loop()
            os.unlink(db.name)
            print("META_POPUP_JSON:" + json.dumps(rows_report))
            """
        )

        proc = subprocess.run(
            ['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, '-c', probe_script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=f"GTK probe failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

        json_line = next(
            (line[len('META_POPUP_JSON:'):] for line in proc.stdout.splitlines() if line.startswith('META_POPUP_JSON:')),
            None,
        )
        self.assertIsNotNone(json_line, msg=f"Missing META_POPUP_JSON output:\n{proc.stdout}")
        rows = json.loads(json_line)
        self.assertEqual([r['label'] for r in rows], ['Web Link:', 'Transcript:', 'Media URL:'])

        btn_starts = set()
        for row in rows:
            # Label allocation must accommodate its full natural rendered text width
            self.assertGreaterEqual(
                row['lbl_alloc_width'],
                row['lbl_nat_width'],
                msg=f"{row['label']} allocated {row['lbl_alloc_width']}px < natural {row['lbl_nat_width']}px",
            )
            # Button must start strictly to the right of the rendered label text (never overwriting it)
            lbl_text_right_edge = row['lbl_x'] + row['lbl_nat_width']
            self.assertGreater(
                row['btn_x'],
                lbl_text_right_edge,
                msg=f"{row['label']} text right edge ({lbl_text_right_edge}) overwritten by field at x={row['btn_x']}",
            )
            btn_starts.add(row['btn_x'])

        # All three link fields should align cleanly at the same horizontal start coordinate
        self.assertEqual(len(btn_starts), 1, msg=f"Expected aligned field start coordinates, got {btn_starts}")


if __name__ == '__main__':
    unittest.main()
