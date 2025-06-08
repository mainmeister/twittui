import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

class TwitTUIForm(toga.App):
    def startup(self):
        # Main box with vertical layout
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=5))
        
        # Show selection section
        show_label = toga.Label('Show:', style=Pack(padding=(0, 5)))
        self.show_combo = toga.Selection(style=Pack(flex=1))
        show_box = toga.Box(style=Pack(direction=ROW, padding=5))
        show_box.add(show_label)
        show_box.add(self.show_combo)
        
        # Sort options section
        sort_label = toga.Label('Sort by:', style=Pack(padding=(0, 5)))
        self.sort_group = toga.Group('sort_options')
        date_radio = toga.Switch('Date', group=self.sort_group, style=Pack(padding=5))
        episode_radio = toga.Switch('Episode Number', group=self.sort_group, style=Pack(padding=5))
        title_radio = toga.Switch('Episode Title', group=self.sort_group, style=Pack(padding=5))
        date_radio.value = True  # Default selection
        
        sort_box = toga.Box(style=Pack(direction=ROW, padding=5))
        sort_box.add(sort_label)
        sort_box.add(date_radio)
        sort_box.add(episode_radio)
        sort_box.add(title_radio)
        
        # Episodes list section
        episodes_label = toga.Label('Episodes:', style=Pack(padding=(0, 5)))
        self.episodes_list = toga.MultilineTextInput(readonly=True, style=Pack(flex=1, padding=5, height=200))
        # Note: Using MultilineTextInput as a placeholder since toga-textual might not support Selection with multiple=True
        
        # Buttons section
        button_box = toga.Box(style=Pack(direction=ROW, padding=5))
        download_button = toga.Button('Download', on_press=self.on_download_press, style=Pack(padding=5))
        stream_button = toga.Button('Stream', on_press=self.on_stream_press, style=Pack(padding=5))
        cancel_button = toga.Button('Cancel', on_press=self.on_cancel_press, style=Pack(padding=5))
        
        button_box.add(download_button)
        button_box.add(stream_button)
        button_box.add(cancel_button)
        
        # Settings section
        settings_box = toga.Box(style=Pack(direction=COLUMN, padding=5))
        
        # TWIT Club URL setting
        url_box = toga.Box(style=Pack(direction=ROW, padding=5))
        url_label = toga.Label('TWIT Club URL:', style=Pack(padding=(0, 5)))
        url_prefix = toga.Label('https://twit.memberfulcontent.com/rss/9041?auth=', style=Pack(padding=(0, 5)))
        self.url_input = toga.TextInput(style=Pack(flex=1))
        url_box.add(url_label)
        url_box.add(url_prefix)
        url_box.add(self.url_input)
        
        # Destination folder setting
        dest_box = toga.Box(style=Pack(direction=ROW, padding=5))
        dest_label = toga.Label('Download Destination:', style=Pack(padding=(0, 5)))
        self.dest_input = toga.TextInput(style=Pack(flex=1))
        dest_button = toga.Button('Browse', on_press=self.on_browse_press, style=Pack(padding=5))
        dest_box.add(dest_label)
        dest_box.add(self.dest_input)
        dest_box.add(dest_button)
        
        # Block size setting
        block_box = toga.Box(style=Pack(direction=ROW, padding=5))
        block_label = toga.Label('Block Size:', style=Pack(padding=(0, 5)))
        self.block_input = toga.TextInput(value='8192', style=Pack(flex=1))
        block_box.add(block_label)
        block_box.add(self.block_input)
        
        # Streamer setting
        streamer_box = toga.Box(style=Pack(direction=ROW, padding=5))
        streamer_label = toga.Label('Streamer:', style=Pack(padding=(0, 5)))
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
        # Implement cancel functionality
        pass
    
    def on_browse_press(self, widget):
        # Implement folder selection
        pass

def main():
    return TwitTUIForm('TWIT.tv TUI', 'org.beeware.twittui')

if __name__ == '__main__':
    app = main()
    app.main_loop()