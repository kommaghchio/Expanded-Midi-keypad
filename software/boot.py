# Runs once on power-up, before code.py. The ESP32-S3 does not have a
# spare USB endpoint for MIDI while the keyboard device is also on.
import usb_cdc
import usb_hid
import usb_midi

usb_cdc.enable(console=True, data=False)
usb_hid.disable()
usb_midi.enable()
