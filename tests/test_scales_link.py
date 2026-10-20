"""Tests for scales.py, scale presets and link.py (automatic linking and live writes) with a fake Orbit.

Run with: python -m unittest discover -s tests
"""
import os
import tempfile
import unittest

from fakes import FakeOrbit
from orbit_editor import link, midi_win, presets, protocol, scales
from orbit_editor.editor import EditorState
from orbit_editor.protocol import ProtocolError
from orbit_editor.scales import ScaleSetting


class ScaleTests(unittest.TestCase):
    def test_all_scales_listed(self):
        self.assertEqual(len(scales.SCALES), 14)
        self.assertEqual(scales.SCALES[9], ("Blues", (0, 3, 5, 6, 7, 10), "kBlues"))

    def test_chromatic_major_c1(self):
        result = scales.pad_notes(ScaleSetting("kMajor", 0, 1, "chromatic"))
        self.assertEqual([n for n, _ in result], list(range(36, 52)))
        roles = [r for _, r in result]
        # C C# D D# E F F# G G# A A# B C C# D D#
        self.assertEqual(roles, ["root", "out", "scale", "out", "scale", "scale", "out", "scale",
                                 "out", "scale", "out", "scale", "root", "out", "scale", "out"])

    def test_in_scale_minor_pentatonic_a(self):
        result = scales.pad_notes(ScaleSetting("kMinorPentatonic", 9, 1, "in_scale"))
        notes = [n for n, _ in result]
        self.assertEqual(notes[:6], [45, 48, 50, 52, 55, 57])   # A C D E G A
        self.assertEqual([r for _, r in result].count("root"), 4)  # 16 pads / 5 notes -> 4 roots
        self.assertTrue(all(r != "out" for _, r in result))

    def test_too_high(self):
        with self.assertRaises(ProtocolError):
            scales.pad_notes(ScaleSetting("kMajor", 11, 8, "chromatic"))

    def test_invalid_settings(self):
        for bad in (ScaleSetting("kNope"), ScaleSetting(root=12), ScaleSetting(octave=9),
                    ScaleSetting(layout="spiral"), ScaleSetting(root=1.0)):
            with self.assertRaises(ProtocolError):
                bad.validate()

    def test_each_bank_lights_differently(self):
        self.assertEqual(len(set(scales.BANK_COLORS)), 4)
        state = EditorState()
        for b in range(4):
            state.select(bank=b)
            state.apply_scale(ScaleSetting("kMajor", 0, 1, "chromatic"))
        roots = [state.config.banks[b].pads[0].color for b in range(4)]
        self.assertEqual(roots, [c[1] for c in scales.BANK_COLORS])
        self.assertTrue(state.dirty)
        self.assertEqual(state.config.banks[0].pads[1].color, 0)  # C# is not in C major

    def test_scale_keeps_channels_and_modes(self):
        state = EditorState()
        state.select(bank=2, pad=4)
        state.update_pad(toggle=True)
        state.apply_scale(ScaleSetting("kDorian", 2, 2, "in_scale"))
        pad = state.config.banks[2].pads[4]
        self.assertEqual((pad.channel, pad.toggle), (2, True))

    def test_failed_scale_changes_nothing(self):
        state = EditorState()
        before = state.config
        with self.assertRaises(ProtocolError):
            state.apply_scale(ScaleSetting("kMajor", 11, 8, "chromatic"))
        self.assertIs(state.config, before)
        self.assertEqual(state.scales, [None] * 4)

    def test_copy_bank_recolors_scale(self):
        state = EditorState()
        state.apply_scale(ScaleSetting("kMajor", 0, 1, "chromatic"))
        state.copy_bank(3)
        self.assertEqual(state.config.banks[3].pads[0].color, scales.BANK_COLORS[3][1])
        self.assertEqual(state.scales[3], state.scales[0])
        self.assertIsNot(state.scales[3], state.scales[0])

    def test_scale_off(self):
        state = EditorState()
        state.apply_scale(ScaleSetting())
        state.apply_scale(None)
        self.assertIsNone(state.scales[0])


class ScalePresetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def test_round_trip(self):
        state = EditorState()
        state.select(bank=1)
        state.apply_scale(ScaleSetting("kBlues", 4, 0, "in_scale"))
        path = os.path.join(self.dir, "s.json")
        presets.save(path, state.config, state.scales)
        config, loaded = presets.load_with_scales(path)
        self.assertEqual(config, state.config)
        self.assertEqual(loaded, state.scales)
        self.assertEqual(presets.load(path), state.config)  # plain load still works

    def test_old_presets_and_syx_have_no_scales(self):
        path = os.path.join(self.dir, "old.json")
        presets.save(path, protocol.factory_config())
        self.assertEqual(presets.load_with_scales(path)[1], [None] * 4)
        syx = os.path.join(self.dir, "a.syx")
        presets.save(syx, protocol.factory_config(), [ScaleSetting()] * 4)
        self.assertEqual(presets.load_with_scales(syx)[1], [None] * 4)

    def test_bad_scale_entry(self):
        data = presets.to_dict(protocol.factory_config(), [ScaleSetting(), None, None, None])
        data["banks"][0]["scale"]["root"] = 99
        with self.assertRaises(ProtocolError):
            presets.scales_from_dict(data)
        del data["banks"][0]["scale"]["root"]
        with self.assertRaises(ProtocolError):
            presets.scales_from_dict(data)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.orbit = FakeOrbit()
        self.present = True
        self.opened = 0
        self.link = link.OrbitLink(opener=self.opener, lister=self.lister, clock=self.clock)

    def opener(self):
        self.opened += 1
        self.orbit.closed = False
        return self.orbit

    def lister(self):
        names = ["Numark ORBIT"] if self.present else []
        return ["UMC404HD"] + names, names

    def events(self):
        out = []
        while not self.link.events.empty():
            out.append(self.link.events.get())
        return out

    def kinds(self):
        return [k for k, _ in self.events()]

    def test_links_and_reads_automatically(self):
        self.orbit.config.banks[0].pads[0].color = 12
        self.link.step()
        events = self.events()
        self.assertEqual([k for k, _ in events], ["linked", "config"])
        self.assertEqual(events[1][1].banks[0].pads[0].color, 12)
        self.assertTrue(self.link.linked)

    def test_waits_for_the_orbit(self):
        self.present = False
        self.link.step()
        self.assertEqual(self.kinds(), [])
        self.clock.now += 0.5
        self.present = True
        self.link.step()
        self.assertEqual(self.kinds(), [])  # next search only after POLL_INTERVAL
        self.clock.now += link.POLL_INTERVAL
        self.link.step()
        self.assertEqual(self.kinds(), ["linked", "config"])

    def test_open_failure_keeps_searching(self):
        def busy():
            raise midi_win.MidiError("in use")
        self.link.opener = busy
        self.link.step()
        self.assertEqual(self.kinds(), ["searching"])
        self.assertFalse(self.link.linked)

    def test_changes_are_written_after_a_pause(self):
        self.link.step()
        self.events()
        config = protocol.factory_config()
        config.banks[0].pads[0].color = 48
        self.link.push(config)
        self.link.step()
        self.assertEqual(self.orbit.writes, [])          # still within WRITE_DELAY
        config.banks[0].pads[0].color = 3                # later edits of the caller's object...
        self.clock.now += link.WRITE_DELAY
        self.link.step()
        self.assertEqual(len(self.orbit.writes), 1)
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 48)  # ...do not leak in
        self.assertEqual(self.kinds(), ["writing", "written"])
        self.assertFalse(self.link.has_pending)

    def test_quick_changes_make_one_write(self):
        self.link.step()
        for color in (1, 2, 3):
            config = protocol.factory_config()
            config.banks[0].pads[0].color = color
            self.link.push(config)
            self.clock.now += 0.1
            self.link.step()
        self.clock.now += link.WRITE_DELAY
        self.link.step()
        self.assertEqual(len(self.orbit.writes), 1)
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 3)

    def test_changes_made_while_away_are_written_on_link(self):
        config = protocol.factory_config()
        config.banks[1].knobs[0].cc = 70
        self.present = False
        self.link.push(config)
        self.link.step()
        self.present = True
        self.clock.now += link.POLL_INTERVAL
        self.link.step()   # links, and writes instead of reading
        self.link.step()
        self.assertEqual(self.orbit.config, config)
        self.assertNotIn("config", self.kinds())

    def test_unplug_and_replug(self):
        self.link.step()
        self.events()
        self.present = False
        self.clock.now += link.POLL_INTERVAL
        self.link.step()
        self.assertFalse(self.link.linked)
        self.assertTrue(self.orbit.closed)
        self.assertEqual(self.kinds(), ["searching"])
        self.present = True
        self.clock.now += link.POLL_INTERVAL
        self.link.step()
        self.assertTrue(self.link.linked)
        self.assertEqual(self.opened, 2)

    def test_write_error_keeps_the_change_for_later(self):
        self.link.step()
        self.events()
        config = protocol.factory_config()
        config.banks[0].pads[0].color = 60
        self.orbit.respond = False   # the verify read gets no answer
        self.link.push(config)
        self.clock.now += link.WRITE_DELAY
        import orbit_editor.device as device
        old = device.READ_TIMEOUT
        try:
            device.read_config.__defaults__ = (0.01,)
            self.link.step()
        finally:
            device.read_config.__defaults__ = (old,)
        self.assertEqual(self.kinds(), ["writing", "write_failed", "searching"])
        self.assertTrue(self.link.has_pending)
        self.orbit.respond = True
        self.clock.now += link.POLL_INTERVAL
        self.link.step()
        self.link.step()
        self.assertFalse(self.link.has_pending)

    def test_verify_mismatch_is_reported_once(self):
        self.link.step()
        self.events()
        self.orbit.apply_writes = False
        config = protocol.factory_config()
        config.banks[0].pads[0].color = 60
        self.link.push(config)
        self.clock.now += link.WRITE_DELAY
        self.link.step()
        self.assertEqual(self.kinds(), ["writing", "write_failed"])
        self.assertFalse(self.link.has_pending)
        self.assertTrue(self.link.linked)

    def test_incoming_notes_become_events(self):
        self.link.step()
        self.events()
        self.orbit.on_short(0x90, 36, 127)
        self.assertEqual(self.events(), [("midi", (0x90, 36, 127))])

    def test_read_request_and_stop_flushes(self):
        self.link.step()
        self.events()
        self.link.request_read()
        self.link.step()
        self.assertEqual(self.kinds(), ["config"])
        config = protocol.factory_config()
        config.banks[0].pads[0].color = 15
        self.link.push(config)
        self.link.stop()
        self.assertEqual(self.orbit.config, config)
        self.assertTrue(self.orbit.closed)
        self.assertFalse(self.link.linked)


if __name__ == "__main__":
    unittest.main()
