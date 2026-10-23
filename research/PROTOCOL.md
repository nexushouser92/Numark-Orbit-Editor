# Numark Orbit SysEx protocol: research notes

Unofficial project, not affiliated with Numark/inMusic. These notes describe the message format **in
our own words**, worked out for interoperability. No code or assets from the original editor were
copied into this project.

## Sources

| Source | What it gave us |
|---|---|
| The official editor's `setup.exe` (NSIS 2.46 installer), unpacked **without running it** with `tools/extract_nsis.py` | It contains a **Max/MSP 6** (Cycling '74) application. The editor is not compiled code: its logic is a set of Max patches and a few JavaScript files stored in an `.mxf` collective, and the SysEx messages can be read there as they are. |
| Official *Orbit Editor – User Guide v1.0* (public PDF on numark.com) | Confirms what can be edited (pads, knobs, accelerometer, colors). |
| Web search | No public documentation of the protocol and no open-source implementation. Only a Bome forum thread describing the LED color encoding (it matches our findings). |
| A real Orbit connected by USB | Every point marked ✅ below was checked on it. |

## MIDI ports

- Windows Vista and later: the port is called **`Numark ORBIT`** (input and output).
- Windows XP: the official editor looked for **`USB Audio Device`** (the XP class driver's generic name).
- Automatic detection can look for "ORBIT" in the port name.

## Common header

```
F0 00 01 3F 2B <command> ...  F7
   └──────┘ └┘
   Numark   Orbit (model id 0x2B)
```

`00 01 3F` is Numark's MIDI manufacturer id.

## Messages

| Direction | Bytes | Size | Meaning |
|---|---|---|---|
| PC → Orbit | `F0 00 01 3F 2B 01 00 00 F7` | 9 | **Request** the current mapping |
| Orbit → PC | `F0 00 01 3F 2B 02 01 70` + 240 bytes + `F7` | 249 | **Reply**: full mapping dump |
| PC → Orbit | `F0 00 01 3F 2B 03 01 70` + 240 bytes + `F7` | 249 | **Write** a full mapping |

- There is no partial write: the whole 240-byte block is always sent.
- The official editor accepts a reply only if it is exactly 249 bytes long and starts with
  `F0 00 01 3F 2B 02 01 70`.
- **How a write is verified**: send command 03, wait 100 ms, send request 01 and compare the 240
  bytes received with the ones sent; with no reply within 5 s, the write is considered failed. The
  Orbit sends no acknowledgement of its own: verification is a read-back.
- The bytes `01 70` after the command are the same in every message; their meaning is unknown
  (format version? memory slot?).

## The 240 data bytes

Always in order bank 1 → bank 4.

### 1) Pads: 4 banks × 16 pads × 3 bytes = 192 bytes (offsets 0–191)

| Byte | Content |
|---|---|
| 0 | `mode × 16 + channel`: bits 0–3 = MIDI channel (0–15 = channels 1–16); bit 4 = mode (0 = momentary, 1 = toggle) |
| 1 | Note number (0–127) |
| 2 | LED color (see the color table) |

Offset of pad *p* (1–16) in bank *b* (1–4): `((b-1)*16 + (p-1)) * 3`. Pad 1 is the top-left pad.

### 2) Knobs: 4 banks × 4 knobs × 2 bytes = 32 bytes (offsets 192–223)

| Byte | Content |
|---|---|
| 0 | `mode × 16 + channel`: bit 4 = mode (0 = absolute, 1 = relative) |
| 1 | CC number (0–127) |

### 3) Accelerometer: 4 banks × 2 axes × 2 bytes = 16 bytes (offsets 224–239)

| Byte | Content |
|---|---|
| 0 | Channel (0–15) |
| 1 | CC number |

Axis 1 = left-right, axis 2 = up-down.

### LED colors

Each color uses 2 bits per component (intensity 0–3): `value = R×16 + G×4 + B`, so 64 colors.
The official editor offers 12 of them:

| Value | R G B | Approximate color |
|---|---|---|
| 0 | 0 0 0 | off |
| 63 | 3 3 3 | white |
| 48 | 3 0 0 | red |
| 12 | 0 3 0 | green |
| 3 | 0 0 3 | blue |
| 60 | 3 3 0 | yellow |
| 52 | 3 1 0 | orange |
| 44 | 2 3 0 | lime |
| 15 | 0 3 3 | cyan |
| 51 | 3 0 3 | magenta |
| 49 | 3 0 1 | pink |
| 19 | 1 0 3 | violet |

## Factory mapping

- Pads: bank *b* → channel *b*, notes 36–51 (C1–D#2), momentary, color 0.
- Knobs: bank *b* → channel *b*, CC 1, 2, 3 and 4; knob 4 has the mode bit set (relative).
- Accelerometer: bank *b* → channel *b*, CC 9 (left-right) and CC 10 (up-down).

## Not covered by the mapping

The pad bank buttons, the K1–K4 buttons and the shoulder buttons are **not** configurable; only
pads, knobs and the accelerometer are.

## Confirmed on a real Orbit (USB cable, 2026-10-19/20)

1. ✅ **Read**: the Orbit answers command 01 with 249 bytes, header `F0 00 01 3F 2B 02 01 70`, and
   nothing else. A factory Orbit returns exactly the factory mapping above, including the mode bit on
   knob 4 (`10 04`, `11 04`…). Saved in `factory_dump.syx`.
2. ✅ **Write**: re-sending the factory dump reads back identical. Changing only bank 1 pad 1's color
   to 48 reads back identical, and the **top-left** pad turns red. That confirms the color encoding
   and that pad 1 is the top-left pad. Restoring the factory dump reads back identical.
3. ✅ **Timing**: a message sent right after the Orbit finishes sending a dump is lost. After a lost
   write the Orbit stops answering for more than 15 s; a read sent that way is answered late
   (~1.75 s). Waiting **0.5 s** after receiving before sending is enough
   (`midi_win.QUIET_AFTER_RECEIVE`). A read is answered in ~0.25 s, and after a write the Orbit
   accepts the verification read after 0.1 s.
4. ✅ **Mode bit** (`monitor_toggle_knobs.txt`):
   - Toggle pad (0x10): every press sends one message, alternating NoteOn 127 / NoteOff 0. A momentary
     pad sends NoteOn 127 on press and NoteOff 0 on release.
   - Absolute knob: CC with the value 0–127 (in steps of 2). Relative knob (0x10): CC value 1 when
     turned right and 127 (−1) when turned left.
5. ✅ **Bank and K buttons** (`monitor_bank_k_buttons.txt`): bank button *n* sends CC 1 on channel 16
   with value *n*, and button K*n* sends CC 2 on channel 16 with value *n*. Pressing the same button
   twice in a row does not send the second message.
6. ✅ **The PC cannot change the Orbit's bank or K**: sending it those same CCs changes nothing
   (`tools/bank_k_test.py`). The app does the opposite: it follows the bank and K chosen on the Orbit.
7. ✅ **Brightness**: the Orbit shows any value 0–63. Red, green, blue and white at levels 1, 2 and 3
   are clearly distinct, so each pad's brightness can be chosen.
8. ✅ **Live LEDs** (`tools/live_led_test.py`, `live_led_test.log`): a NoteOn sent TO the Orbit with a
   pad's note colors that pad, using the velocity as the color (note 36: velocity 3 = blue,
   12 = green, 48 = red). This is not stored. The accelerometer, wheel and K LEDs did **not** change
   with CC 9/10, CC 1–4 (channel 1) or CC 2 (channel 16), and the 240 bytes hold no color for them,
   so they seem fixed in the firmware.

9. ✅ **Shoulder buttons and accelerometer** (`monitor_accelerometer.txt`, 2026-10-23): the left
   shoulder sends note 3 and the right one note 4, on channel 16 (NoteOn 127 on press, NoteOff on
   release). The accelerometer only sends while a shoulder is held (left = left-right axis, right =
   forward-back) or latched with a double press: about 40 values per second, roughly 6–101.
10. ✅ **Wheel LEDs** follow only the physical wheel: no note, CC, pitch bend or aftertouch sent to the
    Orbit moved them (probe of CC 1–4 on channels 1–4, every CC on channel 16, pitch bend,
    aftertouch and notes 0–35).

## Still unconfirmed

- Whether the protocol behaves the same through the **wireless receiver** as through the USB cable.
- What `01 70` means, and whether the firmware answers other commands (nothing unknown is sent to the
  device).
