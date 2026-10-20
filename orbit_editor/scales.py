"""Scale mode: lay out a bank's 16 pads for a scale and light them so the scale can be seen.

Each bank can have its own scale, and each bank lights up in its own colors.
Two layouts:
  chromatic  16 consecutive notes; scale notes lit, root in its own color, other pads off
  in_scale   the 16 pads play only scale notes; all lit, root highlighted
Pad 1 (top-left) is the lowest note, as in the Orbit's factory mapping.
"""
from dataclasses import dataclass

from .protocol import PADS_PER_BANK, ProtocolError

# (name, semitones from the root, id used in preset files)
SCALES = [
    ("Major", (0, 2, 4, 5, 7, 9, 11), "kMajor"),
    ("Dorian", (0, 2, 3, 5, 7, 9, 10), "kDorian"),
    ("Phrygian", (0, 1, 3, 5, 7, 8, 10), "kPhrygian"),
    ("Lydian", (0, 2, 4, 6, 7, 9, 11), "kLydian"),
    ("Mixolydian", (0, 2, 4, 5, 7, 9, 10), "kMixolydian"),
    ("Aeolian", (0, 2, 3, 5, 7, 8, 10), "kNaturalMinor"),
    ("Locrian", (0, 1, 3, 5, 6, 8, 10), "kLocrian"),
    ("H. Minor", (0, 2, 3, 5, 7, 8, 11), "kHarmonicMinor"),
    ("M. Minor", (0, 2, 3, 5, 7, 9, 11), "kMelodicMinor"),
    ("Blues", (0, 3, 5, 6, 7, 10), "kBlues"),
    ("Major Pent", (0, 2, 4, 7, 9), "kMajorPentatonic"),
    ("Minor Pent", (0, 3, 5, 7, 10), "kMinorPentatonic"),
    ("Major Triad", (0, 4, 7), "kMajorTriad"),
    ("Minor Triad", (0, 3, 7), "kMinorTriad"),
]
SCALE_IDS = [s[2] for s in SCALES]

LAYOUTS = ("chromatic", "in_scale")

# Per bank: (scale color, root color) as Orbit color bytes.
BANK_COLORS = (
    (3, 63),    # bank 1: blue, root white
    (12, 60),   # bank 2: green, root yellow
    (52, 48),   # bank 3: orange, root red
    (19, 51),   # bank 4: violet, root magenta
)

MIN_OCTAVE, MAX_OCTAVE = -2, 8   # octave numbering with note 36 = C1


@dataclass
class ScaleSetting:
    scale_id: str = "kMajor"
    root: int = 0            # 0 = C .. 11 = B
    octave: int = 1          # C1 = note 36
    layout: str = "chromatic"

    def validate(self):
        if self.scale_id not in SCALE_IDS:
            raise ProtocolError(f"unknown scale {self.scale_id!r}")
        if type(self.root) is not int or not 0 <= self.root <= 11:
            raise ProtocolError(f"root must be 0..11, got {self.root!r}")
        if type(self.octave) is not int or not MIN_OCTAVE <= self.octave <= MAX_OCTAVE:
            raise ProtocolError(f"octave must be {MIN_OCTAVE}..{MAX_OCTAVE}, got {self.octave!r}")
        if self.layout not in LAYOUTS:
            raise ProtocolError(f"layout must be one of {LAYOUTS}, got {self.layout!r}")

    @property
    def intervals(self):
        return SCALES[SCALE_IDS.index(self.scale_id)][1]

    @property
    def base_note(self):
        return 12 * (self.octave + 2) + self.root


def pad_notes(setting):
    """-> 16 (note, role) pairs, role being 'root', 'scale' or 'out'. Raises if a note passes 127."""
    setting.validate()
    intervals, base = setting.intervals, setting.base_note
    result = []
    for i in range(PADS_PER_BANK):
        if setting.layout == "chromatic":
            note = base + i
            step = i % 12
            role = "root" if step == 0 else ("scale" if step in intervals else "out")
        else:
            octave, degree = divmod(i, len(intervals))
            note = base + 12 * octave + intervals[degree]
            role = "root" if degree == 0 else "scale"
        if note > 127:
            raise ProtocolError(f"the scale goes past MIDI note 127 (pad {i + 1}); choose a lower octave")
        result.append((note, role))
    return result


def apply(bank, bank_index, setting):
    """Set the notes and colors of `bank`'s pads for the scale (channels and modes are kept)."""
    scale_color, root_color = BANK_COLORS[bank_index]
    colors = {"root": root_color, "scale": scale_color, "out": 0}
    for pad, (note, role) in zip(bank.pads, pad_notes(setting)):
        pad.note = note
        pad.color = colors[role]
