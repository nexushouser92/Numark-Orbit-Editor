"""Tests for sequencer.py and the Sequencer page of the window. No MIDI device is needed.

Run with: python -m unittest discover -s tests
"""
import queue
import time
import tkinter as tk
import unittest

import customtkinter as ctk

from fakes import FakeOrbit
from orbit_editor import colors, gui, link, midi_win, protocol, sequencer
from orbit_editor.sequencer import CLOCK, START, STOP, Sequencer

CC16 = 0xBF


def ticks(seq, n):
    actions = []
    for _ in range(n):
        actions += seq.clock_message(CLOCK)
    return actions


def outs(actions):
    return [a[1:] for a in actions if a[0] == "out"]


def leds(actions):
    return {(a[1], a[2]): a[3] for a in actions if a[0] == "led"}


def press(seq, track, step):
    return seq.device_message(0x90 | track, 36 + step, 127)


def release(seq, track, step):
    return seq.device_message(0x80 | track, 36 + step, 0)


def wheel(seq, track, k, value):
    return seq.device_message(0xB0 | track, k + 1, value)


class ConfigTests(unittest.TestCase):
    def test_sequencer_config(self):
        user = protocol.factory_config()
        user.banks[2].pads[5].color = 48
        user.banks[1].axes[0].cc = 77
        seq = sequencer.sequencer_config(user)
        seq.validate()
        for b, bank in enumerate(seq.banks):
            self.assertEqual([(p.channel, p.note, p.toggle, p.color) for p in bank.pads],
                             [(b, 36 + p, False, 0) for p in range(16)])
            self.assertEqual([(k.channel, k.cc, k.relative) for k in bank.knobs],
                             [(b, cc, True) for cc in (1, 2, 3, 4)])
        self.assertEqual(seq.banks[1].axes[0].cc, 77)       # the user's accelerometer stays
        self.assertEqual(user.banks[2].pads[5].color, 48)   # the user's mapping is untouched
        self.assertTrue(sequencer.is_sequencer_config(seq))
        self.assertFalse(sequencer.is_sequencer_config(user))

    def test_backup_round_trip(self):
        user = protocol.factory_config()
        user.banks[3].pads[15].color = 63
        self.assertEqual(sequencer.decode_backup(sequencer.encode_backup(user)), user)
        for bad in (None, "", "zz", "00" * 10):
            self.assertIsNone(sequencer.decode_backup(bad))

    def test_helpers(self):
        self.assertEqual(sequencer.led_message(2, 5, 48), (0x92, 41, 48))
        self.assertEqual([sequencer.wheel_delta(v) for v in (1, 3, 127, 125)], [1, 3, -1, -3])
        self.assertEqual([sequencer.velocity_level(v) for v in (1, 43, 44, 85, 86, 127)], [1, 1, 2, 2, 3, 3])
        self.assertEqual([sequencer.swing_percent(level) for level in range(4)], [50, 58, 67, 75])


class PadTests(unittest.TestCase):
    def setUp(self):
        self.seq = Sequencer()

    def test_press_and_release_toggles_the_step_of_the_bank(self):
        self.assertEqual(press(self.seq, 2, 5), [])           # nothing happens until the release
        self.assertFalse(self.seq.steps[2][5])
        actions = release(self.seq, 2, 5)
        self.assertTrue(self.seq.steps[2][5])
        self.assertEqual(self.seq.selected, 2)
        self.assertEqual(leds(actions), {(2, 5): colors.scale(sequencer.TRACK_COLORS[2], 3)})
        press(self.seq, 2, 5)
        self.assertEqual(leds(release(self.seq, 2, 5)), {(2, 5): 0})
        self.assertFalse(self.seq.steps[2][5])

    def test_note_on_with_velocity_zero_is_a_release(self):
        press(self.seq, 0, 0)
        self.seq.device_message(0x90, 36, 0)
        self.assertTrue(self.seq.steps[0][0])

    def test_release_without_press_does_nothing(self):
        self.assertEqual(release(self.seq, 0, 3), [])
        self.assertFalse(self.seq.steps[0][3])

    def test_hold_and_turn_sets_the_step_velocity(self):
        press(self.seq, 1, 4)
        actions = wheel(self.seq, 1, 2, 127)                 # any K: a held pad takes the wheel
        self.assertTrue(self.seq.steps[1][4])                # turned on right away
        self.assertEqual(self.seq.velocity[1][4], 100 - sequencer.VELOCITY_PER_TICK)
        self.assertIn((1, 4), leds(actions))
        for _ in range(60):
            wheel(self.seq, 1, 2, 127)
        self.assertEqual(self.seq.velocity[1][4], 1)
        self.assertEqual(self.seq.swing, 0)                  # K3 did not change the swing
        release(self.seq, 1, 4)
        self.assertTrue(self.seq.steps[1][4])                # the release does not toggle it back off
        self.assertEqual(sequencer.velocity_level(1), 1)
        self.assertEqual(self.seq.step_color(1, 4), colors.scale(sequencer.TRACK_COLORS[1], 1))

    def test_held_pad_on_another_bank_does_not_take_the_wheel(self):
        self.seq.internal = True
        press(self.seq, 0, 0)
        wheel(self.seq, 3, 3, 1)
        self.assertEqual(self.seq.tempo, sequencer.DEFAULT_TEMPO + 1)
        self.assertEqual(self.seq.velocity[0][0], sequencer.VELOCITY)

    def test_bank_buttons_and_ignored_k_buttons(self):
        self.seq.device_message(CC16, 1, 3)
        self.assertEqual(self.seq.selected, 2)
        self.assertEqual(self.seq.device_message(CC16, 2, 4), [])   # K buttons: not passed through
        self.seq.device_message(CC16, 1, 9)                  # out of range: ignored
        self.assertEqual(self.seq.selected, 2)

    def test_other_messages_pass_through(self):
        self.assertEqual(self.seq.device_message(0xB0, 9, 64), [("out", 0xB0, 9, 64)])     # accelerometer
        self.assertEqual(self.seq.device_message(0x95, 36, 127), [("out", 0x95, 36, 127)])  # not a sequencer pad
        self.assertEqual(self.seq.device_message(0xF8, 0, 0), [])


class WheelTests(unittest.TestCase):
    def setUp(self):
        self.seq = Sequencer()

    def test_internal_clock_wheel_is_the_tempo_on_every_k(self):
        self.seq.internal = True
        self.assertTrue(self.seq.wheel_sets_tempo)
        for k in range(4):
            wheel(self.seq, 0, k, 1)
        self.assertEqual(self.seq.tempo, sequencer.DEFAULT_TEMPO + 4 * sequencer.TEMPO_PER_TICK)
        wheel(self.seq, 2, 0, 125)
        self.assertEqual(self.seq.tempo, sequencer.DEFAULT_TEMPO + 1)
        for _ in range(300):
            wheel(self.seq, 0, 0, 1)
        self.assertEqual(self.seq.tempo, sequencer.MAX_TEMPO)
        self.assertEqual(self.seq.velocity, Sequencer().velocity)

    def test_daw_clock_wheel_is_the_track_velocity(self):
        """The DAW sets the tempo, so the wheel sets the velocity of the bank's track."""
        self.seq.internal = False
        self.assertFalse(self.seq.wheel_sets_tempo)
        self.seq.steps[3][0] = True
        actions = wheel(self.seq, 3, 1, 5)
        self.assertEqual(self.seq.velocity[3], [100 + 5 * sequencer.VELOCITY_PER_TICK] * 16)
        self.assertEqual(self.seq.velocity[0], [100] * 16)
        self.assertEqual(len(leds(actions)), 16)
        self.assertEqual(self.seq.selected, 3)
        self.assertEqual(self.seq.tempo, sequencer.DEFAULT_TEMPO)
        for _ in range(100):
            wheel(self.seq, 3, 0, 127)
        self.assertEqual(self.seq.velocity[3], [1] * 16)


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.seq = Sequencer()

    def test_plays_steps_on_the_clock(self):
        self.seq.steps[0][0] = self.seq.steps[1][1] = True
        self.seq.channels[1] = 3
        self.seq.velocity[1][1] = 77
        self.assertEqual(ticks(self.seq, 3), [])                   # not playing yet
        actions = self.seq.clock_message(START) + ticks(self.seq, 1)
        self.assertEqual(outs(actions), [(0x99, 36, 100)])
        self.assertEqual(self.seq.position, 0)
        self.assertEqual(leds(actions)[(0, 0)], sequencer.PLAYHEAD)
        self.assertEqual(leds(actions)[(2, 0)], sequencer.PLAYHEAD_EMPTY)
        actions = ticks(self.seq, sequencer.TICKS_PER_STEP)
        self.assertEqual(outs(actions), [(0x89, 36, 0), (0x93, 38, 77)])   # gate end, then step 2
        self.assertEqual(leds(actions)[(0, 0)], colors.scale(sequencer.TRACK_COLORS[0], 3))
        actions = self.seq.clock_message(STOP)
        self.assertEqual(outs(actions), [(0x83, 38, 0)])
        self.assertEqual(self.seq.position, -1)
        self.assertEqual(leds(actions)[(1, 1)], colors.scale(sequencer.TRACK_COLORS[1], 2))   # velocity 77

    def test_loops_after_16_steps(self):
        self.seq.steps[2][0] = True
        self.seq.clock_message(START)
        notes = outs(ticks(self.seq, 16 * sequencer.TICKS_PER_STEP + 1))
        self.assertEqual([n for n in notes if n[0] == 0x99], [(0x99, 42, 100)] * 2)

    def test_swing_delays_the_off_beat(self):
        self.seq.steps[0][1] = True
        self.seq.set_swing(2)
        self.seq.clock_message(START)
        actions = ticks(self.seq, sequencer.TICKS_PER_STEP + 1)
        self.assertEqual(outs(actions), [])
        self.assertEqual(outs(ticks(self.seq, 2)), [(0x99, 36, 100)])

    def test_solo(self):
        self.seq.steps[0][0] = self.seq.steps[1][0] = True
        self.seq.toggle_solo(1)
        self.seq.clock_message(START)
        self.assertEqual(outs(ticks(self.seq, 1)), [(0x99, 38, 100)])

    def test_rewind_when_stopped(self):
        self.seq.clock_message(START)
        ticks(self.seq, 20)
        self.seq.clock_message(STOP)
        self.seq.rewind()
        self.seq.clock_message(sequencer.CONTINUE)
        ticks(self.seq, 1)
        self.assertEqual(self.seq.position, 0)

    def test_song_position(self):
        self.seq.clock_message(sequencer.SONG_POSITION, 4, 0)
        self.seq.clock_message(sequencer.CONTINUE)
        ticks(self.seq, 1)
        self.assertEqual(self.seq.position, 4)

    def test_channel_change_ends_sounding_notes_on_the_old_channel(self):
        self.seq.steps[0][0] = True
        self.seq.clock_message(START)
        ticks(self.seq, 1)
        self.assertEqual(outs(self.seq.set_channel(0, 0)), [(0x89, 36, 0)])

    def test_all_leds_cover_every_bank(self):
        self.seq.steps[3][15] = True
        lit = leds(self.seq.all_leds())
        self.assertEqual(len(lit), 64)
        self.assertEqual(lit[(3, 15)], colors.scale(sequencer.TRACK_COLORS[3], 3))


class SettingsTests(unittest.TestCase):
    def test_round_trip(self):
        seq = Sequencer()
        seq.steps[1][2] = True
        seq.velocity[1][2] = 33
        seq.notes[3] = 50
        seq.channels[2] = 4
        seq.solo[0] = True
        seq.set_swing(2)
        seq.set_swing_eighths(True)
        seq.set_tempo(99)
        seq.select(3)
        other = Sequencer()
        other.load_dict(seq.to_dict())
        self.assertEqual(other.to_dict(), seq.to_dict())

    def test_damaged_settings_are_ignored(self):
        seq = Sequencer()
        for bad in ({}, {"steps": 3, "notes": []}, {"steps": [], "notes": ["x"]}):
            seq.load_dict(bad)
        self.assertEqual(seq.to_dict(), Sequencer().to_dict())

    def test_values_are_clamped(self):
        seq = Sequencer()
        seq.load_dict({"steps": [[1] * 20] * 6, "notes": [200, -5], "channels": [99], "tempo": 999,
                       "velocity": [[0, 300]], "swing": 9, "selected": 7})
        self.assertEqual((seq.notes[:2], seq.channels[0], seq.tempo), ([127, 0], 15, sequencer.MAX_TEMPO))
        self.assertEqual(seq.velocity[0][:2], [1, 127])
        self.assertEqual((seq.swing, seq.selected), (sequencer.MAX_SWING, 3))

    def test_file(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "sequencer.json")
            self.assertEqual(sequencer.load_settings(path), {})
            sequencer.save_settings({"output": "x"}, path)
            self.assertEqual(sequencer.load_settings(path), {"output": "x"})


# --------------------------------------------------------------------------- runner

class FakePort:
    def __init__(self, in_index, out_index):
        self.in_index, self.out_index = in_index, out_index
        self.shorts, self.closed, self.on_short = [], False, None

    def send_short(self, status, data1=0, data2=0):
        self.shorts.append((status, data1, data2))

    def close(self):
        self.closed = True


class FakePorts:
    def __init__(self, ins=("DAW clock",), outs=("Synth",)):
        self.ins, self.outs = list(ins), list(outs)
        self.opened = []

    def lister(self):
        return self.ins, self.outs

    def opener(self, in_index, out_index):
        port = FakePort(in_index, out_index)
        self.opened.append(port)
        return port


def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.005)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.ports = FakePorts()
        self.seq = Sequencer()
        self.sent_leds = []
        self.accept_leds = True
        self.runner = sequencer.SequencerRunner(self.seq, self.send_led, opener=self.ports.opener,
                                                lister=self.ports.lister)
        self.addCleanup(self.runner.stop)

    def send_led(self, status, data1, data2):
        if self.accept_leds:
            self.sent_leds.append((status, data1, data2))
        return self.accept_leds

    def settle(self):
        done = queue.SimpleQueue()
        self.runner.post(lambda: done.put(1) or [])
        done.get(timeout=2)

    def test_missing_ports(self):
        with self.assertRaises(midi_win.MidiError):
            self.runner.start("Nope")
        with self.assertRaises(midi_win.MidiError):
            self.runner.start("Synth", "Nope")
        self.assertFalse(self.runner.running)

    def test_daw_clock_drives_the_notes(self):
        self.seq.steps[0][0] = True
        self.runner.start("Synth", "DAW clock")
        out, clock_in = self.ports.opened
        self.assertEqual((out.in_index, out.out_index, clock_in.in_index, clock_in.out_index), (None, 0, 0, None))
        self.assertFalse(self.seq.internal)
        clock_in.on_short(START, 0, 0)
        clock_in.on_short(CLOCK, 0, 0)
        self.settle()
        self.assertEqual(out.shorts, [(0x99, 36, 100)])
        self.assertIn((0x90, 36, sequencer.PLAYHEAD), self.sent_leds)
        self.runner.stop()
        self.assertTrue(out.closed and clock_in.closed)
        self.assertEqual(out.shorts[-1], (0x89, 36, 0))      # nothing left sounding
        self.assertFalse(self.seq.playing)

    def test_orbit_pads_and_leds(self):
        self.runner.start("Synth", "DAW clock")
        self.runner.device_message(0x91, 38, 127)
        self.runner.device_message(0x81, 38, 0)
        self.settle()
        self.assertTrue(self.seq.steps[1][2])
        self.assertEqual(self.sent_leds, [(0x91, 38, colors.scale(sequencer.TRACK_COLORS[1], 3))])

    def test_unchanged_leds_are_not_sent_again_but_repaint_sends_all(self):
        self.runner.start("Synth", "DAW clock")
        self.runner.post(self.seq.all_leds)
        self.runner.post(self.seq.all_leds)
        self.settle()
        self.assertEqual(len(self.sent_leds), 64)
        self.runner.repaint()
        self.settle()
        self.assertEqual(len(self.sent_leds), 128)

    def test_leds_the_orbit_did_not_take_are_sent_again(self):
        self.runner.start("Synth", "DAW clock")
        self.accept_leds = False
        self.runner.post(self.seq.toggle_step, 0, 0)
        self.settle()
        self.accept_leds = True
        self.runner.post(self.seq.all_leds)
        self.settle()
        self.assertIn((0x90, 36, colors.scale(sequencer.TRACK_COLORS[0], 3)), self.sent_leds)

    def test_internal_clock_play_and_stop(self):
        self.seq.set_tempo(sequencer.MAX_TEMPO)
        self.seq.steps[0] = [True] * 16
        self.runner.start("Synth")
        self.assertTrue(self.seq.internal)
        self.assertEqual(len(self.ports.opened), 1)
        self.runner.play()
        wait_for(lambda: self.seq.position >= 1)
        self.runner.stop_playing()
        wait_for(lambda: not self.seq.playing)
        self.runner.stop_playing()                           # stopped: back to step 1
        wait_for(lambda: self.seq.position == -1)
        self.assertTrue(any(s[0] == 0x99 for s in self.ports.opened[0].shorts))

    def test_post_when_not_running_changes_the_pattern_only(self):
        self.runner.post(self.seq.toggle_step, 3, 3)
        self.assertTrue(self.seq.steps[3][3])
        self.assertEqual(self.sent_leds, [])


class LinkTests(unittest.TestCase):
    def test_send_short_and_listener(self):
        orbit = FakeOrbit()
        lnk = link.OrbitLink(opener=lambda: orbit, lister=lambda: (["Numark ORBIT"], ["Numark ORBIT"]))
        self.assertFalse(lnk.send_short(0x90, 36, 3))       # not linked
        lnk.step()
        self.assertTrue(lnk.send_short(0x90, 36, 3))
        self.assertEqual(orbit.shorts, [(0x90, 36, 3)])
        heard = []
        lnk.listener = lambda *m: heard.append(m)
        orbit.on_short(0x90, 40, 127)
        self.assertEqual(heard, [(0x90, 40, 127)])

    def test_no_pad_colors_while_a_mapping_is_read_or_written(self):
        orbit = FakeOrbit()
        lnk = link.OrbitLink(opener=lambda: orbit, lister=lambda: (["Numark ORBIT"], ["Numark ORBIT"]))
        lnk.step()
        with lnk._sysex:
            self.assertFalse(lnk.send_short(0x90, 36, 3))
        self.assertEqual(orbit.shorts, [])


# --------------------------------------------------------------------------- window

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SequencerPageTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.root.withdraw()
        self.addCleanup(self.close_root)
        self.clock = Clock()
        self.orbit = FakeOrbit()
        self.link = link.OrbitLink(opener=lambda: self.orbit, lister=self.orbit_ports, clock=self.clock)
        self.ports = FakePorts(ins=("Numark ORBIT", "loopMIDI clock"),
                               outs=("Numark ORBIT", "Microsoft GS Wavetable Synth", "loopMIDI notes"))
        self.saved = []

    def orbit_ports(self):
        return ["Numark ORBIT"], ["Numark ORBIT"]

    def close_root(self):
        for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(job)
        self.root.destroy()

    def make_app(self, settings=None, connect=True):
        app = gui.App(self.root, lang="en", link=self.link, autostart=False, clock=self.clock,
                      seq_settings=settings or {}, save_seq_settings=self.saved.append,
                      port_lister=self.ports.lister, loopmidi_check=lambda: True, open_url=lambda url: None)
        app.seq_runner = sequencer.SequencerRunner(app.seq, self.link.send_short, opener=self.ports.opener,
                                                   lister=self.ports.lister)
        self.addCleanup(app.seq_runner.stop)
        if connect:
            self.sync(app)
        return app

    def sync(self, app):
        self.link.step()
        self.clock.now += link.WRITE_DELAY
        self.link.step()
        app.process_link_events()

    def start(self, app, clock="Internal clock"):
        app.show_view("sequencer")
        app.set_seq_output("Microsoft GS Wavetable Synth")
        app.set_seq_clock(clock)
        app.start_sequencer()
        self.sync(app)

    def test_page_lists_ports_without_the_orbit(self):
        app = self.make_app()
        app.show_view("sequencer")
        self.assertEqual(app.view, "sequencer")
        self.assertEqual(app.seq_out_menu.cget("values"), ["Microsoft GS Wavetable Synth", "loopMIDI notes"])
        self.assertEqual(app.seq_clock_menu.cget("values"), ["Internal clock", "loopMIDI clock"])
        app.show_view("mapping")
        self.assertEqual(app.view, "mapping")

    def test_needs_the_orbit_and_the_ports(self):
        app = self.make_app(connect=False)
        app.start_sequencer()
        self.assertFalse(app.seq_on)
        self.assertIn("Connect the Orbit", app.message.cget("text"))
        self.sync(app)
        app.start_sequencer()
        self.assertFalse(app.seq_on)
        self.assertIn("First choose", app.message.cget("text"))
        app.set_seq_output("loopMIDI notes")
        app.set_seq_clock("loopMIDI notes")
        app.start_sequencer()
        self.assertFalse(app.seq_on)

    def test_start_writes_the_sequencer_mapping_and_stop_puts_the_users_back(self):
        self.orbit.config.banks[0].pads[0].color = 48
        app = self.make_app()
        self.start(app)
        self.assertTrue(app.seq_on)
        self.assertTrue(sequencer.is_sequencer_config(self.orbit.config))
        self.assertIs(self.link.listener.__self__, app.seq_runner)
        self.assertIn("backup", self.saved[-1])
        app.stop_sequencer()
        self.sync(app)
        self.assertFalse(app.seq_on)
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 48)
        self.assertNotIn("backup", self.saved[-1])
        self.assertIsNone(self.link.listener)

    def test_mapping_edits_wait_while_sequencing(self):
        app = self.make_app()
        self.start(app)
        app._apply(lambda: app.state.update_pad(color=12))
        self.sync(app)
        self.assertTrue(sequencer.is_sequencer_config(self.orbit.config))
        self.assertIn("applied when it stops", app.message.cget("text"))
        app.stop_sequencer()
        self.sync(app)
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 12)

    def test_relinking_puts_the_sequencer_mapping_back(self):
        app = self.make_app()
        self.start(app)
        self.orbit.config = protocol.factory_config()        # e.g. unplugged and plugged back
        self.link.request_read()
        self.sync(app)
        self.sync(app)
        self.assertTrue(sequencer.is_sequencer_config(self.orbit.config))

    def test_pads_are_lit_after_the_write(self):
        app = self.make_app()
        app.seq.steps[2][3] = True
        self.start(app)
        app._repaint_pads()                                  # what the after() timer does
        wait_for(lambda: (0x92, 39, colors.scale(sequencer.TRACK_COLORS[2], 3)) in self.orbit.shorts)

    def test_orbit_messages_go_to_the_sequencer(self):
        app = self.make_app()
        self.start(app)
        self.orbit.on_short(0x93, 40, 127)
        self.orbit.on_short(0x83, 40, 0)
        wait_for(lambda: app.seq.steps[3][4])
        app.process_link_events()
        self.assertEqual(app.state.bank, 0)                  # the mapping editor does not follow them

    def test_restores_the_users_mapping_left_behind(self):
        """The app ended while sequencing: the next start finds the sequencer mapping on the Orbit."""
        user = protocol.factory_config()
        user.banks[1].pads[2].color = 60
        self.orbit.config = sequencer.sequencer_config(user)
        app = self.make_app(settings={"backup": sequencer.encode_backup(user)})
        self.sync(app)
        self.assertEqual(self.orbit.config, user)
        self.assertEqual(app.state.config, user)
        self.assertIn("restored", app.message.cget("text"))
        self.assertNotIn("backup", self.saved[-1])

    def test_window_edits_the_pattern(self):
        app = self.make_app()
        app.show_view("sequencer")
        x1, y1, x2, y2 = gui.render.step_rect(1, 6, app.s)
        pad = gui.render.TILE_PAD * app.s
        event = type("E", (), {"x": (x1 + x2) / 2 + pad, "y": (y1 + y2) / 2 + pad, "delta": -120})()
        app._on_step_click(event)
        self.assertTrue(app.seq.steps[1][6])
        app._on_step_wheel(event)
        self.assertEqual(app.seq.velocity[1][6], sequencer.VELOCITY - gui.WHEEL_VELOCITY)
        app.seq_set_note(2, 50)
        self.assertEqual(app.seq.notes[2], 50)
        app.refresh_sequencer()
        self.assertEqual(app.seq_rows[2]["note_name"].cget("text"), protocol.note_name(50))

    def test_pattern_is_saved_after_a_pause(self):
        app = self.make_app()
        app.seq.toggle_step(0, 0)
        app._autosave_sequencer()
        self.assertEqual(self.saved, [])
        self.clock.now += gui.SEQ_SAVE_SECONDS
        app._autosave_sequencer()
        self.assertEqual(self.saved[-1]["pattern"]["steps"][0][0], 1)

    def test_closing_stops_the_sequencer(self):
        app = self.make_app()
        self.start(app)
        for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(job)
        app.on_close()
        self.root = ctk.CTk()   # on_close destroyed the window; give close_root a fresh one
        self.root.withdraw()
        self.assertFalse(app.seq_on)
        self.assertFalse(sequencer.is_sequencer_config(self.orbit.config))

    def test_status(self):
        app = self.make_app()
        self.assertEqual(app.sequencer_status()[0], "Sequencer off.")
        self.start(app, clock="loopMIDI clock")
        self.assertIn("Waiting for the DAW clock", app.sequencer_status()[0])


if __name__ == "__main__":
    unittest.main()
