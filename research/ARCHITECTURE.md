# Orbit Editor: architecture

Python 3 for Windows, built into a single `.exe` with PyInstaller. MIDI goes through `winmm.dll`
via `ctypes` (no MIDI library); the window uses CustomTkinter, and Pillow draws the anti-aliased
parts (pads, color wheel, brightness bar).

```
orbit_editor/
├─ protocol.py   Pure data model (Pad, Knob, Axis, Bank, OrbitConfig): validation, factory mapping,
│                encoding/decoding of the 240 data bytes and the 249-byte SysEx messages
├─ colors.py     Color byte (R×16 + G×4 + B), brightness levels, palette and names
├─ scales.py     Scale mode: 14 scales, chromatic or in-scale layout, per-bank colors
├─ presets.py    .json presets (with scales) and .syx dumps
├─ editor.py     Editing state behind the window; every change is validated on a copy first
├─ midi_win.py   winmm: find the "ORBIT" ports, send/receive SysEx, notes/CCs as callbacks,
│                0.5 s quiet time after receiving (see PROTOCOL.md)
├─ device.py     read_config() and write_config(verify=True) on any port-like object
├─ link.py       Keeps the Orbit linked: automatic search, read on link, debounced live writes
│                (0.5 s after the last change), incoming notes/CCs as events
├─ render.py     Pillow drawings, supersampled for smooth edges; pads and steps are cached as tiles
├─ sequencer.py  4-track x 16-step sequencer: pure logic (Sequencer) and the MIDI thread
│                (SequencerRunner); the sequencer mapping the Orbit holds while it runs
├─ i18n.py       English and Spanish texts, chosen from the Windows language
├─ gui.py        Main window
└─ cli.py        Command-line tool (ports, read, backup, show, convert, write)
tests/           Unit tests with a simulated Orbit (FakeOrbit) and a fake winmm.dll; no hardware
research/        Protocol notes, wireless research, recordings and the scripts used to test a real Orbit
```

## Safety rules

- The app only sends command 01 (read) and command 03 (write), and 03 always carries a complete,
  validated block: all bytes 0–127, channels 0–15, colors 0–63.
- Every write is verified by reading the mapping back.
- Nothing unknown (other SysEx commands) is ever sent to the device.

## History

| Phase | Content |
|---|---|
| 0 | Protocol research: the official installer was unpacked without running it, and the official editor's Max/MSP patches were read to learn the messages |
| 1 | Tests on a real Orbit: read, identical re-write, one pad color, mode bits, brightness, live LEDs, bank/K buttons |
| 2 | `protocol.py`, `colors.py`, `presets.py` and their tests |
| 3 | `midi_win.py`, `device.py`, command-line tool, tests with simulated MIDI |
| 4 | First window (tkinter) |
| 5 | Modern window (CustomTkinter + Pillow), automatic link with live preview, color wheel, brightness, scale mode, README, MIT license, GitHub Actions, v1.0.0 |
| 6 | Sequencer (inspired by the nanoKONTROL 2 editor's), live pad colors, macOS light look shared with the nanoKONTROL 2 and Swing editors, vector logo and icons, v1.1.0 |

Assets: `assets/fonts` (Inter, SIL OFL), and `assets/logo.png`, `icon.ico` (window) and `app.ico`
(the `.exe`, on a navy background), all drawn by `docs/tools/make_logo.py`.

## Sequencer timing rules (seen on a real Orbit)

- No pad colors are sent while a mapping is read or written (`OrbitLink._sysex`): a SysEx arriving
  right after a burst of notes was lost, and the Orbit stopped answering.
- A SysEx waits `QUIET_AFTER_SHORT` (0.15 s) after the last note sent to the Orbit.
- After each write, the pads are repainted only once the Orbit listens again (0.6 s).
