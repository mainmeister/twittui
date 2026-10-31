import argparse
import importlib.util
import os
import sys

# Redirect stderr to suppress GTK warnings
class StderrRedirector:
    def __init__(self, original_stderr) -> None:
        self.original_stderr = original_stderr

    def write(self, message) -> None:
        # Filter out the specific xapp-gtk3-module warning
        if "Failed to load module" in message and "xapp-gtk3-module" in message:
            return
        self.original_stderr.write(message)

    def flush(self) -> None:
        self.original_stderr.flush()

def configure_gtk_environment() -> None:
    """Configure GTK environment variables and ensure GObject introspection version consistency."""
    # Suppress GTK module warnings and configure GTK environment
    sys.stderr = StderrRedirector(sys.stderr)
    os.environ['GTK_MODULES'] = ''
    if 'GTK_DEBUG' in os.environ:
        del os.environ['GTK_DEBUG']
    os.environ['NO_AT_BRIDGE'] = '1'
    os.environ['GDK_BACKEND'] = 'x11'
    os.environ['G_MESSAGES_DEBUG'] = ''

    # Ensure GTK/GDK namespaces are explicitly bound to consistent versions
    # to avoid runtime namespace version collisions (such as Gdk 4.0 vs 3.0 when both are installed).
    try:
        import gi
        gtk_version = "4.0" if os.getenv("TOGA_GTK") == "4" else "3.0"
        for ns in ("Gtk", "Gdk", "GdkX11", "GdkWayland"):
            try:
                gi.require_version(ns, gtk_version)
            except (ValueError, AttributeError):
                pass
        for ns, ver in (("Pango", "1.0"), ("PangoCairo", "1.0"), ("GLib", "2.0"), ("GObject", "2.0"), ("Gio", "2.0")):
            try:
                gi.require_version(ns, ver)
            except (ValueError, AttributeError):
                pass
        try:
            import gi.overrides.Gtk  # noqa: F401
            import gi.overrides.Pango  # noqa: F401
        except ImportError:
            pass
        from gi.repository import Gtk
        Gtk.init_check()
    except (ImportError, Exception):
        pass

def get_installed_toga_backends() -> dict[str, bool]:
    """Detect whether toga-gtk and toga-textual are installed."""
    has_gtk = importlib.util.find_spec('toga_gtk') is not None
    has_textual = importlib.util.find_spec('toga_textual') is not None
    return {'gtk': has_gtk, 'textual': has_textual}

def parse_backend_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line switches for UI backend selection and installation."""
    parser = argparse.ArgumentParser(
        description="TwitTUI: TWiT.tv Terminal & Desktop Media Browser",
        add_help=True
    )
    backend_group = parser.add_mutually_exclusive_group()
    backend_group.add_argument(
        '-b', '--backend',
        choices=['gtk', 'textual', 'toga_gtk', 'toga_textual', 'gui', 'tui'],
        help="Select Toga UI backend ('gtk'/'gui' for GTK desktop UI or 'textual'/'tui' for terminal UI)"
    )
    backend_group.add_argument(
        '--gtk', '--gui',
        dest='gtk_flag',
        action='store_true',
        help="Launch with GTK graphical desktop backend"
    )
    backend_group.add_argument(
        '--textual', '--tui',
        dest='textual_flag',
        action='store_true',
        help="Launch with Textual terminal UI backend"
    )
    parser.add_argument(
        '-i', '--install',
        dest='install',
        action='store_true',
        help="Build non-debug standalone executable with PyInstaller and copy to local executable PATH"
    )
    parser.add_argument(
        '--install-dir',
        dest='install_dir',
        type=str,
        default=None,
        help="Optional custom target directory for executable installation (e.g. ~/.local/bin)"
    )
    parser.add_argument(
        '-c', '--clean', '--cleanup',
        dest='clean',
        action='store_true',
        help="Remove PyInstaller build artifacts, spec files, and dist folders to free disk space"
    )
    parser.add_argument(
        '--no-clean',
        dest='no_clean',
        action='store_true',
        help="Do not clean up build artifacts after installation"
    )
    parser.add_argument(
        '--uninstall-pyinstaller',
        dest='uninstall_pyinstaller',
        action='store_true',
        help="Also uninstall PyInstaller package when cleaning up"
    )
    parser.add_argument(
        '--python-executable',
        dest='python_executable',
        type=str,
        default=None,
        help="Path to Python interpreter to use for PyInstaller compilation (e.g. /usr/bin/python3)"
    )
    return parser.parse_args(argv)

def resolve_toga_backend(argv: list[str] | None = None, prompt_interactive: bool = True) -> str:
    """Resolve and configure the Toga backend based on CLI arguments, environment, or user prompt."""
    args = parse_backend_args(argv)

    if getattr(args, 'clean', False) and not getattr(args, 'install', False):
        from installer import clean_build_artifacts
        clean_build_artifacts(
            remove_pyinstaller=getattr(args, 'uninstall_pyinstaller', False),
            python_executable=getattr(args, 'python_executable', None),
        )
        sys.exit(0)

    if args.install:
        from installer import clean_build_artifacts, install_twittui
        install_twittui(
            target_dir=args.install_dir,
            python_executable=getattr(args, 'python_executable', None),
            clean_build_artifacts=not getattr(args, 'no_clean', False),
        )
        if getattr(args, 'uninstall_pyinstaller', False):
            clean_build_artifacts(
                remove_dist=False,
                remove_build=False,
                remove_spec=False,
                remove_pyinstaller=True,
                python_executable=getattr(args, 'python_executable', None),
            )
        sys.exit(0)
    backends = get_installed_toga_backends()
    has_gtk = backends['gtk']
    has_textual = backends['textual']

    chosen_backend = None

    if args.backend:
        b = args.backend.lower()
        if b in ('gtk', 'gui', 'toga_gtk'):
            chosen_backend = 'toga_gtk'
        elif b in ('textual', 'tui', 'toga_textual'):
            chosen_backend = 'toga_textual'
    elif args.gtk_flag:
        chosen_backend = 'toga_gtk'
    elif args.textual_flag:
        chosen_backend = 'toga_textual'

    if chosen_backend:
        if chosen_backend == 'toga_gtk' and not has_gtk:
            print("Error: GTK backend ('toga-gtk') was requested but is not installed.", file=sys.stderr)
            print("Please install it with: pip install toga-gtk", file=sys.stderr)
            sys.exit(1)
        elif chosen_backend == 'toga_textual' and not has_textual:
            print("Error: Textual backend ('toga-textual') was requested but is not installed.", file=sys.stderr)
            print("Please install it with: pip install toga-textual", file=sys.stderr)
            sys.exit(1)
    else:
        # No CLI backend switch provided
        if has_gtk and has_textual:
            if prompt_interactive and sys.stdin.isatty():
                print("\nMultiple Toga UI backends detected:")
                print("  1) GTK (Graphical Desktop UI)")
                print("  2) Textual (Terminal User Interface)")
                try:
                    while True:
                        choice = input("Select backend [1/2] (default: 1 - GTK): ").strip().lower()
                        if choice in ('1', 'gtk', 'gui', 'g', ''):
                            chosen_backend = 'toga_gtk'
                            break
                        elif choice in ('2', 'textual', 'tui', 't', 'text'):
                            chosen_backend = 'toga_textual'
                            break
                        else:
                            print("Invalid choice. Please enter 1 for GTK or 2 for Textual.")
                except (EOFError, KeyboardInterrupt):
                    chosen_backend = 'toga_gtk' if os.environ.get('DISPLAY') else 'toga_textual'
            else:
                chosen_backend = 'toga_gtk' if os.environ.get('DISPLAY') else 'toga_textual'
        elif has_gtk:
            chosen_backend = 'toga_gtk'
        elif has_textual:
            chosen_backend = 'toga_textual'
        else:
            print("Error: Neither 'toga-gtk' nor 'toga-textual' backend is installed.", file=sys.stderr)
            print("Please install a backend using:\n  pip install toga-gtk\n  or\n  pip install toga-textual", file=sys.stderr)
            sys.exit(1)

    os.environ['TOGA_BACKEND'] = chosen_backend

    if chosen_backend == 'toga_textual':
        from toga_textual_backend import patch_toga_textual
        patch_toga_textual()
    elif chosen_backend == 'toga_gtk':
        configure_gtk_environment()

    return chosen_backend

if __name__ == '__main__':
    backend = resolve_toga_backend()

    from twittui_form import load_twittui_dotenv, main
    load_twittui_dotenv()

    app = main()
    app.main_loop()
