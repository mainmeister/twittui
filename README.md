Terminal based TUI application for Twit.tv podcast episodes

Allow selection of a single show.
Allow selection of episodes of that show.
Allow streaming of one of the selected episodes.
Allow downloading of all of the selected episodes.
Allow using the clubtwit id to provide access to commercial free and extra club member episodes.

Developing using beeware https://beeware.org/ so that cross platform version can be created (terminal, web, desktop, android, ios)
Initial implementation will use toga-textual which implements the TUI using the Textual module. This is the most limited subset of widgets that toga provides and should run in any terminal window under any OS.

## Known Issues

### GTK Module Warnings
On some Linux systems, you might see GTK module warnings like "Failed to load module 'xapp-gtk3-module'". These warnings are non-critical and don't affect the application's functionality. The application implements two approaches to handle these warnings:

1. **Environment Variables**: The application sets several environment variables in main.py to suppress GTK-related warnings:
   - `GTK_MODULES`: Suppresses GTK module warnings
   - `NO_AT_BRIDGE`: Disables accessibility bridge to prevent module loading
   - `GDK_BACKEND`: Forces GTK to use X11 backend which has fewer module dependencies
   - `G_MESSAGES_DEBUG`: Suppresses GTK module loading warnings
   - Additionally, the application removes the `GTK_DEBUG` environment variable if it exists, as setting it to an empty string can cause warnings when GTK isn't built with debugging enabled.

2. **Stderr Redirection**: For specific warnings like the "Failed to load module 'xapp-gtk3-module'" message, the application implements a custom stderr redirector that filters out these specific messages while allowing other error messages to pass through. This provides a more targeted approach to handling known non-critical warnings.
