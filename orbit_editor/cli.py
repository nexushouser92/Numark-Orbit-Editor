"""Command-line tool: python -m orbit_editor <command>

  ports                      list MIDI ports and say which one is the Orbit
  read [-o FILE]             read the Orbit's mapping, show it, optionally save it (.json/.syx)
  backup [--folder DIR]      read the Orbit and save a dated .syx backup
  show FILE                  show a saved mapping
  convert INPUT OUTPUT       convert between .json and .syx
  write FILE                 back up the Orbit, send the mapping and verify it (asks first)
"""
import argparse
import os
import sys
from datetime import datetime

from . import colors, device, midi_win, presets, protocol
from .protocol import ProtocolError

CONFIRM_WORD = "YES"


def format_config(config):
    lines = []
    for b, bank in enumerate(config.banks, 1):
        lines.append(f"=== Bank {b} ===")
        for p, pad in enumerate(bank.pads, 1):
            mode = "toggle" if pad.toggle else "momentary"
            name = f"({protocol.note_name(pad.note)})"
            lines.append(f"  Pad {p:2}: channel {pad.channel + 1:2}  note {pad.note:3} "
                         f"{name:6}  {mode:9}  color {colors.name(pad.color, 'en')}")
        for k, knob in enumerate(bank.knobs, 1):
            mode = "relative" if knob.relative else "absolute"
            lines.append(f"  Knob {k}: channel {knob.channel + 1:2}  CC {knob.cc:3}  {mode}")
        for name, axis in zip(("left-right", "up-down"), bank.axes):
            lines.append(f"  Accelerometer {name}: channel {axis.channel + 1:2}  CC {axis.cc:3}")
    return "\n".join(lines)


def _backup_path(folder, now):
    return os.path.join(folder, f"Orbit_backup_{now():%Y%m%d_%H%M%S}.syx")


def main(argv=None, opener=midi_win.open_orbit, lister=midi_win.list_ports,
         ask=input, out=print, now=datetime.now):
    parser = argparse.ArgumentParser(prog="orbit_editor",
                                     description="Unofficial MIDI mapping editor for the Numark Orbit.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list the MIDI ports")
    p = sub.add_parser("read", help="read the Orbit's current mapping")
    p.add_argument("-o", "--output", help="save it as .json or .syx")
    p = sub.add_parser("backup", help="save a .syx backup of the Orbit's mapping")
    p.add_argument("--folder", default="backups", help="destination folder (default: backups)")
    p = sub.add_parser("show", help="show a .json or .syx file")
    p.add_argument("file")
    p = sub.add_parser("convert", help="convert between .json and .syx")
    p.add_argument("input")
    p.add_argument("output")
    p = sub.add_parser("write", help="send a mapping to the Orbit (asks first)")
    p.add_argument("file")
    p.add_argument("--folder", default="backups", help="folder for the backup made before writing")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--no-verify", action="store_true", help="do not read the Orbit back after writing")
    p.add_argument("--dry-run", action="store_true",
                   help="only show the bytes that would be sent; the MIDI port is not opened")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "ports":
            ins, outs = lister()
            for label, names in (("Inputs", ins), ("Outputs", outs)):
                out(f"{label}:")
                orbit = midi_win.find_port(names)
                for i, name in enumerate(names):
                    out(f"  {i}: {name}" + ("   <- Orbit" if i == orbit else ""))
            return 0

        if args.cmd == "show":
            out(format_config(presets.load(args.file)))
            return 0

        if args.cmd == "convert":
            presets.save(args.output, presets.load(args.input))
            out(f"Saved: {args.output}")
            return 0

        if args.cmd == "write":
            config = presets.load(args.file)
            message = protocol.build_write_message(config)
            if args.dry_run:
                out(f"Would send {len(message)} bytes:")
                out(message.hex(" ").upper())
                return 0

        with opener() as port:
            if args.cmd == "read":
                config = device.read_config(port)
                out(format_config(config))
                if args.output:
                    presets.save(args.output, config)
                    out(f"Saved: {args.output}")
                return 0

            if args.cmd == "backup":
                os.makedirs(args.folder, exist_ok=True)
                path = _backup_path(args.folder, now)
                presets.save_syx(path, device.read_config(port))
                out(f"Backup saved: {path}")
                return 0

            # write: always back up the current mapping first
            os.makedirs(args.folder, exist_ok=True)
            backup = _backup_path(args.folder, now)
            presets.save_syx(backup, device.read_config(port))
            out(f"Backup of the current mapping: {backup}")
            if not args.yes:
                answer = ask(f"This overwrites the Orbit's mapping with '{args.file}'. "
                             f"Type {CONFIRM_WORD} to continue: ")
                if answer.strip().upper() != CONFIRM_WORD:
                    out("Cancelled. Nothing was sent.")
                    return 1
            device.write_config(port, config, verify=not args.no_verify)
            out("Mapping sent." if args.no_verify else "Mapping sent and verified.")
            return 0

    except device.VerifyError:
        out("ERROR: the Orbit reported a different mapping from the one sent. "
            "You can restore the backup with 'write'.")
        return 2
    except (ProtocolError, device.DeviceError, midi_win.MidiError, OSError) as e:
        out(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
