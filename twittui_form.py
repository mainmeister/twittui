import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW
import os
import requests
from dotenv import load_dotenv

class TwitTUIForm(toga.App):
    def fetch_shows(self):
        """Fetch shows from the TWIT API and return a list of show names."""
        try:
            # Load environment variables from .env file
            load_dotenv()

            # Get API credentials from environment variables
            app_id = os.getenv('TWITAPI_APPLICATIONID')
            app_key = os.getenv('TWITAPI_APPLICATIONKEYS')

            if not app_id or not app_key:
                print("API credentials not found in .env file")
                return []

            # Set up headers for API request
            headers = {
                'Accept': 'application/json',
                'app-id': app_id,
                'app-key': app_key
            }

            # Make request to shows endpoint
            response = requests.get('https://twit.tv/api/v1.0/shows', headers=headers)

            # Check if request was successful
            if response.status_code == 200:
                data = response.json()
                # Extract show names and IDs from response
                shows = []
                self.show_ids = {}  # Dictionary to map show names to their IDs
                if 'shows' in data and isinstance(data['shows'], list):
                    for show in data['shows']:
                        if 'label' in show and 'id' in show:
                            show_name = show['label']
                            show_id = show['id']
                            shows.append(show_name)
                            self.show_ids[show_name] = show_id
                    # Sort the show names alphabetically
                    shows.sort()
                return shows
            else:
                print(f"API request failed with status code {response.status_code}")
                return []
        except Exception as e:
            print(f"Error fetching shows: {e}")
            return []

    def startup(self):
        # Main box with vertical layout
        main_box = toga.Box(style=Pack(direction=COLUMN, margin=5))

        # Show selection section
        show_label = toga.Label('Show:', style=Pack(margin=(0, 5)))
        self.show_combo = toga.Selection(style=Pack(flex=1))
        fetch_button = toga.Button('Fetch', on_press=self.on_fetch_press, style=Pack(margin=5))
        show_box = toga.Box(style=Pack(direction=ROW, margin=5))
        show_box.add(show_label)
        show_box.add(self.show_combo)
        show_box.add(fetch_button)

        # Populate the show combo with show names
        shows = self.fetch_shows()
        if shows:
            self.show_combo.items = shows

        # Sort options section
        sort_label = toga.Label('Sort by:', style=Pack(margin=(0, 5)))
        # Create checkboxes for sort options (using buttons with checkbox-like appearance)
        self.date_radio = toga.Button('☑ Date', on_press=self.on_sort_button_press, style=Pack(margin=5))
        self.episode_radio = toga.Button('☐ Episode Number', on_press=self.on_sort_button_press, style=Pack(margin=5))
        self.title_radio = toga.Button('☐ Episode Title', on_press=self.on_sort_button_press, style=Pack(margin=5))
        # Default selection is date (already checked in the label)

        sort_box = toga.Box(style=Pack(direction=ROW, margin=5))
        sort_box.add(sort_label)
        sort_box.add(self.date_radio)
        sort_box.add(self.episode_radio)
        sort_box.add(self.title_radio)

        # Episodes list section
        episodes_label = toga.Label('Episodes:', style=Pack(margin=(0, 5)))
        self.episodes_list = toga.MultilineTextInput(readonly=True, style=Pack(flex=1, margin=5, height=200))
        # Note: Using MultilineTextInput as a placeholder since toga-textual might not support Selection with multiple=True

        # Buttons section
        button_box = toga.Box(style=Pack(direction=ROW, margin=5))
        download_button = toga.Button('Download', on_press=self.on_download_press, style=Pack(margin=5))
        stream_button = toga.Button('Stream', on_press=self.on_stream_press, style=Pack(margin=5))
        cancel_button = toga.Button('Cancel', on_press=self.on_cancel_press, style=Pack(margin=5))

        button_box.add(download_button)
        button_box.add(stream_button)
        button_box.add(cancel_button)

        # Settings section
        settings_box = toga.Box(style=Pack(direction=COLUMN, margin=5))

        # TWIT Club URL setting
        url_box = toga.Box(style=Pack(direction=ROW, margin=5))
        url_label = toga.Label('TWIT Club URL:', style=Pack(margin=(0, 5)))
        url_prefix = toga.Label('https://twit.memberfulcontent.com/rss/9041?auth=', style=Pack(margin=(0, 5)))
        self.url_input = toga.TextInput(style=Pack(flex=1))
        url_box.add(url_label)
        url_box.add(url_prefix)
        url_box.add(self.url_input)

        # Destination folder setting
        dest_box = toga.Box(style=Pack(direction=ROW, margin=5))
        dest_label = toga.Label('Download Destination:', style=Pack(margin=(0, 5)))
        self.dest_input = toga.TextInput(style=Pack(flex=1))
        dest_button = toga.Button('Browse', on_press=self.on_browse_press, style=Pack(margin=5))
        dest_box.add(dest_label)
        dest_box.add(self.dest_input)
        dest_box.add(dest_button)

        # Block size setting
        block_box = toga.Box(style=Pack(direction=ROW, margin=5))
        block_label = toga.Label('Block Size:', style=Pack(margin=(0, 5)))
        self.block_input = toga.TextInput(value='8192', style=Pack(flex=1))
        block_box.add(block_label)
        block_box.add(self.block_input)

        # Streamer setting
        streamer_box = toga.Box(style=Pack(direction=ROW, margin=5))
        streamer_label = toga.Label('Streamer:', style=Pack(margin=(0, 5)))
        self.streamer_input = toga.TextInput(value='vlc %f', style=Pack(flex=1))
        streamer_box.add(streamer_label)
        streamer_box.add(self.streamer_input)

        # Add all sections to settings box
        settings_box.add(url_box)
        settings_box.add(dest_box)
        settings_box.add(block_box)
        settings_box.add(streamer_box)

        # Add all components to main box
        main_box.add(show_box)
        main_box.add(sort_box)
        main_box.add(episodes_label)
        main_box.add(self.episodes_list)
        main_box.add(button_box)
        main_box.add(settings_box)

        # Create main window
        self.main_window = toga.MainWindow(title='TWIT.tv TUI')
        self.main_window.content = main_box
        self.main_window.show()

    def on_download_press(self, widget):
        # Implement download functionality
        pass

    def on_stream_press(self, widget):
        # Implement stream functionality
        pass

    def on_cancel_press(self, widget):
        # Exit the application
        self.exit()

    def on_browse_press(self, widget):
        # Implement folder selection
        pass

    def fetch_episodes(self, show_id):
        """Fetch episodes for a specific show ID."""
        try:
            # Load environment variables from .env file
            load_dotenv()

            # Get API credentials from environment variables
            app_id = os.getenv('TWITAPI_APPLICATIONID')
            app_key = os.getenv('TWITAPI_APPLICATIONKEYS')

            if not app_id or not app_key:
                print("API credentials not found in .env file")
                return []

            # Set up headers for API request
            headers = {
                'Accept': 'application/json',
                'app-id': app_id,
                'app-key': app_key
            }

            # Make request to episodes endpoint with show filter
            url = f'https://twit.tv/api/v1.0/episodes?filter[shows]={show_id}'
            response = requests.get(url, headers=headers)

            # Check if request was successful
            if response.status_code == 200:
                data = response.json()
                episodes = []
                if 'episodes' in data and isinstance(data['episodes'], list):
                    for episode in data['episodes']:
                        # Extract relevant episode information
                        episode_info = {}
                        if 'title' in episode:
                            episode_info['title'] = episode['title']
                        if 'publishDate' in episode:
                            episode_info['date'] = episode['publishDate']
                        if 'episodeNumber' in episode:
                            episode_info['number'] = episode['episodeNumber']

                        if episode_info:
                            episodes.append(episode_info)

                return episodes
            else:
                print(f"API request failed with status code {response.status_code}")
                return []
        except Exception as e:
            print(f"Error fetching episodes: {e}")
            return []

    def on_fetch_press(self, widget):
        """Fetch episodes for the selected show and refresh the show list."""
        # Refresh the show list
        shows = self.fetch_shows()
        if shows:
            # Remember the currently selected show
            current_selection = self.show_combo.value

            # Update the combo box items
            self.show_combo.items = shows

            # Try to restore the previous selection if it still exists
            if current_selection in shows:
                self.show_combo.value = current_selection

        # Get the selected show from the combo box
        selected_show = self.show_combo.value

        if selected_show and selected_show in self.show_ids:
            # Get the show ID for the selected show
            show_id = self.show_ids[selected_show]

            # Fetch episodes for the selected show
            episodes = self.fetch_episodes(show_id)

            # Clear the episodes list
            self.episodes_list.value = ""

            # Display the episodes in the episodes list
            if episodes:
                # Determine sort order based on selected radio button
                sort_by = 'date'  # Default sort by date
                if '☑' in self.episode_radio.text:
                    sort_by = 'number'
                elif '☑' in self.title_radio.text:
                    sort_by = 'title'

                # Sort episodes based on selected sort option
                if sort_by == 'date':
                    episodes.sort(key=lambda x: x.get('date', ''), reverse=True)
                elif sort_by == 'number':
                    episodes.sort(key=lambda x: x.get('number', 0), reverse=True)
                elif sort_by == 'title':
                    episodes.sort(key=lambda x: x.get('title', ''))

                # Format episodes for display
                episode_texts = []
                for episode in episodes:
                    title = episode.get('title', 'Unknown Title')
                    date = episode.get('date', 'Unknown Date')
                    number = episode.get('number', 'Unknown Number')
                    episode_texts.append(f"Episode {number}: {title} ({date})")

                # Join episode texts with newlines and set as episodes list value
                self.episodes_list.value = "\n".join(episode_texts)
            else:
                self.episodes_list.value = "No episodes found for this show."
        else:
            self.episodes_list.value = "Please select a show first."

    def on_sort_button_press(self, widget):
        """Handle radio button behavior for checkbox-like buttons."""
        # Update all buttons to show unchecked state
        self.date_radio.text = self.date_radio.text.replace('☑', '☐')
        self.episode_radio.text = self.episode_radio.text.replace('☑', '☐')
        self.title_radio.text = self.title_radio.text.replace('☑', '☐')

        # Update the clicked button to show checked state
        if widget == self.date_radio:
            self.date_radio.text = self.date_radio.text.replace('☐', '☑')
        elif widget == self.episode_radio:
            self.episode_radio.text = self.episode_radio.text.replace('☐', '☑')
        elif widget == self.title_radio:
            self.title_radio.text = self.title_radio.text.replace('☐', '☑')

def main():
    return TwitTUIForm('TWIT.tv TUI', 'org.beeware.twittui')

if __name__ == '__main__':
    app = main()
    app.main_loop()
