"""Unit tests for the TwitTUI install option and PyInstaller integration."""

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from installer import (
    build_executable,
    check_python_shared_library,
    clean_build_artifacts,
    ensure_pyinstaller_installed,
    find_local_executable_path,
    format_shared_library_error,
    get_default_executable_name,
    install_twittui,
    is_pyinstaller_installed,
)
from main import parse_backend_args


class TestInstallOption(unittest.TestCase):
    """Test suite for CLI install arguments, PATH resolution, and packaging pipeline."""

    def test_parse_install_args(self) -> None:
        """Verify CLI argument parser correctly parses --install, -i, and cleanup flags."""
        args1 = parse_backend_args(["--install"])
        self.assertTrue(args1.install)
        self.assertIsNone(args1.install_dir)
        self.assertFalse(args1.clean)

        args2 = parse_backend_args(["-i"])
        self.assertTrue(args2.install)
        self.assertIsNone(args2.install_dir)

        args3 = parse_backend_args(["--install", "--install-dir", "/custom/bin"])
        self.assertTrue(args3.install)
        self.assertEqual(args3.install_dir, "/custom/bin")

        args4 = parse_backend_args(["--gtk"])
        self.assertFalse(args4.install)
        self.assertFalse(args4.clean)

        args5 = parse_backend_args(["--clean"])
        self.assertTrue(args5.clean)

        args6 = parse_backend_args(["--cleanup"])
        self.assertTrue(args6.clean)

        args7 = parse_backend_args(["-c"])
        self.assertTrue(args7.clean)

        args8 = parse_backend_args(["--install", "--no-clean", "--uninstall-pyinstaller"])
        self.assertTrue(args8.install)
        self.assertTrue(args8.no_clean)
        self.assertTrue(args8.uninstall_pyinstaller)

        args9 = parse_backend_args(["--install", "--python-executable", "/usr/bin/python3"])
        self.assertTrue(args9.install)
        self.assertEqual(args9.python_executable, "/usr/bin/python3")

    def test_default_executable_name(self) -> None:
        """Verify executable name is platform appropriate."""
        exe_name = get_default_executable_name()
        if platform.system() == "Windows":
            self.assertEqual(exe_name, "twittui.exe")
        else:
            self.assertEqual(exe_name, "twittui")

    def test_find_local_executable_path_explicit_target(self) -> None:
        """Verify explicit target directory is resolved, created, and returned."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_target = os.path.join(tmp_dir, "my_bin")
            resolved = find_local_executable_path(target_dir=custom_target)
            self.assertEqual(resolved, os.path.abspath(custom_target))
            self.assertTrue(os.path.isdir(resolved))

    def test_find_local_executable_path_from_path_env(self) -> None:
        """Verify find_local_executable_path selects a writable directory from PATH."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_bin = os.path.join(tmp_dir, "bin")
            os.makedirs(test_bin, exist_ok=True)
            with patch.dict(os.environ, {"PATH": f"{test_bin}{os.pathsep}/usr/bin"}):
                resolved = find_local_executable_path()
                self.assertEqual(resolved, os.path.abspath(test_bin))

    def test_find_local_executable_path_fallback(self) -> None:
        """Verify find_local_executable_path creates and returns a fallback directory if none in PATH is writable."""
        with patch.dict(os.environ, {"PATH": "/nonexistent/readonly/path"}):
            resolved = find_local_executable_path()
            self.assertTrue(os.path.isabs(resolved))
            self.assertTrue(os.path.isdir(resolved))

    def test_is_pyinstaller_installed(self) -> None:
        """Verify pyinstaller detection function."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self.assertTrue(is_pyinstaller_installed(python_executable="/usr/bin/python3"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            self.assertFalse(is_pyinstaller_installed(python_executable="/usr/bin/python3"))

        with patch("shutil.which", return_value="/usr/bin/pyinstaller"):
            self.assertTrue(is_pyinstaller_installed())

        with patch("shutil.which", return_value=None), patch.dict(sys.modules, {"PyInstaller": None}):
            # Should safely return False or handle import gracefully
            with patch("subprocess.run", return_value=MagicMock(returncode=1)), patch("importlib.util.find_spec", return_value=None):
                val = is_pyinstaller_installed()
                self.assertIsInstance(val, bool)

    @patch("subprocess.run")
    def test_ensure_pyinstaller_installed_success(self, mock_run: MagicMock) -> None:
        """Verify ensure_pyinstaller_installed executes pip upgrade command when not already installed."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr=""),  # version check in is_pyinstaller_installed
            MagicMock(returncode=0, stdout="Successfully installed", stderr=""),  # pip install
        ]
        result = ensure_pyinstaller_installed(python_executable="python_mock")
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        cmd = mock_run.call_args[0][0]
        self.assertIn("pip", cmd)
        self.assertIn("pyinstaller", cmd)

    @patch("subprocess.run")
    def test_ensure_pyinstaller_installed_fallback_on_existing(self, mock_run: MagicMock) -> None:
        """Verify graceful fallback if pip fails but PyInstaller is already present."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["pip"], stderr="Network unreachable")
        with patch("installer.is_pyinstaller_installed", return_value=True):
            result = ensure_pyinstaller_installed()
            self.assertTrue(result)

    @patch("subprocess.run")
    def test_ensure_pyinstaller_installed_failure(self, mock_run: MagicMock) -> None:
        """Verify RuntimeError is raised when pip fails and PyInstaller is not installed."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["pip"], stderr="Package not found")
        with patch("installer.is_pyinstaller_installed", return_value=False):
            with self.assertRaises(RuntimeError):
                ensure_pyinstaller_installed()

    @patch("installer.check_python_shared_library", return_value=(True, ""))
    @patch("subprocess.run")
    def test_build_executable_command_flags(self, mock_run: MagicMock, mock_check: MagicMock) -> None:
        """Verify PyInstaller is invoked with non-debug and standalone packaging flags."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            dist_dir = os.path.join(tmp_dir, "dist")
            os.makedirs(dist_dir, exist_ok=True)
            exe_name = get_default_executable_name()
            fake_exe = os.path.join(dist_dir, exe_name)
            with open(fake_exe, "w") as f:
                f.write("binary-content")

            mock_run.return_value = MagicMock(returncode=0, stdout="Build complete", stderr="")

            built = build_executable(project_root=tmp_dir, output_dir=dist_dir, python_executable="python_test")
            self.assertEqual(built, fake_exe)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]

            self.assertIn("--onefile", cmd)
            self.assertIn("--clean", cmd)
            self.assertIn("--noconfirm", cmd)
            # Ensure --debug is NOT present for non-debug build
            self.assertNotIn("--debug", cmd)

    def test_install_twittui_end_to_end(self) -> None:
        """Verify full install_twittui workflow copies the binary and sets permissions."""
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as install_target_dir:
            # Create a mock built executable in dist
            dist_dir = os.path.join(project_dir, "dist")
            os.makedirs(dist_dir, exist_ok=True)
            exe_name = get_default_executable_name()
            fake_exe = os.path.join(dist_dir, exe_name)
            with open(fake_exe, "w") as f:
                f.write("#!/bin/sh\necho TwitTUI\n")

            with patch("installer.ensure_pyinstaller_installed", return_value=True), \
                 patch("installer.build_executable", return_value=fake_exe):
                installed_path = install_twittui(
                    target_dir=install_target_dir,
                    project_root=project_dir,
                    clean_build_artifacts=True,
                )

                self.assertTrue(os.path.isfile(installed_path))
                self.assertEqual(os.path.dirname(installed_path), os.path.abspath(install_target_dir))
                self.assertEqual(os.path.basename(installed_path), exe_name)

                # Verify permissions on POSIX
                if platform.system() != "Windows":
                    st = os.stat(installed_path)
                    self.assertTrue(bool(st.st_mode & stat.S_IXUSR))

    def test_clean_build_artifacts_removes_dirs_and_specs(self) -> None:
        """Verify clean_build_artifacts removes build/, dist/, and .spec files."""
        with tempfile.TemporaryDirectory() as project_dir:
            build_dir = os.path.join(project_dir, "build")
            dist_dir = os.path.join(project_dir, "dist")
            spec_file = os.path.join(project_dir, "twittui.spec")
            extra_spec = os.path.join(project_dir, "custom.spec")
            dummy_src = os.path.join(project_dir, "main.py")

            os.makedirs(build_dir, exist_ok=True)
            os.makedirs(dist_dir, exist_ok=True)
            with open(os.path.join(build_dir, "temp.o"), "w") as f:
                f.write("object")
            with open(os.path.join(dist_dir, "twittui"), "w") as f:
                f.write("binary")
            with open(spec_file, "w") as f:
                f.write("spec")
            with open(extra_spec, "w") as f:
                f.write("spec2")
            with open(dummy_src, "w") as f:
                f.write("print('keep')")

            removed = clean_build_artifacts(project_root=project_dir)

            self.assertFalse(os.path.exists(build_dir))
            self.assertFalse(os.path.exists(dist_dir))
            self.assertFalse(os.path.exists(spec_file))
            self.assertFalse(os.path.exists(extra_spec))
            self.assertTrue(os.path.exists(dummy_src))
            self.assertEqual(len(removed), 4)

    def test_clean_build_artifacts_selective_flags(self) -> None:
        """Verify selective flags in clean_build_artifacts only remove specified targets."""
        with tempfile.TemporaryDirectory() as project_dir:
            build_dir = os.path.join(project_dir, "build")
            dist_dir = os.path.join(project_dir, "dist")
            spec_file = os.path.join(project_dir, "twittui.spec")

            os.makedirs(build_dir, exist_ok=True)
            os.makedirs(dist_dir, exist_ok=True)
            with open(spec_file, "w") as f:
                f.write("spec")

            clean_build_artifacts(
                project_root=project_dir,
                remove_dist=False,
                remove_build=True,
                remove_spec=False,
            )

            self.assertFalse(os.path.exists(build_dir))
            self.assertTrue(os.path.exists(dist_dir))
            self.assertTrue(os.path.exists(spec_file))

    @patch("subprocess.run")
    def test_clean_build_artifacts_remove_pyinstaller_package(self, mock_run: MagicMock) -> None:
        """Verify remove_pyinstaller triggers pip uninstall."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Successfully uninstalled", stderr="")
        with tempfile.TemporaryDirectory() as project_dir:
            removed = clean_build_artifacts(
                project_root=project_dir,
                remove_dist=False,
                remove_build=False,
                remove_spec=False,
                remove_pyinstaller=True,
                python_executable="python_mock",
            )
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            self.assertIn("pip", cmd)
            self.assertIn("uninstall", cmd)
            self.assertIn("pyinstaller", cmd)
            self.assertIn("pyinstaller (pip package)", removed)

    def test_install_twittui_cleans_dist_and_build_by_default(self) -> None:
        """Verify install_twittui cleans up dist/ and build/ folders post-install when clean_build_artifacts=True."""
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as install_target_dir:
            dist_dir = os.path.join(project_dir, "dist")
            build_dir = os.path.join(project_dir, "build")
            spec_file = os.path.join(project_dir, "twittui.spec")
            os.makedirs(dist_dir, exist_ok=True)
            os.makedirs(build_dir, exist_ok=True)
            with open(spec_file, "w") as f:
                f.write("spec")

            exe_name = get_default_executable_name()
            fake_exe = os.path.join(dist_dir, exe_name)
            with open(fake_exe, "w") as f:
                f.write("#!/bin/sh\necho TwitTUI\n")

            with patch("installer.ensure_pyinstaller_installed", return_value=True), \
                 patch("installer.build_executable", return_value=fake_exe):
                installed_path = install_twittui(
                    target_dir=install_target_dir,
                    project_root=project_dir,
                    clean_build_artifacts=True,
                )

                self.assertTrue(os.path.isfile(installed_path))
                self.assertFalse(os.path.exists(dist_dir))
                self.assertFalse(os.path.exists(build_dir))
                self.assertFalse(os.path.exists(spec_file))

    def test_install_twittui_preserves_artifacts_when_clean_is_false(self) -> None:
        """Verify install_twittui keeps dist/ and build/ when clean_build_artifacts=False."""
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as install_target_dir:
            dist_dir = os.path.join(project_dir, "dist")
            build_dir = os.path.join(project_dir, "build")
            spec_file = os.path.join(project_dir, "twittui.spec")
            os.makedirs(dist_dir, exist_ok=True)
            os.makedirs(build_dir, exist_ok=True)
            with open(spec_file, "w") as f:
                f.write("spec")

            exe_name = get_default_executable_name()
            fake_exe = os.path.join(dist_dir, exe_name)
            with open(fake_exe, "w") as f:
                f.write("#!/bin/sh\necho TwitTUI\n")

            with patch("installer.ensure_pyinstaller_installed", return_value=True), \
                 patch("installer.build_executable", return_value=fake_exe):
                installed_path = install_twittui(
                    target_dir=install_target_dir,
                    project_root=project_dir,
                    clean_build_artifacts=False,
                )

                self.assertTrue(os.path.isfile(installed_path))
                self.assertTrue(os.path.exists(dist_dir))
                self.assertTrue(os.path.exists(build_dir))
                self.assertTrue(os.path.exists(spec_file))

    def test_resolve_toga_backend_clean_flag(self) -> None:
        """Verify resolve_toga_backend intercepts --clean and executes clean_build_artifacts."""
        from main import resolve_toga_backend
        with patch("installer.clean_build_artifacts") as mock_clean, patch("sys.exit") as mock_exit:
            resolve_toga_backend(["--clean", "--uninstall-pyinstaller"])
            mock_clean.assert_called_once_with(remove_pyinstaller=True, python_executable=None)
            mock_exit.assert_called_once_with(0)

    def test_resolve_toga_backend_install_flag(self) -> None:
        """Verify resolve_toga_backend intercepts --install and terminates without launching UI."""
        from main import resolve_toga_backend
        with patch("installer.install_twittui") as mock_install, patch("sys.exit") as mock_exit:
            resolve_toga_backend(["--install", "--install-dir", "/tmp/testbin"])
            mock_install.assert_called_once_with(target_dir="/tmp/testbin", python_executable=None, clean_build_artifacts=True)
            mock_exit.assert_called_once_with(0)

    def test_configure_gtk_environment(self) -> None:
        """Verify configure_gtk_environment configures env vars and GI namespace versions."""
        from main import configure_gtk_environment
        with patch.dict(os.environ, {"GTK_DEBUG": "1", "GDK_BACKEND": "wayland"}):
            configure_gtk_environment()
            self.assertEqual(os.environ.get("GTK_MODULES"), "")
            self.assertNotIn("GTK_DEBUG", os.environ)
            self.assertEqual(os.environ.get("NO_AT_BRIDGE"), "1")
            self.assertEqual(os.environ.get("GDK_BACKEND"), "x11")
            self.assertEqual(os.environ.get("G_MESSAGES_DEBUG"), "")

    @patch("installer.check_python_shared_library", return_value=(True, ""))
    @patch("importlib.util.find_spec")
    @patch("subprocess.run")
    def test_build_executable_collects_toga_gtk(self, mock_run: MagicMock, mock_find_spec: MagicMock, mock_check: MagicMock) -> None:
        """Verify build_executable includes --collect-all=toga_gtk when available."""
        mock_find_spec.return_value = MagicMock()
        with tempfile.TemporaryDirectory() as tmp_dir:
            dist_dir = os.path.join(tmp_dir, "dist")
            os.makedirs(dist_dir, exist_ok=True)
            exe_name = get_default_executable_name()
            fake_exe = os.path.join(dist_dir, exe_name)
            with open(fake_exe, "w") as f:
                f.write("binary-content")

            mock_run.return_value = MagicMock(returncode=0, stdout="Build complete", stderr="")
            build_executable(project_root=tmp_dir, output_dir=dist_dir, python_executable="python_test")
            cmd = mock_run.call_args[0][0]
            self.assertIn("--collect-all=toga_gtk", cmd)

    @patch("installer.check_python_shared_library", return_value=(True, ""))
    @patch("subprocess.run")
    def test_build_executable_includes_icon_and_resources(self, mock_run: MagicMock, mock_check: MagicMock) -> None:
        """Verify build_executable includes --icon and --add-data for resources directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            dist_dir = os.path.join(tmp_dir, "dist")
            res_dir = os.path.join(tmp_dir, "resources")
            os.makedirs(dist_dir, exist_ok=True)
            os.makedirs(res_dir, exist_ok=True)

            # Create dummy icon files
            with open(os.path.join(res_dir, "twittui.png"), "w") as f:
                f.write("fake-png-data")
            with open(os.path.join(res_dir, "twittui.ico"), "w") as f:
                f.write("fake-ico-data")

            exe_name = get_default_executable_name()
            fake_exe = os.path.join(dist_dir, exe_name)
            with open(fake_exe, "w") as f:
                f.write("binary-content")

            mock_run.return_value = MagicMock(returncode=0, stdout="Build complete", stderr="")
            build_executable(project_root=tmp_dir, output_dir=dist_dir, python_executable="python_test")
            cmd = mock_run.call_args[0][0]

            # Verify --icon argument is passed
            icon_flag = any(arg.startswith("--icon=") for arg in cmd)
            self.assertTrue(icon_flag, f"--icon flag missing from command: {cmd}")

            # Verify resources directory is added to data
            data_flags = [arg for arg in cmd if arg.startswith("--add-data=")]
            has_resources = any("resources" in arg for arg in data_flags)
            self.assertTrue(has_resources, f"resources data flag missing from command: {cmd}")

    def test_resolve_app_icon(self) -> None:
        """Verify resolve_app_icon locates valid application icon resources."""
        from twittui_form import resolve_app_icon
        icon_path = resolve_app_icon()
        self.assertIsNotNone(icon_path)
        self.assertTrue(os.path.isfile(f"{icon_path}.png") or os.path.isfile(icon_path))

    def test_generate_all_icons(self) -> None:
        """Verify generate_all_icons creates PNG, ICO, and SVG assets in target directory."""
        from generate_icon import generate_all_icons
        with tempfile.TemporaryDirectory() as tmp_dir:
            res_dir = os.path.join(tmp_dir, "resources")
            created_files = generate_all_icons(res_dir)
            self.assertTrue(len(created_files) >= 9)
            self.assertTrue(os.path.isfile(os.path.join(res_dir, "twittui.svg")))
            self.assertTrue(os.path.isfile(os.path.join(res_dir, "twittui.png")))
            self.assertTrue(os.path.isfile(os.path.join(res_dir, "twittui.ico")))
            self.assertTrue(os.path.isfile(os.path.join(res_dir, "twittui-256.png")))

    def test_format_shared_library_error(self) -> None:
        """Verify format_shared_library_error outputs actionable instructions."""
        msg = format_shared_library_error(python_executable="/usr/local/bin/python3.14")
        self.assertIn("/usr/local/bin/python3.14", msg)
        self.assertIn("--enable-shared", msg)
        self.assertIn("PYTHON_CONFIGURE_OPTS", msg)
        self.assertIn("--python-executable", msg)

    @patch("platform.system", return_value="Windows")
    def test_check_python_shared_library_windows(self, mock_system: MagicMock) -> None:
        """Verify check_python_shared_library always returns True on Windows."""
        is_supported, msg = check_python_shared_library()
        self.assertTrue(is_supported)
        self.assertEqual(msg, "")

    @patch("platform.system", return_value="Linux")
    @patch("subprocess.run")
    def test_check_python_shared_library_linux_supported(self, mock_run: MagicMock, mock_system: MagicMock) -> None:
        """Verify check_python_shared_library returns True when Py_ENABLE_SHARED is 1."""
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n", stderr="")
        is_supported, msg = check_python_shared_library(python_executable="python_mock")
        self.assertTrue(is_supported)
        self.assertEqual(msg, "")

    @patch("platform.system", return_value="Linux")
    @patch("subprocess.run")
    def test_check_python_shared_library_linux_unsupported(self, mock_run: MagicMock, mock_system: MagicMock) -> None:
        """Verify check_python_shared_library returns False and helpful message when Py_ENABLE_SHARED is 0."""
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n", stderr="")
        is_supported, msg = check_python_shared_library(python_executable="python_mock")
        self.assertFalse(is_supported)
        self.assertIn("--enable-shared", msg)

    @patch("installer.check_python_shared_library", return_value=(False, "Missing shared library"))
    def test_build_executable_raises_on_missing_shared_lib(self, mock_check: MagicMock) -> None:
        """Verify build_executable raises RuntimeError with formatted message when shared lib is missing."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(RuntimeError) as ctx:
                build_executable(project_root=tmp_dir, python_executable="python_static")
            self.assertIn("Missing shared library", str(ctx.exception))

    @patch("installer.check_python_shared_library", return_value=(True, ""))
    @patch("subprocess.run")
    def test_build_executable_formats_pyinstaller_shared_lib_error(self, mock_run: MagicMock, mock_check: MagicMock) -> None:
        """Verify build_executable intercepts PyInstaller shared library error output and formats it."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="ERROR: Python was built without a shared library, which is required by PyInstaller.",
            stderr=""
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(RuntimeError) as ctx:
                build_executable(project_root=tmp_dir, python_executable="python_test")
            self.assertIn("--enable-shared", str(ctx.exception))
            self.assertIn("PYTHON_CONFIGURE_OPTS", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
