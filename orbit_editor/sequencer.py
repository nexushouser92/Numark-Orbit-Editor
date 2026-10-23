"""Step sequencer played from the Orbit and clocked by a DAW or by its own internal clock.

4 tracks x 16 steps: each bank of the Orbit is one track, each of its 16 pads one step. On the Orbit:
  Pad (press and release)     turn that step of the bank's track on / off
  Pad held + wheel            velocity of that step (it is turned on if it was off)
  Wheel                       with the internal clock: the tempo; when the DAW sends the clock (and
                              so sets the tempo): the velocity of every step of the bank's track
  K1-K4                       solo of track 1-4 on / off. Every press also toggles the K's own LED,
                              and both start off: LED lit = track soloed
  Right shoulder held + tilt  beat repeat: the step playing when it began is repeated, faster the
                              more the Orbit is tilted forward or back (1/16, 1/32, 1/48)
  Left shoulder held + tilt   filter: left-right tilt sends CC filter_cc (74, cutoff, by default) on
                              the selected track's channel, for a DAW or synth to map
Note, channel and swing are set in the window.
The pads show the pattern live: the track's color for a step that is on (brighter = louder), white for
the playhead. The Orbit has no transport buttons, so Play / Stop of the internal clock are in the window;
with a DAW, its own Play / Stop drive the sequencer.

Each track plays its note on its own MIDI channel. The tempo comes from MIDI clock (24 per quarter
note, so 6 per 16th-note step): the DAW's, whose Start, Continue, Stop and Song Position Pointer are
followed, or the internal clock, which SequencerRunner generates when no clock input is given (to play
a synth on its own, e.g. the Microsoft GS Wavetable Synth).

While it runs, the Orbit holds sequencer_config(): pads of bank b on channel b with notes 36-51
(momentary), the wheel relative on CC 1-4. The user's mapping is put back when it stops.

`Sequencer` is the pure logic: every method returns a list of actions,
  ("out", status, data1, data2)   to the output (DAW or synth)
  ("led", track, pad, color)      to a pad of the Orbit (track = bank)
  ("preview",)                    end the note preview soon
`SequencerRunner` connects it to the MIDI ports on its own thread.
"""
import copy
import ctypes
import json
import os
import queue
import threading
import time

from . import colors, midi_win, protocol, scales

TRACKS = protocol.NUM_BANKS
STEPS = protocol.PADS_PER_BANK
TICKS_PER_STEP = 6
GATE_TICKS = 3
VELOCITY = 100
DEFAULT_NOTES = (36, 38, 42, 46)        # General MIDI drums: kick, snare, closed hi-hat, open hi-hat
DEFAULT_CHANNEL = 9                     # MIDI channel 10, drums in General MIDI
MAX_SWING = 3                           # swing levels 0-3: 50 % (straight) to 75 %
PREVIEW_SECONDS = 0.3
DEFAULT_TEMPO, MIN_TEMPO, MAX_TEMPO = 120, 40, 240

FIRST_NOTE = protocol.FACTORY_FIRST_NOTE   # pad p of the sequencer mapping plays note 36 + p
WHEEL_CCS = protocol.FACTORY_KNOB_CCS      # the wheel on K1-K4
BANK_BUTTON = (0xBF, 1)                    # CC 1 on channel 16, value = bank 1-4
K_BUTTON = (0xBF, 2)                       # CC 2 on channel 16, value = K 1-4
# Measured on a real Orbit (research/monitor_accelerometer.txt): the shoulder buttons send note 3
# (left) and 4 (right) on channel 16; the accelerometer only sends while one is held (or latched with
# a double press), about 40 values per second, roughly 6-101.
SHOULDER_LEFT, SHOULDER_RIGHT = 3, 4
AXIS_CCS = protocol.FACTORY_AXIS_CCS       # (left-right, forward-back)
REPEAT_CC = AXIS_CCS[1]
FILTER_AXIS_CC = AXIS_CCS[0]
DEFAULT_FILTER_CC = 74                     # sound controller 5: cutoff on most synths
FILTER_GAIN = 3                            # filter CC change per accelerometer step
# Beat repeat: tilt (distance from where the Orbit was when the shoulder was pressed) -> clock ticks
# between repeats. 6 ticks = 1/16, 3 = 1/32, 2 = 1/48.
REPEAT_BANDS = ((18, 2), (11, 3), (5, 6))

# Change per wheel tick (the relative wheel sends +1 / -1 per tick, more when turned fast).
VELOCITY_PER_TICK = 2
TEMPO_PER_TICK = 1

TRACK_COLORS = tuple(scale for scale, _ in scales.BANK_COLORS)   # blue, green, orange, violet
PLAYHEAD = 63                           # white
PLAYHEAD_EMPTY = 21                     # dim white

CLOCK, START, CONTINUE, STOP, SONG_POSITION = 0xF8, 0xFA, 0xFB, 0xFC, 0xF2
SPIN_SECONDS = 0.002            # internal clock: busy-wait this long before each tick
INTERNAL = "internal"           # clock setting: use the internal clock
LOOPMIDI_URL = "https://www.tobias-erichsen.de/software/loopmidi.html"
UNINSTALL_KEYS = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                  r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")


def loopmidi_installed():
    """True when loopMIDI is installed (it is only needed to send the sequencer to a DAW). Its license
    forbids redistributing it, so the editor links to its download page instead of bundling it."""
    try:
        import winreg
    except ImportError:
        return False
    for path in UNINSTALL_KEYS:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    with winreg.OpenKey(key, winreg.EnumKey(key, i)) as entry:
                        if winreg.QueryValueEx(entry, "DisplayName")[0] == "loopMIDI":
                            return True
                except OSError:
                    continue
    return False


def swing_percent(level):
    """Swing level as the usual percentage: where the delayed note lands within its pair (50 = straight)."""
    return round(50 + 25 * level / MAX_SWING)


def swing_delay(level, eighths, step):
    """Clock ticks by which `step` (0-15) is delayed. Each level is 1 tick at 1/16 and 2 ticks at 1/8."""
    if eighths:
        return 2 * level if step % 4 == 2 else 0
    return level if step % 2 == 1 else 0


def velocity_level(velocity):
    """Pad brightness 1-3 for a velocity 1-127."""
    return 1 + (velocity - 1) * 3 // 127


def wheel_delta(value):
    """Relative wheel value -> signed ticks (1 = one tick right, 127 = one tick left)."""
    return value if value < 64 else value - 128


def repeat_ticks(tilt):
    """Clock ticks between beat repeats for a tilt (0 = not tilted enough: no repeat)."""
    for limit, ticks in REPEAT_BANDS:
        if abs(tilt) >= limit:
            return ticks
    return 0


def sequencer_config(config):
    """The mapping the Orbit holds while sequencing: bank b's pads on channel b, notes 36-51,
    momentary and unlit (the sequencer lights them), the wheel relative on CC 1-4, the
    accelerometer on channel b with CC 9 / 10."""
    seq = copy.deepcopy(config)
    for b, bank in enumerate(seq.banks):
        bank.pads = [protocol.Pad(b, FIRST_NOTE + p, False, 0) for p in range(STEPS)]
        bank.knobs = [protocol.Knob(b, cc, True) for cc in WHEEL_CCS]
        bank.axes = [protocol.Axis(b, cc) for cc in AXIS_CCS]
    return seq


def is_sequencer_config(config):
    """True when pads and wheel are laid out as sequencer_config() leaves them."""
    return all(bank.pads == [protocol.Pad(b, FIRST_NOTE + p, False, 0) for p in range(STEPS)]
               and bank.knobs == [protocol.Knob(b, cc, True) for cc in WHEEL_CCS]
               for b, bank in enumerate(config.banks))


class Sequencer:
    def __init__(self):
        self.steps = [[False] * STEPS for _ in range(TRACKS)]
        self.velocity = [[VELOCITY] * STEPS for _ in range(TRACKS)]
        self.notes = list(DEFAULT_NOTES)
        self.channels = [DEFAULT_CHANNEL] * TRACKS
        self.solo = [False] * TRACKS
        self.mute = [False] * TRACKS  # K1-K4 on the Orbit, or the M buttons in the window
        self.filter_cc = DEFAULT_FILTER_CC
        self.filter_held = False    # left shoulder held: left-right tilt is the filter
        self._filter_base = None
        self.swing = 0              # swing level, 0-MAX_SWING
        self.swing_eighths = False  # swing the off-beat 8ths (steps 3, 7, ...) instead of the 16ths
        self.tempo = DEFAULT_TEMPO  # BPM of the internal clock
        self.internal = False       # True: the window's Play / Stop drive the internal clock
        self.selected = 0           # track shown first in the window: the bank last used on the Orbit
        self.playing = False
        self.position = -1          # step being played, -1 when stopped
        self._ticks = -1
        self._sounding = []         # (channel, note, tick of its note-off)
        self._previewing = []       # (channel, note) of note previews, released by end_preview()
        self._held = {}             # (track, step) of pads held down -> True once the wheel moved
        self.repeat_held = False    # right shoulder held: tilting forward / back is a beat repeat
        self.repeat = 0             # clock ticks between beat repeats, 0 = off
        self._tilt_base = None      # forward-back value when the shoulder was pressed
        self._repeat_step = None    # the step being repeated
        self._repeat_tick = 0       # tick of the next repeat
        self.version = 0            # bumped on every change the window should redraw

    # ------------------------------------------------------------------ settings

    def to_dict(self):
        return {"steps": [[int(s) for s in row] for row in self.steps], "notes": list(self.notes),
                "velocity": [list(row) for row in self.velocity], "channels": list(self.channels),
                "swing": self.swing, "swing_eighths": int(self.swing_eighths), "tempo": self.tempo,
                "solo": [int(s) for s in self.solo], "mute": [int(m) for m in self.mute],
                "filter_cc": self.filter_cc,
                "selected": self.selected}

    def load_dict(self, data):
        try:
            steps = [[bool(s) for s in row][:STEPS] for row in data["steps"]][:TRACKS]
            notes = [min(127, max(0, int(n))) for n in data["notes"]][:TRACKS]
            channels = [min(15, max(0, int(c))) for c in data.get("channels", [])][:TRACKS]
            solo = [bool(s) for s in data.get("solo", [])][:TRACKS]
            mute = [bool(m) for m in data.get("mute", [])][:TRACKS]
            filter_cc = min(127, max(0, int(data.get("filter_cc", DEFAULT_FILTER_CC))))
            selected = int(data.get("selected", 0))
            velocity = [[min(127, max(1, int(v))) for v in row][:STEPS]
                        for row in data.get("velocity", [])][:TRACKS]
            swing = min(MAX_SWING, max(0, int(data.get("swing", 0))))
            eighths = bool(data.get("swing_eighths", False))
            tempo = min(MAX_TEMPO, max(MIN_TEMPO, int(data.get("tempo", DEFAULT_TEMPO))))
        except (KeyError, TypeError, ValueError):
            return
        for t, row in enumerate(steps):
            self.steps[t][:len(row)] = row
        for t, row in enumerate(velocity):
            self.velocity[t][:len(row)] = row
        self.notes[:len(notes)] = notes
        self.channels[:len(channels)] = channels
        self.solo[:len(solo)] = solo
        self.mute[:len(mute)] = mute
        self.filter_cc = filter_cc
        self.swing = swing
        self.swing_eighths = eighths
        self.tempo = tempo
        self.selected = min(TRACKS - 1, max(0, selected))
        self.version += 1

    # ------------------------------------------------------------------ LEDs

    def step_color(self, track, step):
        """Color of a pad: the track's color for a step that is on (brighter = louder), white on the playhead."""
        on = self.steps[track][step]
        if step == self.position:
            return PLAYHEAD if on else PLAYHEAD_EMPTY
        if not on:
            return 0
        return colors.scale(TRACK_COLORS[track], velocity_level(self.velocity[track][step]))

    def _led(self, track, step):
        return ("led", track, step, self.step_color(track, step))

    def all_leds(self):
        """Every pad of every bank as it should be now (the Orbit shows the bank it is on)."""
        return [self._led(t, s) for t in range(TRACKS) for s in range(STEPS)]

    def _column(self, step):
        return [self._led(t, step) for t in range(TRACKS)]

    # ------------------------------------------------------------------ editing (window or Orbit)

    def toggle_step(self, track, step):
        self.steps[track][step] = not self.steps[track][step]
        self.version += 1
        return [self._led(track, step)]

    def select(self, track):
        track %= TRACKS
        if self.selected != track:
            self.selected = track
            self.version += 1
        return []

    def toggle_solo(self, track):
        self.solo[track] = not self.solo[track]
        self.version += 1
        return []

    def toggle_mute(self, track):
        self.mute[track] = not self.mute[track]
        self.version += 1
        return []

    def mute_all(self, muted=True):
        """All tracks on or off (the sequencer starts with them off, like the K LEDs)."""
        self.mute = [muted] * TRACKS
        self.version += 1
        return []

    def set_filter_cc(self, cc):
        cc = min(127, max(0, int(cc)))
        if self.filter_cc != cc:
            self.filter_cc = cc
            self.version += 1
        return []

    def clear_track(self, track):
        self.steps[track] = [False] * STEPS
        self.version += 1
        return [self._led(track, s) for s in range(STEPS)]

    def set_note(self, track, note):
        note = min(127, max(0, int(note)))
        if self.notes[track] != note:
            self.notes[track] = note
            self.version += 1
        return []

    def set_channel(self, track, channel):
        actions = self._release()        # a note sounding on the old channel must still be ended there
        if self.channels[track] != channel:
            self.channels[track] = channel
            self.version += 1
        return actions

    def set_step_velocity(self, track, step, velocity):
        velocity = min(127, max(1, int(velocity)))
        if self.velocity[track][step] != velocity:
            self.velocity[track][step] = velocity
            self.version += 1
        return [self._led(track, step)]

    def set_track_velocity(self, track, velocity):
        """The same velocity on every step of a track."""
        velocity = min(127, max(1, int(velocity)))
        if self.velocity[track] != [velocity] * STEPS:
            self.velocity[track] = [velocity] * STEPS
            self.version += 1
        return [self._led(track, s) for s in range(STEPS)]

    def set_swing(self, level):
        level = min(MAX_SWING, max(0, int(level)))
        if self.swing != level:
            self.swing = level
            self.version += 1
        return []

    def set_swing_eighths(self, eighths):
        if self.swing_eighths != eighths:
            self.swing_eighths = eighths
            self.version += 1
        return []

    def set_tempo(self, bpm):
        bpm = min(MAX_TEMPO, max(MIN_TEMPO, int(bpm)))
        if self.tempo != bpm:
            self.tempo = bpm
            self.version += 1
        return []

    def preview(self, track):
        """Play a track's note briefly so it can be heard."""
        actions = self.end_preview()
        channel, note = self.channels[track], self.notes[track]
        self._previewing.append((channel, note))
        return actions + [("out", 0x90 | channel, note, VELOCITY), ("preview",)]

    def end_preview(self):
        actions = [("out", 0x80 | channel, note, 0) for channel, note in self._previewing]
        self._previewing.clear()
        return actions

    # ------------------------------------------------------------------ Orbit input

    def device_message(self, status, data1, data2):
        """A short message from the Orbit."""
        kind, channel = status & 0xF0, status & 0x0F
        if (status, data1) == BANK_BUTTON:
            return self.select(data2 - 1) if 1 <= data2 <= TRACKS else []
        if (status, data1) == K_BUTTON:
            return self.toggle_solo(data2 - 1) if 1 <= data2 <= TRACKS else []
        if status == 0xBF:
            return []
        if channel == 15 and kind in (0x80, 0x90) and data1 in (SHOULDER_LEFT, SHOULDER_RIGHT):
            held = kind == 0x90 and data2 > 0
            if data1 == SHOULDER_RIGHT:
                self._hold_repeat(held)
            else:
                self.filter_held, self._filter_base = held, None
            return []
        if kind == 0xB0 and channel < TRACKS and data1 == REPEAT_CC and self.repeat_held:
            return self._tilt(data2)
        if kind == 0xB0 and channel < TRACKS and data1 == FILTER_AXIS_CC and self.filter_held:
            return self._filter(data2)
        is_pad = kind in (0x80, 0x90) and channel < TRACKS and FIRST_NOTE <= data1 < FIRST_NOTE + STEPS
        if is_pad:
            return self._pad(channel, data1 - FIRST_NOTE, kind == 0x90 and data2 > 0)
        if kind == 0xB0 and channel < TRACKS and data1 in WHEEL_CCS:
            return self._turn(channel, wheel_delta(data2))
        if kind in (0x80, 0x90, 0xA0, 0xB0, 0xC0, 0xD0, 0xE0):
            return [("out", status, data1, data2)]      # the accelerometer, or anything else
        return []

    def _pad(self, track, step, pressed):
        actions = self.select(track)
        if pressed:
            self._held[(track, step)] = False
            return actions
        turned = self._held.pop((track, step), None)
        if turned is False:             # pressed and released without turning the wheel
            actions += self.toggle_step(track, step)
        return actions

    def _hold_repeat(self, held):
        self.repeat_held = held
        self._tilt_base = None
        if not held:
            self._set_repeat(0)

    def _tilt(self, value):
        """Forward-back tilt while the right shoulder is held: the beat repeat rate."""
        if self._tilt_base is None:
            self._tilt_base = value     # where the Orbit is held counts as level
        self._set_repeat(repeat_ticks(value - self._tilt_base))
        return []

    def _filter(self, value):
        """Left-right tilt while the left shoulder is held: the filter CC, 64 where the tilt began."""
        if self._filter_base is None:
            self._filter_base = value
        level = min(127, max(0, 64 + (value - self._filter_base) * FILTER_GAIN))
        return [("out", 0xB0 | self.channels[self.selected], self.filter_cc, level)]

    def _set_repeat(self, ticks):
        if ticks == self.repeat:
            return
        if ticks and not self.repeat:   # starting: repeat the step playing now, from the next tick
            self._repeat_step = max(0, self.position)
            self._repeat_tick = self._ticks + 1
        self.repeat = ticks
        self.version += 1

    @property
    def wheel_sets_tempo(self):
        """The wheel is the tempo with the internal clock; with the DAW's clock the DAW sets the tempo,
        so the wheel is the track's velocity instead."""
        return self.internal

    def _turn(self, track, delta):
        actions = self.select(track)
        held = [step for (t, step) in self._held if t == track]
        if held:                        # a pad held down: the wheel sets that step's velocity
            actions = []
            for step in held:
                self._held[(track, step)] = True
                if not self.steps[track][step]:
                    self.steps[track][step] = True
                    self.version += 1
                actions += self.set_step_velocity(track, step,
                                                  self.velocity[track][step] + delta * VELOCITY_PER_TICK)
            return actions
        if self.wheel_sets_tempo:
            return actions + self.set_tempo(self.tempo + delta * TEMPO_PER_TICK)
        return actions + self.set_track_velocity(track, self.velocity[track][0] + delta * VELOCITY_PER_TICK)

    # ------------------------------------------------------------------ clock input

    def clock_message(self, status, data1=0, data2=0):
        """A MIDI realtime / song position message from the DAW or the internal clock."""
        if status == CLOCK:
            return self._tick()
        if status == START:
            actions = self._release()
            self._ticks = -1
            self.playing = True
            self.version += 1
            return actions
        if status == CONTINUE:
            self.playing = True
            self.version += 1
            return []
        if status == STOP:
            actions = self._release()
            self.playing = False
            old, self.position = self.position, -1
            self.version += 1
            if old >= 0:
                actions += self._column(old)
            return actions
        if status == SONG_POSITION:
            sixteenths = data1 | (data2 << 7)
            self._ticks = sixteenths * TICKS_PER_STEP - 1
            return []
        return []

    def rewind(self):
        """Back to step 1: right away when stopped, on the next clock while playing."""
        actions = self._release()
        self._ticks = -1
        if self.playing:
            return actions
        old, self.position = self.position, -1
        self.version += 1
        return actions + (self._column(old) if old >= 0 else [])

    def _audible(self, track):
        return not self.mute[track] and (self.solo[track] or not any(self.solo))

    def _play_step(self, s, actions):
        for track in range(TRACKS):
            if self.steps[track][s] and self._audible(track):
                channel, note = self.channels[track], self.notes[track]
                actions.append(("out", 0x90 | channel, note, self.velocity[track][s]))
                self._sounding.append((channel, note, self._ticks + min(GATE_TICKS, self.repeat or GATE_TICKS)))

    def _tick(self):
        if not self.playing:
            return []
        self._ticks += 1
        actions = self._release(self._ticks)
        phase = self._ticks % TICKS_PER_STEP
        step = (self._ticks // TICKS_PER_STEP) % STEPS
        if phase == 0:
            old, self.position = self.position, step
            self.version += 1
            if old >= 0 and old != step:
                actions += self._column(old)
            actions += self._column(step)
        if self.repeat:                 # beat repeat: the held step instead of the pattern
            if self._ticks >= self._repeat_tick:
                self._repeat_tick = self._ticks + self.repeat
                actions += self._release()
                self._play_step(self._repeat_step, actions)
            return actions
        current = self._ticks // TICKS_PER_STEP
        for absolute in (current, current - 1):     # a 1/8 swing can push a note into the next step
            s = absolute % STEPS
            if absolute < 0 or absolute * TICKS_PER_STEP + swing_delay(self.swing, self.swing_eighths, s) != self._ticks:
                continue
            self._play_step(s, actions)
        return actions

    def _release(self, now=None):
        """Note-offs of the sounding notes that are due by tick `now` (all of them when None)."""
        due = [s for s in self._sounding if now is None or s[2] <= now]
        self._sounding = [s for s in self._sounding if s not in due]
        return [("out", 0x80 | channel, note, 0) for channel, note, _ in due]

    def all_notes_off(self):
        self._held.clear()
        self.repeat_held, self.repeat = False, 0
        self.filter_held = False
        return self._release() + self.end_preview()


# --------------------------------------------------------------------------- ports and thread

def led_message(track, step, color):
    """A live pad color: a note-on TO the Orbit with the pad's channel and note, velocity = color."""
    return 0x90 | track, FIRST_NOTE + step, color


class SequencerRunner:
    """Runs a Sequencer: clock in, notes out, Orbit messages in, pad colors out.

    MIDI driver callbacks only queue messages; one worker thread does all the sending."""

    def __init__(self, sequencer, send_led, opener=midi_win.WinMidiPort, lister=midi_win.list_ports,
                 clock=time.monotonic):
        self.seq = sequencer
        self.send_led = send_led            # (status, data1, data2) -> bool, to the Orbit
        self.opener = opener
        self.lister = lister
        self.clock = clock
        self._queue = queue.SimpleQueue()
        self._out = self._in = None
        self._thread = None
        self._lock = threading.Lock()
        self._preview_timer = None
        self._ticker = None
        self._ticking = None
        self._shown = {}                    # (track, step) -> color last sent to the Orbit
        self.last_clock = None
        self.bpm = None
        self._clock_times = []

    @property
    def running(self):
        return self._thread is not None

    def start(self, out_name, clock_name=None):
        """Open the ports by name and start; with no clock_name the internal clock runs at seq.tempo.
        Raises midi_win.MidiError if a port cannot be opened."""
        ins, outs = self.lister()
        if out_name not in outs:
            raise midi_win.MidiError(f"MIDI output not found: {out_name}")
        if clock_name is not None and clock_name not in ins:
            raise midi_win.MidiError(f"MIDI input not found: {clock_name}")
        self._out = self.opener(None, outs.index(out_name))
        if clock_name is not None:
            try:
                self._in = self.opener(ins.index(clock_name), None)
            except BaseException:
                self._out.close()
                self._out = None
                raise
            self._in.on_short = lambda s, d1, d2: self._queue.put(("clock", s, d1, d2))
        self.seq.internal = clock_name is None
        self._clock_times = []
        self.bpm = self.last_clock = None
        self._shown = {}
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if clock_name is None:
            self._ticking = threading.Event()
            self._ticker = threading.Thread(target=self._internal_clock, args=(self._ticking,), daemon=True)
            self._ticker.start()
        # No pad colors yet: the Orbit is about to be written, and it loses a SysEx that arrives right
        # after a burst of notes. The window calls repaint() once that write is done.

    def stop(self):
        if self._thread is None:
            return
        if self._preview_timer is not None:
            self._preview_timer.cancel()
        if self._ticker is not None:
            self._ticking.set()
            self._ticker.join(2.0)
            self._ticker = None
        self._queue.put(("quit",))
        self._thread.join(2.0)
        self._thread = None
        for port in (self._in, self._out):
            if port is not None:
                port.close()
        self._in = self._out = None
        self.seq.playing = False
        self.seq.position = -1
        self.seq.version += 1
        # The pads are not switched off here: writing the user's mapping back gives them its colors.

    def repaint(self):
        """Send every pad color again (after the Orbit was written, which repaints it)."""
        self._shown = {}
        self.post(self.seq.all_leds)

    def _internal_clock(self, stop):
        """24 clocks per quarter note at seq.tempo. Sleeps with 1 ms timer resolution, then spins the
        last moment, so the ticks stay steady (the default Windows sleep is only 15.6 ms accurate)."""
        winmm = ctypes.windll.winmm if hasattr(ctypes, "windll") else None
        if winmm:
            winmm.timeBeginPeriod(1)
        try:
            due = time.perf_counter()
            while not stop.is_set():
                due += 60.0 / (self.seq.tempo * 24)
                wait = due - time.perf_counter()
                if wait > SPIN_SECONDS:
                    stop.wait(wait - SPIN_SECONDS)
                while time.perf_counter() < due:
                    pass
                if time.perf_counter() - due > 0.1:     # fell far behind (system busy): don't rush
                    due = time.perf_counter()
                self._queue.put(("clock", CLOCK, 0, 0))
        finally:
            if winmm:
                winmm.timeEndPeriod(1)

    def device_message(self, status, data1, data2):
        """From the Orbit link's MIDI callback."""
        self._queue.put(("device", status, data1, data2))

    def post(self, call, *args):
        """Run a Sequencer method on the worker thread and perform the actions it returns."""
        if self._thread is None:
            call(*args)     # not running: change the pattern only, the Orbit is not in sequencer mode
        else:
            self._queue.put(("call", call, args))

    def play(self):
        """Internal clock: start from step 1."""
        if self.seq.internal and not self.seq.playing:
            self.post(self.seq.clock_message, START)

    def stop_playing(self):
        """Internal clock: stop, or go back to step 1 when already stopped."""
        if not self.seq.internal:
            return
        if self.seq.playing:
            self.post(self.seq.clock_message, STOP)
        else:
            self.post(self.seq.rewind)

    def _run(self):
        while True:
            item = self._queue.get()
            kind = item[0]
            if kind == "quit":
                with self._lock:
                    self._apply(self.seq.all_notes_off())
                return
            with self._lock:
                if kind == "clock":
                    _, status, d1, d2 = item
                    if status == CLOCK:
                        self._measure()
                    self._apply(self.seq.clock_message(status, d1, d2))
                elif kind == "device":
                    self._apply(self.seq.device_message(*item[1:]))
                elif kind == "call":
                    self._apply(item[1](*item[2]))

    def _measure(self):
        now = self.clock()
        self.last_clock = now
        times = self._clock_times
        times.append(now)
        if len(times) > 48:
            del times[0]
        if len(times) >= 12 and times[-1] > times[0]:
            self.bpm = 60.0 / ((times[-1] - times[0]) / (len(times) - 1) * 24)

    def _apply(self, actions):
        for action in actions:
            if action[0] == "preview":
                if self._preview_timer is not None:
                    self._preview_timer.cancel()
                self._preview_timer = threading.Timer(PREVIEW_SECONDS, self.post, (self.seq.end_preview,))
                self._preview_timer.daemon = True
                self._preview_timer.start()
            elif action[0] == "out":
                if self._out is not None:
                    try:
                        self._out.send_short(*action[1:])
                    except midi_win.MidiError:
                        pass
            elif action[0] == "led":
                _, track, step, color = action
                if self._shown.get((track, step)) == color:
                    continue                    # unchanged: spare the Orbit's MIDI input
                if self.send_led(*led_message(track, step, color)):
                    self._shown[(track, step)] = color
                else:
                    self._shown.pop((track, step), None)


# --------------------------------------------------------------------------- settings file

def settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Orbit Editor", "sequencer.json")


def load_settings(path=None):
    try:
        with open(path or settings_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data, path=None):
    path = path or settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def encode_backup(config):
    """The user's mapping, kept in the settings file while the Orbit holds the sequencer mapping."""
    return protocol.encode_payload(config).hex()


def decode_backup(text):
    """The mapping saved by encode_backup(), or None if it is missing or damaged."""
    try:
        return protocol.decode_payload(bytes.fromhex(text))
    except (TypeError, ValueError):
        return None
