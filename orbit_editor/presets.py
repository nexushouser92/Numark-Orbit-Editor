"""Save and load Orbit mappings: our own readable JSON presets and raw .syx files.

JSON uses MIDI channels 1..16 (as shown to the user); the protocol model uses 0..15.
"""
import json
import os

from . import protocol
from .protocol import Axis, Bank, Knob, OrbitConfig, Pad, ProtocolError
from .scales import ScaleSetting

FORMAT_NAME = "orbit-editor-preset"
FORMAT_VERSION = 1


def to_dict(config, bank_scales=None):
    """bank_scales: optional ScaleSetting (or None) per bank, stored as an extra "scale" entry."""
    config.validate()
    banks = []
    for i, bank in enumerate(config.banks):
        entry = {
            "pads": [{"channel": p.channel + 1, "note": p.note,
                      "mode": "toggle" if p.toggle else "momentary", "color": p.color}
                     for p in bank.pads],
            "knobs": [{"channel": k.channel + 1, "cc": k.cc,
                       "mode": "relative" if k.relative else "absolute"}
                      for k in bank.knobs],
            "accelerometer": [{"channel": a.channel + 1, "cc": a.cc} for a in bank.axes],
        }
        setting = bank_scales[i] if bank_scales else None
        if setting is not None:
            setting.validate()
            entry["scale"] = {"id": setting.scale_id, "root": setting.root,
                              "octave": setting.octave, "layout": setting.layout}
        banks.append(entry)
    return {"format": FORMAT_NAME, "version": FORMAT_VERSION, "banks": banks}


def scales_from_dict(data):
    """The optional per-bank scale settings of a preset dict (None where a bank has none)."""
    result = []
    try:
        for b in data["banks"]:
            s = b.get("scale")
            if s is None:
                result.append(None)
                continue
            setting = ScaleSetting(s["id"], s["root"], s["octave"], s["layout"])
            setting.validate()
            result.append(setting)
    except (KeyError, TypeError, AttributeError) as e:
        raise ProtocolError(f"malformed scale in preset: {e!r}") from None
    return result


def from_dict(data):
    """Preset dict -> validated OrbitConfig. Raises ProtocolError on anything malformed."""
    try:
        if data.get("format") != FORMAT_NAME:
            raise ProtocolError("not an Orbit Editor preset")
        if data.get("version") != FORMAT_VERSION:
            raise ProtocolError(f"unsupported preset version {data.get('version')!r}")
        banks = []
        for b in data["banks"]:
            banks.append(Bank(
                pads=[Pad(_channel(p), p["note"], _mode(p, "toggle", "momentary"), p["color"])
                      for p in b["pads"]],
                knobs=[Knob(_channel(k), k["cc"], _mode(k, "relative", "absolute"))
                       for k in b["knobs"]],
                axes=[Axis(_channel(a), a["cc"]) for a in b["accelerometer"]],
            ))
    except (KeyError, TypeError, AttributeError) as e:
        raise ProtocolError(f"malformed preset: {e!r}") from None
    config = OrbitConfig(banks)
    config.validate()
    return config


def _channel(item):
    ch = item["channel"]
    if type(ch) is not int or not 1 <= ch <= 16:
        raise ProtocolError(f"channel must be 1..16, got {ch!r}")
    return ch - 1


def _mode(item, on, off):
    mode = item["mode"]
    if mode not in (on, off):
        raise ProtocolError(f"mode must be '{on}' or '{off}', got {mode!r}")
    return mode == on


def save_json(path, config, bank_scales=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_dict(config, bank_scales), f, indent=2, ensure_ascii=False)
        f.write("\n")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"not a valid JSON file: {e}") from None
    if not isinstance(data, dict):
        raise ProtocolError("not an Orbit Editor preset")
    return data


def load_json(path):
    return from_dict(_read_json(path))


def save_syx(path, config):
    """Write the mapping as the Orbit's own dump message (command 02), e.g. for backups."""
    with open(path, "wb") as f:
        f.write(protocol.build_dump_message(config))


def load_syx(path):
    """Read a .syx file holding one Orbit dump (02) or write (03) message."""
    with open(path, "rb") as f:
        data = f.read()
    return protocol.parse_message(data, allowed=(protocol.CMD_DUMP, protocol.CMD_WRITE))


def _kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".json", ".syx"):
        raise ProtocolError(f"unsupported file type '{ext}' (use .json or .syx)")
    return ext


def load(path):
    """Load a .json preset or a .syx dump, chosen by file extension."""
    return load_json(path) if _kind(path) == ".json" else load_syx(path)


def load_with_scales(path):
    """Like load(), plus the per-bank scale settings (a .syx file has none)."""
    if _kind(path) == ".syx":
        return load_syx(path), [None] * protocol.NUM_BANKS
    data = _read_json(path)
    return from_dict(data), scales_from_dict(data)


def save(path, config, bank_scales=None):
    """Save as a .json preset (with scales) or a .syx dump, chosen by file extension."""
    if _kind(path) == ".json":
        save_json(path, config, bank_scales)
    else:
        save_syx(path, config)
