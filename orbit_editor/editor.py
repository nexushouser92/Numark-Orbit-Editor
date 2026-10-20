"""Editing state behind the window, without any tkinter code so it can be tested on its own.

Every change is applied to a copy and validated first, so an invalid value never reaches the mapping.
"""
import copy

from . import scales
from .protocol import NUM_BANKS, PADS_PER_BANK, ProtocolError, factory_config


class EditorState:
    def __init__(self, config=None):
        self.config = config or factory_config()
        self.bank = 0   # 0..3
        self.pad = 0    # 0..15
        self.dirty = False
        self.scales = [None] * NUM_BANKS   # ScaleSetting per bank, or None

    @property
    def current_bank(self):
        return self.config.banks[self.bank]

    @property
    def current_pad(self):
        return self.current_bank.pads[self.pad]

    def set_config(self, config, dirty=False, bank_scales=None):
        config.validate()
        for setting in bank_scales or ():
            if setting is not None:
                setting.validate()
        self.config = config
        self.dirty = dirty
        self.scales = list(bank_scales) if bank_scales else [None] * NUM_BANKS

    def apply_scale(self, setting):
        """Lay out and light the current bank for a scale; None turns scale mode off for the bank."""
        if setting is None:
            self.scales[self.bank] = None
            return
        setting.validate()
        self._change(lambda config: scales.apply(config.banks[self.bank], self.bank, setting))
        self.scales[self.bank] = copy.copy(setting)

    def select(self, bank=None, pad=None):
        if bank is not None:
            if not 0 <= bank < NUM_BANKS:
                raise ProtocolError(f"bank index {bank} out of range")
            self.bank = bank
        if pad is not None:
            if not 0 <= pad < PADS_PER_BANK:
                raise ProtocolError(f"pad index {pad} out of range")
            self.pad = pad

    def _change(self, edit):
        """Run edit(config copy); keep the result only if it is still a valid mapping."""
        new = copy.deepcopy(self.config)
        edit(new)
        new.validate()
        if new != self.config:
            self.config = new
            self.dirty = True

    def update_pad(self, **fields):
        def edit(config):
            pad = config.banks[self.bank].pads[self.pad]
            for name, value in fields.items():
                _set(pad, name, value)
        self._change(edit)

    def update_knob(self, index, **fields):
        def edit(config):
            knob = config.banks[self.bank].knobs[index]
            for name, value in fields.items():
                _set(knob, name, value)
        self._change(edit)

    def update_axis(self, index, **fields):
        def edit(config):
            axis = config.banks[self.bank].axes[index]
            for name, value in fields.items():
                _set(axis, name, value)
        self._change(edit)

    def ascending_notes(self):
        """From the selected pad to pad 16, each pad gets the previous pad's note + 1."""
        start = self.current_pad.note

        def edit(config):
            for i, pad in enumerate(config.banks[self.bank].pads[self.pad:]):
                pad.note = start + i
        self._change(edit)

    def channel_to_bank(self):
        """Give the selected pad's channel to every pad, knob and accelerometer axis of the bank."""
        channel = self.current_pad.channel

        def edit(config):
            bank = config.banks[self.bank]
            for item in bank.pads + bank.knobs + bank.axes:
                item.channel = channel
        self._change(edit)

    def color_to_bank(self):
        color = self.current_pad.color

        def edit(config):
            for pad in config.banks[self.bank].pads:
                pad.color = color
        self._change(edit)

    def mode_to_bank(self):
        toggle = self.current_pad.toggle

        def edit(config):
            for pad in config.banks[self.bank].pads:
                pad.toggle = toggle
        self._change(edit)

    def copy_bank(self, target):
        if not 0 <= target < NUM_BANKS:
            raise ProtocolError(f"bank index {target} out of range")

        setting = self.scales[self.bank]

        def edit(config):
            config.banks[target] = copy.deepcopy(config.banks[self.bank])
            if setting is not None:  # a scale keeps the target bank's own colors
                scales.apply(config.banks[target], target, setting)
        self._change(edit)
        self.scales[target] = copy.copy(setting)


def _set(item, name, value):
    if not hasattr(item, name):
        raise AttributeError(f"{type(item).__name__} has no field '{name}'")
    setattr(item, name, value)
