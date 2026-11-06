"""Unit tests for TwitTUI Snap packaging specification and configuration."""

import os
import stat
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
except ImportError:
    yaml = None

from twittui_form import TwitTUIForm, load_twittui_dotenv


class TestSnapPackaging(unittest.TestCase):
    """Test suite for Snapcraft recipe, desktop entry, launcher, and Snap integration."""

    def setUp(self) -> None:
        self.project_root = os.path.dirname(os.path.abspath(__file__))

    def test_snapcraft_yaml_exists_and_valid(self) -> None:
        """Verify snap/snapcraft.yaml exists, is valid YAML, and specifies expected fields."""
        snapcraft_path = os.path.join(self.project_root, "snap", "snapcraft.yaml")
        self.assertTrue(os.path.isfile(snapcraft_path), "snap/snapcraft.yaml must exist")

        with open(snapcraft_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("name: twittui", content)
        self.assertTrue("base: core22" in content or "base: core24" in content)
        self.assertIn("confinement: strict", content)
        self.assertIn("apps:", content)
        self.assertIn("parts:", content)

        if yaml is not None:
            data = yaml.safe_load(content)
            self.assertEqual(data.get("name"), "twittui")
            self.assertIn(data.get("base"), ["core22", "core24"])
            self.assertEqual(data.get("confinement"), "strict")
            self.assertIn("apps", data)
            self.assertIn("twittui", data["apps"])
            self.assertIn("parts", data)
            self.assertIn("twittui", data["parts"])

            # Verify plugs
            plugs = data["apps"]["twittui"].get("plugs", [])
            for required_plug in ["network", "audio-playback", "home", "desktop", "x11", "wayland"]:
                self.assertIn(required_plug, plugs)

            # Verify build and stage packages
            build_packages = data["parts"]["twittui"].get("build-packages", [])
            stage_packages = data["parts"]["twittui"].get("stage-packages", [])
            self.assertIn("shared-mime-info", build_packages)
            self.assertIn("shared-mime-info", stage_packages)
            self.assertIn("update-mime-database", data["parts"]["twittui"].get("override-build", ""))

    def test_desktop_entry_file(self) -> None:
        """Verify snap/gui/twittui.desktop exists and contains standard freedesktop entries."""
        desktop_path = os.path.join(self.project_root, "snap", "gui", "twittui.desktop")
        self.assertTrue(os.path.isfile(desktop_path), "snap/gui/twittui.desktop must exist")

        with open(desktop_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertIn("[Desktop Entry]", lines)
        self.assertTrue(any(line.startswith("Name=") for line in lines))
        self.assertTrue(any(line.startswith("Exec=") for line in lines))
        self.assertTrue(any(line.startswith("Icon=") for line in lines))
        self.assertTrue(any(line.startswith("Type=Application") for line in lines))
        self.assertTrue(any(line.startswith("Categories=") for line in lines))

    def test_snap_icon_exists(self) -> None:
        """Verify snap/gui/twittui.png exists and is non-empty."""
        icon_path = os.path.join(self.project_root, "snap", "gui", "twittui.png")
        self.assertTrue(os.path.isfile(icon_path), "snap/gui/twittui.png must exist")
        self.assertGreater(os.path.getsize(icon_path), 0)

    def test_launcher_script(self) -> None:
        """Verify snap/local/launcher.sh exists, is executable, and contains launcher logic."""
        launcher_path = os.path.join(self.project_root, "snap", "local", "launcher.sh")
        self.assertTrue(os.path.isfile(launcher_path), "snap/local/launcher.sh must exist")

        # Verify executable permissions
        file_stat = os.stat(launcher_path)
        self.assertTrue(bool(file_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)))

        with open(launcher_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("#!/bin/bash", content)
        self.assertIn("SNAP", content)
        self.assertIn("PYTHONPATH", content)
        self.assertIn("GDK_PIXBUF_MODULEDIR", content)
        self.assertIn("LD_LIBRARY_PATH", content)
        self.assertIn("unset GTK_MODULES", content)
        self.assertIn("GSETTINGS_SCHEMA_DIR", content)

    def test_requirements_and_setup(self) -> None:
        """Verify requirements.txt and setup.py/pyproject.toml exist and declare core dependencies."""
        req_path = os.path.join(self.project_root, "requirements.txt")
        self.assertTrue(os.path.isfile(req_path), "requirements.txt must exist")
        with open(req_path, "r", encoding="utf-8") as f:
            req_content = f.read()
        self.assertIn("toga", req_content)
        self.assertIn("toga-gtk", req_content)
        self.assertIn("toga-textual", req_content)

        setup_path = os.path.join(self.project_root, "setup.py")
        self.assertTrue(os.path.isfile(setup_path), "setup.py must exist")

        pyproject_path = os.path.join(self.project_root, "pyproject.toml")
        self.assertTrue(os.path.isfile(pyproject_path), "pyproject.toml must exist")

    def test_snap_user_data_env_loading(self) -> None:
        """Verify load_twittui_dotenv loads configuration from SNAP_USER_DATA."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            snap_env = os.path.join(tmp_dir, ".env")
            with open(snap_env, "w", encoding="utf-8") as f:
                f.write("TWITAPI_APPLICATIONID=snap_test_app_id\n")

            with patch.dict(os.environ, {"SNAP_USER_DATA": tmp_dir}):
                load_twittui_dotenv()
                self.assertEqual(os.environ.get("TWITAPI_APPLICATIONID"), "snap_test_app_id")

    def test_snap_user_data_env_saving(self) -> None:
        """Verify save_env_setting persists configuration into SNAP_USER_DATA."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"SNAP_USER_DATA": tmp_dir}):
                app_dummy = TwitTUIForm.__new__(TwitTUIForm)
                app_dummy.save_env_setting("TWITCLUBSTREAMER", "snap_custom_vlc %f")

                target_file = os.path.join(tmp_dir, ".env")
                self.assertTrue(os.path.isfile(target_file))
                with open(target_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertIn("snap_custom_vlc %f", content)
                self.assertIn("TWITCLUBSTREAMER=", content)

    def test_snap_resource_resolution(self) -> None:
        """Verify resolve_app_icon finds resources in SNAP directory."""
        from twittui_form import resolve_app_icon
        with tempfile.TemporaryDirectory() as tmp_snap:
            res_dir = os.path.join(tmp_snap, "resources")
            os.makedirs(res_dir, exist_ok=True)
            with open(os.path.join(res_dir, "twittui.png"), "wb") as f:
                f.write(b"PNGDATA")

            with patch.dict(os.environ, {"SNAP": tmp_snap}):
                resolved = resolve_app_icon()
                self.assertIsNotNone(resolved)
                self.assertTrue(resolved.startswith(os.path.join(tmp_snap, "resources")))


if __name__ == "__main__":
    unittest.main()
