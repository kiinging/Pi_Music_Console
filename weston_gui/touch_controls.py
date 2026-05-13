import os
import requests

from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.config import Config

# =========================
# KIVY CONFIG
# =========================
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'fullscreen', '1')
Config.set('graphics', 'borderless', '1')
Config.set('graphics', 'show_cursor', '0')

API_URL = "http://localhost:5000/api"

MUSIC_FOLDER = os.path.expanduser("~/Music")

# =========================
# MAIN UI
# =========================
class TouchOverlay(FloatLayout):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Transparent background
        Window.clearcolor = (0, 0, 0, 0)

        # =========================
        # TOP STATUS LABEL
        # =========================
        self.lbl_playing = Label(
            text="Pi Music Console",
            font_size='18sp',
            bold=True,
            color=(1, 1, 1, 1),
            size_hint=(1, 0.08),
            pos_hint={"top": 1}
        )

        self.add_widget(self.lbl_playing)

        # =========================
        # TOP BUTTON BAR
        # =========================
        self.topbar = GridLayout(
            cols=4,
            size_hint=(1, 0.12),
            pos_hint={"top": 0.90},
            padding=10,
            spacing=10
        )

        def top_btn(text, color):
            return Button(
                text=text,
                font_size='22sp',
                bold=True,
                background_normal='',
                background_color=color,
                color=(1,1,1,1)
            )

        # Nice colors
        BLUE = (0.15, 0.35, 0.75, 0.95)
        PURPLE = (0.45, 0.20, 0.70, 0.95)
        GREEN = (0.10, 0.60, 0.30, 0.95)
        GRAY = (0.20, 0.20, 0.20, 0.90)

        self.btn_home = top_btn("⌂", BLUE)
        self.btn_music = top_btn("🎵", PURPLE)
        self.btn_settings = top_btn("⚙", GRAY)
        self.btn_wifi = top_btn("📶", GREEN)

        self.topbar.add_widget(self.btn_home)
        self.topbar.add_widget(self.btn_music)
        self.topbar.add_widget(self.btn_settings)
        self.topbar.add_widget(self.btn_wifi)

        self.add_widget(self.topbar)

        # =========================
        # MUSIC LIST AREA
        # =========================
        self.scroll = ScrollView(
            size_hint=(1, 0.78),
            pos_hint={"x": 0, "y": 0}
        )

        self.music_layout = BoxLayout(
            orientation='vertical',
            spacing=8,
            padding=10,
            size_hint_y=None
        )

        self.music_layout.bind(
            minimum_height=self.music_layout.setter('height')
        )

        self.scroll.add_widget(self.music_layout)

        self.add_widget(self.scroll)

        # Hide music list initially
        self.scroll.opacity = 0

        # =========================
        # BUTTON ACTIONS
        # =========================
        self.btn_music.bind(on_release=self.show_music_library)
        self.btn_home.bind(on_release=self.go_home)

        # =========================
        # UPDATE NOW PLAYING
        # =========================
        Clock.schedule_interval(self.update_status, 2)

    # ==================================================
    # SHOW HOME
    # ==================================================
    def go_home(self, instance=None):
        self.scroll.opacity = 0
        self.lbl_playing.text = "Pi Music Console"

    # ==================================================
    # SHOW MUSIC LIBRARY
    # ==================================================
    def show_music_library(self, instance=None):

        self.scroll.opacity = 1

        self.music_layout.clear_widgets()

        supported = (
            ".mp3",
            ".flac",
            ".wav",
            ".m4a",
            ".aac",
            ".ogg",
            ".mp4",
            ".mkv"
        )

        files = []

        for root, dirs, filenames in os.walk(MUSIC_FOLDER):
            for f in filenames:
                if f.lower().endswith(supported):
                    full = os.path.join(root, f)
                    files.append(full)

        files.sort()

        if not files:
            self.music_layout.add_widget(
                Label(
                    text="No music found",
                    size_hint_y=None,
                    height=60
                )
            )
            return

        for filepath in files:

            filename = os.path.basename(filepath)

            btn = Button(
                text=filename,
                size_hint_y=None,
                height=75,
                font_size='16sp',
                bold=True,
                halign='left',
                valign='middle',
                text_size=(700, None),
                background_normal='',
                background_color=(0.12, 0.12, 0.15, 0.92),
                color=(1,1,1,1)
            )

            btn.bind(
                on_release=lambda x, p=filepath: self.play_track(p)
            )

            self.music_layout.add_widget(btn)

    # ==================================================
    # PLAY TRACK
    # ==================================================
    def play_track(self, path):

        try:

            ext = os.path.splitext(path)[1].lower()

            media_type = "music"

            if ext in [".mp4", ".mkv"]:
                media_type = "video"

            payload = {
                "path": path,
                "type": media_type
            }

            r = requests.post(
                f"{API_URL}/play",
                json=payload,
                timeout=5
            )

            print(r.text)

        except Exception as e:
            print("Play Error:", e)

    # ==================================================
    # UPDATE STATUS
    # ==================================================
    def update_status(self, dt):

        try:

            r = requests.get(
                f"{API_URL}/status",
                timeout=3
            )

            if r.status_code == 200:

                data = r.json()

                title = data.get("title", "Nothing Playing")
                artist = data.get("artist", "")

                self.lbl_playing.text = f"{title}\n{artist}"

        except:
            pass


# =========================
# APP
# =========================
class MusicGuiApp(App):

    def build(self):
        return TouchOverlay()


if __name__ == '__main__':
    MusicGuiApp().run()