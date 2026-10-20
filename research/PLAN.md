# Orbit Editor (no oficial) — arquitectura y plan por fases

> **Estado (2026-10-20):** las fases 0–5 están hechas. Este documento es el plan inicial. Desde
> entonces la interfaz pasó a CustomTkinter + Pillow, la app se vincula sola al Orbit (`link.py`) y
> aplica cada cambio en vivo sin copia de seguridad ni confirmación, y se añadió el modo escalas. Las
> funciones actuales están en el [README](../README.md).

## Arquitectura propuesta

Igual que tus otros proyectos: **Python + tkinter**, compilado con **PyInstaller**, sin dependencias
externas en Windows (MIDI por `winmm` vía `ctypes`, como Exit-Demo-Mode).

```
Orbit-Editor/
├─ orbit_editor/
│  ├─ protocol.py   # Puro, sin MIDI: clases Pad/Knob/Accel/Config, codificar y
│  │                #   decodificar los 249 bytes, validar rangos, config de fábrica
│  ├─ colors.py     # Paleta (R×16+G×4+B) y nombres ES/EN
│  ├─ midi_win.py   # winmm/ctypes: buscar puerto "ORBIT", enviar y recibir SysEx largo
│  ├─ device.py     # leer_config() y escribir_config(verificar=True): petición 01,
│  │                #   espera respuesta, escribe 03, relee y compara; tiempos de espera
│  ├─ presets.py    # Guardar/abrir presets en JSON propio + importar/exportar .syx
│  ├─ i18n.py       # Textos español/inglés según el idioma de Windows
│  └─ gui.py        # Ventana tkinter
├─ tests/           # Sin hardware: MIDI simulado que imita al Orbit
├─ .github/workflows/release.yml   # Compila .exe, publica release con SHA256.txt
├─ LICENSE (MIT)  README.md
└─ research/        # Estas notas
```

### Ventana (idea)

- Arriba: estado de conexión ("Orbit detectado" / "no encontrado") y botones **Leer del Orbit**,
  **Enviar al Orbit**, **Abrir preset**, **Guardar preset**, **Restaurar fábrica**.
- Pestañas **Banco 1–4**. En cada una: rejilla 4×4 de pads pintados con su color; al pulsar un pad se
  editan canal, nota (con nombre, p. ej. C1), modo momentáneo/toggle y color.
- Panel de **knobs 1–4** (canal, CC, absoluto/relativo) y **acelerómetro** (canal y CC de cada eje).
- Ayudas: "aplicar a todos los pads" en orden ascendente o con el mismo valor; copiar un banco a otro.
- Antes de enviar: copia de seguridad automática de la configuración actual del Orbit (.syx con fecha).
  Tras enviar: relectura y mensaje "Enviado y verificado" o el error.

### Seguridad

- La app nunca envía comandos distintos de 01 (leer) y 03 (escribir), y el 03 siempre con un bloque
  completo y validado (todos los bytes 0–127, canales 0–15, colores 0–63).
- Siempre se hace copia de seguridad antes de escribir.

## Plan por fases

| Fase | Contenido | Necesita tu permiso |
|---|---|---|
| 0 ✅ | Investigación del protocolo (este documento) | — |
| 1 | Pruebas con el Orbit: (a) leer y guardar el volcado actual; (b) reenviar el mismo volcado y verificar; (c) cambiar solo el color de un pad, comprobarlo y restaurar; (d) repetir lectura por el receptor inalámbrico | Sí, en (a) y antes de cada escritura |
| 2 | `protocol.py`, `colors.py`, `presets.py` + tests (ida y vuelta de bytes, fábrica, validación) | No |
| 3 | `midi_win.py` + `device.py` + herramienta de consola (leer / copia de seguridad / escribir) y tests con MIDI simulado | Para probar escrituras reales |
| 4 | Interfaz tkinter completa, ES/EN | No |
| 5 | README, licencia MIT, GitHub Actions con .exe y SHA256.txt, repo en GitHub | Sí, para crear el repo |
| 6 | Extras opcionales: versión Linux (mido + python-rtmidi), importar presets JSON del editor oficial (solo leer el formato) | — |
