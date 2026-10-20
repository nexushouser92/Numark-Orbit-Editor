"""Tests for midi_win.py with a fake winmm (Windows only: it uses ctypes.WINFUNCTYPE).

Run with: python -m unittest discover -s tests
"""
import unittest
from unittest import mock

from fakes import FakeWinmm, orbit_replies
from orbit_editor import device, midi_win, protocol

DUMP = protocol.build_dump_message(protocol.factory_config())


class PortListTests(unittest.TestCase):
    def test_list_and_find(self):
        fake = FakeWinmm(ins=["UMC404HD", "Numark ORBIT"], outs=["GS Wavetable", "x", "Numark ORBIT"])
        ins, outs = midi_win.list_ports(fake)
        self.assertEqual(ins, ["UMC404HD", "Numark ORBIT"])
        self.assertEqual(midi_win.find_port(ins), 1)
        self.assertEqual(midi_win.find_port(outs), 2)
        self.assertIsNone(midi_win.find_port(["Maschine MK2 In", None]))
        self.assertEqual(midi_win.find_port(["numark orbit"]), 0)

    def test_open_orbit_uses_matching_ports(self):
        fake = FakeWinmm(ins=["A", "Numark ORBIT"], outs=["Numark ORBIT"])
        with midi_win.open_orbit(fake):
            self.assertEqual((fake.opened_in, fake.opened_out), (1, 0))

    def test_open_orbit_not_found(self):
        for ins, outs in ((["A"], ["Numark ORBIT"]), (["Numark ORBIT"], ["B"])):
            with self.assertRaises(midi_win.MidiError):
                midi_win.open_orbit(FakeWinmm(ins=ins, outs=outs))


class OpenCloseTests(unittest.TestCase):
    def test_open_prepares_buffers_and_close_releases_everything(self):
        fake = FakeWinmm()
        port = midi_win.open_orbit(fake)
        self.assertEqual(len(fake.prepared_in), midi_win.NUM_BUFFERS)
        self.assertEqual(len(fake.available), midi_win.NUM_BUFFERS)
        port.close()
        port.close()  # closing twice is harmless
        self.assertEqual(fake.in_unprepared, midi_win.NUM_BUFFERS)
        self.assertEqual((fake.in_closed, fake.out_closed), (1, 1))

    def test_input_open_failure(self):
        fake = FakeWinmm(in_open=4)
        with self.assertRaises(midi_win.MidiError):
            midi_win.open_orbit(fake)
        self.assertEqual((fake.in_closed, fake.out_closed), (0, 0))

    def test_output_open_failure_closes_input(self):
        fake = FakeWinmm(out_open=4)
        with self.assertRaises(midi_win.MidiError):
            midi_win.open_orbit(fake)
        self.assertEqual((fake.in_closed, fake.out_closed), (1, 0))

    def test_buffers_returned_by_reset_are_not_reused(self):
        fake = FakeWinmm()
        port = midi_win.open_orbit(fake)
        added = fake.added
        port.close()
        self.assertEqual(fake.added, added)


class SendTests(unittest.TestCase):
    def test_send_sysex(self):
        fake = FakeWinmm()
        with midi_win.open_orbit(fake) as port:
            port.send(protocol.READ_REQUEST)
        self.assertEqual(fake.sent, [protocol.READ_REQUEST])
        self.assertEqual(fake.out_prepared, fake.out_unprepared)

    def test_only_complete_sysex(self):
        fake = FakeWinmm()
        with midi_win.open_orbit(fake) as port:
            for bad in (b"", b"\x90\x24\x7f", b"\xf0\x00\x01"):
                with self.assertRaises(midi_win.MidiError):
                    port.send(bad)
        self.assertEqual(fake.sent, [])

    def test_waits_while_still_playing(self):
        fake = FakeWinmm(still_playing=3)
        with midi_win.open_orbit(fake) as port:
            port.send(protocol.READ_REQUEST)
        self.assertEqual(fake.out_unprepared, 1)
        self.assertEqual(fake.out_resets, 0)

    def test_driver_that_never_finishes(self):
        fake = FakeWinmm(still_playing=10 ** 9)
        with mock.patch.object(midi_win, "SEND_TIMEOUT", 0.02), midi_win.open_orbit(fake) as port:
            with self.assertRaises(midi_win.MidiError):
                port.send(protocol.READ_REQUEST)
        self.assertEqual(fake.out_resets, 1)
        self.assertEqual(fake.out_unprepared, 1)

    def test_quiet_time_after_receiving(self):
        fake = FakeWinmm()
        with midi_win.open_orbit(fake) as port:
            now, pauses = [100.0], []
            port._clock, port._sleep = lambda: now[0], pauses.append
            port.send(protocol.READ_REQUEST)  # nothing received yet: no pause
            fake.deliver(DUMP)
            self.assertEqual(port.receive(1), DUMP)
            now[0] = 100.2
            port.send(protocol.READ_REQUEST)
            now[0] = 101.0
            port.send(protocol.READ_REQUEST)  # long after the dump: no pause
        self.assertEqual(len(pauses), 1)
        self.assertAlmostEqual(pauses[0], midi_win.QUIET_AFTER_RECEIVE - 0.2)
        self.assertEqual(len(fake.sent), 3)

    def test_long_msg_error(self):
        fake = FakeWinmm(long_msg=11)
        with midi_win.open_orbit(fake) as port:
            with self.assertRaises(midi_win.MidiError):
                port.send(protocol.READ_REQUEST)
        self.assertEqual(fake.out_unprepared, 1)


class ReceiveTests(unittest.TestCase):
    def test_whole_message(self):
        fake = FakeWinmm()
        with midi_win.open_orbit(fake) as port:
            fake.deliver(DUMP)
            self.assertEqual(port.receive(1), DUMP)
            self.assertEqual(len(fake.available), midi_win.NUM_BUFFERS)  # buffer given back

    def test_message_split_over_buffers(self):
        fake = FakeWinmm()
        with midi_win.open_orbit(fake) as port:
            fake.deliver(DUMP, chunk=100)
            self.assertEqual(port.receive(1), DUMP)

    def test_two_messages_and_junk(self):
        fake = FakeWinmm()
        other = bytes([0xF0, 0x7E, 0x00, 0x06, 0x02, 0xF7])
        with midi_win.open_orbit(fake) as port:
            fake.deliver(b"\x12\x34" + other + DUMP)
            self.assertEqual(port.receive(1), other)
            self.assertEqual(port.receive(1), DUMP)
            self.assertIsNone(port.receive(0.01))

    def test_timeout(self):
        with midi_win.open_orbit(FakeWinmm()) as port:
            self.assertIsNone(port.receive(0.02))

    def test_drain(self):
        fake = FakeWinmm()
        with midi_win.open_orbit(fake) as port:
            fake.deliver(DUMP[:50])
            fake.deliver(DUMP)
            port.drain()
            self.assertEqual(len(fake.available), midi_win.NUM_BUFFERS)
            self.assertIsNone(port.receive(0.01))
            fake.deliver(DUMP[100:])  # tail of an old message without its start: ignored
            self.assertIsNone(port.receive(0.01))


class WithDeviceTests(unittest.TestCase):
    def test_read_config_through_winmm(self):
        fake = FakeWinmm(on_send=orbit_replies)
        with midi_win.open_orbit(fake) as port:
            self.assertEqual(device.read_config(port, timeout=1), protocol.factory_config())
        self.assertEqual(fake.sent, [protocol.READ_REQUEST])


if __name__ == "__main__":
    unittest.main()
