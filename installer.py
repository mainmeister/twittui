"""Installation and PyInstaller packaging module for TwitTUI.

This module automates downloading and installing PyInstaller for the current OS,
building a standalone non-debug binary, and installing it into a directory on the
user's local executable search PATH.
"""

import os
import platform
import shutil
import subprocess
import sys


def is_pyinstaller_installed() -> bool:
    """Check if PyInstaller is available in the current Python environment or system PATH."""
    try:
        import PyInstaller  # type: ignore # noqa: F401
        return True
    except ImportError:
        pass
    return shutil.which("pyinstaller") is not None


def ensure_pyinstaller_installed(python_executable: str | None = None) -> bool:
    """Download and install/upgrade PyInstaller for the current operating system."""
    py_exec = python_executable or sys.executable
    print("Checking PyInstaller installation for current operating system...")

    cmd_base = [py_exec, "-m", "pip", "install", "--upgrade", "pyinstaller"]
    try:
        result = subprocess.run(cmd_base, check=True, capture_output=True, text=True)
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
        if is_pyinstaller_installed():
            print("Warning: pip upgrade failed, but existing PyInstaller installation was found and will be used.")
            return True
        err_msg = f"Failed to install PyInstaller via pip: {e.stderr or e.stdout or e}"
        print(f"Error: {err_msg}", file=sys.stderr)
        raise RuntimeError(err_msg) from e
    except Exception as e:
        if is_pyinstaller_installed():
            print("Warning: pip command encountered an issue, using existing PyInstaller.")
            return True
        raise RuntimeError(f"Failed to install PyInstaller: {e}") from e


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
    path_dirs = [os.path.abspath(p.strip()) for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]

    if is_windows:
        # Preferred directories on Windows
        candidates = [
            os.path.join(sys.prefix, "Scripts"),
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Microsoft\WindowsApps"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\twittui\bin"),
        ]
    else:
        # Preferred user binary directories on Unix/Linux/macOS
        candidates = [
            os.path.expanduser("~/.local/bin"),
            os.path.expanduser("~/bin"),
            "/usr/local/bin",
        ]
        if hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix):
            # Running inside a virtualenv
            candidates.append(os.path.join(sys.prefix, "bin"))

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

    # Check any directory currently in PATH that is writable by the user
    for p in path_dirs:
        if os.path.isdir(p) and os.access(p, os.W_OK):
            # Avoid placing directly in root temp or root system directories
            if p not in ("/tmp", "/var/tmp", "/"):
                return p

    # Fallback to standard candidate (creating it)
    fallback = candidates[0]
    os.makedirs(fallback, exist_ok=True)
    return fallback


def build_executable(
    project_root: str | None = None,
    output_dir: str | None = None,
    python_executable: str | None = None,
) -> str:
    """Run PyInstaller to create a non-debug standalone executable of TwitTUI."""
    root = project_root or os.path.dirname(os.path.abspath(__file__))
    py_exec = python_executable or sys.executable
    main_script = os.path.join(root, "main.py")
    dist_dir = output_dir or os.path.join(root, "dist")
    build_dir = os.path.join(root, "build")
    spec_file = os.path.join(root, "twittui.spec")

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

    # Non-debug: ensure --debug is not included. Use --strip on POSIX if available.
    if platform.system() != "Windows" and shutil.which("strip"):
        cmd.append("--strip")

    # Add data assets if present in the project directory
    data_files = ["feed-style.css", "feed-style.xsl", "twittv.apib", "README.md"]
    for df in data_files:
        full_df = os.path.join(root, df)
        if os.path.isfile(full_df):
            cmd.append(f"--add-data={full_df}{os.pathsep}.")

    # Include resources folder containing application icons and assets
    resources_dir = os.path.join(root, "resources")
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

    # Collect packages and hidden imports needed by Toga / Textual / GTK backends
    packages_to_collect = ["toga", "toga_textual", "textual", "dotenv", "requests"]
    for extra_pkg in ("toga_gtk", "gi"):
        try:
            import importlib.util
            if importlib.util.find_spec(extra_pkg) is not None:
                packages_to_collect.append(extra_pkg)
        except Exception:
            pass
    for pkg in packages_to_collect:
        cmd.append(f"--collect-all={pkg}")

    cmd.append("--hidden-import=toga_textual_backend")
    cmd.append("--hidden-import=gi.overrides.Gtk")
    cmd.append("--hidden-import=gi.overrides.Pango")
    cmd.append(main_script)

    print(f"Compiling non-debug executable with PyInstaller from '{main_script}'...")
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
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
            except Exception as e:
                print(f"Warning: Could not remove build directory '{build_dir}': {e}", file=sys.stderr)

    # 2. Clean dist directory (the installable binary folder)
    if remove_dist:
        dist_dir = os.path.join(root, "dist")
        if os.path.isdir(dist_dir):
            try:
                shutil.rmtree(dist_dir, ignore_errors=False)
                removed_items.append(dist_dir)
                print(f"Removed distribution directory: '{dist_dir}'")
            except Exception as e:
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
            pass

        for spec_file in set(spec_candidates):
            if os.path.isfile(spec_file):
                try:
                    os.remove(spec_file)
                    removed_items.append(spec_file)
                    print(f"Removed PyInstaller spec file: '{spec_file}'")
                except Exception as e:
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
            print(f"Warning: Failed to uninstall PyInstaller: {e.stderr or e.stdout or e}", file=sys.stderr)
        except Exception as e:
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
) -> str:
    """Run full installation pipeline: install PyInstaller, build non-debug binary, and copy to local PATH."""
    root = project_root or os.path.dirname(os.path.abspath(__file__))

    # 1. Download and ensure PyInstaller is installed for current OS
    ensure_pyinstaller_installed(python_executable=python_executable)

    # 2. Build non-debug executable
    built_exe = build_executable(
        project_root=root,
        python_executable=python_executable,
    )

    # 3. Determine local executable search PATH directory
    install_dir = find_local_executable_path(target_dir=target_dir)
    exe_name = os.path.basename(built_exe)
    destination_path = os.path.join(install_dir, exe_name)

    print(f"Installing executable to local PATH destination: '{destination_path}'...")
    shutil.copy2(built_exe, destination_path)

    # Make executable on Unix-like operating systems
    if platform.system() != "Windows":
        try:
            current_mode = os.stat(destination_path).st_mode
            os.chmod(destination_path, current_mode | 0o755)
        except Exception as e:
            print(f"Warning: Could not set executable permissions on '{destination_path}': {e}")

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

    args = parser.parse_args()

    if args.clean and not args.install:
        clean_build_artifacts(remove_pyinstaller=args.uninstall_pyinstaller)
        sys.exit(0)
    elif args.install:
        install_twittui(
            target_dir=args.install_dir,
            clean_build_artifacts=not args.no_clean,
        )
        if args.uninstall_pyinstaller:
            clean_build_artifacts(
                remove_dist=False,
                remove_build=False,
                remove_spec=False,
                remove_pyinstaller=True,
            )
        sys.exit(0)
    elif args.clean:
        clean_build_artifacts(remove_pyinstaller=args.uninstall_pyinstaller)
        sys.exit(0)
    else:
        parser.print_help()
