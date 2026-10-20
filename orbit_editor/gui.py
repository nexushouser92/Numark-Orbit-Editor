"""Main window (CustomTkinter + Pillow drawings).

The Orbit stays linked while the window is open (link.py): it is found automatically, every change
is applied to it half a second after the last edit, and pads pressed on the Orbit light up on screen.
"""
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import ImageTk

from . import __version__, colors, presets, protocol, render, scales
from .editor import EditorState
from .i18n import Translator
from .link import OrbitLink
from .protocol import KNOBS_PER_BANK, NUM_BANKS, ProtocolError
from .scales import ScaleSetting

BG = "#121418"
CARD = "#1b1e24"
CARD_HI = "#262b34"
EDGE = "#333944"
TEXT = "#e9ecf1"
MUTED = "#8a93a3"
ACCENT = "#3d8bfd"
ACCENT_HOVER = "#2f6fd0"
OK = "#2fbf71"
OK_DARK = "#1d6e45"
ERROR = "#ff6159"
ACCEL_LR = "#f2c230"   # the Orbit's fixed accelerometer light colors
ACCEL_UD = "#2f7df6"
FONT = "Segoe UI"

WHEEL = 196
BAR_W, BAR_H = 300, 30
RECEIVING_SECONDS = 1.2
WRITTEN_SECONDS = 2.0
NOTE_NAMES = protocol.NOTE_NAMES


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


class Spin(ctk.CTkFrame):
    """[-] number [+]; calls on_change(int) with a value in low..high. Invalid input is put back."""

    def __init__(self, master, low, high, on_change, width=48):
        super().__init__(master, fg_color="transparent")
        self.low, self.high, self.on_change = low, high, on_change
        self.value = low
        style = dict(width=28, height=30, fg_color=CARD_HI, hover_color=EDGE, corner_radius=8)
        self.minus = ctk.CTkButton(self, text="−", command=lambda: self.step(-1), **style)
        self.entry = ctk.CTkEntry(self, width=width, height=30, justify="center", border_width=1,
                                  border_color=EDGE, fg_color=BG, corner_radius=8)
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
                 ask_save=filedialog.asksaveasfilename, clock=time.monotonic):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.t = Translator(lang)
        self.link = link or OrbitLink()
        self.ask_yes_no, self.ask_open, self.ask_save, self.clock = ask_yes_no, ask_open, ask_save, clock
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
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16, border_width=1, border_color="#232730")
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
        return ctk.CTkSegmentedButton(parent, values=values, command=command, selected_color=ACCENT,
                                      selected_hover_color=ACCENT_HOVER, unselected_color=CARD_HI,
                                      unselected_hover_color=EDGE, fg_color=CARD_HI, corner_radius=8,
                                      font=(FONT, 12), height=30, **kw)

    def _option(self, parent, values, command, width=72):
        return ctk.CTkOptionMenu(parent, values=values, command=command, width=width, height=30,
                                 fg_color=CARD_HI, button_color=CARD_HI, button_hover_color=EDGE,
                                 corner_radius=8, dynamic_resizing=False)

    def _show(self, key, value, apply):
        """Call apply(value) only if value changed since last time (prevents flicker)."""
        if self._shown.get(key, object()) != value:
            self._shown[key] = value
            apply(value)

    # ------------------------------------------------------------------ build
    def _build(self):
        t = self.t
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(16, 12))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text=t("heading"), font=(FONT, 22, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(titles, text=t("subheading"), font=(FONT, 12), text_color=MUTED).pack(anchor="w")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")
        plain = dict(height=36, fg_color=CARD_HI, hover_color=EDGE, corner_radius=10, font=(FONT, 13))
        for key, command in (("open", self.open_file), ("save", self.save_file), ("factory", self.load_factory)):
            ctk.CTkButton(actions, text=t(key), width=96, command=command, **plain).pack(side="left", padx=(0, 6))
        ctk.CTkFrame(actions, fg_color="transparent", width=6, height=1).pack(side="left")
        self.status_button = ctk.CTkButton(actions, text="", width=330, height=36, corner_radius=18,
                                           font=(FONT, 13, "bold"), command=self.on_status_click)
        self.status_button.pack(side="left")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22)

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

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=(10, 12))
        self.message = ctk.CTkLabel(footer, text="", font=(FONT, 12), text_color=MUTED, anchor="w")
        self.message.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(footer, text=f"{t('disclaimer')}   v{__version__}", font=(FONT, 11),
                     text_color="#5d6573").pack(side="right")

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
        for i, (key, color) in enumerate((("red", "#ff5a5a"), ("green", "#3ecf6a"), ("blue", "#4a90ff"))):
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=2)
            ctk.CTkLabel(row, text=t(key), font=(FONT, 12, "bold"), text_color=color, width=22).pack(side="left")
            seg = ctk.CTkSegmentedButton(row, values=["0", "1", "2", "3"], width=240, height=28,
                                         selected_color=color, selected_hover_color=color,
                                         unselected_color=CARD_HI, unselected_hover_color=EDGE, fg_color=CARD_HI,
                                         corner_radius=8, command=lambda v, i=i: self.on_component(i, int(v)))
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
            ctk.CTkButton(grid, text=t(key), height=30, fg_color=CARD_HI, hover_color=EDGE, corner_radius=8,
                          font=(FONT, 12), command=lambda a=action: self._apply(a)).grid(
                row=i // 2, column=i % 2, padx=3, pady=3, sticky="we")
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(6, 14))
        self._label(row, t("copy_bank")).pack(side="left")
        self.copy_target = self._option(row, [str(b + 1) for b in range(NUM_BANKS)], None, width=60)
        self.copy_target.pack(side="left", padx=6)
        ctk.CTkButton(row, text=t("copy"), width=80, height=30, fg_color=CARD_HI, hover_color=EDGE,
                      corner_radius=8, command=self.on_copy_bank).pack(side="left")

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
            button.configure(border_width=3 if v == hue else 0, border_color="#ffffff")
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
        self.scale_dot.configure(text_color=_hex(render.screen_rgb(scale_color)))
        self.root_dot.configure(text_color=_hex(render.screen_rgb(root_color)))
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
            self._pushed = self.state.config
            self._failed = False
            self.link.push(self.state.config)

    def _poll(self):
        self.process_link_events()
        self.after(40, self._poll)

    def process_link_events(self):
        changed = False
        while not self.link.events.empty():
            kind, payload = self.link.events.get_nowait()
            changed = True
            if kind == "config":
                self.state.set_config(payload, dirty=False)
                self._pushed = self.state.config
                self.show(self.t("read_ok"), OK)
            elif kind == "writing":
                self._writing = True
            elif kind == "written":
                self._writing, self._failed = False, False
                self._written_at = self.clock()
            elif kind == "write_failed":
                self._writing, self._failed = False, True
                from .device import VerifyError
                self.show(self.t("verify_error") if isinstance(payload, VerifyError)
                          else self.t("write_error", err=payload), ERROR)
            elif kind == "searching":
                self._writing = False
                self.pressed.clear()
            elif kind == "midi":
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
            return "status_searching", CARD_HI, MUTED
        if self._failed:
            return "status_failed", "#5c2422", "#ffd6d3"
        if self._writing or self.link.has_pending:
            return "status_writing", ACCENT, "#ffffff"
        if now - self._last_midi < RECEIVING_SECONDS:
            return "status_receiving", OK, "#ffffff"
        if now - self._written_at < WRITTEN_SECONDS:
            return "status_written", OK, "#ffffff"
        return "status_linked", OK_DARK, "#ffffff"

    def _draw_status(self):
        key, bg, fg = self._status()
        self._show("status", key, lambda _: self.status_button.configure(
            text=self.t(key), fg_color=bg, hover_color=bg, text_color=fg))

    def on_status_click(self):
        """Apply the mapping again (e.g. after an error)."""
        if self.link.linked:
            self._failed = False
            self.link.push(self.state.config)
            self.link.flush()
            self._draw_status()

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
        self.link.stop()   # applies any change still waiting before closing the port
        self.master.destroy()


def main(lang=None):
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk(fg_color=BG)
    root.resizable(False, False)
    App(root, lang=lang)
    root.mainloop()


if __name__ == "__main__":
    main()
