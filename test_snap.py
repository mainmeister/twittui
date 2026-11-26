"""Unit tests for TwitTUI Snap packaging specification and configuration."""

import os
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

try:
    import yaml
except ImportError:
    yaml = None

from twittui_form import TwitTUIForm, load_twittui_dotenv


class TestSnapPackaging(unittest.TestCase):
    """Test suite for Snapcraft recipe, desktop entry, launcher, and Snap integration."""

    def setUp(self) -> None:
        self.project_root = os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def _extract_yaml_list(content: str, section_key: str) -> list[str]:
        """Indentation-aware YAML list extractor used as a fallback when PyYAML is absent."""
        items: list[str] = []
        in_section = False
        section_indent = -1
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            if in_section:
                if indent <= section_indent:
                    break
                if stripped.startswith("- "):
                    items.append(stripped[2:].strip().strip('"').strip("'"))
            elif stripped == f"{section_key}:":
                in_section = True
                section_indent = indent
        return items

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
            twittui_part = data["parts"]["twittui"]
            build_packages = twittui_part.get("build-packages", [])
            stage_packages = twittui_part.get("stage-packages", [])
            self.assertIn("shared-mime-info", build_packages)
            self.assertIn("shared-mime-info", stage_packages)
            self.assertIn("mpv", stage_packages)
            self.assertIn("ffmpeg", stage_packages)
            override_pull = twittui_part.get("override-pull", "")
            self.assertIn(".env", override_pull)
            self.assertIn("craftctl default", override_pull)
            override_build = twittui_part.get("override-build", "")
            self.assertIn("update-mime-database", override_build)
            self.assertIn("requirements-snap.txt", override_build)
            self.assertIn("pip install --no-deps .", override_build)
            self.assertNotIn("cp -a *.py", override_build)
            for list_key in ("stage", "prime"):
                entries = twittui_part.get(list_key, [])
                self.assertNotIn("*.py", entries)
                self.assertNotIn("*.md", entries)
                self.assertIn(".env.example", entries)
        else:
            plugs = self._extract_yaml_list(content, "plugs")
            for required_plug in ["network", "audio-playback", "home", "desktop", "x11", "wayland"]:
                self.assertIn(required_plug, plugs)

            build_packages = self._extract_yaml_list(content, "build-packages")
            stage_packages = self._extract_yaml_list(content, "stage-packages")
            self.assertIn("shared-mime-info", build_packages)
            self.assertIn("shared-mime-info", stage_packages)
            self.assertIn("mpv", stage_packages)
            self.assertIn("ffmpeg", stage_packages)

            stage_entries = self._extract_yaml_list(content, "stage")
            prime_entries = self._extract_yaml_list(content, "prime")
            for entries in (stage_entries, prime_entries):
                self.assertNotIn("*.py", entries)
                self.assertNotIn("*.md", entries)
                self.assertIn(".env.example", entries)

            self.assertIn("override-pull:", content)
            self.assertIn("craftctl default", content)
            self.assertIn("requirements-snap.txt", content)
            self.assertIn("pip install --no-deps .", content)
            self.assertIn("update-mime-database", content)
            self.assertNotIn("cp -a *.py", content)

        # Verify .env.example template referenced by launcher.sh exists, uses valid keys, and contains no secrets
        env_example_path = os.path.join(self.project_root, ".env.example")
        self.assertTrue(os.path.isfile(env_example_path), ".env.example must exist for Snap launcher")
        with open(env_example_path, "r", encoding="utf-8") as f:
            env_example_content = f.read()
        self.assertIn("TWITCLUBSHOWFOLDERS=0", env_example_content)
        self.assertNotIn("TWITSHOWFOLDERS=", env_example_content)
        # Blank optional overrides must remain commented out so load_dotenv(override=True) does not clobber launcher exports
        uncommented_lines = [
            line.strip() for line in env_example_content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertNotIn("TWITCLUBSTREAMER=", uncommented_lines)
        self.assertNotIn("TWITCLUBDESTINATION=", uncommented_lines)

        # Verify pinned requirements-snap.txt lockfile exists and pins every non-comment entry with ==
        lockfile_path = os.path.join(self.project_root, "requirements-snap.txt")
        self.assertTrue(os.path.isfile(lockfile_path), "requirements-snap.txt lockfile must exist")
        with open(lockfile_path, "r", encoding="utf-8") as f:
            lock_lines = [
                line.strip() for line in f.read().splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        self.assertGreaterEqual(len(lock_lines), 10)
        for dep in lock_lines:
            self.assertIn("==", dep, f"Lockfile dependency must be pinned with '==': {dep}")

    def test_yaml_fallback_parser_and_pyyaml_dev_dependency(self) -> None:
        """Verify the YAML fallback parser always runs (even when PyYAML is present) and pyproject declares PyYAML."""
        snapcraft_path = os.path.join(self.project_root, "snap", "snapcraft.yaml")
        with open(snapcraft_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Fallback parser must accurately isolate stage-packages vs build-packages
        stage_packages = self._extract_yaml_list(content, "stage-packages")
        self.assertIn("shared-mime-info", stage_packages)
        self.assertIn("mpv", stage_packages)
        self.assertIn("ffmpeg", stage_packages)
        # Synthetic YAML missing shared-mime-info from stage-packages must be caught even if present in build-packages
        broken_yaml = (
            "parts:\n"
            "  twittui:\n"
            "    build-packages:\n"
            "      - shared-mime-info\n"
            "    stage-packages:\n"
            "      - libgtk-3-0\n"
        )
        self.assertNotIn("shared-mime-info", self._extract_yaml_list(broken_yaml, "stage-packages"))

        # Verify pyproject.toml declares PyYAML in dev optional dependencies
        pyproject_path = os.path.join(self.project_root, "pyproject.toml")
        with open(pyproject_path, "r", encoding="utf-8") as f:
            pyproject_text = f.read()
        self.assertIn("PyYAML", pyproject_text)

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
        self.assertIn("$SNAP/bin:$SNAP/usr/bin", content)
        self.assertIn("install -m 600", content)
        self.assertIn('export TWITCLUBSTREAMER="mpv %f"', content)
        self.assertIn("PYTHONPATH", content)
        self.assertIn("GDK_PIXBUF_MODULEDIR", content)
        self.assertIn("LD_LIBRARY_PATH", content)
        self.assertIn("unset GTK_MODULES", content)
        self.assertIn("GSETTINGS_SCHEMA_DIR", content)

    def test_launcher_prefers_bundled_mpv_and_initializes_private_env(self) -> None:
        """Verify host VLC visibility cannot override bundled mpv or user configuration."""
        launcher_path = os.path.join(self.project_root, "snap", "local", "launcher.sh")
        with tempfile.TemporaryDirectory() as tmp_dir:
            snap_root = os.path.join(tmp_dir, "snap")
            snap_bin = os.path.join(snap_root, "bin")
            snap_usr_bin = os.path.join(snap_root, "usr", "bin")
            snap_user_data = os.path.join(tmp_dir, "user-data")
            host_bin = os.path.join(tmp_dir, "host-bin")
            home = os.path.join(tmp_dir, "home")
            for path in (snap_bin, snap_usr_bin, snap_user_data, host_bin, home):
                os.makedirs(path, exist_ok=True)

            with open(os.path.join(snap_root, ".env.example"), "w", encoding="utf-8") as fh:
                fh.write("TWITCLUBSHOWFOLDERS=0\n")
            for path, content in (
                (os.path.join(snap_usr_bin, "mpv"), "#!/bin/sh\nexit 0\n"),
                (os.path.join(host_bin, "vlc"), "#!/bin/sh\nexit 0\n"),
                (
                    os.path.join(snap_bin, "python3"),
                    "#!/bin/sh\nprintf 'streamer=%s\\n' \"${TWITCLUBSTREAMER:-}\"\n",
                ),
            ):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                os.chmod(path, 0o755)

            env = {
                "HOME": home,
                "PATH": f"{host_bin}:/usr/bin:/bin",
                "SNAP": snap_root,
                "SNAP_USER_DATA": snap_user_data,
            }
            result = subprocess.run(
                ["bash", launcher_path, "--tui"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("streamer=mpv %f", result.stdout)

            env_file = os.path.join(snap_user_data, ".env")
            self.assertTrue(os.path.isfile(env_file))
            self.assertEqual(stat.S_IMODE(os.stat(env_file).st_mode), 0o600)
            with open(env_file, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "TWITCLUBSHOWFOLDERS=0\n")

            with open(env_file, "w", encoding="utf-8") as fh:
                fh.write("TWITCLUBSTREAMER=custom-player %f\n")
            subprocess.run(
                ["bash", launcher_path, "--tui"],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            with open(env_file, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "TWITCLUBSTREAMER=custom-player %f\n")

    def test_requirements_and_pyproject(self) -> None:
        """Verify requirements.txt and consolidated pyproject.toml exist (without redundant setup.py)."""
        req_path = os.path.join(self.project_root, "requirements.txt")
        self.assertTrue(os.path.isfile(req_path), "requirements.txt must exist")
        with open(req_path, "r", encoding="utf-8") as f:
            req_content = f.read()
        requirement_lines = [
            line.strip()
            for line in req_content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(requirement_lines, ["."], "requirements.txt must use project metadata as its source")

        setup_path = os.path.join(self.project_root, "setup.py")
        self.assertFalse(os.path.exists(setup_path), "redundant setup.py should be consolidated into pyproject.toml")

        pyproject_path = os.path.join(self.project_root, "pyproject.toml")
        self.assertTrue(os.path.isfile(pyproject_path), "pyproject.toml must exist")
        with open(pyproject_path, "rb") as f:
            meta = tomllib.load(f)
        self.assertEqual(meta["build-system"]["build-backend"], "setuptools.build_meta")
        self.assertIn("toga-core>=0.4.0", meta["project"]["dependencies"])
        self.assertFalse(any(d.lower().startswith("toga>=") for d in meta["project"]["dependencies"]))
        self.assertTrue(any("toga-gtk" in d and "sys_platform" in d for d in meta["project"]["optional-dependencies"]["gtk"]))
        self.assertIn("twittui.resources", meta["tool"]["setuptools"]["packages"])

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
