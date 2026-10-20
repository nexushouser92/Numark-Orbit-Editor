# Logs every MIDI message the Orbit sends (notes, CCs and SysEx) for a number of seconds.
# Sends nothing to the Orbit.
# Usage: python -I monitor.py SECONDS OUTPUT.txt [PORT_NAME]
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from orbit_editor import midi_win

MIM_DATA = 0x3C3
KINDS = {0x80: "NoteOff", 0x90: "NoteOn", 0xA0: "PolyAT", 0xB0: "CC", 0xC0: "Prog", 0xD0: "ChanAT", 0xE0: "Pitch"}


class MonitorPort(midi_win.WinMidiPort):
    def __init__(self, *args, **kw):
        self.short = []
        super().__init__(*args, **kw)

    def _on_midi_in(self, handle, msg, instance, param1, param2):
        if msg == MIM_DATA:
            self.short.append((time.monotonic(), param1 & 0xFF, (param1 >> 8) & 0xFF, (param1 >> 16) & 0xFF))
        super()._on_midi_in(handle, msg, instance, param1, param2)


def describe(status, d1, d2):
    kind = KINDS.get(status & 0xF0, f"0x{status:02X}")
    return f"{kind:7} canal {(status & 0x0F) + 1:2}  {d1:3}  {d2:3}"


def main(seconds, out, needle="ORBIT"):
    ins, outs = midi_win.list_ports()
    index = midi_win.find_port(ins, needle)
    out_index = midi_win.find_port(outs, needle)
    if index is None or out_index is None:
        sys.exit(f"Port '{needle}' not found. Inputs: {ins}")
    lines = []
    with MonitorPort(index, out_index) as port:
        print(f"Grabando {seconds} s desde '{ins[index]}'...", flush=True)
        t0 = time.monotonic()
        end = t0 + seconds
        while time.monotonic() < end:
            msg = port.receive(0.2)
            if msg:
                lines.append(f"{time.monotonic() - t0:7.3f}  SysEx {msg.hex(' ')}")
        for t, s, d1, d2 in port.short:
            lines.append(f"{t - t0:7.3f}  {describe(s, d1, d2)}")
    lines.sort(key=lambda l: float(l.split()[0]))
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# puerto: {ins[index]}\n" + "\n".join(lines) + "\n")
    print(f"{len(lines)} mensajes guardados en {out}")


if __name__ == "__main__":
    main(float(sys.argv[1]), sys.argv[2], *(sys.argv[3:4]))
