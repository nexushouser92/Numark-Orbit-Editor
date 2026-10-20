"""Tests for protocol.py, colors.py and presets.py. No MIDI device is needed.

Run with: python -m unittest discover -s tests
"""
import copy
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from orbit_editor import colors, presets, protocol
from orbit_editor.protocol import ProtocolError

# Reply captured from a real Orbit at factory settings (read request only, 2026-10-19).
FACTORY_DUMP_PATH = os.path.join(ROOT, "tests", "data", "factory_dump.syx")


def factory_dump():
    with open(FACTORY_DUMP_PATH, "rb") as f:
        return f.read()


def custom_config():
    config = protocol.factory_config()
    pad = config.banks[2].pads[5]
    pad.channel, pad.note, pad.toggle, pad.color = 9, 100, True, 52
    knob = config.banks[1].knobs[0]
    knob.channel, knob.cc, knob.relative = 15, 74, True
    axis = config.banks[3].axes[1]
    axis.channel, axis.cc = 4, 127
    return config


class LayoutTests(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(protocol.KNOBS_OFFSET, 192)
        self.assertEqual(protocol.AXES_OFFSET, 224)
        self.assertEqual(protocol.PAYLOAD_LEN, 240)
        self.assertEqual(protocol.MESSAGE_LEN, 249)

    def test_read_request(self):
        self.assertEqual(protocol.READ_REQUEST.hex(" "), "f0 00 01 3f 2b 01 00 00 f7")


class FactoryDumpTests(unittest.TestCase):
    def test_real_dump_is_factory_config(self):
        self.assertEqual(protocol.parse_message(factory_dump()), protocol.factory_config())

    def test_factory_config_encodes_to_real_dump(self):
        self.assertEqual(protocol.build_dump_message(protocol.factory_config()), factory_dump())

    def test_factory_values(self):
        config = protocol.factory_config()
        bank3 = config.banks[2]
        self.assertEqual([p.note for p in bank3.pads], list(range(36, 52)))
        self.assertTrue(all(p.channel == 2 and not p.toggle and p.color == 0 for p in bank3.pads))
        self.assertEqual([(k.cc, k.relative) for k in bank3.knobs],
                         [(1, False), (2, False), (3, False), (4, True)])
        self.assertEqual([(a.channel, a.cc) for a in bank3.axes], [(2, 9), (2, 10)])


class EncodeDecodeTests(unittest.TestCase):
    def test_round_trip(self):
        config = custom_config()
        self.assertEqual(protocol.decode_payload(protocol.encode_payload(config)), config)

    def test_byte_positions(self):
        data = protocol.encode_payload(custom_config())
        i = (2 * 16 + 5) * 3  # bank 3, pad 6
        self.assertEqual(list(data[i:i + 3]), [0x10 | 9, 100, 52])
        i = 192 + (1 * 4 + 0) * 2  # bank 2, knob 1
        self.assertEqual(list(data[i:i + 2]), [0x10 | 15, 74])
        i = 224 + (3 * 2 + 1) * 2  # bank 4, axis 2
        self.assertEqual(list(data[i:i + 2]), [4, 127])

    def test_write_message(self):
        msg = protocol.build_write_message(custom_config())
        self.assertEqual(len(msg), 249)
        self.assertEqual(msg[:8].hex(" "), "f0 00 01 3f 2b 03 01 70")
        self.assertEqual(msg[-1], 0xF7)
        self.assertTrue(all(b < 0x80 for b in msg[1:-1]))

    def test_encode_does_not_change_config(self):
        config = custom_config()
        before = copy.deepcopy(config)
        protocol.encode_payload(config)
        self.assertEqual(config, before)


class ValidationTests(unittest.TestCase):
    def assertInvalid(self, change):
        config = protocol.factory_config()
        change(config)
        with self.assertRaises(ProtocolError):
            protocol.build_write_message(config)

    def test_out_of_range_values(self):
        self.assertInvalid(lambda c: setattr(c.banks[0].pads[0], "channel", 16))
        self.assertInvalid(lambda c: setattr(c.banks[0].pads[0], "channel", -1))
        self.assertInvalid(lambda c: setattr(c.banks[0].pads[0], "note", 128))
        self.assertInvalid(lambda c: setattr(c.banks[0].pads[0], "color", 64))
        self.assertInvalid(lambda c: setattr(c.banks[0].knobs[3], "cc", 200))
        self.assertInvalid(lambda c: setattr(c.banks[3].axes[1], "channel", 16))

    def test_wrong_types(self):
        self.assertInvalid(lambda c: setattr(c.banks[0].pads[0], "note", 36.0))
        self.assertInvalid(lambda c: setattr(c.banks[0].pads[0], "note", True))
        self.assertInvalid(lambda c: setattr(c.banks[0].pads[0], "toggle", 1))

    def test_wrong_counts(self):
        self.assertInvalid(lambda c: c.banks.pop())
        self.assertInvalid(lambda c: c.banks[1].pads.pop())
        self.assertInvalid(lambda c: c.banks[1].knobs.append(protocol.Knob()))
        self.assertInvalid(lambda c: c.banks[1].axes.pop())


class ParseTests(unittest.TestCase):
    def mutated(self, index, value):
        msg = bytearray(factory_dump())
        msg[index] = value
        return bytes(msg)

    def test_rejects_wrong_length(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_message(factory_dump()[:-2] + b"\xf7")

    def test_rejects_other_manufacturer_or_model(self):
        for index in (1, 2, 3, 4):
            with self.assertRaises(ProtocolError):
                protocol.parse_message(self.mutated(index, 0x7E))

    def test_rejects_write_command_unless_allowed(self):
        msg = protocol.build_write_message(protocol.factory_config())
        with self.assertRaises(ProtocolError):
            protocol.parse_message(msg)
        self.assertEqual(protocol.parse_message(msg, allowed=(protocol.CMD_WRITE,)),
                         protocol.factory_config())

    def test_rejects_unknown_block_tag(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_message(self.mutated(7, 0x71))

    def test_rejects_missing_eox(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_message(self.mutated(248, 0x00))

    def test_rejects_unknown_bits(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_message(self.mutated(8, 0x20))         # pad mode/channel byte
        with self.assertRaises(ProtocolError):
            protocol.parse_message(self.mutated(8 + 2, 0x40))     # pad color
        with self.assertRaises(ProtocolError):
            protocol.parse_message(self.mutated(8 + 224, 0x10))   # axis channel has no mode bit


class NoteNameTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(protocol.note_name(36), "C1")
        self.assertEqual(protocol.note_name(51), "D#2")
        self.assertEqual(protocol.note_name(0), "C-2")
        self.assertEqual(protocol.note_name(127), "G8")
        with self.assertRaises(ProtocolError):
            protocol.note_name(128)


class ColorTests(unittest.TestCase):
    def test_palette_values(self):
        values = [v for v, _, _ in colors.PALETTE]
        self.assertEqual(sorted(values), [0, 3, 12, 15, 19, 44, 48, 49, 51, 52, 60, 63])

    def test_components(self):
        self.assertEqual(colors.components(48), (3, 0, 0))
        self.assertEqual(colors.components(12), (0, 3, 0))
        self.assertEqual(colors.components(3), (0, 0, 3))
        self.assertEqual(colors.components(52), (3, 1, 0))
        for v in range(64):
            self.assertEqual(colors.from_components(*colors.components(v)), v)

    def test_hex_and_names(self):
        self.assertEqual(colors.to_hex(63), "#ffffff")
        self.assertEqual(colors.to_hex(48), "#ff0000")
        self.assertEqual(colors.to_hex(0), colors.OFF_HEX)
        self.assertEqual(colors.name(60), "Amarillo")
        self.assertEqual(colors.name(60, "en"), "Yellow")
        self.assertEqual(colors.name(21), "RGB 1-1-1")

    def test_brightness(self):
        # The levels the user saw on the real Orbit in the brightness test.
        self.assertEqual([colors.scale(48, n) for n in (1, 2, 3)], [16, 32, 48])
        self.assertEqual([colors.scale(12, n) for n in (1, 2, 3)], [4, 8, 12])
        self.assertEqual([colors.scale(3, n) for n in (1, 2, 3)], [1, 2, 3])
        self.assertEqual([colors.scale(63, n) for n in (1, 2, 3)], [21, 42, 63])
        self.assertEqual(colors.scale(52, 2), 36)   # orange keeps some green
        self.assertEqual(colors.scale(52, 1), 20)   # weak components never vanish
        self.assertEqual(colors.scale(48, 0), 0)
        self.assertEqual(colors.scale(0, 3), 0)
        self.assertEqual(colors.brightness(36), 2)
        with self.assertRaises(ValueError):
            colors.scale(48, 4)

    def test_split(self):
        self.assertEqual(colors.split(16), (48, 1))
        self.assertEqual(colors.split(42), (63, 2))
        self.assertEqual(colors.split(36), (52, 2))
        self.assertEqual(colors.split(0), (0, 0))
        self.assertEqual(colors.split(33), (49, 2))     # pink at medium
        self.assertEqual(colors.split(37), (None, 2))   # (2,1,1) is no palette color
        for hue, _, _ in colors.PALETTE[1:]:
            for level in colors.LEVELS:
                found, got_level = colors.split(colors.scale(hue, level))
                self.assertEqual(got_level, level)
                self.assertEqual(colors.scale(found, level), colors.scale(hue, level))

    def test_invalid(self):
        for bad in (-1, 64, 1.5, None):
            with self.assertRaises(ValueError):
                colors.components(bad)
        with self.assertRaises(ValueError):
            colors.from_components(4, 0, 0)


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_json_round_trip(self):
        config = custom_config()
        presets.save_json(self.path("p.json"), config)
        self.assertEqual(presets.load_json(self.path("p.json")), config)

    def test_json_uses_channels_1_to_16(self):
        data = presets.to_dict(custom_config())
        self.assertEqual(data["banks"][0]["pads"][0]["channel"], 1)
        self.assertEqual(data["banks"][2]["pads"][5],
                         {"channel": 10, "note": 100, "mode": "toggle", "color": 52})
        self.assertEqual(data["banks"][1]["knobs"][0]["mode"], "relative")

    def test_json_rejects_bad_presets(self):
        good = presets.to_dict(protocol.factory_config())
        cases = []
        for path, value in ((("format",), "other"), (("version",), 2),
                            (("banks", 0, "pads", 0, "channel"), 0),
                            (("banks", 0, "pads", 0, "channel"), 17),
                            (("banks", 0, "pads", 0, "mode"), "latch"),
                            (("banks", 0, "knobs", 0, "cc"), 128),
                            (("banks", 0, "accelerometer"), None)):
            data = copy.deepcopy(good)
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            cases.append(data)
        missing = copy.deepcopy(good)
        del missing["banks"][3]["pads"][0]["note"]
        cases.append(missing)
        for data in cases:
            with self.assertRaises(ProtocolError):
                presets.from_dict(data)

    def test_load_json_rejects_non_json(self):
        with open(self.path("bad.json"), "wb") as f:
            f.write(b"\xff\x00 not json")
        with self.assertRaises(ProtocolError):
            presets.load_json(self.path("bad.json"))
        with open(self.path("list.json"), "w") as f:
            f.write("[1, 2]")
        with self.assertRaises(ProtocolError):
            presets.load_json(self.path("list.json"))

    def test_syx_round_trip(self):
        config = custom_config()
        presets.save_syx(self.path("p.syx"), config)
        with open(self.path("p.syx"), "rb") as f:
            self.assertEqual(f.read()[5], protocol.CMD_DUMP)
        self.assertEqual(presets.load_syx(self.path("p.syx")), config)

    def test_load_real_dump_and_write_message(self):
        self.assertEqual(presets.load_syx(FACTORY_DUMP_PATH), protocol.factory_config())
        with open(self.path("w.syx"), "wb") as f:
            f.write(protocol.build_write_message(custom_config()))
        self.assertEqual(presets.load_syx(self.path("w.syx")), custom_config())


if __name__ == "__main__":
    unittest.main()
