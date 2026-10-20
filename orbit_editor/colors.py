"""Orbit pad LED colors: one byte, 2 bits (intensity 0..3) per component, value = R*16 + G*4 + B."""
from .protocol import MAX_COLOR

# The colors offered to the user, in menu order: (value, Spanish name, English name).
PALETTE = (
    (0, "Apagado", "Off"),
    (63, "Blanco", "White"),
    (48, "Rojo", "Red"),
    (52, "Naranja", "Orange"),
    (60, "Amarillo", "Yellow"),
    (44, "Lima", "Lime"),
    (12, "Verde", "Green"),
    (15, "Cian", "Cyan"),
    (3, "Azul", "Blue"),
    (19, "Violeta", "Violet"),
    (51, "Magenta", "Magenta"),
    (49, "Rosa", "Pink"),
)

# Screen brightness for each 2-bit intensity; off is drawn dark grey so the pad stays visible.
_LEVELS = (0x00, 0x60, 0xB0, 0xFF)
OFF_HEX = "#3a3a3a"


def components(value):
    """Color byte -> (red, green, blue), each 0..3."""
    if type(value) is not int or not 0 <= value <= MAX_COLOR:
        raise ValueError(f"color must be an integer in 0..{MAX_COLOR}, got {value!r}")
    return (value >> 4) & 3, (value >> 2) & 3, value & 3


def from_components(red, green, blue):
    """(red, green, blue), each 0..3 -> color byte."""
    for c in (red, green, blue):
        if type(c) is not int or not 0 <= c <= 3:
            raise ValueError(f"each component must be an integer in 0..3, got {c!r}")
    return red * 16 + green * 4 + blue


def to_hex(value):
    """Color byte -> '#rrggbb' for drawing the pad on screen."""
    if value == 0:
        components(value)
        return OFF_HEX
    return "#" + "".join(f"{_LEVELS[c]:02x}" for c in components(value))


LEVELS = (1, 2, 3)  # low, medium, high: confirmed on a real Orbit to be clearly distinct (2026-10-19)


def brightness(value):
    """Color byte -> brightness level 0..3 (its strongest component)."""
    return max(components(value))


def scale(value, level):
    """Same hue at brightness level 0..3; components that are on stay at least at 1."""
    if level not in (0,) + LEVELS:
        raise ValueError(f"level must be 0..3, got {level!r}")
    comps = components(value)
    top = max(comps)
    if top == 0 or level == 0:
        return 0
    return from_components(*(0 if c == 0 else max(1, int(c * level / top + 0.5)) for c in comps))


def split(value):
    """Color byte -> (palette color it comes from or None, brightness level).

    A dimmed palette color is recognised, e.g. 16 -> (48 red, 1). Some dim colors are shared by two
    palette entries; the first one in PALETTE wins.
    """
    level = brightness(value)
    if level == 0:
        return 0, 0
    for hue, _, _ in PALETTE:
        if hue and scale(hue, level) == value:
            return hue, level
    return None, level


def name(value, lang="es"):
    """Color byte -> palette name in 'es' or 'en', or a generic 'R G B' label for other values."""
    for v, es, en in PALETTE:
        if v == value:
            return es if lang == "es" else en
    r, g, b = components(value)
    return f"RGB {r}-{g}-{b}"
