"""Main window (CustomTkinter + Pillow drawings).

The Orbit stays linked while the window is open (link.py): it is found automatically, every change
is applied to it half a second after the last edit, and pads pressed on the Orbit light up on screen.
The Sequencer page turns the Orbit into a 4-track step sequencer (sequencer.py).
"""
import ctypes
import os
import sys
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from . import __version__, colors, midi_win, presets, protocol, render, scales, sequencer
from .editor import EditorState
from .i18n import Translator
from .link import OrbitLink
from .protocol import KNOBS_PER_BANK, NUM_BANKS, ProtocolError
from .scales import ScaleSetting

# Same look as the nanoKONTROL 2 and Swing editors, from the macOS (light) system colours:
# window #ececec, white content, a light toolbar, white push buttons with a hairline border,
# system blue for accents and selections, labels in black at 85 / 50 %.
BG = "#ececec"            # window background
TOOLBAR = "#f6f6f6"       # header
CARD = "#ffffff"          # content
BUTTON = "#ffffff"        # push button, with a BUTTON_EDGE border
BUTTON_HOVER = "#f6f6f6"
BUTTON_EDGE = "#cfcfcf"
TRACK = "#e3e3e3"         # segmented control track
EDGE = "#d9d9d9"          # separators
TEXT = "#262626"          # labels: black 85 %
MUTED = "#808080"         # secondary labels: black 50 %
DIM = "#a6a6a6"
ACCENT = "#007aff"        # system blue
ACCENT_HOVER = "#1a88ff"
SELECTED = "#0063e1"
OK = "#1f9d3a"
WARN = "#c26a00"
ERROR = "#d70015"
ACCEL_LR = "#e0a800"      # the Orbit's fixed accelerometer light colors
ACCEL_UD = "#2f7df6"
FONT_CHOICES = ("Inter", "Segoe UI")
FONT = "Segoe UI"         # replaced by Inter in main() when assets/fonts loads
PUSH = dict(fg_color=BUTTON, hover_color=BUTTON_HOVER, border_width=1, border_color=BUTTON_EDGE,
            text_color=TEXT, text_color_disabled=DIM)

WHEEL = 196
BAR_W, BAR_H = 300, 30
RECEIVING_SECONDS = 1.2
WRITTEN_SECONDS = 2.0
CLOCK_TIMEOUT = 1.0        # no DAW clock for this long: the sequencer is waiting for it
SEQ_SAVE_SECONDS = 2.0     # the pattern is saved this long after the last change
WHEEL_VELOCITY = 8         # velocity change per mouse wheel notch over a step
REPAINT_DELAY_MS = int(midi_win.QUIET_AFTER_RECEIVE * 1000) + 100
NOTE_NAMES = protocol.NOTE_NAMES


TRACK_COLUMN = 416        # width of the track controls left of the step grid


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


def _asset(*parts):
    """A file in assets/, both when run from source and when bundled by PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", *parts)


def _logo(size):
    """The app logo as a CTkImage, or None if the file is missing (e.g. a partial checkout)."""
    try:
        image = Image.open(_asset("logo.png"))
    except OSError:
        return None
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


def _dot(color, size=12):
    """A small round swatch of an Orbit color, with a hairline edge so white shows on white."""
    k = 4
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((0, 0, size * k - 1, size * k - 1), fill=render.screen_rgb(color),
                                outline=(0, 0, 0, 60), width=k)
    img = img.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def _load_fonts():
    """Make the fonts in assets/fonts (Inter, SIL OFL) usable by this process only, without installing
    them in Windows, and use the first available family of FONT_CHOICES."""
    global FONT
    folder = _asset("fonts")
    if sys.platform == "win32" and os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".ttf"):
                try:
                    ctypes.windll.gdi32.AddFontResourceExW(os.path.join(folder, name), 0x10, 0)   # FR_PRIVATE
                except (AttributeError, OSError):
                    pass
    families = set(tkfont.families())
    FONT = next((f for f in FONT_CHOICES if f in families), FONT)


class Spin(ctk.CTkFrame):
    """[-] number [+]; calls on_change(int) with a value in low..high. Invalid input is put back."""

    def __init__(self, master, low, high, on_change, width=48):
        super().__init__(master, fg_color="transparent")
        self.low, self.high, self.on_change = low, high, on_change
        self.value = low
        style = dict(width=28, height=30, corner_radius=7, **PUSH)
        self.minus = ctk.CTkButton(self, text="−", command=lambda: self.step(-1), **style)
        self.entry = ctk.CTkEntry(self, width=width, height=30, justify="center", border_width=1,
                                  border_color=BUTTON_EDGE, fg_color=CARD, text_color=TEXT, corner_radius=7,
                                  font=(FONT, 13))
        self.plus = ctk.CTkButton(self, text="+", command=lambda: self.step(1), **style)
        self.minus.pack(side="left")
        self.entry.pack(side="left", padx=4)
        self.plus.pack(side="left")
        self.entry.bind("<Return>", self.commit)
        self.entry.bind("<FocusOut>", self.commit)

    def set(self, value):
        if value != self.value or self.entry.get() != str(value):
            self.value = value
            self.entry.delete(0, "end")
            self.entry.insert(0, str(value))

    def get_text(self):
        return self.entry.get()

    def set_text(self, text):
        self.entry.delete(0, "end")
        self.entry.insert(0, text)

    def step(self, delta):
        value = min(self.high, max(self.low, self.value + delta))
        if value != self.value:
            self.on_change(value)

    def commit(self, event=None):
        try:
            value = int(self.entry.get())
            if not self.low <= value <= self.high:
                raise ValueError
        except ValueError:
            self.value = None
            self.set(self.on_invalid())
            return
        if value != self.value:
            self.on_change(value)

    def on_invalid(self):
        return self.low


class ImageView(tk.Canvas):
    """A canvas showing one Pillow image; redrawn only when the image changes."""

    def __init__(self, master, width, height, bg=CARD):
        super().__init__(master, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
        self._photo = None
        self._item = None

    def show(self, image, x=0, y=0):
        self._photo = ImageTk.PhotoImage(image)
        if self._item is None:
            self._item = self.create_image(x, y, image=self._photo, anchor="nw")
        else:
            self.itemconfigure(self._item, image=self._photo)


class App(ctk.CTkFrame):
    def __init__(self, master, lang=None, link=None, autostart=True,
                 ask_yes_no=messagebox.askyesno, ask_open=filedialog.askopenfilename,
                 ask_save=filedialog.asksaveasfilename, clock=time.monotonic, seq_runner=None,
                 seq_settings=None, save_seq_settings=sequencer.save_settings, port_lister=midi_win.list_ports,
                 loopmidi_check=sequencer.loopmidi_installed, open_url=webbrowser.open):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.t = Translator(lang)
        self.link = link or OrbitLink()
        self.ask_yes_no, self.ask_open, self.ask_save, self.clock = ask_yes_no, ask_open, ask_save, clock
        self.port_lister, self.loopmidi_check, self.open_url = port_lister, loopmidi_check, open_url
        self._save_seq_settings = save_seq_settings
        self.seq_settings = sequencer.load_settings() if seq_settings is None else dict(seq_settings)
        self.seq = sequencer.Sequencer()
        self.seq.load_dict(self.seq_settings.get("pattern", {}))
        self.seq_output = self.seq_settings.get("output")
        self.seq_clock = self.seq_settings.get("clock")
        self.seq_on = False
        self._seq_config = None       # the mapping the Orbit holds while the sequencer runs
        self._seq_saved = (self.seq.version, self.seq_output, self.seq_clock)
        self._seq_changed_at = None
        self._repaint_job = None
        self.seq_runner = seq_runner or sequencer.SequencerRunner(self.seq, self.link.send_short)
        self.view = "mapping"
        self.state = EditorState()
        self.s = self._get_widget_scaling()
        self.selected_knob = 0
        self.selected_axis = 0
        self.pressed = set()          # (bank, pad) held down on the Orbit
        self._shown = {}              # last value pushed to each widget, to avoid redrawing (flicker)
        self._pushed = self.state.config
        self._last_midi = -100.0
        self._written_at = -100.0
        self._writing = False
        self._failed = False
        self._wheel_point = None      # last point picked on the wheel (keeps the marker where clicked)

        self.master.title(self.t("title"))
        self.master.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self.pack(fill="both", expand=True)
        self.refresh()
        if autostart:
            self.link.start()
            self.after(40, self._poll)

    # ------------------------------------------------------------------ layout helpers
    def _card(self, parent, title=None):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10, border_width=1, border_color=EDGE)
        if title is not None:
            card.title = ctk.CTkLabel(card, text=title, font=(FONT, 15, "bold"), text_color=TEXT, anchor="w")
            card.title.pack(fill="x", padx=18, pady=(14, 8))
        return card

    def _label(self, parent, text, muted=True, size=12, **kw):
        return ctk.CTkLabel(parent, text=text, font=(FONT, size), text_color=MUTED if muted else TEXT, **kw)

    def _row(self, parent, label, width=74):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=4)
        self._label(row, label, width=width, anchor="w").pack(side="left")
        return row

    def _segmented(self, parent, values, command, **kw):
        # macOS segmented control: the chosen segment is white on a grey track
        return ctk.CTkSegmentedButton(parent, values=values, command=command, selected_color=BUTTON,
                                      selected_hover_color=BUTTON, unselected_color=TRACK,
                                      unselected_hover_color=EDGE, fg_color=TRACK, text_color=TEXT,
                                      corner_radius=7, font=(FONT, 12), height=30, **kw)

    def _option(self, parent, values, command, width=72):
        # macOS pop-up button: light with the blue arrow box on the right
        return ctk.CTkOptionMenu(parent, values=values, command=command, width=width, height=30,
                                 fg_color=TRACK, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                 text_color=TEXT, text_color_disabled=DIM, dropdown_fg_color=CARD,
                                 dropdown_hover_color=TRACK, dropdown_text_color=TEXT, corner_radius=7,
                                 dynamic_resizing=False, font=(FONT, 12), dropdown_font=(FONT, 12))

    def _show(self, key, value, apply):
        """Call apply(value) only if value changed since last time (prevents flicker)."""
        if self._shown.get(key, object()) != value:
            self._shown[key] = value
            apply(value)

    # ------------------------------------------------------------------ build
    def _build(self):
        t = self.t
        toolbar = ctk.CTkFrame(self, fg_color=TOOLBAR, corner_radius=0)
        toolbar.pack(fill="x")
        ctk.CTkFrame(self, fg_color=EDGE, height=1, corner_radius=0).pack(fill="x")
        header = ctk.CTkFrame(toolbar, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(12, 12))
        logo = _logo(46)
        if logo is not None:
            ctk.CTkLabel(header, text="", image=logo, width=46).pack(side="left", padx=(0, 12))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text=t("heading"), font=(FONT, 22, "bold"), text_color=TEXT,
                     height=28).pack(anchor="w")
        ctk.CTkLabel(titles, text=t("subheading"), font=(FONT, 12), text_color=MUTED, height=18).pack(anchor="w")
        self.view_names = {"mapping": t("view_mapping"), "sequencer": t("view_sequencer")}
        self.view_selector = self._segmented(header, list(self.view_names.values()), self.on_view_name, width=250)
        self.view_selector.configure(height=34, font=(FONT, 13))
        self.view_selector.set(self.view_names["mapping"])
        self.view_selector.pack(side="left", padx=(32, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")
        plain = dict(height=34, corner_radius=7, font=(FONT, 13), **PUSH)
        for key, command in (("open", self.open_file), ("save", self.save_file), ("factory", self.load_factory)):
            ctk.CTkButton(actions, text=t(key), width=90, command=command, **plain).pack(side="left", padx=(0, 6))
        ctk.CTkFrame(actions, fg_color="transparent", width=6, height=1).pack(side="left")
        self.status_button = ctk.CTkButton(actions, text="", width=320, height=34, corner_radius=7,
                                           fg_color=BUTTON, hover_color=BUTTON_HOVER, border_width=1,
                                           border_color=BUTTON_EDGE, font=(FONT, 13, "bold"),
                                           command=self.on_status_click)
        self.status_button.pack(side="left")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(16, 0))

        left = self._card(body)
        left.pack(side="left", fill="y")
        self.bank_selector = self._segmented(left, [t("bank", n=b + 1) for b in range(NUM_BANKS)], self.on_bank_name)
        self.bank_selector.pack(fill="x", padx=18, pady=(18, 12))
        size = int(render.GRID * self.s)
        self.grid_view = ImageView(left, size, size)
        self.grid_view.pack(padx=18)
        self.grid_view.bind("<Button-1>", self._on_grid_click)
        self._label(left, t("pad_hint")).pack(pady=(10, 16))

        middle = self._card(body, "")
        middle.pack(side="left", fill="y", padx=14)
        self.pad_card = middle
        self._build_pad_editor(middle)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        self._build_knobs(right)
        self._build_accel(right)
        self._build_scales(right)
        self._build_tools(right)

        self.seq_body = ctk.CTkFrame(self, fg_color="transparent")
        self._build_sequencer(self.seq_body)
        self.views = {"mapping": body, "sequencer": self.seq_body}

        footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer = footer
        footer.pack(fill="x", padx=22, pady=(10, 12))
        self.message = ctk.CTkLabel(footer, text="", font=(FONT, 12), text_color=MUTED, anchor="w")
        self.message.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(footer, text=f"{t('disclaimer')}   v{__version__}", font=(FONT, 11),
                     text_color=DIM).pack(side="right")

    def _build_pad_editor(self, card):
        t = self.t
        row = self._row(card, t("channel"))
        self.pad_channel = self._option(row, [str(c) for c in range(1, 17)],
                                        lambda v: self._apply(lambda: self.state.update_pad(channel=int(v) - 1)))
        self.pad_channel.pack(side="left")
        row = self._row(card, t("note"))
        self.pad_note = Spin(row, 0, 127, lambda v: self._apply(lambda: self.state.update_pad(note=v)))
        self.pad_note.on_invalid = lambda: self.state.current_pad.note
        self.pad_note.pack(side="left")
        self.note_name = ctk.CTkLabel(row, text="", font=(FONT, 15, "bold"), text_color=TEXT, width=50)
        self.note_name.pack(side="left", padx=8)
        row = self._row(card, t("mode"))
        self.mode_names = [t("momentary"), t("toggle")]
        self.pad_mode = self._segmented(row, self.mode_names, lambda v: self._apply(
            lambda: self.state.update_pad(toggle=self.mode_names.index(v) == 1)))
        self.pad_mode.pack(side="left")

        self._label(card, t("color"), anchor="w").pack(fill="x", padx=18, pady=(12, 4))
        color_row = ctk.CTkFrame(card, fg_color="transparent")
        color_row.pack(fill="x", padx=18)
        side = int(WHEEL * self.s)
        self.wheel_view = ImageView(color_row, side, side)
        self.wheel_view.pack(side="left")
        self.wheel_view.show(render.color_wheel(side))
        self._marker_img = ImageTk.PhotoImage(render.marker(16 * self.s))
        self._marker = self.wheel_view.create_image(side / 2, side / 2, image=self._marker_img)
        for event in ("<Button-1>", "<B1-Motion>"):
            self.wheel_view.bind(event, self._on_wheel)

        swatches = ctk.CTkFrame(color_row, fg_color="transparent")
        swatches.pack(side="left", padx=(16, 0), anchor="n")
        self.preview = ctk.CTkFrame(swatches, width=120, height=44, corner_radius=12, border_width=1,
                                    border_color=EDGE)
        self.preview.pack(anchor="w")
        self.color_name = ctk.CTkLabel(swatches, text="", font=(FONT, 12, "bold"), text_color=TEXT, anchor="w")
        self.color_name.pack(anchor="w", pady=(4, 8))
        palette = ctk.CTkFrame(swatches, fg_color="transparent")
        palette.pack(anchor="w")
        self.color_buttons = {}
        for i, (value, _, _) in enumerate(colors.PALETTE):
            fill = _hex(render.screen_rgb(value))
            button = ctk.CTkButton(palette, text="", width=26, height=26, corner_radius=13, fg_color=fill,
                                   hover_color=fill, border_width=0, command=lambda v=value: self.on_color(v))
            button.grid(row=i // 4, column=i % 4, padx=3, pady=3)
            self.color_buttons[value] = button

        self._label(card, t("brightness"), anchor="w").pack(fill="x", padx=18, pady=(14, 2))
        self.bar_view = ImageView(card, int(BAR_W * self.s), int(BAR_H * self.s))
        self.bar_view.pack(anchor="w", padx=18)
        self.bar_view.bind("<Button-1>", self._on_bar)
        labels = ctk.CTkFrame(card, fg_color="transparent", width=BAR_W, height=20)
        labels.pack(anchor="w", padx=18)
        self.level_labels = []
        for i, key in enumerate(("low", "medium", "high")):
            lab = ctk.CTkLabel(labels, text=t(key), font=(FONT, 11), text_color=MUTED, width=60)
            lab.place(relx=render.BAR_STOPS[i], rely=0.5, anchor="center")
            self.level_labels.append(lab)

        self._label(card, t("custom"), anchor="w").pack(fill="x", padx=18, pady=(12, 4))
        self.rgb = []
        for i, (key, color) in enumerate((("red", "#ff3b30"), ("green", "#28cd41"), ("blue", "#007aff"))):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=2)
            ctk.CTkLabel(row, text=t(key), font=(FONT, 12, "bold"), text_color=color, width=22).pack(side="left")
            seg = ctk.CTkSegmentedButton(row, values=["0", "1", "2", "3"], width=240, height=28,
                                         selected_color=color, selected_hover_color=color, text_color=TEXT,
                                         unselected_color=TRACK, unselected_hover_color=EDGE, fg_color=TRACK,
                                         corner_radius=7, font=(FONT, 12),
                                         command=lambda v, i=i: self.on_component(i, int(v)))
            seg.pack(side="left", padx=(6, 0))
            self.rgb.append(seg)
        ctk.CTkFrame(card, fg_color="transparent", height=14).pack()

    def _build_knobs(self, parent):
        t = self.t
        card = self._card(parent, t("knobs"))
        card.pack(fill="x")
        self.knob_selector = self._segmented(card, ["K1", "K2", "K3", "K4"],
                                             lambda v: self.on_knob(int(v[1]) - 1))
        self.knob_selector.pack(fill="x", padx=18)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(10, 14))
        self._label(row, t("channel")).pack(side="left")
        self.knob_channel = self._option(row, [str(c) for c in range(1, 17)], lambda v: self._apply(
            lambda: self.state.update_knob(self.selected_knob, channel=int(v) - 1)), width=64)
        self.knob_channel.pack(side="left", padx=(6, 12))
        self._label(row, t("cc")).pack(side="left")
        self.knob_cc = Spin(row, 0, 127, lambda v: self._apply(
            lambda: self.state.update_knob(self.selected_knob, cc=v)), width=42)
        self.knob_cc.on_invalid = lambda: self.state.current_bank.knobs[self.selected_knob].cc
        self.knob_cc.pack(side="left", padx=(6, 12))
        self.knob_mode_names = [t("absolute"), t("relative")]
        self.knob_mode = self._segmented(row, self.knob_mode_names, lambda v: self._apply(
            lambda: self.state.update_knob(self.selected_knob, relative=self.knob_mode_names.index(v) == 1)))
        self.knob_mode.pack(side="left")

    def _build_accel(self, parent):
        t = self.t
        card = self._card(parent, t("accel"))
        card.pack(fill="x", pady=(12, 0))
        self.axis_names = [t("axis_lr"), t("axis_ud")]
        self.axis_selector = self._segmented(card, self.axis_names, lambda v: self.on_axis(self.axis_names.index(v)))
        self.axis_selector.pack(fill="x", padx=18)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(10, 4))
        self.axis_dot = ctk.CTkLabel(row, text="●", font=(FONT, 18), width=18)
        self.axis_dot.pack(side="left", padx=(0, 8))
        self._label(row, t("channel")).pack(side="left")
        self.axis_channel = self._option(row, [str(c) for c in range(1, 17)], lambda v: self._apply(
            lambda: self.state.update_axis(self.selected_axis, channel=int(v) - 1)), width=64)
        self.axis_channel.pack(side="left", padx=(6, 12))
        self._label(row, t("cc")).pack(side="left")
        self.axis_cc = Spin(row, 0, 127, lambda v: self._apply(
            lambda: self.state.update_axis(self.selected_axis, cc=v)), width=42)
        self.axis_cc.on_invalid = lambda: self.state.current_bank.axes[self.selected_axis].cc
        self.axis_cc.pack(side="left", padx=6)
        self._label(card, t("fixed_leds"), size=11, anchor="w", wraplength=420, justify="left").pack(
            fill="x", padx=18, pady=(2, 12))

    def _build_scales(self, parent):
        t = self.t
        card = self._card(parent, t("scales"))
        card.pack(fill="x", pady=(12, 0))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=2)
        self.scale_names = [t("no_scale")] + [s[0] for s in scales.SCALES]
        self._label(row, t("scale"), width=56, anchor="w").pack(side="left")
        self.scale_menu = self._option(row, self.scale_names, lambda v: self.on_scale_change(), width=140)
        self.scale_menu.pack(side="left", padx=(0, 12))
        self._label(row, t("root")).pack(side="left")
        self.root_menu = self._option(row, list(NOTE_NAMES), lambda v: self.on_scale_change(), width=64)
        self.root_menu.pack(side="left", padx=6)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(8, 2))
        self._label(row, t("octave"), width=56, anchor="w").pack(side="left")
        self.octave_spin = Spin(row, scales.MIN_OCTAVE, scales.MAX_OCTAVE, lambda v: self.on_scale_change(v),
                                width=38)
        self.octave_spin.on_invalid = lambda: (self.state.scales[self.state.bank] or ScaleSetting()).octave
        self.octave_spin.pack(side="left", padx=(0, 12))
        self.layout_names = [t("chromatic"), t("in_scale")]
        self.layout_selector = self._segmented(row, self.layout_names, lambda v: self.on_scale_change())
        self.layout_selector.pack(side="left")
        self.scale_info = ctk.CTkFrame(card, fg_color="transparent")
        self.scale_info.pack(fill="x", padx=18, pady=(8, 14))
        self._label(self.scale_info, t("scale_colors")).pack(side="left")
        self.scale_dot = ctk.CTkLabel(self.scale_info, text="●", font=(FONT, 16))
        self.scale_dot.pack(side="left", padx=(8, 2))
        self._label(self.scale_info, t("scale_color_scale")).pack(side="left")
        self.root_dot = ctk.CTkLabel(self.scale_info, text="●", font=(FONT, 16))
        self.root_dot.pack(side="left", padx=(10, 2))
        self._label(self.scale_info, t("scale_color_root")).pack(side="left")

    def _build_tools(self, parent):
        t = self.t
        card = self._card(parent, t("tools"))
        card.pack(fill="x", pady=(12, 0))
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=16)
        grid.columnconfigure((0, 1), weight=1)
        helpers = (("ascending", self.state.ascending_notes), ("same_channel", self.state.channel_to_bank),
                   ("same_color", self.state.color_to_bank), ("same_mode", self.state.mode_to_bank))
        for i, (key, action) in enumerate(helpers):
            ctk.CTkButton(grid, text=t(key), height=30, corner_radius=7, font=(FONT, 12), **PUSH,
                          command=lambda a=action: self._apply(a)).grid(
                row=i // 2, column=i % 2, padx=3, pady=3, sticky="we")
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(6, 14))
        self._label(row, t("copy_bank")).pack(side="left")
        self.copy_target = self._option(row, [str(b + 1) for b in range(NUM_BANKS)], None, width=60)
        self.copy_target.pack(side="left", padx=6)
        ctk.CTkButton(row, text=t("copy"), width=80, height=30, corner_radius=7, font=(FONT, 12), **PUSH,
                      command=self.on_copy_bank).pack(side="left")

    def _build_sequencer(self, parent):
        t = self.t
        top = self._card(parent)
        top.pack(fill="x")
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(16, 12))
        titles = ctk.CTkFrame(row, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text=t("seq_title"), font=(FONT, 17, "bold"), text_color=TEXT,
                     height=24).pack(anchor="w")
        self._label(titles, t("seq_subtitle"), height=18).pack(anchor="w")
        transport = dict(height=34, corner_radius=7, font=(FONT, 13, "bold"), **PUSH)
        self.seq_stop_button = ctk.CTkButton(row, text=t("stop"), width=92, command=self.seq_stop_playing,
                                             **transport)
        self.seq_stop_button.pack(side="right")
        self.seq_play_button = ctk.CTkButton(row, text=t("play"), width=92, command=self.seq_play, **transport)
        self.seq_play_button.pack(side="right", padx=6)
        self.seq_power = ctk.CTkButton(row, text=t("seq_start"), width=210, height=34, corner_radius=7,
                                       border_width=1, font=(FONT, 13, "bold"), command=self.toggle_sequencer)
        self.seq_power.pack(side="right", padx=(0, 10))
        ctk.CTkFrame(top, fg_color=EDGE, height=1, corner_radius=0).pack(fill="x", padx=20)

        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(12, 4))
        self._label(row, t("notes_to")).pack(side="left")
        self.seq_out_menu = self._option(row, [], self.set_seq_output, width=240)
        self.seq_out_menu.pack(side="left", padx=(8, 22))
        self._label(row, t("clock_from")).pack(side="left")
        self.seq_clock_menu = self._option(row, [], self.set_seq_clock, width=200)
        self.seq_clock_menu.pack(side="left", padx=(8, 22))
        self._label(row, t("tempo")).pack(side="left")
        self.seq_tempo = Spin(row, sequencer.MIN_TEMPO, sequencer.MAX_TEMPO,
                              lambda v: self.seq_runner.post(self.seq.set_tempo, v), width=46)
        self.seq_tempo.on_invalid = lambda: self.seq.tempo
        self.seq_tempo.pack(side="left", padx=(8, 4))
        self._label(row, "BPM").pack(side="left", padx=(0, 22))
        self._label(row, t("swing")).pack(side="left")
        self.swing_names = [f"{sequencer.swing_percent(level)} %" for level in range(sequencer.MAX_SWING + 1)]
        self.seq_swing = self._segmented(row, self.swing_names, lambda v: self.seq_runner.post(
            self.seq.set_swing, self.swing_names.index(v)))
        self.seq_swing.pack(side="left", padx=(8, 6))
        self.seq_swing_res = self._segmented(row, ["1/16", "1/8"], lambda v: self.seq_runner.post(
            self.seq.set_swing_eighths, v == "1/8"))
        self.seq_swing_res.pack(side="left")

        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(8, 0))
        self.seq_status = ctk.CTkLabel(row, text="", font=(FONT, 13, "bold"), text_color=MUTED, anchor="w")
        self.seq_status.pack(side="left")
        self.seq_wheel = ctk.CTkLabel(row, text="", font=(FONT, 12, "bold"), text_color=ACCENT)
        self.seq_wheel.pack(side="right")

        self.seq_notice = ctk.CTkFrame(top, fg_color="transparent")
        self._label(self.seq_notice, t("loopmidi_notice"), muted=False).pack(side="left")
        ctk.CTkButton(self.seq_notice, text=t("loopmidi_download"), width=170, height=28, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color="#ffffff", corner_radius=7, font=(FONT, 12),
                      command=self.download_loopmidi).pack(side="left", padx=10)
        self.seq_help = self._label(top, t("seq_help"), size=11, anchor="w", justify="left", wraplength=1100)
        self.seq_bottom = ctk.CTkFrame(top, fg_color="transparent", height=14)
        self.seq_bottom.pack(fill="x", padx=12)   # inset, so it does not paint over the card's rounded edge

        grid_card = self._card(parent)
        grid_card.pack(fill="x", pady=(12, 0))
        inner = ctk.CTkFrame(grid_card, fg_color="transparent")
        inner.pack(padx=20, pady=(12, 14))
        tracks = ctk.CTkFrame(inner, fg_color="transparent")
        tracks.pack(side="left", anchor="n")
        heads = ctk.CTkFrame(tracks, fg_color="transparent", height=render.TILE_PAD + render.STEP_NUMBERS,
                             width=TRACK_COLUMN)
        heads.pack_propagate(False)
        heads.pack(anchor="w")
        for text, x in ((t("track_head"), 0), (t("note"), 112), (t("channel"), 220)):
            ctk.CTkLabel(heads, text=text, font=(FONT, 11), text_color=MUTED, height=16).place(x=x, y=4)
        self.seq_rows = []
        for track in range(sequencer.TRACKS):
            line = ctk.CTkFrame(tracks, fg_color="transparent", height=render.STEP_ROW, width=TRACK_COLUMN)
            line.pack_propagate(False)
            line.pack(anchor="w")
            pad = (render.STEP - 32) // 2
            name = ctk.CTkButton(line, text="  " + t("track", n=track + 1), width=104, height=32, corner_radius=7,
                                 font=(FONT, 13, "bold"), anchor="w", image=_dot(sequencer.TRACK_COLORS[track]),
                                 compound="left", **PUSH,
                                 command=lambda tr=track: self.seq_runner.post(self.seq.select, tr))
            name.pack(side="left", anchor="n", pady=(render.TILE_PAD + pad, 0))
            note = Spin(line, 0, 127, lambda v, tr=track: self.seq_set_note(tr, v), width=40)
            note.on_invalid = lambda tr=track: self.seq.notes[tr]
            note.pack(side="left", anchor="n", padx=(8, 2), pady=(render.TILE_PAD + pad + 1, 0))
            note_name = ctk.CTkLabel(line, text="", width=36, font=(FONT, 12, "bold"), text_color=TEXT)
            note_name.pack(side="left", anchor="n", pady=(render.TILE_PAD + pad + 2, 0))
            channel = self._option(line, [str(c) for c in range(1, 17)],
                                   lambda v, tr=track: self.seq_runner.post(self.seq.set_channel, tr, int(v) - 1),
                                   width=58)
            channel.pack(side="left", anchor="n", padx=(2, 6), pady=(render.TILE_PAD + pad + 1, 0))
            solo = ctk.CTkButton(line, text=t("solo"), width=30, height=30, corner_radius=7,
                                 font=(FONT, 12, "bold"), **PUSH,
                                 command=lambda tr=track: self.seq_runner.post(self.seq.toggle_solo, tr))
            solo.pack(side="left", anchor="n", padx=(0, 4), pady=(render.TILE_PAD + pad + 1, 0))
            clear = ctk.CTkButton(line, text=t("clear"), width=60, height=30, corner_radius=7, font=(FONT, 12),
                                  **PUSH, command=lambda tr=track: self.seq_runner.post(self.seq.clear_track, tr))
            clear.pack(side="left", anchor="n", pady=(render.TILE_PAD + pad + 1, 0))
            self.seq_rows.append(dict(name=name, note=note, note_name=note_name, channel=channel, solo=solo))
        width = int((render.STEPS_W + 2 * render.TILE_PAD) * self.s)
        height = int((render.STEPS_H + 2 * render.TILE_PAD) * self.s)
        self.step_view = ImageView(inner, width, height)
        self.step_view.pack(side="left", padx=(6, 0))
        self.step_view.bind("<Button-1>", self._on_step_click)
        self.step_view.bind("<MouseWheel>", self._on_step_wheel)

        help_card = self._card(parent, t("on_orbit"))
        help_card.pack(fill="x", pady=(12, 0))
        grid = ctk.CTkFrame(help_card, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=(0, 14))
        grid.columnconfigure((0, 1), weight=1, uniform="help")
        for i, (head, key) in enumerate((("help_pads_head", "help_pads"), ("help_hold_head", "help_hold"),
                                         ("help_wheel_head", "help_wheel"), ("help_accel_head", "help_accel"))):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=i // 2, column=i % 2, sticky="nw", pady=4, padx=(0, 20))
            ctk.CTkLabel(cell, text=t(head), font=(FONT, 13, "bold"), text_color=TEXT, anchor="w",
                         height=20).pack(anchor="w")
            self._label(cell, t(key), anchor="w", justify="left", wraplength=560, height=18).pack(anchor="w")

    # ------------------------------------------------------------------ editing
    def _apply(self, action):
        try:
            action()
        except ProtocolError as e:
            self.show(self.t("error", err=e), ERROR)
        self.refresh()

    def on_bank(self, index):
        self.state.select(bank=index)
        self.refresh()

    def on_bank_name(self, name):
        self.on_bank([self.t("bank", n=b + 1) for b in range(NUM_BANKS)].index(name))

    def on_pad(self, index):
        self.state.select(pad=index)
        self._wheel_point = None
        self.refresh()

    def _on_grid_click(self, event):
        index = render.pad_at(event.x, event.y, self.s)
        if index is not None:
            self.on_pad(index)

    def on_knob(self, index):
        self.selected_knob = index
        self.refresh()

    def on_axis(self, index):
        self.selected_axis = index
        self.refresh()

    def _level(self):
        return colors.brightness(self.state.current_pad.color) or 3

    def on_color(self, value):
        """Pick a palette color, keeping the pad's current brightness."""
        self._wheel_point = None
        self._apply(lambda: self.state.update_pad(color=colors.scale(value, self._level())))

    def _on_wheel(self, event):
        r = WHEEL * self.s / 2
        dx, dy = event.x - r, event.y - r
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > r and event.type == tk.EventType.ButtonPress:
            return  # a click outside the wheel
        if dist > r:  # dragging past the edge: stay on the edge
            dx, dy = dx * r / dist, dy * r / dist
        self._wheel_point = (dx / r, dy / r)
        value = render.color_from_wheel(dx, dy, r, self._level())
        self._apply(lambda: self.state.update_pad(color=value))

    def on_brightness(self, level):
        current = self.state.current_pad.color
        if not current:
            return
        hue, _ = colors.split(current)
        self._apply(lambda: self.state.update_pad(color=colors.scale(hue if hue else current, level)))

    def _on_bar(self, event):
        self.on_brightness(render.level_at(event.x, BAR_W * self.s))

    def on_component(self, index, level):
        comps = list(colors.components(self.state.current_pad.color))
        comps[index] = level
        self._wheel_point = None
        self._apply(lambda: self.state.update_pad(color=colors.from_components(*comps)))

    def on_copy_bank(self):
        self._apply(lambda: self.state.copy_bank(int(self.copy_target.get()) - 1))

    def _scale_from_widgets(self, octave=None):
        name = self.scale_menu.get()
        if name == self.t("no_scale"):
            return None
        scale_id = scales.SCALES[self.scale_names.index(name) - 1][2]
        root = NOTE_NAMES.index(self.root_menu.get())
        octave = self.octave_spin.value if octave is None else octave
        chosen = self.layout_selector.get()
        layout = scales.LAYOUTS[self.layout_names.index(chosen)] if chosen in self.layout_names else "chromatic"
        return ScaleSetting(scale_id, root, octave, layout)

    def on_scale_change(self, octave=None):
        if octave is not None:
            self.octave_spin.set(octave)
        self._apply(lambda: self.state.apply_scale(self._scale_from_widgets(octave)))

    # ------------------------------------------------------------------ drawing
    def refresh(self):
        """Bring every widget up to date with the editor state (only what changed is redrawn)."""
        state, t = self.state, self.t
        bank, pad = state.current_bank, state.current_pad
        self._show("bank", state.bank, lambda b: self.bank_selector.set(t("bank", n=b + 1)))
        pressed = frozenset(p for b, p in self.pressed if b == state.bank)
        grid_key = (tuple((p.color, p.note) for p in bank.pads), state.pad, pressed)
        self._show("grid", grid_key, lambda _: self.grid_view.show(
            render.pad_grid(bank.pads, state.pad, pressed, self.s)))

        self._show("pad_title", (state.pad, state.bank), lambda v: self.pad_card.title.configure(
            text=t("pad_settings", n=v[0] + 1, b=v[1] + 1)))
        self._show("pad_channel", pad.channel, lambda v: self.pad_channel.set(str(v + 1)))
        self._show("pad_note", pad.note, lambda v: (self.pad_note.set(v),
                                                   self.note_name.configure(text=protocol.note_name(v))))
        self._show("pad_mode", pad.toggle, lambda v: self.pad_mode.set(self.mode_names[int(v)]))
        self._show("color", (pad.color, self._wheel_point), lambda _: self._draw_color(pad.color))

        knob = bank.knobs[self.selected_knob]
        self._show("knob_sel", self.selected_knob, lambda k: self.knob_selector.set(f"K{k + 1}"))
        self._show("knob_channel", knob.channel, lambda v: self.knob_channel.set(str(v + 1)))
        self._show("knob_cc", knob.cc, self.knob_cc.set)
        self._show("knob_mode", knob.relative, lambda v: self.knob_mode.set(self.knob_mode_names[int(v)]))
        axis = bank.axes[self.selected_axis]
        self._show("axis_sel", self.selected_axis, lambda a: (
            self.axis_selector.set(self.axis_names[a]),
            self.axis_dot.configure(text_color=(ACCEL_LR, ACCEL_UD)[a])))
        self._show("axis_channel", axis.channel, lambda v: self.axis_channel.set(str(v + 1)))
        self._show("axis_cc", axis.cc, self.axis_cc.set)

        setting = state.scales[state.bank]
        self._show("scale", (state.bank, setting), lambda _: self._draw_scale(setting))
        self._push_if_changed()
        self._draw_status()

    def _draw_color(self, value):
        hue, level = colors.split(value)
        self.preview.configure(fg_color=_hex(render.screen_rgb(value)))
        self.color_name.configure(text=colors.name(hue if hue is not None else value, self.t.lang)
                                  if value else colors.name(0, self.t.lang))
        for v, button in self.color_buttons.items():
            button.configure(border_width=3 if v == hue else 1, border_color=ACCENT if v == hue else BUTTON_EDGE)
        r = WHEEL * self.s / 2
        if self._wheel_point is not None:
            dx, dy = self._wheel_point[0] * r, self._wheel_point[1] * r
        else:
            dx, dy = render.wheel_position(value, r)
        self.wheel_view.coords(self._marker, r + dx, r + dy)
        self.bar_view.show(render.brightness_bar(BAR_W, BAR_H, value, level, self.s))
        for i, lab in enumerate(self.level_labels):
            lab.configure(text_color=TEXT if level == i + 1 else MUTED,
                          font=(FONT, 11, "bold" if level == i + 1 else "normal"))
        for seg, comp in zip(self.rgb, colors.components(value)):
            seg.set(str(comp))

    def _draw_scale(self, setting):
        scale_color, root_color = scales.BANK_COLORS[self.state.bank]
        self.scale_dot.configure(text="", image=_dot(scale_color, 13))
        self.root_dot.configure(text="", image=_dot(root_color, 13))
        shown = setting or ScaleSetting()
        self.scale_menu.set(self.t("no_scale") if setting is None
                            else scales.SCALES[scales.SCALE_IDS.index(setting.scale_id)][0])
        self.root_menu.set(NOTE_NAMES[shown.root])
        self.octave_spin.set(shown.octave)
        self.layout_selector.set(self.layout_names[scales.LAYOUTS.index(shown.layout)])

    def show(self, text, color=MUTED):
        self.message.configure(text=text, text_color=color)

    # ------------------------------------------------------------------ Orbit link
    def _push_if_changed(self):
        if self.state.config is not self._pushed:
            if self.seq_on:   # the Orbit holds the sequencer mapping: the edit is applied when it stops
                self.show(self.t("seq_mapping_waits"))
                return
            self._pushed = self.state.config
            self._failed = False
            self.link.push(self.state.config)

    def _poll(self):
        self.process_link_events()
        self.refresh_sequencer()
        self._autosave_sequencer()
        self.after(40, self._poll)

    def process_link_events(self):
        changed = False
        while not self.link.events.empty():
            kind, payload = self.link.events.get_nowait()
            changed = True
            if kind == "config" and self.seq_on:
                if payload != self._seq_config:   # linked again: put the sequencer mapping back
                    self.link.push(self._seq_config)
                    self.link.flush()
                else:
                    self._repaint_pads_soon()
            elif kind == "config":
                backup = sequencer.decode_backup(self.seq_settings.get("backup"))
                if backup is not None and sequencer.is_sequencer_config(payload):
                    # The app ended while sequencing: the Orbit still holds the sequencer mapping.
                    self.state.set_config(backup, dirty=True)
                    self.seq_settings.pop("backup", None)
                    self._store_seq_settings()
                    self.show(self.t("seq_restored"), OK)
                else:
                    self.state.set_config(payload, dirty=False)
                    self._pushed = self.state.config
                    self.show(self.t("read_ok"), OK)
            elif kind == "writing":
                self._writing = True
            elif kind == "written":
                self._writing, self._failed = False, False
                self._written_at = self.clock()
                if self.seq_on:   # writing the mapping repaints the pads: light the pattern again
                    self._repaint_pads_soon()
            elif kind == "write_failed":
                self._writing, self._failed = False, True
                from .device import VerifyError
                self.show(self.t("verify_error") if isinstance(payload, VerifyError)
                          else self.t("write_error", err=payload), ERROR)
            elif kind == "searching":
                self._writing = False
                self.pressed.clear()
            elif kind == "midi":
                if self.seq_on:   # the sequencer handles it (link.listener); just show the activity
                    self._last_midi = self.clock()
                else:
                    self._on_midi(*payload)
        if changed:
            self.refresh()
        self._draw_status()

    def _on_midi(self, status, data1, data2):
        """Follow what is played on the Orbit: pressed pads light up, banks/knobs get selected."""
        self._last_midi = self.clock()
        kind, channel = status & 0xF0, status & 0x0F
        config = self.state.config
        if kind in (0x80, 0x90):
            for b in [self.state.bank] + [i for i in range(NUM_BANKS) if i != self.state.bank]:
                for p, pad in enumerate(config.banks[b].pads):
                    if pad.channel == channel and pad.note == data1:
                        if kind == 0x90 and data2 > 0:
                            self.pressed.add((b, p))
                            self.state.select(bank=b, pad=p)
                            self._wheel_point = None
                        else:
                            self.pressed.discard((b, p))
                        return
        elif kind == 0xB0:
            if channel == 15 and data1 == 1 and 1 <= data2 <= NUM_BANKS:  # a bank button was pressed
                self.state.select(bank=data2 - 1)
                return
            if channel == 15 and data1 == 2 and 1 <= data2 <= KNOBS_PER_BANK:  # a K button was pressed
                self.selected_knob = data2 - 1
                return
            for b in [self.state.bank] + [i for i in range(NUM_BANKS) if i != self.state.bank]:
                bank = config.banks[b]
                for k, knob in enumerate(bank.knobs):
                    if knob.channel == channel and knob.cc == data1:
                        self.state.select(bank=b)
                        self.selected_knob = k
                        return
                for a, axis in enumerate(bank.axes):
                    if axis.channel == channel and axis.cc == data1:
                        self.state.select(bank=b)
                        self.selected_axis = a
                        return

    def _status(self):
        now = self.clock()
        if not self.link.linked:
            return "status_searching", MUTED
        if self._failed:
            return "status_failed", ERROR
        if self._writing or self.link.has_pending:
            return "status_writing", WARN
        if now - self._last_midi < RECEIVING_SECONDS:
            return "status_receiving", ACCENT
        if now - self._written_at < WRITTEN_SECONDS:
            return "status_written", OK
        return "status_linked", OK

    def _draw_status(self):
        key, ink = self._status()
        self._show("status", key, lambda _: self.status_button.configure(text=self.t(key), text_color=ink))

    def on_status_click(self):
        """Apply the mapping again (e.g. after an error)."""
        if self.link.linked:
            self._failed = False
            self.link.push(self._seq_config if self.seq_on else self.state.config)
            self.link.flush()
            self._draw_status()

    # ------------------------------------------------------------------ views
    def on_view_name(self, name):
        self.show_view(next(key for key, text in self.view_names.items() if text == name))

    def show_view(self, view):
        if view != self.view:
            self.views[self.view].pack_forget()
            self.views[view].pack(fill="both", expand=True, padx=22, before=self.footer)
            self.view = view
        self.view_selector.set(self.view_names[view])
        if view == "sequencer":
            self.refresh_seq_ports()
            self._shown.pop("seq_grid", None)
            self.refresh_sequencer()

    # ------------------------------------------------------------------ sequencer
    def seq_ports(self):
        """(outputs, inputs) the sequencer can use: every MIDI port except the Orbit's own."""
        try:
            ins, outs = self.port_lister()
        except OSError:
            return [], []
        keep = lambda names: [n for n in names if n and midi_win.find_port([n]) is None]
        return keep(outs), keep(ins)

    def refresh_seq_ports(self):
        outs, ins = self.seq_ports()
        internal = self.t("internal_clock")
        self.seq_out_menu.configure(values=outs or [self.t("choose_port")])
        self.seq_clock_menu.configure(values=[internal] + ins)
        self.seq_out_menu.set(self.seq_output or self.t("choose_port"))
        self.seq_clock_menu.set(internal if self.seq_clock == sequencer.INTERNAL
                                else self.seq_clock or self.t("choose_port"))
        installed = self.loopmidi_check()
        if installed:
            self.seq_notice.pack_forget()
            self.seq_help.pack(fill="x", padx=18, pady=(4, 0), before=self.seq_bottom)
        else:
            self.seq_help.pack_forget()
            self.seq_notice.pack(fill="x", padx=18, pady=(6, 0), before=self.seq_bottom)

    def download_loopmidi(self):
        self.open_url(sequencer.LOOPMIDI_URL)
        self.show(self.t("loopmidi_opened"))

    def set_seq_output(self, name):
        if name != self.t("choose_port"):
            self.seq_output = name

    def set_seq_clock(self, name):
        self.seq_clock = sequencer.INTERNAL if name == self.t("internal_clock") else name

    def toggle_sequencer(self):
        if self.seq_on:
            self.stop_sequencer()
        else:
            self.start_sequencer()

    def start_sequencer(self):
        t = self.t
        if self.seq_on:
            return
        if not self.link.linked:
            self.show(t("seq_need_orbit"), ERROR)
            return
        if not self.seq_output or not self.seq_clock:
            self.show(t("seq_need_ports"), ERROR)
            return
        internal = self.seq_clock == sequencer.INTERNAL
        if self.seq_output == self.seq_clock:
            self.show(t("seq_same_port"), ERROR)
            return
        try:
            self.seq_runner.start(self.seq_output, None if internal else self.seq_clock)
        except midi_win.MidiError as e:
            self.show(t("seq_port_error", err=e), ERROR)
            return
        self.seq_on = True
        # Keep the user's mapping in the settings file: if the app ends without stopping the
        # sequencer, the next start finds the Orbit still holding the sequencer mapping and puts it back.
        self.seq_settings["backup"] = sequencer.encode_backup(self.state.config)
        self._store_seq_settings()
        self._seq_config = sequencer.sequencer_config(self.state.config)
        self.link.listener = self.seq_runner.device_message
        self.link.push(self._seq_config)
        self.link.flush()
        self.show(t("seq_on_internal") if internal else t("seq_on_daw"), OK)
        self.refresh_sequencer()

    def stop_sequencer(self):
        if not self.seq_on:
            return
        self.link.listener = None
        self.seq_runner.stop()
        self.seq_on = False
        self._seq_config = None
        self._pushed = self.state.config
        self.link.push(self.state.config)    # back to the user's mapping (written when linked)
        self.link.flush()
        self.seq_settings.pop("backup", None)
        self._store_seq_settings()
        self.show(self.t("seq_off_msg"))
        self.refresh_sequencer()

    def seq_play(self):
        self.seq_runner.play()
        self.show("")   # "press Play" is done; the status line shows the playing step

    def seq_stop_playing(self):
        self.seq_runner.stop_playing()

    def seq_set_note(self, track, note):
        self.seq_runner.post(self.seq.set_note, track, note)
        if self.seq_on:
            self.seq_runner.post(self.seq.preview, track)

    def _on_step_click(self, event):
        hit = render.step_at(event.x, event.y, self.s)
        if hit is not None:
            self.seq_runner.post(self.seq.select, hit[0])
            self.seq_runner.post(self.seq.toggle_step, *hit)
            self.refresh_sequencer()

    def _on_step_wheel(self, event):
        """Mouse wheel over a step: its velocity (the step is turned on)."""
        hit = render.step_at(event.x, event.y, self.s)
        if hit is None:
            return
        track, step = hit
        if not self.seq.steps[track][step]:
            self.seq_runner.post(self.seq.toggle_step, track, step)
        delta = WHEEL_VELOCITY if event.delta > 0 else -WHEEL_VELOCITY
        self.seq_runner.post(self.seq.set_step_velocity, track, step, self.seq.velocity[track][step] + delta)
        self.refresh_sequencer()

    def sequencer_status(self):
        t, seq, runner = self.t, self.seq, self.seq_runner
        if not self.seq_on:
            return t("seq_off"), MUTED
        if self.seq_clock == sequencer.INTERNAL:
            if seq.playing and seq.position >= 0:
                return t("seq_playing", bpm=seq.tempo, step=seq.position + 1), OK
            return t("seq_stopped_internal"), MUTED
        bpm = f"{runner.bpm:.0f}" if runner.bpm else "–"
        if runner.last_clock is None or self.clock() - runner.last_clock > CLOCK_TIMEOUT:
            return t("seq_waiting"), WARN
        if seq.playing and seq.position >= 0:
            return t("seq_playing", bpm=bpm, step=seq.position + 1), OK
        return t("seq_stopped", bpm=bpm), MUTED

    def refresh_sequencer(self):
        """Bring the sequencer page up to date (only what changed is redrawn)."""
        if self.view != "sequencer":
            return
        t, seq = self.t, self.seq
        on, internal = self.seq_on, self.seq_clock == sequencer.INTERNAL
        # Off: a blue default button. On: a white push button with a red label (macOS destructive).
        self._show("seq_power", on, lambda v: self.seq_power.configure(
            text=t("seq_stop") if v else t("seq_start"), fg_color=BUTTON if v else ACCENT,
            hover_color=BUTTON_HOVER if v else ACCENT_HOVER, border_color=BUTTON_EDGE if v else ACCENT,
            text_color=ERROR if v else "#ffffff"))
        transport = "normal" if on and internal else "disabled"
        self._show("seq_transport", transport, lambda v: (self.seq_play_button.configure(state=v),
                                                          self.seq_stop_button.configure(state=v)))
        self._show("seq_ports_state", on, lambda v: (self.seq_out_menu.configure(state="disabled" if v else "normal"),
                                                     self.seq_clock_menu.configure(state="disabled" if v else "normal")))
        status = self.sequencer_status()
        self._show("seq_status", status, lambda v: self.seq_status.configure(text=v[0], text_color=v[1]))
        self._show("seq_wheel", internal, lambda v: self.seq_wheel.configure(
            text=t("wheel_now", what=t("wheel_tempo" if v else "wheel_velocity"))))
        self._show("seq_tempo", seq.tempo, self.seq_tempo.set)
        self._show("seq_swing", seq.swing, lambda v: self.seq_swing.set(self.swing_names[v]))
        self._show("seq_swing_res", seq.swing_eighths, lambda v: self.seq_swing_res.set("1/8" if v else "1/16"))
        for track, row in enumerate(self.seq_rows):
            self._show(f"seq_sel{track}", track == seq.selected, lambda v, r=row: r["name"].configure(
                fg_color=SELECTED if v else BUTTON, hover_color=SELECTED if v else BUTTON_HOVER,
                border_color=SELECTED if v else BUTTON_EDGE, text_color="#ffffff" if v else TEXT))
            self._show(f"seq_note{track}", seq.notes[track], lambda v, r=row: (
                r["note"].set(v), r["note_name"].configure(text=protocol.note_name(v))))
            self._show(f"seq_ch{track}", seq.channels[track], lambda v, r=row: r["channel"].set(str(v + 1)))
            self._show(f"seq_solo{track}", seq.solo[track], lambda v, r=row: r["solo"].configure(
                fg_color=ACCENT if v else BUTTON, hover_color=ACCENT_HOVER if v else BUTTON_HOVER,
                border_color=ACCENT if v else BUTTON_EDGE, text_color="#ffffff" if v else TEXT))
        self._show("seq_grid", (seq.version, seq.position), lambda _: self._draw_steps())

    def _draw_steps(self):
        seq = self.seq
        cells = []
        for track in range(sequencer.TRACKS):
            row = []
            for step in range(sequencer.STEPS):
                on = seq.steps[track][step]
                color = colors.scale(sequencer.TRACK_COLORS[track],
                                     sequencer.velocity_level(seq.velocity[track][step])) if on else 0
                row.append((color, str(seq.velocity[track][step]) if on else ""))
            cells.append(tuple(row))
        self.step_view.show(render.step_grid(tuple(cells), seq.position, self.s, background=(255, 255, 255)))

    def _repaint_pads_soon(self):
        """Light the pattern again once the Orbit listens: it drops what arrives right after it sent a dump."""
        if self._repaint_job is not None:
            self.master.after_cancel(self._repaint_job)
        self._repaint_job = self.master.after(REPAINT_DELAY_MS, self._repaint_pads)

    def _repaint_pads(self):
        self._repaint_job = None
        if self.seq_on:
            self.seq_runner.repaint()

    def _store_seq_settings(self):
        self.seq_settings.update(pattern=self.seq.to_dict(), output=self.seq_output, clock=self.seq_clock)
        self._save_seq_settings(dict(self.seq_settings))

    def _autosave_sequencer(self, force=False):
        state = (self.seq.version, self.seq_output, self.seq_clock)
        if state == self._seq_saved:
            return
        now = self.clock()
        if self._seq_changed_at is None:
            self._seq_changed_at = now
        if force or now - self._seq_changed_at >= SEQ_SAVE_SECONDS:
            self._seq_saved = state
            self._seq_changed_at = None
            self._store_seq_settings()

    # ------------------------------------------------------------------ files
    def _file_types(self):
        return [(self.t("file_types_json"), "*.json"), (self.t("file_types_syx"), "*.syx")]

    def open_file(self):
        path = self.ask_open(filetypes=self._file_types())
        if not path:
            return
        try:
            config, bank_scales = presets.load_with_scales(path)
            self.state.set_config(config, dirty=True, bank_scales=bank_scales)
            self.show(self.t("opened", path=path), OK)
        except (ProtocolError, OSError) as e:
            self.show(self.t("error", err=e), ERROR)
        self.refresh()

    def save_file(self):
        path = self.ask_save(filetypes=self._file_types(), defaultextension=".json")
        if not path:
            return
        try:
            presets.save(path, self.state.config, self.state.scales)
            self.show(self.t("saved", path=path), OK)
        except (ProtocolError, OSError) as e:
            self.show(self.t("error", err=e), ERROR)

    def load_factory(self):
        if not self.ask_yes_no(self.t("factory_title"), self.t("factory_confirm")):
            return
        self.state.set_config(protocol.factory_config(), dirty=True)
        self.show(self.t("factory_done"))
        self.refresh()

    def on_close(self):
        self.stop_sequencer()   # gives the Orbit back the user's mapping
        self._autosave_sequencer(force=True)
        self.link.stop()   # applies any change still waiting before closing the port
        self.master.destroy()


def main(lang=None):
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk(fg_color=BG)
    _load_fonts()
    root.resizable(False, False)
    try:
        # CustomTkinter sets its own icon a moment after start; set ours after it.
        root.iconbitmap(_asset("icon.ico"))
        root.after(250, lambda: root.iconbitmap(_asset("icon.ico")))
    except tk.TclError:
        pass   # no icon file (e.g. a source checkout without assets) or a non-Windows Tk
    app = App(root, lang=lang)
    sizes = []
    for view in ("sequencer", "mapping"):   # the window fits the larger page, so it keeps its size
        app.show_view(view)
        root.update_idletasks()
        sizes.append((root.winfo_reqwidth(), root.winfo_reqheight()))
    root.wm_geometry("%dx%d" % (max(w for w, _ in sizes), max(h for _, h in sizes)))
    root.mainloop()


if __name__ == "__main__":
    main()
