import requests
import time
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.config import Config

from kivy.uix.label import Label

# Kivy configuration for touch screens
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'fullscreen', '1')
Config.set('graphics', 'borderless', '1')
Config.set('graphics', 'window_state', 'maximized')
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')
Config.set('graphics', 'show_cursor', '0')

API_URL = "http://localhost:5000/api"

class TouchOverlay(FloatLayout):
    def __init__(self, **kwargs):
        super(TouchOverlay, self).__init__(**kwargs)
        
        # Now Playing Label (Top)
        self.lbl_playing = Label(
            text="Waiting for Music...",
            font_size='20sp',
            pos_hint={'top': 0.95, 'center_x': 0.5},
            size_hint=(1, 0.1),
            bold=True,
            color=(1, 1, 1, 1),
            opacity=0 # Hidden by default
        )
        
        # Main button container
        self.controls = GridLayout(
            cols=3, 
            size_hint=(0.8, 0.4),
            pos_hint={'center_x': 0.5, 'center_y': 0.45},
            spacing=20,
            padding=20
        )
        
        # Hide controls initially
        self.controls.opacity = 0
        self.controls.disabled = True
        
        # Premium Button styling helper
        def create_btn(text, color):
            return Button(
                text=text,
                font_size='20sp',
                background_normal='',
                background_color=color,
                color=(1, 1, 1, 1),
                bold=True,
                halign='center'
            )

        # Colors (Modern Palette)
        BLUE = (0.1, 0.4, 0.8, 0.9)
        GREEN = (0.1, 0.7, 0.3, 0.9)
        RED = (0.8, 0.2, 0.2, 0.9)
        ORANGE = (0.9, 0.5, 0.1, 0.9)
        GRAY = (0.3, 0.3, 0.3, 0.6)

        # Create buttons
        self.btn_prev = create_btn('⏮\nPrev', BLUE)
        self.btn_play = create_btn('⏯\nPlay/Pause', GREEN)
        self.btn_next = create_btn('⏭\nNext', BLUE)
        
        self.btn_vol_down = create_btn('🔉\nVol -', ORANGE)
        self.btn_stop = create_btn('⏹\nStop', RED)
        self.btn_vol_up = create_btn('🔊\nVol +', ORANGE)
        
        # Close button (top right, small)
        self.btn_close = Button(
            text='X',
            size_hint=(None, None),
            size=(60, 60),
            pos_hint={'top': 0.98, 'right': 0.98},
            background_color=GRAY,
            opacity=0
        )
        
        # Bind buttons
        self.btn_prev.bind(on_release=lambda x: self.api_call("prev"))
        self.btn_play.bind(on_release=lambda x: self.api_call("resume"))
        self.btn_next.bind(on_release=lambda x: self.api_call("next"))
        self.btn_stop.bind(on_release=lambda x: self.api_call("stop"))
        self.btn_vol_up.bind(on_release=lambda x: self.adjust_volume(5))
        self.btn_vol_down.bind(on_release=lambda x: self.adjust_volume(-5))
        self.btn_close.bind(on_release=lambda x: self.hide_controls())
        
        # Add buttons to grid
        self.controls.add_widget(self.btn_prev)
        self.controls.add_widget(self.btn_play)
        self.controls.add_widget(self.btn_next)
        self.controls.add_widget(self.btn_vol_down)
        self.controls.add_widget(self.btn_stop)
        self.controls.add_widget(self.btn_vol_up)
        
        self.add_widget(self.lbl_playing)
        self.add_widget(self.controls)
        self.add_widget(self.btn_close)
        
        # Polling for status (every 2 seconds)
        Clock.schedule_interval(self.update_status, 2)
        
        # Timer for hiding
        self.hide_event = None
        
    def update_status(self, dt):
        try:
            # Increased timeout to 3s to be more patient with the server
            r = requests.get(f"{API_URL}/status", timeout=3)
            if r.status_code == 200:
                data = r.json()
                title = data.get("title", "Unknown")
                artist = data.get("artist", "")
                self.lbl_playing.text = f"Now Playing: {title}\n{artist}"
        except:
            pass

    def on_touch_down(self, touch):
        # If controls are hidden, show them
        if self.controls.opacity == 0:
            self.show_controls()
            return True 
        
        return super(TouchOverlay, self).on_touch_down(touch)

    def show_controls(self):
        self.controls.opacity = 1
        self.controls.disabled = False
        self.btn_close.opacity = 1
        self.lbl_playing.opacity = 1
        
        if self.hide_event:
            self.hide_event.cancel()
        self.hide_event = Clock.schedule_once(self.hide_controls, 15)

    def hide_controls(self, dt=None):
        self.controls.opacity = 0
        self.controls.disabled = True
        self.btn_close.opacity = 0
        self.lbl_playing.opacity = 0

    def api_call(self, endpoint):
        self.show_controls()
        try:
            requests.post(f"{API_URL}/{endpoint}", timeout=2)
        except Exception as e:
            print(f"API Error: {e}")

    def adjust_volume(self, delta):
        self.show_controls()
        try:
            r = requests.get(f"{API_URL}/volume", timeout=2)
            if r.status_code == 200:
                curr = r.json().get("volume", 50)
                new_vol = max(0, min(100, curr + delta))
                requests.post(f"{API_URL}/volume", json={"volume": new_vol}, timeout=2)
        except Exception as e:
            print(f"Volume API Error: {e}")

class MusicGuiApp(App):
    def build(self):
        if Window:
            # Set background to 100% transparent to see video underneath
            Window.clearcolor = (0, 0, 0, 0)
        return TouchOverlay()

if __name__ == '__main__':
    MusicGuiApp().run()
