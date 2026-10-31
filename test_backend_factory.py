"""Unit tests verifying factory widget resolution and isolation for GTK and Textual backends."""

import os
import unittest
import importlib
import toga
import toga.platform
from toga_textual_backend import patch_toga_textual, TextualSelection, TextualTable
from textual.widgets import Select


class TestBackendFactoryIsolation(unittest.TestCase):
    """Test that patching toga_textual does not overwrite widgets on GTK backend."""

    def test_gtk_factory_preserves_native_widgets(self) -> None:
        """Verify GTK factory keeps toga_gtk implementations for Selection and Table."""
        os.environ['TOGA_BACKEND'] = 'toga_gtk'
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()

        patch_toga_textual()
        factory = toga.platform.get_factory()

        if importlib.util.find_spec('toga_gtk') is not None:
            from toga_gtk.widgets.selection import Selection as GtkSelection
            from toga_gtk.widgets.table import Table as GtkTable
            self.assertEqual(factory.Selection, GtkSelection)
            self.assertEqual(factory.Table, GtkTable)
            self.assertNotEqual(factory.Selection, TextualSelection)
            self.assertNotEqual(factory.Table, TextualTable)

    def test_textual_factory_uses_textual_widgets(self) -> None:
        """Verify Textual factory uses TextualSelection and TextualTable."""
        os.environ['TOGA_BACKEND'] = 'toga_textual'
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()

        patch_toga_textual()
        factory = toga.platform.get_factory()

        self.assertEqual(factory.Selection, TextualSelection)
        self.assertEqual(factory.Table, TextualTable)

    def test_textual_selection_sync_and_change(self) -> None:
        """Verify TextualSelection populates options and fires on_change correctly."""
        import asyncio
        from textual.app import App, ComposeResult

        os.environ['TOGA_BACKEND'] = 'toga_textual'
        toga.platform.get_backend.cache_clear()
        toga.platform.get_factory.cache_clear()
        patch_toga_textual()

        changed_values = []
        sel = toga.Selection(
            items=['Show 1', 'Show 2', 'Show 3'],
            on_change=lambda widget: changed_values.append(widget.value)
        )

        class SelectionTestApp(App):
            def compose(self) -> ComposeResult:
                yield sel._impl.native

        async def run_selection_test() -> None:
            app = SelectionTestApp()
            async with app.run_test() as pilot:
                # Options should be synced upon mount
                self.assertEqual(len(sel._impl.native._options), 3)
                self.assertEqual(sel._impl.native.value, '0')
                self.assertEqual(sel.value, 'Show 1')

                # Change selection to index 1 ("Show 2")
                sel._impl.native.value = '1'
                await pilot.pause()
                self.assertEqual(sel.value, 'Show 2')
                self.assertIn('Show 2', changed_values)

                # Programmatic change via Toga
                sel.value = 'Show 3'
                await pilot.pause()
                self.assertEqual(sel._impl.native.value, '2')
                self.assertEqual(sel.value, 'Show 3')

        asyncio.run(run_selection_test())


if __name__ == '__main__':
    unittest.main()
