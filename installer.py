"""Installation and PyInstaller packaging module for TwitTUI.

This module automates downloading and installing PyInstaller for the current OS,
building a standalone non-debug binary, and installing it into a directory on the
user's local executable search PATH.
"""

import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile

_logger = logging.getLogger("twittui.installer")


def format_shared_library_error(python_executable: str | None = None) -> str:
    """Format actionable instructions for resolving missing Python shared library errors."""
    py_exec = python_executable or sys.executable
    return (
        f"Python shared library (libpython) is missing for interpreter '{py_exec}'.\n"
        "PyInstaller requires Python to be compiled with dynamic shared library support (--enable-shared) on Linux.\n\n"
        "To resolve this error, use one of the following solutions:\n\n"
        "1. Rebuild Python from source with --enable-shared:\n"
        "   ./configure --enable-shared --enable-optimizations\n"
        "   make -j$(nproc)\n"
        "   sudo make altinstall\n"
        "   sudo ldconfig\n\n"
        "2. If using pyenv, reinstall Python with shared library support:\n"
        '   env PYTHON_CONFIGURE_OPTS="--enable-shared" pyenv install <version>\n\n'
        "3. If using Ubuntu/Debian system Python, install development headers:\n"
        "   sudo apt update && sudo apt install -y python3-dev libpython3-dev\n\n"
        "4. If another Python interpreter with shared library support is available, specify it via --python-executable:\n"
        "   python main.py --install --python-executable /usr/bin/python3\n"
        "   # or:\n"
        "   python installer.py --install --python-executable /usr/bin/python3\n"
    )


def check_python_shared_library(python_executable: str | None = None) -> tuple[bool, str]:
    """Check if the target Python interpreter was built with shared library support on Linux/Unix.

    Returns:
        A tuple of (is_supported: bool, error_message: str).
    """
    if platform.system() == "Windows":
        return True, ""

    py_exec = python_executable or sys.executable
    try:
        code = (
            "import sysconfig;"
            "val = sysconfig.get_config_var('Py_ENABLE_SHARED');"
            "print('1' if val == 1 else '0')"
        )
        res = subprocess.run([py_exec, "-c", code], capture_output=True, text=True, check=True)
        output = res.stdout.strip()
        if output == "0":
            return False, format_shared_library_error(py_exec)
        return True, ""
    except (OSError, subprocess.SubprocessError):
        # If unable to probe, allow build to proceed and let PyInstaller's output be handled
        _logger.debug("Unable to probe Py_ENABLE_SHARED for %s", py_exec, exc_info=True)
        return True, ""


def is_pyinstaller_installed(python_executable: str | None = None) -> bool:
    """Check if PyInstaller is available in the target Python environment or system PATH."""
    py_exec = python_executable or sys.executable
    try:
        res = subprocess.run([py_exec, "-m", "PyInstaller", "--version"], capture_output=True, text=True)
        if res.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        _logger.debug("PyInstaller subprocess probe failed for %s", py_exec, exc_info=True)
    if python_executable is None or python_executable == sys.executable:
        try:
            import PyInstaller  # noqa: F401
            return True
        except ImportError:
            pass
        return shutil.which("pyinstaller") is not None
    return False


def ensure_pyinstaller_installed(python_executable: str | None = None) -> bool:
    """Download and install/upgrade PyInstaller for the current operating system."""
    py_exec = python_executable or sys.executable
    print(f"Checking PyInstaller installation for '{py_exec}'...")

    if is_pyinstaller_installed(py_exec):
        print("PyInstaller is installed and up to date.")
        return True

    cmd_base = [py_exec, "-m", "pip", "install", "--upgrade", "pyinstaller"]
    try:
        subprocess.run(cmd_base, check=True, capture_output=True, text=True)
        print("PyInstaller is installed and up to date.")
        return True
    except subprocess.CalledProcessError as e:
        # If PEP 668 externally managed environment is encountered, retry with --break-system-packages or --user
        if "externally-managed-environment" in (e.stderr or ""):
            for extra_flag in (["--break-system-packages"], ["--user"]):
                try:
                    subprocess.run(cmd_base + extra_flag, check=True, capture_output=True, text=True)
                    print("PyInstaller successfully installed.")
                    return True
                except subprocess.CalledProcessError:
                    continue
        if is_pyinstaller_installed(py_exec):
            print("Warning: pip upgrade failed, but existing PyInstaller installation was found and will be used.")
            return True
        err_msg = (
            f"Failed to install PyInstaller for interpreter '{py_exec}': {e.stderr or e.stdout or e}\n\n"
            f"To resolve this, install PyInstaller into '{py_exec}' directly or create a virtual environment:\n"
            f"  {py_exec} -m pip install pyinstaller\n"
            f"  # or create a shared venv:\n"
            f"  {py_exec} -m venv .venv\n"
            f"  source .venv/bin/activate\n"
            f"  pip install -r requirements.txt pyinstaller"
        )
        print(f"Error: {err_msg}", file=sys.stderr)
        raise RuntimeError(err_msg) from e
    except Exception as e:
        if is_pyinstaller_installed(py_exec):
            print("Warning: pip command encountered an issue, using existing PyInstaller.")
            return True
        raise RuntimeError(f"Failed to install PyInstaller for '{py_exec}': {e}") from e


def get_default_executable_name() -> str:
    """Return the platform-specific executable name."""
    return "twittui.exe" if platform.system() == "Windows" else "twittui"


def find_local_executable_path(target_dir: str | None = None) -> str:
    """Determine the optimal directory on the local system's executable search PATH."""
    if target_dir:
        expanded = os.path.abspath(os.path.expanduser(target_dir))
        os.makedirs(expanded, exist_ok=True)
        return expanded

    is_windows = platform.system() == "Windows"
    raw_path_entries = [p.strip() for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]
    path_dirs = [os.path.abspath(p) for p in raw_path_entries if os.path.isabs(p)]

    if is_windows:
        # Preferred directories on Windows
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\twittui\bin"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Microsoft\WindowsApps"),
            os.path.join(sys.prefix, "Scripts"),
        ]
    else:
        # Preferred user binary directories on Unix/Linux/macOS
        candidates = [
            os.path.expanduser("~/.local/bin"),
            os.path.expanduser("~/bin"),
            "/usr/local/bin",
        ]

    # First check if any preferred candidate is in PATH
    for cand in candidates:
        cand_norm = os.path.abspath(cand)
        if cand_norm in path_dirs:
            if os.path.isdir(cand_norm) and os.access(cand_norm, os.W_OK):
                return cand_norm
            parent = os.path.dirname(cand_norm)
            if not os.path.exists(cand_norm) and os.path.exists(parent) and os.access(parent, os.W_OK):
                os.makedirs(cand_norm, exist_ok=True)
                return cand_norm

    # Build exclusion set for ephemeral virtualenvs and language-specific toolchain directories
    excluded_prefixes: list[str] = []
    for env_key in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        env_val = os.environ.get(env_key)
        if env_val:
            excluded_prefixes.append(os.path.abspath(env_val))
    if hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix):
        excluded_prefixes.append(os.path.abspath(sys.prefix))

    toolchain_markers = (
        "/.venv/",
        "/venv/",
        "/.conda/",
        "/.cargo/",
        "/.rustup/",
        "/.nvm/",
        "/.pyenv/",
        "/.rbenv/",
        "/.asdf/",
        "/.poetry/",
        "/node_modules/",
    )

    # Check any absolute directory currently in PATH that is writable by the user
    for raw_p in raw_path_entries:
        if raw_p in (".", "./") or not os.path.isabs(raw_p):
            continue
        p = os.path.abspath(raw_p)
        if p in ("/tmp", "/var/tmp", "/"):
            continue
        if any(p == pref or p.startswith(pref + os.sep) for pref in excluded_prefixes):
            continue
        norm_check = p.replace("\\", "/").rstrip("/") + "/"
        if any(marker in norm_check for marker in toolchain_markers):
            continue
        if os.path.isdir(p) and os.access(p, os.W_OK):
            return p

    # Fallback to standard candidate (creating it)
    fallback = candidates[0]
    os.makedirs(fallback, exist_ok=True)
    return fallback


def _probe_packages_in_interpreter(packages: tuple[str, ...], py_exec: str) -> set[str]:
    """Check which optional packages are importable in the target Python interpreter."""
    import importlib.util
    import json

    same_interp = (
        not py_exec
        or os.path.abspath(py_exec) == os.path.abspath(sys.executable)
    )
    resolved_exec = py_exec if os.path.isfile(py_exec) else (shutil.which(py_exec) if py_exec else None)

    if not same_interp and resolved_exec:
        try:
            code = (
                "import importlib.util, json, sys; "
                "pkgs = sys.argv[1:]; "
                "print(json.dumps([p for p in pkgs if importlib.util.find_spec(p) is not None]))"
            )
            res = subprocess.run(
                [resolved_exec, "-c", code, *packages],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout.strip():
                found = json.loads(res.stdout.strip())
                if isinstance(found, list):
                    return {str(p) for p in found}
            return set()
        except (OSError, subprocess.SubprocessError, ValueError):
            _logger.debug("Target interpreter package probe failed for %s", resolved_exec, exc_info=True)
            return set()

    available: set[str] = set()
    for pkg in packages:
        try:
            if importlib.util.find_spec(pkg) is not None:
                available.add(pkg)
        except (ImportError, ValueError, AttributeError):
            _logger.debug("Could not probe package %s", pkg, exc_info=True)
    return available


def build_executable(
    project_root: str | None = None,
    output_dir: str | None = None,
    python_executable: str | None = None,
    strip_binary: bool = False,
) -> str:
    """Run PyInstaller to create a non-debug standalone executable of TwitTUI."""
    root = project_root or os.path.dirname(os.path.abspath(__file__))
    py_exec = python_executable or sys.executable
    main_script = os.path.join(root, "main.py")
    dist_dir = output_dir or os.path.join(root, "dist")
    build_dir = os.path.join(root, "build")

    exe_name = get_default_executable_name()
    target_exe = os.path.join(dist_dir, exe_name if platform.system() != "Windows" else "twittui.exe")

    cmd = [
        py_exec,
        "-m",
        "PyInstaller",
        "--name=twittui",
        "--onefile",
        "--clean",
        "--noconfirm",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        f"--specpath={root}",
    ]

    # Non-debug: ensure --debug is not included. Keep --strip opt-in on POSIX so binary
    # wheels and PyGObject shared libraries are not corrupted by default.
    if strip_binary and platform.system() != "Windows" and shutil.which("strip"):
        cmd.append("--strip")

    # Add data assets if present in the project directory
    data_files = ["feed-style.css", "feed-style.xsl", "twittv.apib", "README.md"]
    for df in data_files:
        full_df = os.path.join(root, df)
        if os.path.isfile(full_df):
            cmd.append(f"--add-data={full_df}{os.pathsep}.")

    # Include resources folder containing application icons and assets
    resources_dir = os.path.join(root, "resources")
    master_icon = os.path.join(resources_dir, "twittui.png")
    if not os.path.isfile(master_icon):
        try:
            from generate_icon import generate_all_icons
            generate_all_icons(resources_dir)
        except Exception as e:
            _logger.warning("Could not auto-generate icon assets: %s", e, exc_info=True)
            print(f"Warning: Could not auto-generate icon assets: {e}", file=sys.stderr)

    if os.path.isdir(resources_dir):
        cmd.append(f"--add-data={resources_dir}{os.pathsep}resources")

    # Add application icon for the standalone executable
    icon_candidates = [
        os.path.join(resources_dir, "twittui.ico" if platform.system() == "Windows" else "twittui.png"),
        os.path.join(resources_dir, "twittui.png"),
        os.path.join(resources_dir, "twittui.ico"),
    ]
    for ic in icon_candidates:
        if os.path.isfile(ic):
            cmd.append(f"--icon={ic}")
            break

    # Collect packages and hidden imports needed by TwitTUI / Toga / Textual / GTK / yt-dlp in target interpreter
    packages_to_collect = ["twittui", "toga", "toga_textual", "textual", "dotenv", "requests"]
    optional_pkgs = ("toga_gtk", "gi", "yt_dlp", "defusedxml", "nh3")
    optional_available = _probe_packages_in_interpreter(optional_pkgs, py_exec)
    for extra_pkg in optional_pkgs:
        if extra_pkg in optional_available:
            packages_to_collect.append(extra_pkg)
    for pkg in packages_to_collect:
        cmd.append(f"--collect-all={pkg}")

    cmd.append("--hidden-import=toga_textual_backend")
    cmd.append("--hidden-import=tiered_search")
    cmd.append("--hidden-import=double_metaphone")
    if "gi" in optional_available and platform.system() not in ("Windows", "Darwin"):
        cmd.append("--hidden-import=gi.overrides.Gtk")
        cmd.append("--hidden-import=gi.overrides.Pango")
    cmd.append(main_script)

    # Verify Python shared library availability before building
    is_shared, shared_err = check_python_shared_library(python_executable=py_exec)
    if not is_shared:
        print(f"Error: {shared_err}", file=sys.stderr)
        raise RuntimeError(shared_err)

    print(f"Compiling non-debug executable with PyInstaller from '{main_script}'...")
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        combined_output = (result.stderr or "") + "\n" + (result.stdout or "")
        if "without a shared library" in combined_output or "enable-shared" in combined_output:
            err_msg = format_shared_library_error(py_exec)
        else:
            err_msg = f"PyInstaller build failed with exit code {result.returncode}:\n{result.stderr or result.stdout}"
        print(f"Error: {err_msg}", file=sys.stderr)
        raise RuntimeError(err_msg)

    if not os.path.isfile(target_exe):
        raise FileNotFoundError(f"Expected compiled binary not found at '{target_exe}'")

    print(f"Compiled executable successfully created at '{target_exe}'.")
    return target_exe


def clean_build_artifacts(
    project_root: str | None = None,
    remove_dist: bool = True,
    remove_build: bool = True,
    remove_spec: bool = True,
    remove_pyinstaller: bool = False,
    python_executable: str | None = None,
) -> list[str]:
    """Remove temporary and intermediate PyInstaller build artifacts and directories.

    Args:
        project_root: The root directory of the TwitTUI project.
        remove_dist: Whether to remove the 'dist' folder created by PyInstaller.
        remove_build: Whether to remove the 'build' folder created by PyInstaller.
        remove_spec: Whether to remove generated .spec files (e.g. 'twittui.spec').
        remove_pyinstaller: Whether to uninstall PyInstaller package via pip.
        python_executable: Path to Python interpreter for pip operations.

    Returns:
        List of paths/items that were successfully removed.
    """
    root = project_root or os.path.dirname(os.path.abspath(__file__))
    removed_items: list[str] = []

    print("Cleaning up PyInstaller build artifacts and temporary files...")

    # 1. Clean build directory
    if remove_build:
        build_dir = os.path.join(root, "build")
        if os.path.isdir(build_dir):
            try:
                shutil.rmtree(build_dir, ignore_errors=False)
                removed_items.append(build_dir)
                print(f"Removed build directory: '{build_dir}'")
            except OSError as e:
                _logger.warning("Could not remove build directory '%s': %s", build_dir, e, exc_info=True)
                print(f"Warning: Could not remove build directory '{build_dir}': {e}", file=sys.stderr)

    # 2. Clean dist directory (the installable binary folder)
    if remove_dist:
        dist_dir = os.path.join(root, "dist")
        if os.path.isdir(dist_dir):
            try:
                shutil.rmtree(dist_dir, ignore_errors=False)
                removed_items.append(dist_dir)
                print(f"Removed distribution directory: '{dist_dir}'")
            except OSError as e:
                _logger.warning("Could not remove dist directory '%s': %s", dist_dir, e, exc_info=True)
                print(f"Warning: Could not remove dist directory '{dist_dir}': {e}", file=sys.stderr)

    # 3. Clean .spec files
    if remove_spec:
        spec_candidates = [
            os.path.join(root, "twittui.spec"),
        ]
        # Also check for any extra .spec files in the project root
        try:
            for f in os.listdir(root):
                if f.endswith(".spec"):
                    spec_candidates.append(os.path.join(root, f))
        except OSError:
            _logger.debug("Could not list project root '%s' for .spec cleanup", root, exc_info=True)

        for spec_file in set(spec_candidates):
            if os.path.isfile(spec_file):
                try:
                    os.remove(spec_file)
                    removed_items.append(spec_file)
                    print(f"Removed PyInstaller spec file: '{spec_file}'")
                except OSError as e:
                    _logger.warning("Could not remove spec file '%s': %s", spec_file, e, exc_info=True)
                    print(f"Warning: Could not remove spec file '{spec_file}': {e}", file=sys.stderr)

    # 4. Optionally uninstall PyInstaller package
    if remove_pyinstaller:
        py_exec = python_executable or sys.executable
        print("Uninstalling PyInstaller package...")
        try:
            subprocess.run(
                [py_exec, "-m", "pip", "uninstall", "-y", "pyinstaller"],
                check=True,
                capture_output=True,
                text=True,
            )
            removed_items.append("pyinstaller (pip package)")
            print("Successfully uninstalled PyInstaller package.")
        except subprocess.CalledProcessError as e:
            _logger.warning("Failed to uninstall PyInstaller: %s", e.stderr or e.stdout or e)
            print(f"Warning: Failed to uninstall PyInstaller: {e.stderr or e.stdout or e}", file=sys.stderr)
        except (OSError, subprocess.SubprocessError) as e:
            _logger.warning("Error during PyInstaller uninstallation: %s", e, exc_info=True)
            print(f"Warning: Error during PyInstaller uninstallation: {e}", file=sys.stderr)

    if removed_items:
        print(f"Cleanup complete. Removed {len(removed_items)} item(s).")
    else:
        print("Cleanup complete. No temporary build artifacts were found.")

    return removed_items


def install_twittui(
    target_dir: str | None = None,
    project_root: str | None = None,
    python_executable: str | None = None,
    clean_build_artifacts: bool = True,
    strip_binary: bool = False,
) -> str:
    """Run full installation pipeline: install PyInstaller, build non-debug binary, and copy to local PATH."""
    root = project_root or os.path.dirname(os.path.abspath(__file__))

    # 1. Download and ensure PyInstaller is installed for current OS
    ensure_pyinstaller_installed(python_executable=python_executable)

    # 2. Build non-debug executable
    if strip_binary:
        built_exe = build_executable(
            project_root=root,
            python_executable=python_executable,
            strip_binary=True,
        )
    else:
        built_exe = build_executable(
            project_root=root,
            python_executable=python_executable,
        )

    # 3. Determine local executable search PATH directory
    install_dir = find_local_executable_path(target_dir=target_dir)
    exe_name = os.path.basename(built_exe)
    destination_path = os.path.join(install_dir, exe_name)

    print(f"Installing executable to local PATH destination: '{destination_path}'...")
    # Create an exclusive staging file in the target directory, then atomically replace
    # (prevents collisions, ETXTBSY when upgrading a running binary, and brief mode widening).
    staged_fd, staged_path = tempfile.mkstemp(prefix=f".{exe_name}.tmp.", dir=install_dir)
    fd_owned = True
    promoted = False
    try:
        staged_file = os.fdopen(staged_fd, "wb")
        fd_owned = False
        with staged_file:
            with open(built_exe, "rb") as source:
                shutil.copyfileobj(source, staged_file)
            if platform.system() != "Windows":
                current_umask = os.umask(0o022)
                try:
                    desired_mode = (0o755 & ~current_umask) | 0o700
                finally:
                    os.umask(current_umask)
                os.fchmod(staged_file.fileno(), desired_mode)
        os.replace(staged_path, destination_path)
        promoted = True
    finally:
        if fd_owned:
            try:
                os.close(staged_fd)
            except OSError:
                _logger.debug("Could not close staged executable descriptor %s", staged_fd, exc_info=True)
        if not promoted:
            try:
                os.remove(staged_path)
            except FileNotFoundError:
                pass
            except OSError:
                _logger.debug("Could not remove staged executable %s", staged_path, exc_info=True)

    # Verify if install_dir is in PATH
    path_dirs = [os.path.abspath(p.strip()) for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]
    if os.path.abspath(install_dir) not in path_dirs:
        print(f"\nNotice: The install directory '{install_dir}' is not currently in your system PATH.")
        if platform.system() != "Windows":
            print(f"To run 'twittui' directly from any shell, add it to your profile (e.g. ~/.bashrc or ~/.zshrc):")
            print(f'  export PATH="{install_dir}:$PATH"\n')
        else:
            print(f"To run 'twittui' directly from any shell, add '{install_dir}' to your user PATH environment variable.\n")

    print(f"Installation complete! Executable is available at: {destination_path}")

    # Optionally clean build artifacts (build, dist, and spec)
    if clean_build_artifacts:
        clean_build_artifacts_fn(
            project_root=root,
            remove_dist=True,
            remove_build=True,
            remove_spec=True,
            remove_pyinstaller=False,
            python_executable=python_executable,
        )

    return destination_path


# Alias for backwards compatibility / clear naming
clean_build_artifacts_fn = clean_build_artifacts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="TwitTUI Installer and Packaging Utility",
        add_help=True,
    )
    parser.add_argument(
        "-i", "--install",
        action="store_true",
        help="Build non-debug standalone executable with PyInstaller and copy to local executable PATH",
    )
    parser.add_argument(
        "--install-dir",
        type=str,
        default=None,
        help="Optional custom target directory for executable installation (e.g. ~/.local/bin)",
    )
    parser.add_argument(
        "-c", "--clean", "--cleanup",
        dest="clean",
        action="store_true",
        help="Remove PyInstaller build artifacts, spec files, and dist folders to free disk space",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean up build artifacts after installation",
    )
    parser.add_argument(
        "--uninstall-pyinstaller",
        action="store_true",
        help="Also uninstall PyInstaller package when cleaning up",
    )
    parser.add_argument(
        "--python-executable",
        type=str,
        default=None,
        help="Path to Python interpreter to use for PyInstaller compilation (e.g. /usr/bin/python3)",
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="Strip binary symbols with PyInstaller --strip on POSIX (opt-in)",
    )

    args = parser.parse_args()

    if args.clean and not args.install:
        clean_build_artifacts(
            remove_pyinstaller=args.uninstall_pyinstaller,
            python_executable=args.python_executable,
        )
        sys.exit(0)
    elif args.install:
        install_twittui(
            target_dir=args.install_dir,
            python_executable=args.python_executable,
            clean_build_artifacts=not args.no_clean,
            strip_binary=getattr(args, "strip", False),
        )
        if args.uninstall_pyinstaller:
            clean_build_artifacts(
                remove_dist=False,
                remove_build=False,
                remove_spec=False,
                remove_pyinstaller=True,
                python_executable=args.python_executable,
            )
        sys.exit(0)
    elif args.clean:
        clean_build_artifacts(
            remove_pyinstaller=args.uninstall_pyinstaller,
            python_executable=args.python_executable,
        )
        sys.exit(0)
    else:
        parser.print_help()
