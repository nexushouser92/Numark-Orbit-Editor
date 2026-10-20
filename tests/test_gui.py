"""Tests for editor.py, i18n.py and gui.py with a fake Orbit. No MIDI device is needed.

The window is created hidden; the Orbit link is stepped by hand instead of on a thread.
Run with: python -m unittest discover -s tests
"""
import os
import tempfile
import tkinter as tk
import unittest
from unittest import mock

import customtkinter as ctk

from fakes import FakeOrbit
from orbit_editor import colors, gui, i18n, link, presets, protocol, scales
from orbit_editor.editor import EditorState
from orbit_editor.protocol import ProtocolError


class EditorStateTests(unittest.TestCase):
    def setUp(self):
        self.state = EditorState()

    def test_starts_with_factory_and_clean(self):
        self.assertEqual(self.state.config, protocol.factory_config())
        self.assertFalse(self.state.dirty)

    def test_update_pad(self):
        self.state.select(bank=2, pad=5)
        self.state.update_pad(note=60, color=48, toggle=True, channel=9)
        pad = self.state.config.banks[2].pads[5]
        self.assertEqual((pad.note, pad.color, pad.toggle, pad.channel), (60, 48, True, 9))
        self.assertTrue(self.state.dirty)

    def test_same_value_is_not_a_change(self):
        self.state.update_pad(note=36)
        self.assertFalse(self.state.dirty)

    def test_invalid_change_is_rejected_whole(self):
        before = self.state.config
        with self.assertRaises(ProtocolError):
            self.state.update_pad(color=12, note=128)
        self.assertIs(self.state.config, before)
        self.assertFalse(self.state.dirty)
        with self.assertRaises(AttributeError):
            self.state.update_pad(velocity=1)

    def test_knob_and_axis(self):
        self.state.select(bank=1)
        self.state.update_knob(3, cc=20, relative=False)
        self.state.update_axis(0, channel=15)
        self.assertEqual(self.state.config.banks[1].knobs[3].cc, 20)
        self.assertFalse(self.state.config.banks[1].knobs[3].relative)
        self.assertEqual(self.state.config.banks[1].axes[0].channel, 15)

    def test_ascending_notes(self):
        self.state.select(pad=4)
        self.state.update_pad(note=60)
        self.state.ascending_notes()
        notes = [p.note for p in self.state.current_bank.pads]
        self.assertEqual(notes, [36, 37, 38, 39] + list(range(60, 72)))

    def test_ascending_notes_past_127_changes_nothing(self):
        self.state.update_pad(note=120)
        before = self.state.config
        with self.assertRaises(ProtocolError):
            self.state.ascending_notes()
        self.assertIs(self.state.config, before)

    def test_bank_helpers(self):
        self.state.select(bank=3, pad=0)
        self.state.update_pad(channel=12, color=60, toggle=True)
        self.state.channel_to_bank()
        self.state.color_to_bank()
        self.state.mode_to_bank()
        bank = self.state.config.banks[3]
        self.assertTrue(all(i.channel == 12 for i in bank.pads + bank.knobs + bank.axes))
        self.assertTrue(all(p.color == 60 and p.toggle for p in bank.pads))
        self.assertEqual(self.state.config.banks[2], protocol.factory_config().banks[2])

    def test_copy_bank_is_independent(self):
        self.state.update_pad(color=3)
        self.state.copy_bank(1)
        self.assertEqual(self.state.config.banks[1], self.state.config.banks[0])
        self.state.update_pad(color=12)
        self.assertEqual(self.state.config.banks[1].pads[0].color, 3)
        with self.assertRaises(ProtocolError):
            self.state.copy_bank(4)

    def test_select_out_of_range(self):
        with self.assertRaises(ProtocolError):
            self.state.select(bank=4)
        with self.assertRaises(ProtocolError):
            self.state.select(pad=16)


class TranslationTests(unittest.TestCase):
    def test_same_keys_in_both_languages(self):
        self.assertEqual(set(i18n.TEXTS["es"]), set(i18n.TEXTS["en"]))

    def test_detect(self):
        for name, lang in (("es_MX", "es"), ("Spanish_Mexico", "es"), ("en_US", "en"), (None, "en")):
            with mock.patch.object(i18n.locale, "getlocale", return_value=(name, "cp1252")):
                self.assertEqual(i18n.detect_language(), lang)
        with mock.patch.object(i18n.locale, "getlocale", side_effect=ValueError):
            self.assertEqual(i18n.detect_language(), "en")

    def test_format(self):
        self.assertEqual(i18n.Translator("es")("bank", n=2), "Banco 2")
        self.assertEqual(i18n.Translator("en")("bank", n=2), "Bank 2")



class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class GuiTests(unittest.TestCase):
    """The window with a fake Orbit; the link is stepped by hand instead of on a thread."""

    def setUp(self):
        try:
            self.root = ctk.CTk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.root.withdraw()
        self.addCleanup(self.close_root)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.clock = Clock()
        self.orbit = FakeOrbit()
        self.present = True
        self.link = link.OrbitLink(opener=lambda: self.orbit, lister=self.lister, clock=self.clock)
        self.yes_no = []
        self.answer = True

    def lister(self):
        names = ["Numark ORBIT"] if self.present else []
        return ["UMC404HD"] + names, names

    def close_root(self):
        # CustomTkinter schedules some window tweaks with after(); cancel them before destroying.
        for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(job)
        self.root.destroy()

    def make_app(self, lang="es", connect=True, **kw):
        def ask(title, text):
            self.yes_no.append(text)
            return self.answer
        defaults = dict(lang=lang, link=self.link, autostart=False, ask_yes_no=ask, clock=self.clock)
        defaults.update(kw)
        app = gui.App(self.root, **defaults)
        if connect:
            self.sync(app)
        return app

    def sync(self, app, wait=link.WRITE_DELAY):
        """Let the link do its work, as the background thread would, and show the results."""
        self.link.step()
        self.clock.now += wait
        self.link.step()
        app.process_link_events()

    def pad(self, app, bank=0, pad=0):
        return app.state.config.banks[bank].pads[pad]

    def status(self, app):
        return app.status_button.cget("text")

    # --- linking
    def test_links_and_reads_automatically(self):
        self.orbit.config.banks[0].pads[0].color = 63
        app = self.make_app()
        self.assertEqual(self.pad(app).color, 63)
        self.assertIn("Orbit vinculado", self.status(app))
        self.assertEqual(self.orbit.writes, [])
        self.assertFalse(hasattr(app, "read_button"))

    def test_searching_when_absent(self):
        self.present = False
        app = self.make_app()
        self.assertIn("Buscando Orbit", self.status(app))

    def test_english(self):
        app = self.make_app(lang="en")
        self.assertIn("Orbit linked", self.status(app))
        self.assertEqual(self.root.title(), "MIDI mapping editor · Unofficial project")

    def test_title(self):
        self.make_app()
        self.assertEqual(self.root.title(), "Editor de mapeo MIDI · Proyecto no oficial")

    # --- live preview
    def test_every_change_reaches_the_orbit(self):
        app = self.make_app()
        app.on_color(48)
        self.assertIn("aplicando cambios", self.status(app))
        self.sync(app)
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 48)
        self.assertIn("cambios aplicados", self.status(app))
        self.clock.now += gui.WRITTEN_SECONDS
        app.process_link_events()
        self.assertEqual(self.status(app), "●   Orbit vinculado")

    def test_quick_edits_make_one_write(self):
        app = self.make_app()
        for note in (40, 41, 42):
            app.pad_note.set_text(str(note))
            app.pad_note.commit()
            self.link.step()
        self.sync(app)
        self.assertEqual(len(self.orbit.writes), 1)
        self.assertEqual(self.orbit.config.banks[0].pads[0].note, 42)

    def test_reading_does_not_write_back(self):
        app = self.make_app()
        self.link.request_read()
        self.sync(app)
        self.assertEqual(self.orbit.writes, [])

    def test_failed_write_and_retry(self):
        self.orbit.apply_writes = False
        app = self.make_app()
        app.on_color(12)
        self.sync(app)
        self.assertIn("No se pudo aplicar", self.status(app))
        self.assertIn("no guardó", app.message.cget("text"))
        self.orbit.apply_writes = True
        app.on_status_click()
        self.sync(app, wait=0)
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 12)
        self.assertNotIn("No se pudo", self.status(app))

    def test_unplug_and_changes_wait_for_return(self):
        app = self.make_app()
        self.present = False
        self.clock.now += link.POLL_INTERVAL
        self.sync(app)
        self.assertIn("Buscando", self.status(app))
        app.on_color(60)
        self.sync(app)
        self.assertEqual(self.orbit.writes, [])
        self.present = True
        self.clock.now += link.POLL_INTERVAL
        self.sync(app)
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 60)

    # --- receiving data from the Orbit
    def test_pressed_pad_lights_and_gets_selected(self):
        app = self.make_app()
        self.orbit.on_short(0x91, 41, 127)     # bank 2 (channel 2), pad 6 (note 41)
        app.process_link_events()
        self.assertEqual((app.state.bank, app.state.pad), (1, 5))
        self.assertIn((1, 5), app.pressed)
        self.assertIn("recibiendo datos", self.status(app))
        self.orbit.on_short(0x81, 41, 0)
        app.process_link_events()
        self.assertNotIn((1, 5), app.pressed)
        self.clock.now += gui.RECEIVING_SECONDS
        app.process_link_events()
        self.assertNotIn("recibiendo", self.status(app))

    def test_k_buttons_knobs_and_accelerometer_follow_the_orbit(self):
        app = self.make_app()
        self.orbit.on_short(0xBF, 1, 4)        # bank button 4 pressed (CC 1, channel 16)
        app.process_link_events()
        self.assertEqual(app.state.bank, 3)
        self.assertEqual(app.bank_selector.get(), "Banco 4")
        self.orbit.on_short(0xBF, 1, 1)
        app.process_link_events()
        self.assertEqual(app.state.bank, 0)
        self.orbit.on_short(0xBF, 2, 3)        # K3 pressed (CC 2, channel 16)
        app.process_link_events()
        self.assertEqual(app.selected_knob, 2)
        self.assertEqual(app.knob_selector.get(), "K3")
        self.orbit.on_short(0xB2, 10, 64)      # bank 3 up-down axis
        app.process_link_events()
        self.assertEqual((app.state.bank, app.selected_axis), (2, 1))
        self.orbit.on_short(0xB3, 4, 1)        # bank 4 knob 4
        app.process_link_events()
        self.assertEqual((app.state.bank, app.selected_knob), (3, 3))

    # --- editing
    def test_grid_click_selects_pad(self):
        app = self.make_app()
        x1, y1, x2, y2 = gui.render.pad_rect(9, app.s)
        app._on_grid_click(type("E", (), {"x": (x1 + x2) / 2, "y": (y1 + y2) / 2})())
        self.assertEqual(app.state.pad, 9)
        self.assertEqual(app.pad_card.title.cget("text"), "Pad 10 · Banco 1")

    def test_knob_and_axis_selectors(self):
        app = self.make_app()
        app.knob_selector._command("K2")
        app.knob_cc.set_text("90")
        app.knob_cc.commit()
        app.knob_mode._command("Relativo")
        knob = app.state.config.banks[0].knobs[1]
        self.assertEqual((knob.cc, knob.relative), (90, True))
        app.axis_selector._command(app.axis_names[1])
        app.axis_cc.set_text("20")
        app.axis_cc.commit()
        self.assertEqual(app.state.config.banks[0].axes[1].cc, 20)
        self.assertEqual(app.state.config.banks[0].axes[0].cc, 9)

    def test_invalid_input_is_put_back(self):
        app = self.make_app()
        for bad in ("200", "abc", ""):
            app.pad_note.set_text(bad)
            app.pad_note.commit()
            self.assertEqual(app.pad_note.get_text(), "36")
        self.assertEqual(self.pad(app).note, 36)

    def test_wheel_picks_quantized_color(self):
        app = self.make_app()
        r = gui.WHEEL * app.s / 2
        event = type("E", (), {"x": 2 * r - 2, "y": r, "type": tk.EventType.ButtonPress})()
        app._on_wheel(event)                      # right edge of the wheel = red
        self.assertEqual(self.pad(app).color, 48)
        app.on_brightness(1)
        self.assertEqual(self.pad(app).color, 16)
        event = type("E", (), {"x": r, "y": 2, "type": tk.EventType.Motion})()
        app._on_wheel(event)                      # top = between yellow-green and green, kept dim
        self.assertEqual(colors.brightness(self.pad(app).color), 1)
        outside = type("E", (), {"x": 0, "y": 0, "type": tk.EventType.ButtonPress})()
        before = self.pad(app).color
        app._on_wheel(outside)
        self.assertEqual(self.pad(app).color, before)

    def test_brightness_bar(self):
        app = self.make_app()
        app.on_color(63)
        app._on_bar(type("E", (), {"x": 5})())
        self.assertEqual(self.pad(app).color, 21)
        app._on_bar(type("E", (), {"x": gui.BAR_W * app.s * 0.5})())
        self.assertEqual(self.pad(app).color, 42)
        app.on_color(52)
        app.on_brightness(1)
        app.on_brightness(3)  # orange comes back, not yellow
        self.assertEqual(self.pad(app).color, 52)

    def test_off_pad_ignores_brightness(self):
        app = self.make_app()
        app.on_brightness(2)
        self.assertEqual(self.pad(app).color, 0)

    def test_mix_buttons(self):
        app = self.make_app()
        app.on_component(0, 2)
        app.on_component(2, 1)
        self.assertEqual(self.pad(app).color, 2 * 16 + 1)
        self.assertEqual([seg.get() for seg in app.rgb], ["2", "0", "1"])

    def test_scale_mode(self):
        app = self.make_app()
        app.on_bank_name("Banco 2")
        app.scale_menu.set("Minor Pent")
        app.root_menu.set("A")
        app.on_scale_change()
        bank = app.state.config.banks[1]
        self.assertEqual(bank.pads[0].note, 45)
        self.assertEqual(bank.pads[0].color, scales.BANK_COLORS[1][1])
        app.on_scale_change(octave=2)
        self.assertEqual(app.state.config.banks[1].pads[0].note, 57)
        app.layout_selector.set("Solo escala")
        app.layout_selector._command("Solo escala")
        self.assertEqual(app.state.scales[1].layout, "in_scale")
        self.sync(app)
        self.assertEqual(self.orbit.config, app.state.config)   # previewed on the Orbit
        app.scale_menu.set("Ninguna")
        app.on_scale_change()
        self.assertIsNone(app.state.scales[1])
        app.on_bank_name("Banco 1")
        self.assertEqual(app.scale_menu.get(), "Ninguna")

    def test_scale_too_high_shows_error(self):
        app = self.make_app()
        app.scale_menu.set("Major")
        app.root_menu.set("B")
        app.on_scale_change(octave=8)
        self.assertTrue(app.message.cget("text").startswith("Error"))

    def test_helpers_and_copy(self):
        app = self.make_app()
        app.on_color(60)
        app._apply(app.state.color_to_bank)
        self.assertTrue(all(p.color == 60 for p in app.state.current_bank.pads))
        app.copy_target.set("4")
        app.on_copy_bank()
        self.assertEqual(app.state.config.banks[3], app.state.config.banks[0])

    def test_open_and_save_with_scales(self):
        app = self.make_app(ask_save=lambda **kw: os.path.join(self.dir, "out.json"))
        app.scale_menu.set("Dorian")
        app.on_scale_change()
        app.save_file()
        other = gui.App(self.root, lang="es", link=link.OrbitLink(opener=lambda: FakeOrbit(), lister=self.lister),
                        autostart=False, ask_open=lambda **kw: os.path.join(self.dir, "out.json"))
        other.open_file()
        self.assertEqual(other.state.config, app.state.config)
        self.assertEqual(other.state.scales, app.state.scales)
        self.assertEqual(other.scale_menu.get(), "Dorian")

    def test_factory_asks_first(self):
        app = self.make_app()
        app.on_color(3)
        self.answer = False
        app.load_factory()
        self.assertEqual(self.pad(app).color, 3)
        self.answer = True
        app.load_factory()
        self.assertEqual(app.state.config, protocol.factory_config())

    def test_close_applies_waiting_change(self):
        app = self.make_app()
        app.on_color(15)
        for job in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(job)
        app.on_close()
        self.assertEqual(self.orbit.config.banks[0].pads[0].color, 15)
        self.assertTrue(self.orbit.closed)
        self.root = ctk.CTk()   # on_close destroyed the window; give close_root a fresh one
        self.root.withdraw()

    def test_redraw_only_when_needed(self):
        app = self.make_app()
        calls = []
        original = app.grid_view.show
        app.grid_view.show = lambda img: (calls.append(1), original(img))
        app.refresh()
        app.refresh()
        self.assertEqual(calls, [])
        app.on_color(48)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
