# CircuitPython firmware for the MIDI keypad (Waveshare ESP32-S3-ZERO).
# Touch pads play the current instrument. Turning the encoder changes
# the instrument. The OLED shows a bar visualizer for the notes in the air.
import keypad
import touchio
import busio
from adafruit_midi.note_off import NoteOff
from adafruit_midi.note_on import NoteOn
from microcontroller import pin
from supervisor import ticks_ms

from kmk.keys import Key
from kmk.kmk_keyboard import KMKKeyboard
from kmk.modules.encoder import EncoderHandler
from kmk.scanners import Scanner


# Name, then the MIDI note for pads 1 through 7.
# Drums are General MIDI percussion; the others are pitched notes.
INSTRUMENTS = (
    ("Drums", (36, 38, 42, 46, 39, 45, 50)),
    ("Guitar", (40, 43, 45, 47, 50, 52, 55)),
    ("Piano", (60, 62, 64, 65, 67, 69, 71)),
    ("Horn", (60, 62, 64, 67, 69, 72, 74)),
)

NOTE_VELOCITY = 127

# 3-wide glyphs, five rows, leftmost bit is the high bit.
GLYPHS = {
    "A": (0b010, 0b101, 0b111, 0b101, 0b101),
    "D": (0b110, 0b101, 0b101, 0b101, 0b110),
    "G": (0b011, 0b100, 0b101, 0b101, 0b011),
    "H": (0b101, 0b101, 0b111, 0b101, 0b101),
    "I": (0b111, 0b010, 0b010, 0b010, 0b111),
    "M": (0b101, 0b111, 0b101, 0b101, 0b101),
    "N": (0b110, 0b101, 0b101, 0b101, 0b101),
    "O": (0b010, 0b101, 0b101, 0b101, 0b010),
    "P": (0b110, 0b101, 0b110, 0b100, 0b100),
    "R": (0b110, 0b101, 0b110, 0b101, 0b101),
    "S": (0b011, 0b100, 0b010, 0b001, 0b110),
    "T": (0b111, 0b010, 0b010, 0b010, 0b010),
    "U": (0b101, 0b101, 0b101, 0b101, 0b111),
}


class Visualizer:
    """Bars and a dotted reflection, the shape of a media-player visualizer.

    The title sits on top. Bars grow up from a center line and a dimmer
    copy hangs below it. A peak cap falls slower than the bar.
    """

    WIDTH = 128
    HEIGHT = 64
    BARS = 16
    BAR_W = 6
    GAP = 2
    BODY_BOTTOM = 34
    MAX_H = 22
    REFLECT_AT = 36
    LOW_NOTE = 36
    HIGH_NOTE = 74

    def __init__(self):
        self.levels = [0.0] * self.BARS
        self.peaks = [0.0] * self.BARS
        self.held = [0] * self.BARS
        self.title = ""
        self.bitmap = None
        self._title_dirty = True
        self._last_ms = None
        self._drawn_h = [-1] * self.BARS
        self._drawn_p = [-1] * self.BARS

    def bar_for(self, note):
        if note <= self.LOW_NOTE:
            return 0
        if note >= self.HIGH_NOTE:
            return self.BARS - 1
        span = self.HIGH_NOTE - self.LOW_NOTE
        return (note - self.LOW_NOTE) * (self.BARS - 1) // span

    def set_title(self, title):
        self.title = title
        self._title_dirty = True
        self.draw()

    def note_on(self, note):
        index = self.bar_for(note)
        self.held[index] += 1
        self.levels[index] = float(self.MAX_H)
        self.peaks[index] = float(self.MAX_H)
        for offset, scale in ((-1, 0.55), (1, 0.55), (-2, 0.28), (2, 0.28)):
            neighbor = index + offset
            if neighbor < 0 or neighbor >= self.BARS or self.held[neighbor]:
                continue
            splash = self.MAX_H * scale
            if splash > self.levels[neighbor]:
                self.levels[neighbor] = splash
                if splash > self.peaks[neighbor]:
                    self.peaks[neighbor] = splash
        self.draw()

    def note_off(self, note):
        index = self.bar_for(note)
        if self.held[index] > 0:
            self.held[index] -= 1

    def tick(self, now):
        if self._last_ms is None:
            self._last_ms = now
            return
        elapsed = (now - self._last_ms) & 0x1FFFFFFF
        if elapsed < 32:
            return
        steps = elapsed / 32
        if steps > 8:
            steps = 8
        self._last_ms = now
        for index in range(self.BARS):
            if self.held[index]:
                self.levels[index] = float(self.MAX_H)
            else:
                self.levels[index] = max(0.0, self.levels[index] - 6 * steps)
            if self.peaks[index] < self.levels[index]:
                self.peaks[index] = self.levels[index]
            elif self.peaks[index] > self.levels[index]:
                self.peaks[index] = max(self.levels[index], self.peaks[index] - 1.2 * steps)
        self.draw()

    def attach(self, bitmap):
        self.bitmap = bitmap
        self._title_dirty = True
        self._drawn_h = [-1] * self.BARS
        self._drawn_p = [-1] * self.BARS
        self.draw()

    def draw(self):
        if self.bitmap is None:
            return
        if self._title_dirty:
            self._draw_title()
            self._title_dirty = False
        self._draw_bars()

    def _draw_title(self):
        bitmap = self.bitmap
        for x in range(self.WIDTH):
            for y in range(8):
                bitmap[x, y] = 0
            bitmap[x, 35] = 1
        cursor = 2
        for char in self.title.upper():
            glyph = GLYPHS.get(char)
            if glyph is None:
                cursor += 4
                continue
            for row, bits in enumerate(glyph):
                for col in range(3):
                    if bits & (1 << (2 - col)):
                        bitmap[cursor + col, row] = 1
            cursor += 4

    def _draw_bars(self):
        bitmap = self.bitmap
        for index in range(self.BARS):
            height = int(self.levels[index])
            peak = int(self.peaks[index])
            if height == self._drawn_h[index] and peak == self._drawn_p[index]:
                continue
            x0 = index * (self.BAR_W + self.GAP)
            for dx in range(self.BAR_W):
                x = x0 + dx
                for y in range(12, 35):
                    bitmap[x, y] = 0
                for y in range(36, self.HEIGHT):
                    bitmap[x, y] = 0
                if height:
                    top = self.BODY_BOTTOM - height + 1
                    for y in range(top, self.BODY_BOTTOM + 1):
                        bitmap[x, y] = 1
                        mirror = self.REFLECT_AT + (self.BODY_BOTTOM - y)
                        if mirror < self.HEIGHT and ((x + mirror) & 1) == 0:
                            bitmap[x, mirror] = 1
                if peak:
                    peak_y = self.BODY_BOTTOM - peak
                    if 12 <= peak_y < 35:
                        bitmap[x, peak_y] = 1
            self._drawn_h[index] = height
            self._drawn_p[index] = peak


class VisualizerTask:
    def __init__(self, visualizer):
        self.visualizer = visualizer

    def before_matrix_scan(self, keyboard):
        self.visualizer.tick(ticks_ms())

    def during_bootup(self, keyboard):
        return

    def after_matrix_scan(self, keyboard):
        return

    def before_hid_send(self, keyboard):
        return

    def after_hid_send(self, keyboard):
        return

    def on_runtime_enable(self, keyboard):
        return

    def on_runtime_disable(self, keyboard):
        return

    def on_powersave_enable(self, keyboard):
        return

    def on_powersave_disable(self, keyboard):
        return

    def deinit(self, keyboard):
        return


class Player:
    def __init__(self):
        self.instrument = 0
        self.held = {}
        self.visualizer = Visualizer()
        self.midi = open_midi()
        self.visualizer.set_title(self.instrument_name)

    @property
    def instrument_name(self):
        return INSTRUMENTS[self.instrument][0]

    def change(self, steps):
        self.release_all()
        self.instrument = (self.instrument + steps) % len(INSTRUMENTS)
        self.visualizer.set_title(self.instrument_name)

    def note_on(self, key_index):
        if key_index in self.held:
            return
        note = INSTRUMENTS[self.instrument][1][key_index]
        self.held[key_index] = note
        self.midi.send(NoteOn(note, NOTE_VELOCITY))
        self.visualizer.note_on(note)

    def note_off(self, key_index):
        note = self.held.pop(key_index, None)
        if note is None:
            return
        self.midi.send(NoteOff(note, 0))
        self.visualizer.note_off(note)

    def release_all(self):
        for key_index in list(self.held):
            self.note_off(key_index)


def open_midi():
    import usb_midi
    from adafruit_midi import MIDI

    ports = usb_midi.ports
    if not ports:
        print("USB MIDI is off. Power-cycle the board so boot.py can enable it.")

        class _SilentMidi:
            def send(self, _message):
                return None

        return _SilentMidi()
    midi_out = ports[1] if len(ports) > 1 else ports[0]
    return MIDI(midi_out=midi_out, out_channel=0)


def attach_display(visualizer):
    try:
        import displayio
        import adafruit_displayio_ssd1306
        try:
            from i2cdisplaybus import I2CDisplayBus
        except ImportError:
            from displayio import I2CDisplay as I2CDisplayBus
    except ImportError as error:
        print("OLED library missing:", error)
        return
    try:
        displayio.release_displays()
        i2c = busio.I2C(OLED_SCL, OLED_SDA)
        bus = I2CDisplayBus(i2c, device_address=0x3C)
        display = adafruit_displayio_ssd1306.SSD1306(bus, width=128, height=64)
        bitmap = displayio.Bitmap(128, 64, 2)
        palette = displayio.Palette(2)
        palette[0] = 0x000000
        palette[1] = 0xFFFFFF
        group = displayio.Group()
        group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
        display.root_group = group
        visualizer.attach(bitmap)
    except Exception as error:
        print("OLED init failed:", error)


class TouchScanner(Scanner):
    # Don't touch the pads while the board boots - they calibrate on startup.
    def __init__(self, pins):
        self.pads = [touchio.TouchIn(pad) for pad in pins]
        self.pressed = [False] * len(pins)

    @property
    def key_count(self):
        return len(self.pads)

    def scan_for_changes(self):
        for index, pad in enumerate(self.pads):
            touched = pad.value
            if touched != self.pressed[index]:
                self.pressed[index] = touched
                return keypad.Event(index + self.offset, touched)


class NoteKey(Key):
    def __init__(self, key_index):
        super().__init__()
        self.key_index = key_index

    def on_press(self, keyboard, coord_int=None):
        player.note_on(self.key_index)

    def on_release(self, keyboard, coord_int=None):
        player.note_off(self.key_index)


class InstrumentKey(Key):
    def __init__(self, steps):
        super().__init__()
        self.steps = steps

    def on_press(self, keyboard, coord_int=None):
        player.change(self.steps)


class NoKey(Key):
    pass


# Capacitive pads, left to right.
TOUCH_PINS = (
    pin.GPIO1,
    pin.GPIO2,
    pin.GPIO3,
    pin.GPIO4,
    pin.GPIO5,
    pin.GPIO6,
    pin.GPIO7,
)

# EC11. Common is ground. The push switch is not connected.
ENCODER_A = pin.GPIO8
ENCODER_B = pin.GPIO9

# 0.96" SSD1306, 128x64. Pin order on the module is GND, 3V3, SCL, SDA.
OLED_SCL = pin.GPIO10
OLED_SDA = pin.GPIO11

player = Player()

keyboard = KMKKeyboard()
keyboard.matrix = TouchScanner(TOUCH_PINS)
keyboard.keymap = [[NoteKey(index) for index in range(len(TOUCH_PINS))]]

encoder = EncoderHandler()
encoder.pins = ((ENCODER_A, ENCODER_B, None),)
encoder.map = [((InstrumentKey(-1), InstrumentKey(1), NoKey()),)]

visualizer_task = VisualizerTask(player.visualizer)
keyboard.modules = [encoder, visualizer_task]

attach_display(player.visualizer)

if __name__ == '__main__':
    keyboard.go()
