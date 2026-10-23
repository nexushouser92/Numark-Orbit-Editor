"""Anti-aliased drawings for the window, made with Pillow: pad grid, color wheel, brightness bar.

Everything is drawn SUPERSAMPLE times larger and scaled down, which gives smooth edges
(tkinter's own canvas does not anti-alias on Windows).
"""
import colorsys
import functools
import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import colors, protocol

SUPERSAMPLE = 3

# macOS light look, as in the nanoKONTROL 2 editor.
PANEL = (245, 245, 247)
PANEL_EDGE = (217, 217, 217)
PAD_OFF = (226, 226, 230)
SELECTED = (0, 122, 255)        # system blue
PRESSED = (255, 149, 0)         # system orange, the color of what the hardware lights
MUTED = (128, 128, 128)

# Pad grid geometry in logical pixels (multiplied by the screen scaling).
PAD = 104
GAP = 12
MARGIN = 20
RADIUS = 14
GRID = 2 * MARGIN + 4 * PAD + 3 * GAP


@functools.lru_cache(maxsize=32)
def _font(size, bold=False):
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def screen_rgb(value):
    """Orbit color byte -> (r, g, b) for the screen. Off pads are drawn grey."""
    if value == 0:
        return PAD_OFF
    hex_color = colors.to_hex(value)
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _text_fill(rgb):
    r, g, b = rgb
    return (17, 17, 17) if r * 0.299 + g * 0.587 + b * 0.114 > 140 else (255, 255, 255)


def pad_rect(index, scale=1.0):
    """(x1, y1, x2, y2) of pad `index` in the final (scaled) grid image."""
    row, col = divmod(index, 4)
    x1 = (MARGIN + col * (PAD + GAP)) * scale
    y1 = (MARGIN + row * (PAD + GAP)) * scale
    return x1, y1, x1 + PAD * scale, y1 + PAD * scale


def pad_at(x, y, scale=1.0):
    """Pad index under a click at (x, y) in the final image, or None."""
    for i in range(protocol.PADS_PER_BANK):
        x1, y1, x2, y2 = pad_rect(i, scale)
        if x1 <= x <= x2 and y1 <= y <= y2:
            return i
    return None


TILE_PAD = 8   # room around a pad for the selection ring


@functools.lru_cache(maxsize=4)
def _panel(scale):
    k = scale * SUPERSAMPLE
    size = int(GRID * k)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(22 * k), fill=PANEL,
                                          outline=PANEL_EDGE, width=max(1, int(1.5 * k)))
    return img.resize((int(GRID * scale), int(GRID * scale)), Image.LANCZOS)


@functools.lru_cache(maxsize=512)
def _tile(color, note, number, selected, pressed, scale):
    """One pad (with room for its selection ring), drawn large and scaled down."""
    k = scale * SUPERSAMPLE
    side = PAD + 2 * TILE_PAD
    img = Image.new("RGBA", (int(side * k), int(side * k)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x1 = y1 = TILE_PAD * k
    x2 = y2 = (TILE_PAD + PAD) * k
    rgb = screen_rgb(color)
    if selected:
        o = 5 * k
        draw.rounded_rectangle((x1 - o, y1 - o, x2 + o, y2 + o), radius=int((RADIUS + 5) * k),
                               outline=SELECTED, width=max(2, int(2.5 * k)))
    if pressed:  # lit brighter while the pad is held down on the Orbit
        rgb = tuple(min(255, int(c + (255 - c) * 0.55)) for c in rgb)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=int(RADIUS * k), fill=rgb)
    if pressed:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=int(RADIUS * k), outline=PRESSED,
                               width=max(3, int(4 * k)))
    fg = _text_fill(rgb)
    draw.text((x1 + 10 * k, y1 + 7 * k), str(number), font=_font(int(11 * k)), fill=fg)
    draw.text(((x1 + x2) / 2, (y1 + y2) / 2 + 4 * k), protocol.note_name(note),
              font=_font(int(17 * k), bold=True), fill=fg, anchor="mm")
    draw.text(((x1 + x2) / 2, y2 - 14 * k), str(note), font=_font(int(11 * k)), fill=fg, anchor="mm")
    return img.resize((int(side * scale), int(side * scale)), Image.LANCZOS)


def pad_grid(pads, selected=None, pressed=(), scale=1.0):
    """Image of the 16 pads of one bank, colored as on the Orbit."""
    size = int(GRID * scale)
    img = _panel(scale).copy()
    # Soft glow under lit pads.
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for i, pad in enumerate(pads):
        if pad.color:
            glow_draw.rounded_rectangle(pad_rect(i, scale), radius=int(RADIUS * scale),
                                        fill=screen_rgb(pad.color) + (110,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9 * scale)))
    for i, pad in enumerate(pads):
        tile = _tile(pad.color, pad.note, i + 1, i == selected, i in pressed, scale)
        x1, y1, _, _ = pad_rect(i, scale)
        img.alpha_composite(tile, (int(round(x1 - TILE_PAD * scale)), int(round(y1 - TILE_PAD * scale))))
    return img


# Sequencer step grid geometry in logical pixels: 4 tracks x 16 steps, steps grouped by 4,
# with the step numbers above them.
STEP = 44
STEP_GAP = 5
STEP_GROUP_GAP = 10
STEP_ROW = 56
STEP_RADIUS = 10
STEP_NUMBERS = 24               # height of the step-number row
STEPS_W = 15 * (STEP + STEP_GAP) + 3 * STEP_GROUP_GAP + STEP
STEPS_H = STEP_NUMBERS + 3 * STEP_ROW + STEP
PLAYHEAD = PRESSED


def step_rect(track, step, scale=1.0):
    """(x1, y1, x2, y2) of a step cell in the final (scaled) step grid image."""
    x1 = (step * (STEP + STEP_GAP) + (step // 4) * STEP_GROUP_GAP) * scale
    y1 = (STEP_NUMBERS + track * STEP_ROW) * scale
    return x1, y1, x1 + STEP * scale, y1 + STEP * scale


def step_at(x, y, scale=1.0):
    """(track, step) under a click at (x, y) in the final image (which has a TILE_PAD margin), or None."""
    x, y = x - TILE_PAD * scale, y - TILE_PAD * scale
    for track in range(protocol.NUM_BANKS):
        for step in range(protocol.PADS_PER_BANK):
            x1, y1, x2, y2 = step_rect(track, step, scale)
            if x1 <= x <= x2 and y1 <= y <= y2:
                return track, step
    return None


@functools.lru_cache(maxsize=512)
def _step_tile(color, label, playhead, scale):
    """One step cell, drawn large and scaled down; the playhead is a white ring."""
    k = scale * SUPERSAMPLE
    side = STEP + 2 * TILE_PAD
    img = Image.new("RGBA", (int(side * k), int(side * k)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x1 = y1 = TILE_PAD * k
    x2 = y2 = (TILE_PAD + STEP) * k
    rgb = screen_rgb(color)
    if playhead:
        o = 4 * k
        draw.rounded_rectangle((x1 - o, y1 - o, x2 + o, y2 + o), radius=int((STEP_RADIUS + 4) * k),
                               outline=PLAYHEAD, width=max(2, int(2.5 * k)))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=int(STEP_RADIUS * k), fill=rgb)
    if label:
        draw.text(((x1 + x2) / 2, (y1 + y2) / 2), label, font=_font(int(11 * k), bold=True),
                  fill=_text_fill(rgb), anchor="mm")
    return img.resize((int(side * scale), int(side * scale)), Image.LANCZOS)


@functools.lru_cache(maxsize=40)
def _step_numbers(position, scale, background):
    """The 1-16 row above the steps; the playing step's number in the playhead color."""
    k = scale * SUPERSAMPLE
    img = Image.new("RGBA", (int(STEPS_W * k), int(STEP_NUMBERS * k)), background + (0,))
    draw = ImageDraw.Draw(img)
    for step in range(protocol.PADS_PER_BANK):
        x1, _, x2, _ = step_rect(0, step, k)
        draw.text(((x1 + x2) / 2, STEP_NUMBERS * k * 0.45), str(step + 1),
                  font=_font(int(12 * k), bold=step == position or step % 4 == 0),
                  fill=PLAYHEAD if step == position else MUTED, anchor="mm")
    return img.resize((int(STEPS_W * scale), int(STEP_NUMBERS * scale)), Image.LANCZOS)


def step_grid(cells, position=-1, scale=1.0, background=PANEL):
    """Image of the sequencer: cells[track][step] = (Orbit color byte, label); `position` is the playhead."""
    pad = TILE_PAD * scale
    img = Image.new("RGBA", (int(STEPS_W * scale + 2 * pad), int(STEPS_H * scale + 2 * pad)),
                    background + (255,))
    numbers = _step_numbers(position, scale, background)
    img.alpha_composite(numbers, (int(round(pad)), int(round(pad))))
    for track, row in enumerate(cells):
        for step, (color, label) in enumerate(row):
            tile = _step_tile(color, label, step == position, scale)
            x1, y1, _, _ = step_rect(track, step, scale)
            img.alpha_composite(tile, (int(round(x1)), int(round(y1))))
    return img


def color_wheel(diameter):
    """Hue (angle) / saturation (distance) wheel at full brightness, with a smooth round edge."""
    d = int(diameter)
    img = Image.new("RGB", (d, d))
    r = d / 2
    pixels = []
    for y in range(d):
        for x in range(d):
            dx, dy = x + 0.5 - r, y + 0.5 - r
            h, s = wheel_hs(dx, dy, r)
            rr, gg, bb = colorsys.hsv_to_rgb(h, min(s, 1.0), 1.0)
            pixels.append((int(rr * 255), int(gg * 255), int(bb * 255)))
    img.putdata(pixels)
    mask = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask.resize((d, d), Image.LANCZOS))
    return out


def wheel_hs(dx, dy, radius):
    """Offset from the wheel center -> (hue 0..1, saturation 0..; above 1 is outside the wheel)."""
    hue = (math.atan2(-dy, dx) / (2 * math.pi)) % 1.0
    return hue, math.hypot(dx, dy) / radius


def wheel_position(value, radius):
    """Where an Orbit color sits on the wheel, as an offset from its center (dx, dy)."""
    comps = colors.components(value)
    top = max(comps)
    if top == 0:
        return 0.0, 0.0
    h, s, _ = colorsys.rgb_to_hsv(*(c / top for c in comps))
    angle = h * 2 * math.pi
    return math.cos(angle) * s * radius, -math.sin(angle) * s * radius


def color_from_wheel(dx, dy, radius, level):
    """A point on the wheel -> nearest Orbit color byte at brightness `level` (1..3)."""
    hue, sat = wheel_hs(dx, dy, radius)
    rgb = colorsys.hsv_to_rgb(hue, min(sat, 1.0), 1.0)
    full = colors.from_components(*(int(c * 3 + 0.5) for c in rgb))
    return colors.scale(full, level)


def marker(diameter):
    """Small ring used to show the picked point on the wheel."""
    d = int(diameter) * 4
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, d - 3, d - 3), outline=(0, 0, 0, 160), width=max(2, d // 7))
    draw.ellipse((d // 9, d // 9, d - d // 9, d - d // 9), outline=(255, 255, 255, 255), width=max(2, d // 9))
    return img.resize((int(diameter), int(diameter)), Image.LANCZOS)


BAR_STOPS = (1 / 6, 1 / 2, 5 / 6)   # where low, medium and high sit along the brightness bar


def brightness_bar(width, height, value, level, scale=1.0):
    """Rounded black-to-color bar with a handle on the chosen brightness (level 1..3, 0 = off)."""
    k = scale * SUPERSAMPLE
    w, h = int(width * k), int(height * k)
    top = colors.scale(value, 3) if value else 0
    end = screen_rgb(top) if top else (90, 94, 102)
    bar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    grad = Image.new("RGB", (w, 1))
    grad.putdata([tuple(int(c * x / max(1, w - 1)) for c in end) for x in range(w)])
    grad = grad.resize((w, h))
    mask = Image.new("L", (w, h), 0)
    track = int(h * 0.55)
    y0 = (h - track) // 2
    ImageDraw.Draw(mask).rounded_rectangle((0, y0, w - 1, y0 + track), radius=track // 2, fill=255)
    bar.paste(grad, (0, 0), mask)
    draw = ImageDraw.Draw(bar)
    for stop in BAR_STOPS:
        cx = stop * w
        draw.ellipse((cx - 2 * k, h / 2 - 2 * k, cx + 2 * k, h / 2 + 2 * k), fill=(255, 255, 255, 120))
    if level:
        cx = BAR_STOPS[level - 1] * w
        rad = h / 2 - 1
        fill = screen_rgb(value) if value else end
        draw.ellipse((cx - rad, 1, cx + rad, h - 2), fill=fill, outline=(255, 255, 255), width=max(2, int(2.5 * k)))
    return bar.resize((int(width * scale), int(height * scale)), Image.LANCZOS)


def level_at(x, width):
    """Click position along the brightness bar -> nearest level 1..3."""
    pos = x / width
    return min(range(3), key=lambda i: abs(BAR_STOPS[i] - pos)) + 1
