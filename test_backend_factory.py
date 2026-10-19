"""Unit tests verifying factory widget resolution and isolation for GTK and Textual backends."""

import os
import unittest
import importlib
import toga.platform
from toga_textual_backend import patch_toga_textual, TextualSelection, TextualTable


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


if __name__ == '__main__':
    unittest.main()
