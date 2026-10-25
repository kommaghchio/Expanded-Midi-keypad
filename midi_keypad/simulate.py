# Runs code.py on this computer with stand-ins for CircuitPython and KMK.
# The stand-ins only supply the hardware objects. Pads, turns, and the
# visualizer clock then go through the firmware's own handlers.
#
#   py -3 simulate.py          check the firmware and print the bars
#   py -3 simulate.py --play   play it from the keyboard
import importlib.util
import sys
import traceback
from pathlib import Path
from types import ModuleType


FIRMWARE_PATH = Path(__file__).with_name("code.py")


class Pin:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


class Event:
    def __init__(self, key_number, pressed):
        self.key_number = key_number
        self.pressed = pressed


class TouchIn:
    def __init__(self, pad):
        self.pin = pad
        self.value = False


class I2C:
    def __init__(self, scl, sda):
        self.scl = scl
        self.sda = sda


class Key:
    def __init__(self, *args, **kwargs):
        pass

    def on_press(self, keyboard, coord_int=None):
        return None

    def on_release(self, keyboard, coord_int=None):
        return None


class Scanner:
    offset = 0


class KMKKeyboard:
    def __init__(self):
        self.keymap = []
        self.matrix = None
        self.modules = []

    def go(self):
        raise RuntimeError("simulator must not enter keyboard.go()")


class EncoderHandler:
    def __init__(self):
        self.pins = None
        self.map = None


class NoteOn:
    def __init__(self, note, velocity=127, channel=None):
        self.note = note
        self.velocity = velocity
        self.channel = channel


class NoteOff:
    def __init__(self, note, velocity=0, channel=None):
        self.note = note
        self.velocity = velocity
        self.channel = channel


class MIDI:
    def __init__(self, midi_in=None, midi_out=None, in_channel=0, out_channel=0, **kwargs):
        self.midi_out = midi_out
        self.out_channel = out_channel
        self.sent = []

    def send(self, message):
        self.sent.append(message)


class Bitmap:
    def __init__(self, width, height, colors):
        self.width = width
        self.height = height
        self.pixels = [0] * (width * height)

    def __setitem__(self, key, value):
        x, y = key
        self.pixels[y * self.width + x] = value

    def __getitem__(self, key):
        x, y = key
        return self.pixels[y * self.width + x]


class Palette:
    def __init__(self, count):
        self.entries = [0] * count

    def __setitem__(self, index, value):
        self.entries[index] = value


class TileGrid:
    def __init__(self, bitmap, pixel_shader=None):
        self.bitmap = bitmap
        self.pixel_shader = pixel_shader


class Group:
    def __init__(self):
        self.items = []

    def append(self, item):
        self.items.append(item)


class I2CDisplay:
    def __init__(self, i2c, device_address=0x3C):
        self.i2c = i2c
        self.device_address = device_address


class SSD1306:
    def __init__(self, bus, width, height):
        self.bus = bus
        self.width = width
        self.height = height
        self.root_group = None


CLOCK = {"t": 0}


def ticks_ms():
    return CLOCK["t"]


def install_mocks():
    pin = ModuleType("microcontroller.pin")
    for number in range(0, 49):
        setattr(pin, f"GPIO{number}", Pin(f"GPIO{number}"))
    microcontroller = ModuleType("microcontroller")
    microcontroller.pin = pin

    keypad = ModuleType("keypad")
    keypad.Event = Event
    touchio = ModuleType("touchio")
    touchio.TouchIn = TouchIn
    busio = ModuleType("busio")
    busio.I2C = I2C

    supervisor = ModuleType("supervisor")
    supervisor.ticks_ms = ticks_ms

    usb_midi = ModuleType("usb_midi")
    usb_midi.ports = (object(), object())

    adafruit_midi = ModuleType("adafruit_midi")
    adafruit_midi.__path__ = []
    adafruit_midi.MIDI = MIDI
    note_on = ModuleType("adafruit_midi.note_on")
    note_on.NoteOn = NoteOn
    note_off = ModuleType("adafruit_midi.note_off")
    note_off.NoteOff = NoteOff

    displayio = ModuleType("displayio")
    displayio.Bitmap = Bitmap
    displayio.Palette = Palette
    displayio.TileGrid = TileGrid
    displayio.Group = Group
    displayio.I2CDisplay = I2CDisplay
    displayio.release_displays = lambda: None

    i2cdisplaybus = ModuleType("i2cdisplaybus")
    i2cdisplaybus.I2CDisplayBus = I2CDisplay

    ssd1306 = ModuleType("adafruit_displayio_ssd1306")
    ssd1306.SSD1306 = SSD1306

    kmk = ModuleType("kmk")
    kmk.__path__ = []
    keys = ModuleType("kmk.keys")
    keys.Key = Key
    keyboard_mod = ModuleType("kmk.kmk_keyboard")
    keyboard_mod.KMKKeyboard = KMKKeyboard
    modules = ModuleType("kmk.modules")
    modules.__path__ = []
    encoder = ModuleType("kmk.modules.encoder")
    encoder.EncoderHandler = EncoderHandler
    scanners = ModuleType("kmk.scanners")
    scanners.Scanner = Scanner

    sys.modules["microcontroller"] = microcontroller
    sys.modules["microcontroller.pin"] = pin
    sys.modules["keypad"] = keypad
    sys.modules["touchio"] = touchio
    sys.modules["busio"] = busio
    sys.modules["supervisor"] = supervisor
    sys.modules["usb_midi"] = usb_midi
    sys.modules["adafruit_midi"] = adafruit_midi
    sys.modules["adafruit_midi.note_on"] = note_on
    sys.modules["adafruit_midi.note_off"] = note_off
    sys.modules["displayio"] = displayio
    sys.modules["i2cdisplaybus"] = i2cdisplaybus
    sys.modules["adafruit_displayio_ssd1306"] = ssd1306
    sys.modules["kmk"] = kmk
    sys.modules["kmk.keys"] = keys
    sys.modules["kmk.kmk_keyboard"] = keyboard_mod
    sys.modules["kmk.modules"] = modules
    sys.modules["kmk.modules.encoder"] = encoder
    sys.modules["kmk.scanners"] = scanners


def load_firmware():
    CLOCK["t"] = 0
    install_mocks()
    spec = importlib.util.spec_from_file_location("midi_keypad_firmware", FIRMWARE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dispatch_matrix(firmware):
    event = firmware.keyboard.matrix.scan_for_changes()
    if event is None:
        return None
    keymap = firmware.keyboard.keymap[0]
    if event.key_number < 0 or event.key_number >= len(keymap):
        raise RuntimeError(
            f"scanner returned key {event.key_number}, keymap has {len(keymap)} keys"
        )
    key = keymap[event.key_number]
    if event.pressed:
        key.on_press(firmware.keyboard, event.key_number)
    else:
        key.on_release(firmware.keyboard, event.key_number)
    return event


def turn(firmware, steps):
    slot = 0 if steps < 0 else 1
    key = firmware.encoder.map[0][0][slot]
    key.on_press(firmware.keyboard, None)
    key.on_release(firmware.keyboard, None)


def touch(firmware, pad_index, pressed):
    firmware.keyboard.matrix.pads[pad_index].value = pressed
    return dispatch_matrix(firmware)


def messages(firmware, kind):
    return [message for message in firmware.player.midi.sent if isinstance(message, kind)]


def tick(firmware, now):
    CLOCK["t"] = now
    firmware.visualizer_task.before_matrix_scan(firmware.keyboard)


def preview(visualizer):
    rows = [visualizer.title]
    for step in range(8, 0, -1):
        limit = step * visualizer.MAX_H / 8
        rows.append("".join("#" if level >= limit else "." for level in visualizer.levels))
    return rows


class Report:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            print(f"PASS  {name}")
            return
        self.failed += 1
        print(f"FAIL  {name}")
        if detail:
            print(detail)

    def expect(self, name, actual, expected):
        self.check(
            name,
            actual == expected,
            f"    expected {expected!r}\n    actual   {actual!r}",
        )

    def run(self, name, function):
        try:
            function()
        except Exception:
            self.failed += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
            return False
        return True


def check_firmware(report, firmware):
    player = firmware.player
    visualizer = player.visualizer
    bitmap = visualizer.bitmap

    report.expect("starts on Drums", player.instrument_name, "Drums")
    report.expect("nothing is held", player.held, {})
    report.check("OLED bitmap is 128x64", bitmap is not None and bitmap.width == 128 and bitmap.height == 64)

    pads = firmware.keyboard.matrix.pads
    report.expect(
        "touch pads are GPIO1 through GPIO7",
        [pad.pin.name for pad in pads],
        [f"GPIO{number}" for number in range(1, 8)],
    )
    encoder_a, encoder_b, encoder_switch = firmware.encoder.pins[0]
    report.expect("encoder A is GPIO8", encoder_a.name, "GPIO8")
    report.expect("encoder B is GPIO9", encoder_b.name, "GPIO9")
    report.check("encoder switch is not wired", encoder_switch is None)
    report.expect("display SCL is GPIO10", firmware.OLED_SCL.name, "GPIO10")
    report.expect("display SDA is GPIO11", firmware.OLED_SDA.name, "GPIO11")

    # "D" in DRUMS has its top-left pixel on. "G" in GUITAR does not.
    report.expect("title draws the Drums label", bitmap[2, 0], 1)

    report.expect("low notes land on the left", visualizer.bar_for(36), 0)
    report.expect("high notes land on the right", visualizer.bar_for(74), visualizer.BARS - 1)
    report.check(
        "pitch moves left to right",
        visualizer.bar_for(36) < visualizer.bar_for(60) < visualizer.bar_for(74),
    )

    tick(firmware, 0)
    touch(firmware, 0, True)
    report.expect("pad 1 plays drums kick 36", messages(firmware, NoteOn)[-1].note, 36)
    report.expect("note velocity is 127", messages(firmware, NoteOn)[-1].velocity, 127)
    kick_bar = visualizer.bar_for(36)
    report.expect("held note pins its bar", visualizer.levels[kick_bar], float(visualizer.MAX_H))
    report.expect("bar body reaches the center line", bitmap[0, visualizer.BODY_BOTTOM], 1)
    report.expect("reflection is lit on even pixels", bitmap[0, visualizer.REFLECT_AT], 1)
    report.expect("reflection is dotted", bitmap[1, visualizer.REFLECT_AT], 0)
    sent = len(firmware.player.midi.sent)
    repeat = dispatch_matrix(firmware)
    report.check("holding a pad does not replay", repeat is None and len(firmware.player.midi.sent) == sent)

    tick(firmware, 500)
    report.expect("a held note stays at full height", visualizer.levels[kick_bar], float(visualizer.MAX_H))

    touch(firmware, 0, False)
    report.expect("release sends note off", messages(firmware, NoteOff)[-1].note, 36)
    tick(firmware, 500 + 64)
    report.check("released bar falls", visualizer.levels[kick_bar] < visualizer.MAX_H)
    report.check("peak cap falls slower than the bar", visualizer.peaks[kick_bar] > visualizer.levels[kick_bar])
    peak_y = visualizer.BODY_BOTTOM - int(visualizer.peaks[kick_bar])
    body_top = visualizer.BODY_BOTTOM - int(visualizer.levels[kick_bar]) + 1
    report.expect("peak cap is drawn above the bar", bitmap[0, peak_y], 1)
    report.expect("gap under the peak is empty", bitmap[0, peak_y + 2], 0)
    report.check("peak is above the body", peak_y < body_top)

    touch(firmware, 0, True)
    turn(firmware, 1)
    report.expect("clockwise selects Guitar", player.instrument_name, "Guitar")
    report.expect("turning releases the held note", messages(firmware, NoteOff)[-1].note, 36)
    report.expect("no pads stay held across the change", player.held, {})
    report.expect("title switches to Guitar", bitmap[2, 0], 0)

    # The finger was still down, so lift it before the next press.
    # The scanner only reports a change, and the new note starts on that press.
    touch(firmware, 0, False)
    touch(firmware, 0, True)
    touch(firmware, 0, False)
    report.expect("pad 1 now plays the guitar note 40", messages(firmware, NoteOn)[-1].note, 40)

    turn(firmware, -1)
    turn(firmware, -1)
    report.expect("counter-clockwise wraps to Horn", player.instrument_name, "Horn")
    touch(firmware, 6, True)
    touch(firmware, 6, False)
    report.expect("pad 7 plays the top horn note", messages(firmware, NoteOn)[-1].note, 74)
    report.check(
        "top horn note uses the rightmost bar",
        visualizer.bar_for(74) > visualizer.bar_for(40),
    )


def play(firmware):
    print("a/d instrument, 1-7 play a note, q quit")
    task_time = 0
    while True:
        print("\n".join(preview(firmware.player.visualizer)))
        command = input("> ").strip().lower()
        if command in ("q", "quit"):
            return
        if command in ("d", ">", "right"):
            turn(firmware, 1)
        elif command in ("a", "<", "left"):
            turn(firmware, -1)
        elif command in ("1", "2", "3", "4", "5", "6", "7"):
            pad_index = int(command) - 1
            touch(firmware, pad_index, True)
            touch(firmware, pad_index, False)
        else:
            print("use a, d, 1-7, or q")
        task_time += 80
        tick(firmware, task_time)


def main():
    report = Report()
    firmware = None

    def load():
        nonlocal firmware
        firmware = load_firmware()

    if not report.run("code.py imports", load):
        return 1

    print("MusicDJ simulator")
    if "--play" in sys.argv:
        play(firmware)
        return 0

    report.run("firmware behavior", lambda: check_firmware(report, firmware))
    print(f"\n{report.passed} passed, {report.failed} failed")
    print("\n".join(preview(firmware.player.visualizer)))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
