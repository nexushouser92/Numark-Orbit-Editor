"""Tests for device.py and cli.py with a fake Orbit. No MIDI device is needed.

Run with: python -m unittest discover -s tests
"""
import os
import tempfile
import unittest
from datetime import datetime

from fakes import FakeOrbit
from orbit_editor import cli, device, midi_win, presets, protocol
from orbit_editor.protocol import ProtocolError


def custom_config():
    config = protocol.factory_config()
    config.banks[0].pads[0].color = 48
    config.banks[3].knobs[2].cc = 77
    return config


class ReadTests(unittest.TestCase):
    def test_read(self):
        orbit = FakeOrbit(custom_config())
        self.assertEqual(device.read_config(orbit), custom_config())
        self.assertEqual(orbit.sent, [protocol.READ_REQUEST])

    def test_ignores_other_sysex(self):
        noise = [bytes([0xF0, 0x7E, 0x00, 0x06, 0x02, 0xF7]),
                 protocol.build_write_message(custom_config())]  # an echo is not a dump
        orbit = FakeOrbit(noise=noise)
        self.assertEqual(device.read_config(orbit), protocol.factory_config())

    def test_no_answer(self):
        with self.assertRaises(device.DeviceError):
            device.read_config(FakeOrbit(respond=False), timeout=0.05)

    def test_invalid_answer(self):
        with self.assertRaises(device.DeviceError):
            device.read_config(FakeOrbit(corrupt=True))


class WriteTests(unittest.TestCase):
    def test_write_and_verify(self):
        orbit = FakeOrbit()
        pauses = []
        result = device.write_config(orbit, custom_config(), sleep=pauses.append)
        self.assertEqual(result, custom_config())
        self.assertEqual(orbit.config, custom_config())
        self.assertEqual(pauses, [device.VERIFY_DELAY])
        self.assertEqual(orbit.sent, [protocol.build_write_message(custom_config()),
                                      protocol.READ_REQUEST])

    def test_mismatch(self):
        orbit = FakeOrbit(apply_writes=False)
        with self.assertRaises(device.VerifyError) as ctx:
            device.write_config(orbit, custom_config(), sleep=lambda s: None)
        self.assertEqual(ctx.exception.received, protocol.factory_config())

    def test_without_verify(self):
        orbit = FakeOrbit()
        self.assertIsNone(device.write_config(orbit, custom_config(), verify=False))
        self.assertEqual(len(orbit.sent), 1)

    def test_invalid_config_sends_nothing(self):
        config = custom_config()
        config.banks[0].pads[0].note = 128
        orbit = FakeOrbit()
        with self.assertRaises(ProtocolError):
            device.write_config(orbit, config)
        self.assertEqual(orbit.sent, [])


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.orbit = FakeOrbit()
        self.output = []
        self.answers = []
        self.opened = 0

    def opener(self):
        self.opened += 1
        return self.orbit

    def run_cli(self, *argv, answer="YES"):
        def ask(prompt):
            self.answers.append(prompt)
            return answer
        return cli.main(list(argv), opener=self.opener,
                        lister=lambda: (["UMC404HD", "Numark ORBIT"], ["Numark ORBIT"]),
                        ask=ask, out=self.output.append, now=lambda: datetime(2026, 10, 19, 23, 5, 9))

    def path(self, name):
        return os.path.join(self.dir, name)

    def preset(self):
        path = self.path("nuevo.json")
        presets.save(path, custom_config())
        return path

    def test_ports(self):
        self.assertEqual(self.run_cli("ports"), 0)
        self.assertIn("  1: Numark ORBIT   <- Orbit", self.output)
        self.assertEqual(self.opened, 0)

    def test_read_and_save(self):
        self.assertEqual(self.run_cli("read", "-o", self.path("a.json")), 0)
        self.assertIn("Pad  1: channel  1  note  36 (C1)", self.output[0])
        self.assertEqual(presets.load(self.path("a.json")), protocol.factory_config())
        self.assertTrue(self.orbit.closed)

    def test_backup(self):
        self.assertEqual(self.run_cli("backup", "--folder", self.dir), 0)
        backup = self.path("Orbit_backup_20261019_230509.syx")
        self.assertEqual(presets.load(backup), protocol.factory_config())

    def test_show_and_convert(self):
        src = self.preset()
        self.assertEqual(self.run_cli("convert", src, self.path("b.syx")), 0)
        self.assertEqual(presets.load(self.path("b.syx")), custom_config())
        self.assertEqual(self.run_cli("show", self.path("b.syx")), 0)
        self.assertIn("color Red", self.output[-1])
        self.assertEqual(self.opened, 0)

    def test_unknown_extension(self):
        self.assertEqual(self.run_cli("show", self.path("x.txt")), 2)

    def test_write_simulated_never_opens_the_port(self):
        self.assertEqual(self.run_cli("write", self.preset(), "--dry-run"), 0)
        self.assertEqual(self.opened, 0)
        self.assertTrue(self.output[-1].startswith("F0 00 01 3F 2B 03 01 70"))

    def test_write_cancelled(self):
        code = self.run_cli("write", self.preset(), "--folder", self.dir, answer="no")
        self.assertEqual(code, 1)
        self.assertEqual(self.orbit.writes, [])
        self.assertTrue(os.path.exists(self.path("Orbit_backup_20261019_230509.syx")))

    def test_write_confirmed(self):
        code = self.run_cli("write", self.preset(), "--folder", self.dir, answer=" yes ")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.answers), 1)
        self.assertEqual(self.orbit.config, custom_config())
        self.assertEqual(self.output[-1], "Mapping sent and verified.")
        # The backup holds the mapping from before the write.
        backup = self.path("Orbit_backup_20261019_230509.syx")
        self.assertEqual(presets.load(backup), protocol.factory_config())

    def test_write_verify_failure(self):
        self.orbit = FakeOrbit(apply_writes=False)
        code = self.run_cli("write", self.preset(), "--folder", self.dir, "--yes")
        self.assertEqual(code, 2)
        self.assertEqual(self.answers, [])
        self.assertIn("different", self.output[-1])

    def test_write_invalid_file_opens_nothing(self):
        bad = self.path("bad.json")
        with open(bad, "w") as f:
            f.write("{}")
        self.assertEqual(self.run_cli("write", bad, "--yes"), 2)
        self.assertEqual(self.opened, 0)

    def test_port_missing(self):
        def missing():
            raise midi_win.MidiError("MIDI port 'ORBIT' not found")
        code = cli.main(["read"], opener=missing, out=self.output.append)
        self.assertEqual(code, 2)
        self.assertIn("not found", self.output[-1])


if __name__ == "__main__":
    unittest.main()
