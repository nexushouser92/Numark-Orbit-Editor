"""Numark Orbit SysEx protocol: pure data model and byte encoding, no MIDI I/O.

Messages (see research/PROTOCOLO.md):
  read request  F0 00 01 3F 2B 01 00 00 F7
  dump (reply)  F0 00 01 3F 2B 02 01 70 <240 data bytes> F7
  write         F0 00 01 3F 2B 03 01 70 <240 data bytes> F7

Data block, banks 1..4 in order:
  64 pads  x 3 bytes: mode<<4 | channel, note, color
  16 knobs x 2 bytes: mode<<4 | channel, cc
   8 axes  x 2 bytes: channel, cc   (axis 1 = left-right, axis 2 = up-down)
"""
from dataclasses import dataclass, field
from typing import List

HEADER = bytes([0xF0, 0x00, 0x01, 0x3F, 0x2B])
CMD_READ = 0x01
CMD_DUMP = 0x02
CMD_WRITE = 0x03
BLOCK_TAG = bytes([0x01, 0x70])  # constant after the dump/write command; meaning unknown
EOX = 0xF7

READ_REQUEST = HEADER + bytes([CMD_READ, 0x00, 0x00, EOX])

NUM_BANKS = 4
PADS_PER_BANK = 16
KNOBS_PER_BANK = 4
AXES_PER_BANK = 2

PAD_SIZE = 3
KNOB_SIZE = 2
AXIS_SIZE = 2
PADS_OFFSET = 0
KNOBS_OFFSET = PADS_OFFSET + NUM_BANKS * PADS_PER_BANK * PAD_SIZE      # 192
AXES_OFFSET = KNOBS_OFFSET + NUM_BANKS * KNOBS_PER_BANK * KNOB_SIZE    # 224
PAYLOAD_LEN = AXES_OFFSET + NUM_BANKS * AXES_PER_BANK * AXIS_SIZE      # 240
PREFIX_LEN = len(HEADER) + 1 + len(BLOCK_TAG)                          # 8
MESSAGE_LEN = PREFIX_LEN + PAYLOAD_LEN + 1                             # 249

MODE_BIT = 0x10
CHANNEL_MASK = 0x0F
MAX_COLOR = 0x3F  # 2 bits per component: R*16 + G*4 + B

FACTORY_FIRST_NOTE = 36
FACTORY_KNOB_CCS = (1, 2, 3, 4)
FACTORY_RELATIVE_KNOBS = (False, False, False, True)
FACTORY_AXIS_CCS = (9, 10)


class ProtocolError(ValueError):
    """Bytes that are not a valid Orbit message, or a value out of range."""


@dataclass
class Pad:
    channel: int = 0        # 0..15 (MIDI channel 1..16)
    note: int = 36          # 0..127
    toggle: bool = False    # False = momentary, True = toggle
    color: int = 0          # 0..63, see colors.py


@dataclass
class Knob:
    channel: int = 0
    cc: int = 1
    relative: bool = False  # False = absolute, True = relative


@dataclass
class Axis:
    channel: int = 0
    cc: int = 9


@dataclass
class Bank:
    pads: List[Pad] = field(default_factory=lambda: [Pad() for _ in range(PADS_PER_BANK)])
    knobs: List[Knob] = field(default_factory=lambda: [Knob() for _ in range(KNOBS_PER_BANK)])
    axes: List[Axis] = field(default_factory=lambda: [Axis() for _ in range(AXES_PER_BANK)])


@dataclass
class OrbitConfig:
    banks: List[Bank] = field(default_factory=lambda: [Bank() for _ in range(NUM_BANKS)])

    def validate(self):
        """Raise ProtocolError if any value cannot be sent to the Orbit."""
        if len(self.banks) != NUM_BANKS:
            raise ProtocolError(f"expected {NUM_BANKS} banks, got {len(self.banks)}")
        for b, bank in enumerate(self.banks, 1):
            _check_count(bank.pads, PADS_PER_BANK, f"bank {b} pads")
            _check_count(bank.knobs, KNOBS_PER_BANK, f"bank {b} knobs")
            _check_count(bank.axes, AXES_PER_BANK, f"bank {b} axes")
            for p, pad in enumerate(bank.pads, 1):
                where = f"bank {b} pad {p}"
                _check_range(pad.channel, 0, 15, where + " channel")
                _check_range(pad.note, 0, 127, where + " note")
                _check_range(pad.color, 0, MAX_COLOR, where + " color")
                _check_bool(pad.toggle, where + " toggle")
            for k, knob in enumerate(bank.knobs, 1):
                where = f"bank {b} knob {k}"
                _check_range(knob.channel, 0, 15, where + " channel")
                _check_range(knob.cc, 0, 127, where + " cc")
                _check_bool(knob.relative, where + " relative")
            for a, axis in enumerate(bank.axes, 1):
                where = f"bank {b} axis {a}"
                _check_range(axis.channel, 0, 15, where + " channel")
                _check_range(axis.cc, 0, 127, where + " cc")


def _check_count(items, expected, where):
    if len(items) != expected:
        raise ProtocolError(f"{where}: expected {expected}, got {len(items)}")


def _check_range(value, low, high, where):
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError(f"{where}: {value!r} is not an integer in {low}..{high}")


def _check_bool(value, where):
    if type(value) is not bool:
        raise ProtocolError(f"{where}: {value!r} is not true/false")


def factory_config():
    """Factory mapping, identical to what a fresh Orbit returns: bank n uses MIDI channel n."""
    config = OrbitConfig()
    for b, bank in enumerate(config.banks):
        bank.pads = [Pad(b, FACTORY_FIRST_NOTE + p, False, 0) for p in range(PADS_PER_BANK)]
        bank.knobs = [Knob(b, cc, rel) for cc, rel in zip(FACTORY_KNOB_CCS, FACTORY_RELATIVE_KNOBS)]
        bank.axes = [Axis(b, cc) for cc in FACTORY_AXIS_CCS]
    return config


def encode_payload(config):
    """OrbitConfig -> the 240 data bytes."""
    config.validate()
    pads, knobs, axes = bytearray(), bytearray(), bytearray()
    for bank in config.banks:
        for pad in bank.pads:
            pads += bytes([(MODE_BIT if pad.toggle else 0) | pad.channel, pad.note, pad.color])
        for knob in bank.knobs:
            knobs += bytes([(MODE_BIT if knob.relative else 0) | knob.channel, knob.cc])
        for axis in bank.axes:
            axes += bytes([axis.channel, axis.cc])
    return bytes(pads + knobs + axes)


def decode_payload(data):
    """The 240 data bytes -> OrbitConfig. Rejects bits the protocol does not define."""
    data = bytes(data)
    if len(data) != PAYLOAD_LEN:
        raise ProtocolError(f"data block must be {PAYLOAD_LEN} bytes, got {len(data)}")
    config = OrbitConfig()
    for b, bank in enumerate(config.banks):
        for p in range(PADS_PER_BANK):
            i = PADS_OFFSET + (b * PADS_PER_BANK + p) * PAD_SIZE
            mode_chan, note, color = data[i:i + PAD_SIZE]
            _check_mode_chan(mode_chan, f"bank {b + 1} pad {p + 1}")
            _check_range(note, 0, 127, f"bank {b + 1} pad {p + 1} note")
            _check_range(color, 0, MAX_COLOR, f"bank {b + 1} pad {p + 1} color")
            bank.pads[p] = Pad(mode_chan & CHANNEL_MASK, note, bool(mode_chan & MODE_BIT), color)
        for k in range(KNOBS_PER_BANK):
            i = KNOBS_OFFSET + (b * KNOBS_PER_BANK + k) * KNOB_SIZE
            mode_chan, cc = data[i:i + KNOB_SIZE]
            _check_mode_chan(mode_chan, f"bank {b + 1} knob {k + 1}")
            _check_range(cc, 0, 127, f"bank {b + 1} knob {k + 1} cc")
            bank.knobs[k] = Knob(mode_chan & CHANNEL_MASK, cc, bool(mode_chan & MODE_BIT))
        for a in range(AXES_PER_BANK):
            i = AXES_OFFSET + (b * AXES_PER_BANK + a) * AXIS_SIZE
            channel, cc = data[i:i + AXIS_SIZE]
            _check_range(channel, 0, 15, f"bank {b + 1} axis {a + 1} channel")
            _check_range(cc, 0, 127, f"bank {b + 1} axis {a + 1} cc")
            bank.axes[a] = Axis(channel, cc)
    return config


def _check_mode_chan(value, where):
    if value & ~(MODE_BIT | CHANNEL_MASK):
        raise ProtocolError(f"{where}: unknown bits in mode/channel byte 0x{value:02X}")


def _build(command, config):
    return HEADER + bytes([command]) + BLOCK_TAG + encode_payload(config) + bytes([EOX])


def build_write_message(config):
    """OrbitConfig -> the 249-byte write message (command 03)."""
    return _build(CMD_WRITE, config)


def build_dump_message(config):
    """OrbitConfig -> a 249-byte message in the same form the Orbit replies with (command 02)."""
    return _build(CMD_DUMP, config)


def parse_message(message, allowed=(CMD_DUMP,)):
    """A full dump (02) or write (03) message -> OrbitConfig.

    By default only the Orbit's reply is accepted; pass allowed=(CMD_DUMP, CMD_WRITE) to read files.
    """
    message = bytes(message)
    if len(message) != MESSAGE_LEN:
        raise ProtocolError(f"message must be {MESSAGE_LEN} bytes, got {len(message)}")
    if message[:len(HEADER)] != HEADER:
        raise ProtocolError("not a Numark Orbit SysEx message")
    command = message[len(HEADER)]
    if command not in allowed:
        raise ProtocolError(f"unexpected command 0x{command:02X}")
    if message[len(HEADER) + 1:PREFIX_LEN] != BLOCK_TAG:
        raise ProtocolError("unexpected bytes after the command")
    if message[-1] != EOX:
        raise ProtocolError("message does not end with F7")
    return decode_payload(message[PREFIX_LEN:-1])


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(note):
    """MIDI note number -> name, with note 36 = C1 (the Orbit's first factory pad)."""
    _check_range(note, 0, 127, "note")
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 2}"
