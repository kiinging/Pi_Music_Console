"""Weston touch launcher: opens CSI library in Chromium (same Pi as Flask).

CSI_LIBRARY_URL:
  - Default http://127.0.0.1:5000/csi is correct when Chromium runs ON THE SAME Pi as Flask.
  - Phone/PC on LAN: open http://<Pi-LAN-IP>:5000/csi manually (no env needed on phone).
  - Override only if Flask listens elsewhere: export CSI_LIBRARY_URL=http://...

CHROMIUM_COMMAND:
  - Optional full path to browser if not on PATH (e.g. /usr/bin/chromium-browser).
"""
import datetime
import glob
import os
import shutil
import subprocess
import sys
from typing import List, Optional

import requests

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.config import Config
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label

Config.set("graphics", "resizable", "0")
Config.set("graphics", "fullscreen", "1")
Config.set("graphics", "borderless", "1")
Config.set("graphics", "show_cursor", "0")

API_URL = os.environ.get("PI_MUSIC_API", "http://127.0.0.1:5000/api")
CSI_URL = os.environ.get("CSI_LIBRARY_URL", "http://127.0.0.1:5000/csi")

_BG = (0.05, 0.05, 0.07, 1)
_GOLD = (0.79, 0.66, 0.38, 1)
_TILE = (0.12, 0.12, 0.16, 0.95)
_MUTED = (0.55, 0.55, 0.62, 1)

_LOG_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "touch_controls.log")


def _log(msg: str) -> None:
    line = f"{datetime.datetime.now().isoformat()} {msg}\n"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="", file=sys.stderr)


_WHICH_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"


def _is_exe(path: str) -> bool:
    return bool(path and os.path.isfile(path) and os.access(path, os.X_OK))


def _find_browser() -> Optional[str]:
    """Resolve Chromium/Chrome/Firefox for the CSI web UI. Pi images often lack a full PATH."""
    override = os.environ.get("CHROMIUM_COMMAND") or os.environ.get("BROWSER_EXE")
    if override:
        if _is_exe(override):
            return override
        w = shutil.which(override, path=_WHICH_PATH)
        if w:
            return w

    candidates: List[str] = []
    for path in (
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/lib/chromium-browser/chromium-browser",
        "/usr/lib/chromium/chromium",
    ):
        candidates.append(path)

    for pat in (
        "/usr/lib/chromium*/chromium-browser",
        "/usr/lib/chromium*/chromium",
        "/usr/lib/*/chrome/chrome",
    ):
        candidates.extend(sorted(glob.glob(pat)))

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if _is_exe(path):
            return path

    which_kw = {}
    try:
        which_kw["path"] = os.environ.get("PATH", "") + ":" + _WHICH_PATH
    except Exception:
        pass

    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome-stable",
        "google-chrome",
        "firefox",
        "firefox-esr",
    ):
        try:
            found = shutil.which(name, **which_kw)
        except TypeError:
            found = shutil.which(name)
        if found and _is_exe(found):
            return found

    return None


def _browser_argv(exe: str, url: str) -> List[str]:
    base = os.path.basename(exe).lower()
    if "firefox" in base:
        return [exe, "-new-instance", "-kiosk", url]
    if base == "epiphany" or base == "epiphany-browser":
        return [exe, "--application-mode", url]
    # Chromium / Chrome
    return [
        exe,
        "--ozone-platform=wayland",
        "--new-window",
        "--no-first-run",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--disable-translate",
        "--app=" + url,
    ]


class TouchOverlay(FloatLayout):
    _browser_watch_ev = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._browser_proc = None
        self._browser_stderr = None
        Window.clearcolor = _BG

        root = BoxLayout(orientation="vertical", padding=[12, 10, 12, 8], spacing=6)
        self.add_widget(root)

        top = BoxLayout(orientation="horizontal", size_hint=(1, 0.14), spacing=8)
        self.lbl_brand = Label(
            text="REJANG A1",
            font_size="16sp",
            bold=True,
            color=_GOLD,
            size_hint_x=0.34,
            halign="left",
            valign="middle",
        )
        self.lbl_brand.bind(size=lambda *_: setattr(self.lbl_brand, "text_size", self.lbl_brand.size))

        self.lbl_clock = Label(
            text="--:-- • -- -- ---",
            font_size="16sp",
            color=(0.92, 0.92, 0.95, 1),
            size_hint_x=0.38,
            halign="center",
            valign="middle",
        )
        self.lbl_clock.bind(size=lambda *_: setattr(self.lbl_clock, "text_size", self.lbl_clock.size))

        icons = BoxLayout(orientation="horizontal", size_hint_x=0.28, spacing=4)
        for sym in ("\u2699", "\u29e4", "\u2318"):
            icons.add_widget(Label(text=sym, font_size="20sp", color=_MUTED, size_hint_x=1))

        top.add_widget(self.lbl_brand)
        top.add_widget(self.lbl_clock)
        top.add_widget(icons)
        root.add_widget(top)

        center = AnchorLayout(size_hint=(1, 0.78))
        tile_col = BoxLayout(orientation="vertical", spacing=14, size_hint=(0.92, 0.92))

        self.btn_music = Button(
            text="~/Music\n[size=12sp]Video and audio from your library[/size]",
            font_size="20sp",
            bold=True,
            markup=True,
            halign="center",
            valign="middle",
            background_normal="",
            background_color=(0.16, 0.14, 0.12, 1),
            color=(0.95, 0.92, 0.86, 1),
            size_hint_y=0.45,
        )
        self.btn_music.bind(size=self._bind_text_size)
        self.btn_music.bind(on_release=self.open_csi_library)

        grid = GridLayout(cols=2, spacing=12, size_hint_y=0.55)
        self.btn_yt = self._small_tile("YouTube", _MUTED)
        self.btn_vol_up = self._small_tile("Vol +", _MUTED)
        self.btn_vol_dn = self._small_tile("Vol -", _MUTED)
        self.btn_settings = self._small_tile("Settings", _MUTED)
        for b in (self.btn_yt, self.btn_vol_up, self.btn_vol_dn, self.btn_settings):
            b.bind(on_release=self._dummy)
        grid.add_widget(self.btn_yt)
        grid.add_widget(self.btn_vol_up)
        grid.add_widget(self.btn_vol_dn)
        grid.add_widget(self.btn_settings)

        tile_col.add_widget(self.btn_music)
        tile_col.add_widget(grid)
        center.add_widget(tile_col)
        root.add_widget(center)

        self.lbl_playing = Label(
            text="Ready — tap ~/Music for library",
            font_size="13sp",
            color=_MUTED,
            size_hint=(1, 0.08),
            halign="center",
            valign="middle",
        )
        self.lbl_playing.bind(size=lambda *_: setattr(self.lbl_playing, "text_size", self.lbl_playing.size))
        root.add_widget(self.lbl_playing)

        Clock.schedule_interval(self._tick_clock, 1)
        Clock.schedule_interval(self.update_status, 2)

    @staticmethod
    def _small_tile(title, color):
        b = Button(
            text=title,
            font_size="16sp",
            bold=True,
            background_normal="",
            background_color=_TILE,
            color=color,
        )
        b.bind(size=TouchOverlay._bind_text_size)
        return b

    @staticmethod
    def _bind_text_size(inst, size):
        inst.text_size = size

    @staticmethod
    def _dummy(*_a):
        return

    def _tick_clock(self, _dt):
        n = datetime.datetime.now()
        self.lbl_clock.text = n.strftime("%H:%M") + " • " + n.strftime("%a %d %b")

    def _stop_browser_watch(self):
        if self._browser_watch_ev is not None:
            self._browser_watch_ev.cancel()
            self._browser_watch_ev = None

    def _close_csi_browser(self):
        self._stop_browser_watch()
        if self._browser_proc is None:
            return
        if self._browser_proc.poll() is None:
            try:
                self._browser_proc.terminate()
                self._browser_proc.wait(timeout=3)
            except Exception:
                try:
                    self._browser_proc.kill()
                except Exception:
                    pass
        self._browser_proc = None
        self._close_browser_stderr()

    def _close_browser_stderr(self):
        if getattr(self, "_browser_stderr", None) is not None:
            try:
                self._browser_stderr.close()
            except Exception:
                pass
            self._browser_stderr = None

    def _show_kivy_after_browser(self, _dt=None):
        try:
            Window.show()
        except Exception as e:
            _log(f"Window.show failed: {e}")
        try:
            Window.opacity = 1
        except Exception:
            pass
        self.lbl_playing.text = "Ready — tap ~/Music for library"

    def _watch_browser_process(self, _dt):
        if self._browser_proc is None:
            return False
        rc = self._browser_proc.poll()
        if rc is None:
            return True
        _log(f"browser subprocess exited rc={rc}")
        self._browser_proc = None
        self._close_browser_stderr()
        Clock.schedule_once(self._show_kivy_after_browser, 0)
        return False

    def open_csi_library(self, *_a):
        self.lbl_playing.text = "Opening library…"
        exe = _find_browser()
        if not exe:
            msg = (
                "No browser found. On Pi run:\n"
                "sudo apt update && sudo apt install -y chromium\n"
                "Or: export CHROMIUM_COMMAND=/usr/bin/chromium"
            )
            self.lbl_playing.text = msg
            _log("No browser executable found (chromium/firefox)")
            return

        self._close_csi_browser()
        env = os.environ.copy()
        env.setdefault("WAYLAND_DISPLAY", "wayland-0")
        env.setdefault("XDG_RUNTIME_DIR", "/tmp/weston-runtime")

        err_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "browser_csi.err")
        err_f = open(err_path, "w", encoding="utf-8")

        cmd = _browser_argv(exe, CSI_URL)
        env.setdefault("MOZ_ENABLE_WAYLAND", "1")
        _log(f"launch cmd={' '.join(cmd)}")
        try:
            self._browser_stderr = err_f
            self._browser_proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=err_f,
                start_new_session=True,
            )
        except Exception as e:
            try:
                err_f.close()
            except Exception:
                pass
            self.lbl_playing.text = "Browser error: " + str(e)[:100]
            _log(f"Popen failed: {e}")
            return

        try:
            Window.opacity = 0
            Window.hide()
        except Exception as e:
            _log(f"Window.hide warning (may still work): {e}")

        self.lbl_playing.text = "Library opened — close browser to return"
        self._browser_watch_ev = Clock.schedule_interval(self._watch_browser_process, 0.7)

        Clock.schedule_once(self._early_browser_check, 1.5)

    def _early_browser_check(self, _dt):
        if self._browser_proc is None:
            return
        if self._browser_proc.poll() is not None:
            rc = self._browser_proc.returncode
            err_tail = ""
            err_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "browser_csi.err")
            try:
                with open(err_path, "r", encoding="utf-8", errors="replace") as f:
                    err_tail = f.read()[-400:]
            except Exception:
                pass
            _log(f"browser exited early rc={rc} stderr_tail={err_tail!r}")
            self._browser_proc = None
            self._close_browser_stderr()
            self._stop_browser_watch()
            self._show_kivy_after_browser()
            short = (err_tail.replace("\n", " ")[:120]) if err_tail else ""
            self.lbl_playing.text = f"Browser exited ({rc}). {short}"[:200]

    def update_status(self, _dt):
        if self._browser_proc is not None and self._browser_proc.poll() is None:
            return
        try:
            r = requests.get(API_URL + "/status", timeout=3)
            if r.status_code != 200:
                return
            data = r.json()
            if data.get("status") == "error":
                return
            title = data.get("title") or "Nothing playing"
            artist = data.get("artist") or ""
            self.lbl_playing.text = (title + ("\n" + artist if artist else ""))[:120]
        except Exception:
            pass


class MusicGuiApp(App):
    def build(self):
        return TouchOverlay()


if __name__ == "__main__":
    MusicGuiApp().run()
