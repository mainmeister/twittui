Terminal based TUI application for Twit.tv podcast episodes

Allow selection of a single show.
Allow selection of episodes of that show.
Allow streaming of one of the selected episodes.
Allow downloading of all of the selected episodes.
Allow using the clubtwit id to provide access to commercial free and extra club member episodes.

Developing using beeware https://beeware.org/ so that cross platform version can be created (terminal, web, desktop, android, ios)
Initial implementation will use toga-textual which implements the TUI using the Textual module. This is the most limited subset of widgets that toga provides and should run in any terminal window under any OS.
