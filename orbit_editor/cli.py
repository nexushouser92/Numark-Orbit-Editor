"""Command-line tool: python -m orbit_editor <comando>

  puertos                     list MIDI ports and say which one is the Orbit
  leer [-o archivo]           read the Orbit's mapping, show it, optionally save it (.json/.syx)
  copia [--carpeta DIR]       read the Orbit and save a dated .syx backup
  ver ARCHIVO                 show a saved mapping
  convertir ENTRADA SALIDA    convert between .json and .syx
  escribir ARCHIVO            back up the Orbit, send the mapping and verify it (asks first)
"""
import argparse
import os
import sys
from datetime import datetime

from . import colors, device, midi_win, presets, protocol
from .protocol import ProtocolError

CONFIRM_WORD = "SI"


def format_config(config):
    lines = []
    for b, bank in enumerate(config.banks, 1):
        lines.append(f"=== Banco {b} ===")
        for p, pad in enumerate(bank.pads, 1):
            mode = "toggle" if pad.toggle else "momentáneo"
            name = f"({protocol.note_name(pad.note)})"
            lines.append(f"  Pad {p:2}: canal {pad.channel + 1:2}  nota {pad.note:3} "
                         f"{name:6}  {mode:10}  color {colors.name(pad.color)}")
        for k, knob in enumerate(bank.knobs, 1):
            mode = "relativo" if knob.relative else "absoluto"
            lines.append(f"  Knob {k}: canal {knob.channel + 1:2}  CC {knob.cc:3}  {mode}")
        for name, axis in zip(("izq-der", "arriba-abajo"), bank.axes):
            lines.append(f"  Acelerómetro {name}: canal {axis.channel + 1:2}  CC {axis.cc:3}")
    return "\n".join(lines)


def _backup_path(folder, now):
    return os.path.join(folder, f"Orbit_copia_{now():%Y%m%d_%H%M%S}.syx")


def main(argv=None, opener=midi_win.open_orbit, lister=midi_win.list_ports,
         ask=input, out=print, now=datetime.now):
    parser = argparse.ArgumentParser(prog="orbit_editor",
                                     description="Editor no oficial del mapeo MIDI del Numark Orbit.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("puertos", help="lista los puertos MIDI")
    p = sub.add_parser("leer", help="lee el mapeo actual del Orbit")
    p.add_argument("-o", "--salida", help="guardar en .json o .syx")
    p = sub.add_parser("copia", help="guarda una copia de seguridad .syx del Orbit")
    p.add_argument("--carpeta", default="copias", help="carpeta de destino (por defecto: copias)")
    p = sub.add_parser("ver", help="muestra un archivo .json o .syx")
    p.add_argument("archivo")
    p = sub.add_parser("convertir", help="convierte entre .json y .syx")
    p.add_argument("entrada")
    p.add_argument("salida")
    p = sub.add_parser("escribir", help="envía un mapeo al Orbit (pide confirmación)")
    p.add_argument("archivo")
    p.add_argument("--carpeta", default="copias", help="carpeta para la copia de seguridad previa")
    p.add_argument("--si", action="store_true", help="no pedir confirmación")
    p.add_argument("--sin-verificar", action="store_true", help="no releer el Orbit tras enviar")
    p.add_argument("--simular", action="store_true",
                   help="solo muestra los bytes que se enviarían; no abre el puerto MIDI")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "puertos":
            ins, outs = lister()
            for label, names in (("Entradas", ins), ("Salidas", outs)):
                out(f"{label}:")
                orbit = midi_win.find_port(names)
                for i, name in enumerate(names):
                    out(f"  {i}: {name}" + ("   <- Orbit" if i == orbit else ""))
            return 0

        if args.cmd == "ver":
            out(format_config(presets.load(args.archivo)))
            return 0

        if args.cmd == "convertir":
            presets.save(args.salida, presets.load(args.entrada))
            out(f"Guardado: {args.salida}")
            return 0

        if args.cmd == "escribir":
            config = presets.load(args.archivo)
            message = protocol.build_write_message(config)
            if args.simular:
                out(f"Se enviarían {len(message)} bytes:")
                out(message.hex(" ").upper())
                return 0

        with opener() as port:
            if args.cmd == "leer":
                config = device.read_config(port)
                out(format_config(config))
                if args.salida:
                    presets.save(args.salida, config)
                    out(f"Guardado: {args.salida}")
                return 0

            if args.cmd == "copia":
                os.makedirs(args.carpeta, exist_ok=True)
                path = _backup_path(args.carpeta, now)
                presets.save_syx(path, device.read_config(port))
                out(f"Copia de seguridad guardada: {path}")
                return 0

            # escribir: always back up the current mapping first
            os.makedirs(args.carpeta, exist_ok=True)
            backup = _backup_path(args.carpeta, now)
            presets.save_syx(backup, device.read_config(port))
            out(f"Copia de seguridad del mapeo actual: {backup}")
            if not args.si:
                answer = ask(f"Se va a sobrescribir el mapeo del Orbit con '{args.archivo}'. "
                             f"Escribe {CONFIRM_WORD} para continuar: ")
                if answer.strip().upper() not in (CONFIRM_WORD, "SÍ"):
                    out("Cancelado. No se ha enviado nada.")
                    return 1
            device.write_config(port, config, verify=not args.sin_verificar)
            out("Mapeo enviado." if args.sin_verificar else "Mapeo enviado y verificado.")
            return 0

    except device.VerifyError:
        out("ERROR: el Orbit devolvió un mapeo distinto del enviado. "
            "Puedes restaurar la copia de seguridad con 'escribir'.")
        return 2
    except (ProtocolError, device.DeviceError, midi_win.MidiError, OSError) as e:
        out(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
