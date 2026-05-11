from kivy.app import App
from kivy.uix.label import Label
from kivy.core.window import Window

class TestApp(App):
    def build(self):
        # If Window is None, Kivy failed to find a driver
        if Window:
            Window.clearcolor = (0.2, 0.2, 0.2, 1)
        return Label(text='Hello Pi 5!\nWayland is working.', font_size='40sp')

if __name__ == '__main__':
    TestApp().run()
