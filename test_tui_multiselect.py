"""Unit and Textual pilot tests for TUI multi-select visual feedback and interactions."""

import asyncio
import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("TOGA_BACKEND", "toga_textual")

from rich.style import Style
from textual import events
from textual.app import App, ComposeResult
import toga
import toga.platform

from toga_textual_backend import TogaDataTable, patch_toga_textual
from twittui_form import TwitTUIForm


def _ensure_textual_backend() -> None:
    os.environ["TOGA_BACKEND"] = "toga_textual"
    toga.platform.get_backend.cache_clear()
    toga.platform.get_factory.cache_clear()
    patch_toga_textual()


class TestTuiMultiSelectVisualFeedback(unittest.TestCase):
    """Verify visual markers, row styles, shortcuts, mouse clicks, and state resets."""

    def setUp(self) -> None:
        _ensure_textual_backend()

    def test_space_toggle_renders_checkbox_labels_and_persistent_row_style(self) -> None:
        """Marked rows render ☑ labels and marked-row styles even after cursor moves away."""
        select_events: list[int] = []
        table = toga.Table(
            columns=["Episode", "Title", "Date"],
            multiple_select=True,
            on_select=lambda w: select_events.append(len(w._impl.native._marked_rows)),
            data=[
                {"episode": "101", "title": "Episode Alpha", "date": "2026-11-01"},
                {"episode": "102", "title": "Episode Beta", "date": "2026-11-02"},
                {"episode": "103", "title": "Episode Gamma", "date": "2026-11-03"},
                {"episode": "104", "title": "Episode Delta", "date": "2026-11-04"},
            ],
        )
        native: TogaDataTable = table._impl.native

        class TableTestApp(App):
            def compose(self) -> ComposeResult:
                yield native

        async def run_check() -> None:
            app = TableTestApp()
            async with app.run_test(size=(90, 20)) as pilot:
                native.focus()
                await pilot.pause()

                # Data columns stay untouched; checkbox indicators live in pinned row labels
                self.assertEqual([c.label.plain for c in native.ordered_columns], ["Episode", "Title", "Date"])
                self.assertTrue(native._should_render_row_labels)
                self.assertEqual(
                    [r.label.plain for r in native.ordered_rows],
                    ["☐", "☐", "☐", "☐"],
                )
                self.assertFalse(native.check_action("clear_row_selection", ()))

                # Mark row 0 and row 2, then move cursor down to unmarked row 3
                await pilot.press("space")
                await pilot.press("down", "down")
                await pilot.press("space")
                await pilot.press("down")
                await pilot.pause()

                self.assertEqual(native.cursor_row, 3)
                self.assertEqual(
                    [r.label.plain for r in native.ordered_rows],
                    ["☑", "☐", "☑", "☐"],
                )
                self.assertEqual([r.episode for r in table.selection], ["101", "103"])
                self.assertTrue(native.check_action("clear_row_selection", ()))

                # Marked rows use distinct bold highlight style compared to unmarked rows
                marked_style_0 = native._get_row_style(0, native.rich_style)
                unmarked_style_1 = native._get_row_style(1, native.rich_style)
                marked_style_2 = native._get_row_style(2, native.rich_style)
                self.assertEqual(marked_style_0, marked_style_2)
                self.assertNotEqual(marked_style_0, unmarked_style_1)
                self.assertTrue(marked_style_0.bold)

                # Rendered terminal lines include visible ☑ and ☐ markers
                rendered_text = "\n".join(
                    line.text for line in [native.render_line(y) for y in range(6)]
                )
                self.assertIn("☑", rendered_text)
                self.assertIn("☐", rendered_text)
                self.assertGreaterEqual(len(select_events), 2)

        asyncio.run(run_check())

    def test_shift_arrow_range_select_and_rollback_preserves_prior_marks(self) -> None:
        """Shift+Down/Shift+Up selects a contiguous range, rolls back cleanly, and keeps prior marks."""
        table = toga.Table(
            columns=["Episode", "Title"],
            multiple_select=True,
            data=[
                {"episode": str(100 + i), "title": f"Ep {i}"}
                for i in range(6)
            ],
        )
        native: TogaDataTable = table._impl.native

        class TableTestApp(App):
            def compose(self) -> ComposeResult:
                yield native

        async def run_check() -> None:
            app = TableTestApp()
            async with app.run_test(size=(80, 20)) as pilot:
                native.focus()
                await pilot.pause()

                # Mark row 0 with Space, then move normally to row 2
                await pilot.press("space")
                await pilot.press("down", "down")
                self.assertEqual(native.cursor_row, 2)

                # Shift+Down twice: selects range 2..4 while preserving row 0
                await pilot.press("shift+down", "shift+down")
                await pilot.pause()
                self.assertEqual(native.cursor_row, 4)
                self.assertEqual(native._marked_rows, {0, 2, 3, 4})
                self.assertEqual(
                    [r.label.plain for r in native.ordered_rows],
                    ["☑", "☐", "☑", "☑", "☑", "☐"],
                )

                # Shift+Up once: rolls back row 4 without losing {0, 2, 3}
                await pilot.press("shift+up")
                await pilot.pause()
                self.assertEqual(native.cursor_row, 3)
                self.assertEqual(native._marked_rows, {0, 2, 3})
                self.assertEqual(
                    [r.label.plain for r in native.ordered_rows],
                    ["☑", "☐", "☑", "☑", "☐", "☐"],
                )

        asyncio.run(run_check())

    def test_select_all_and_clear_shortcuts(self) -> None:
        """Ctrl+A selects all rows and Escape / u clears all marked rows."""
        table = toga.Table(
            columns=["Episode", "Title"],
            multiple_select=True,
            data=[
                {"episode": "1", "title": "First"},
                {"episode": "2", "title": "Second"},
                {"episode": "3", "title": "Third"},
            ],
        )
        native: TogaDataTable = table._impl.native

        class TableTestApp(App):
            def compose(self) -> ComposeResult:
                yield native

        async def run_check() -> None:
            app = TableTestApp()
            async with app.run_test(size=(80, 16)) as pilot:
                native.focus()
                await pilot.pause()

                await pilot.press("ctrl+a")
                await pilot.pause()
                self.assertEqual(native._marked_rows, {0, 1, 2})
                self.assertEqual([r.label.plain for r in native.ordered_rows], ["☑", "☑", "☑"])

                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(native._marked_rows, set())
                self.assertEqual([r.label.plain for r in native.ordered_rows], ["☐", "☐", "☐"])

                # Also verify 'u' clears marked rows
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(native._marked_rows, {0})
                await pilot.press("u")
                await pilot.pause()
                self.assertEqual(native._marked_rows, set())
                self.assertEqual([r.label.plain for r in native.ordered_rows], ["☐", "☐", "☐"])

        asyncio.run(run_check())

    def test_mouse_gutter_ctrl_and_shift_clicks_toggle_without_activating(self) -> None:
        """Checkbox gutter click, Ctrl+Click, and Shift+Click update marks without firing on_activate."""
        activated: list[str] = []
        table = toga.Table(
            columns=["Episode", "Title"],
            multiple_select=True,
            on_activate=lambda w, row, **kw: activated.append(row.episode),
            data=[
                {"episode": "10", "title": "Row Zero"},
                {"episode": "20", "title": "Row One"},
                {"episode": "30", "title": "Row Two"},
                {"episode": "40", "title": "Row Three"},
                {"episode": "50", "title": "Row Four"},
            ],
        )
        native: TogaDataTable = table._impl.native

        class TableTestApp(App):
            def compose(self) -> ComposeResult:
                yield native

        def make_click(row: int, column: int, *, ctrl: bool = False, shift: bool = False) -> events.Click:
            style = Style.from_meta({"row": row, "column": column})
            return events.Click(
                native,
                x=1,
                y=row + 1,
                delta_x=0,
                delta_y=0,
                button=1,
                shift=shift,
                meta=False,
                ctrl=ctrl,
                style=style,
            )

        async def run_check() -> None:
            app = TableTestApp()
            async with app.run_test(size=(80, 16)) as pilot:
                native.focus()
                await pilot.pause()

                # Click checkbox label on row 1 (column == -1)
                await native._on_click(make_click(1, -1))
                await pilot.pause()
                self.assertEqual(native._marked_rows, {1})
                self.assertEqual(activated, [])
                self.assertEqual(native.ordered_rows[1].label.plain, "☑")

                # Shift+Click data cell on row 3 -> marks range 1..3 without activating
                await native._on_click(make_click(3, 1, shift=True))
                await pilot.pause()
                self.assertEqual(native._marked_rows, {1, 2, 3})
                self.assertEqual(activated, [])

                # Ctrl+Click data cell on row 2 -> unmarks row 2 without activating
                await native._on_click(make_click(2, 0, ctrl=True))
                await pilot.pause()
                self.assertEqual(native._marked_rows, {1, 3})
                self.assertEqual(activated, [])
                self.assertEqual(
                    [r.label.plain for r in native.ordered_rows],
                    ["☐", "☑", "☐", "☑", "☐"],
                )

                # Plain click on data cell still triggers row selection / on_activate
                await native._on_click(make_click(0, 0))
                await pilot.pause()
                self.assertEqual(activated, ["10"])

        asyncio.run(run_check())

    def test_change_source_clears_stale_marks_and_insert_remove_shift_indices(self) -> None:
        """Reloading data resets marks; inserting/removing items shifts marked row indices accurately."""
        table = toga.Table(
            columns=["Episode", "Title"],
            multiple_select=True,
            data=[
                {"episode": "1", "title": "A"},
                {"episode": "2", "title": "B"},
                {"episode": "3", "title": "C"},
            ],
        )
        native: TogaDataTable = table._impl.native

        class TableTestApp(App):
            def compose(self) -> ComposeResult:
                yield native

        async def run_check() -> None:
            app = TableTestApp()
            async with app.run_test(size=(80, 16)) as pilot:
                native.focus()
                await pilot.pause()

                # Mark row 1 ("2" / "B")
                await pilot.press("down", "space")
                await pilot.pause()
                self.assertEqual([r.episode for r in table.selection], ["2"])

                # Insert at index 0 -> "2" moves to index 2 and keeps its ☑ mark
                table.data.insert(0, {"episode": "0", "title": "Zero"})
                await pilot.pause()
                self.assertEqual(native._marked_rows, {2})
                self.assertEqual([r.episode for r in table.selection], ["2"])
                self.assertEqual([r.label.plain for r in native.ordered_rows], ["☐", "☐", "☑", "☐"])

                # Remove index 1 ("1" / "A") -> "2" moves back to index 1 and keeps its ☑ mark
                del table.data[1]
                await pilot.pause()
                self.assertEqual(native._marked_rows, {1})
                self.assertEqual([r.episode for r in table.selection], ["2"])
                self.assertEqual([r.label.plain for r in native.ordered_rows], ["☐", "☑", "☐"])

                # Reassigning table.data (e.g. show switch / search / sort) clears stale marks
                table.data = [
                    {"episode": "900", "title": "New Show Ep 1"},
                    {"episode": "901", "title": "New Show Ep 2"},
                ]
                await pilot.pause()
                self.assertEqual(native._marked_rows, set())
                self.assertEqual([r.label.plain for r in native.ordered_rows], ["☐", "☐"])

        asyncio.run(run_check())

    def test_single_select_table_hides_checkbox_gutter_and_multiselect_actions(self) -> None:
        """Tables with multiple_select=False do not render ☐/☑ row labels or multi-select actions."""
        table = toga.Table(
            columns=["Episode", "Title"],
            multiple_select=False,
            data=[
                {"episode": "1", "title": "Single A"},
                {"episode": "2", "title": "Single B"},
            ],
        )
        native: TogaDataTable = table._impl.native

        class TableTestApp(App):
            def compose(self) -> ComposeResult:
                yield native

        async def run_check() -> None:
            app = TableTestApp()
            async with app.run_test(size=(80, 12)) as pilot:
                native.focus()
                await pilot.pause()

                self.assertFalse(native._should_render_row_labels)
                self.assertFalse(native.check_action("toggle_row_select", ()))
                self.assertFalse(native.check_action("select_all_rows", ()))
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(native._marked_rows, set())
                self.assertEqual(table.selection.episode, "1")

        asyncio.run(run_check())

    def test_twittui_form_updates_episodes_label_with_selection_count(self) -> None:
        """TwitTUIForm updates 'Episodes (N selected):' live as rows are marked, cleared, or reloaded."""
        form = TwitTUIForm("TwitTUI", "org.twit.multiselecttest")
        form.load_shows_from_api = MagicMock()
        form.load_episodes_for_selected_show = MagicMock()
        form.show_splash_screen = MagicMock()
        form.close_splash_screen = MagicMock()
        form.startup()

        form.current_episodes = [
            {"number": "1001", "title": "Security Now 1001", "date": "2026-11-01", "duration": "01:30:00", "size": "50000000"},
            {"number": "1002", "title": "Security Now 1002", "date": "2026-11-08", "duration": "01:45:00", "size": "60000000"},
            {"number": "1003", "title": "Security Now 1003", "date": "2026-11-15", "duration": "02:00:00", "size": "70000000"},
        ]
        form.update_episodes_display()
        native: TogaDataTable = form.episodes_list._impl.native

        class FormTableApp(App):
            def compose(self) -> ComposeResult:
                yield form.episodes_label._impl.native
                yield native

        async def run_check() -> None:
            app = FormTableApp()
            async with app.run_test(size=(100, 20)) as pilot:
                native.focus()
                await pilot.pause()

                self.assertEqual(form.episodes_label.text, "Episodes:")

                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(form.episodes_label.text, "Episodes (1 selected):")

                await pilot.press("down", "space")
                await pilot.pause()
                self.assertEqual(form.episodes_label.text, "Episodes (2 selected):")

                await pilot.press("ctrl+a")
                await pilot.pause()
                self.assertEqual(form.episodes_label.text, "Episodes (3 selected):")

                # Reloading episodes display (e.g., sorting or switching show) resets count and marks
                form.update_episodes_display()
                await pilot.pause()
                self.assertEqual(native._marked_rows, set())
                self.assertEqual(form.episodes_label.text, "Episodes:")

        asyncio.run(run_check())


if __name__ == "__main__":
    unittest.main()
