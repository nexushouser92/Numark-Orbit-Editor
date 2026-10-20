# Sends the Orbit the same messages its bank and K buttons send (CC 1 / CC 2 on channel 16) to see
# whether it switches bank or knob when told to by the PC. Ordinary CCs only: nothing is stored.
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from orbit_editor import midi_win

TIMELINE = [  # (seconds, label, cc, value)
    (5, "bank 3", 1, 3), (9, "bank 2", 1, 2), (13, "bank 4", 1, 4), (17, "bank 1", 1, 1),
    (21, "K3", 2, 3), (25, "K2", 2, 2), (29, "K4", 2, 4), (33, "K1", 2, 1),
]
END = 37


def main():
    ins, outs = midi_win.list_ports()
    port = midi_win.WinMidiPort(midi_win.find_port(ins), midi_win.find_port(outs))
    try:
        t0 = time.monotonic()
        for at, label, cc, value in TIMELINE:
            while time.monotonic() - t0 < at:
                time.sleep(0.01)
            r = port._w.midiOutShortMsg(port._hout, 0xBF | (cc << 8) | (value << 16))
            print(f"{time.monotonic() - t0:5.1f}s  {label}  (CC{cc} ch16 = {value}, result {r})", flush=True)
        while time.monotonic() - t0 < END:
            time.sleep(0.05)
    finally:
        port.close()


if __name__ == "__main__":
    main()
