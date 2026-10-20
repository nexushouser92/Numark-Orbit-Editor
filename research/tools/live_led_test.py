# Live LED test: sends ordinary note/CC messages TO the Orbit (never SysEx, never a mapping write)
# on a fixed timeline, so the user can watch which LEDs react. Also logs what the Orbit sends back.
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from orbit_editor import midi_win


def short(status, d1, d2):
    return status | (d1 << 8) | (d2 << 16)


# (seconds from start, label, status, data1, data2)
TIMELINE = [
    (10.0, "F1 pad1 note36 vel3 (blue)", 0x90, 36, 3),
    (13.0, "F1 pad1 note36 vel12 (green)", 0x90, 36, 12),
    (16.0, "F1 pad1 note36 vel48 (red)", 0x90, 36, 48),
    (19.0, "F1 pad1 noteoff", 0x80, 36, 0),
]
TIMELINE += [(20.0 + 2 * i, f"F2 CC9 ch1 = {v}", 0xB0, 9, v) for i, v in enumerate((0, 32, 64, 96, 127))]
TIMELINE += [(30.0 + 2 * i, f"F3 CC10 ch1 = {v}", 0xB0, 10, v) for i, v in enumerate((0, 32, 64, 96, 127))]
TIMELINE += [(40.0 + i, f"F4 CC{cc} ch1 = {v}", 0xB0, cc, v)
             for i, (cc, v) in enumerate(((1, 0), (1, 64), (1, 127), (4, 0), (4, 64), (4, 127),
                                          (1, 0), (4, 0), (1, 127), (4, 127)))]
TIMELINE += [(50.0 + 2.5 * i, f"F5 CC2 ch16 = {v}", 0xBF, 2, v) for i, v in enumerate((1, 2, 3, 4))]
END = 61.0


def main(log_path):
    ins, outs = midi_win.list_ports()
    port = midi_win.WinMidiPort(midi_win.find_port(ins), midi_win.find_port(outs))
    log = []
    try:
        t0 = time.monotonic()
        for at, label, status, d1, d2 in TIMELINE:
            while time.monotonic() - t0 < at:
                time.sleep(0.01)
            r = port._w.midiOutShortMsg(port._hout, short(status, d1, d2))
            log.append(f"{time.monotonic() - t0:6.2f}  {label}  (result {r})")
        while time.monotonic() - t0 < END:
            time.sleep(0.05)
    finally:
        port.close()
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1])
