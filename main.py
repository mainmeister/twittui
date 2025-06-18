import os
import sys

# Redirect stderr to suppress GTK warnings
class StderrRedirector:
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr

    def write(self, message):
        # Filter out the specific xapp-gtk3-module warning
        if "Failed to load module" in message and "xapp-gtk3-module" in message:
            return
        self.original_stderr.write(message)

    def flush(self):
        self.original_stderr.flush()

# Redirect stderr to filter out GTK warnings
sys.stderr = StderrRedirector(sys.stderr)

# Suppress GTK module warnings
os.environ['GTK_MODULES'] = ''
# Remove GTK_DEBUG environment variable instead of setting it to empty string
if 'GTK_DEBUG' in os.environ:
    del os.environ['GTK_DEBUG']
# Disable accessibility bridge to prevent module loading
os.environ['NO_AT_BRIDGE'] = '1'
# Force GTK to use X11 backend which has fewer module dependencies
os.environ['GDK_BACKEND'] = 'x11'
# Suppress GTK module loading warnings
os.environ['G_MESSAGES_DEBUG'] = ''

from twittui_form import main

if __name__ == '__main__':
    app = main()
    app.main_loop()
