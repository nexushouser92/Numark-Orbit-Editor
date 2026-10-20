# Protocolo SysEx del Numark Orbit — notas de investigación (fase 1)

Proyecto no oficial, sin relación con Numark/inMusic. Estas notas describen **con palabras propias**
el formato de los mensajes, deducido por interoperabilidad. No se ha copiado código ni recursos
del editor original al proyecto.

## De dónde sale la información

| Fuente | Qué aportó |
|---|---|
| `setup.exe` (instalador NSIS 2.46) extraído **sin ejecutarlo** con `herramientas/extraer_nsis.py` | Dentro hay una aplicación hecha en **Max/MSP 6** (Cycling '74). El editor no es un programa compilado: su lógica es un conjunto de "patches" de Max y unos scripts JavaScript, guardados en un archivo `.mxf`. Leyéndolos se ven los mensajes SysEx tal cual. |
| Guía oficial *Orbit Editor – User Guide v1.0* (PDF público de numark.com) | Confirma qué se puede editar (pads, knobs, acelerómetro, colores). |
| Búsqueda web | No existe documentación pública del protocolo ni proyectos libres que lo implementen. Solo un hilo del foro de Bome que describe la codificación de colores de los LEDs (coincide con lo encontrado). |
| Orbit conectado a este PC | Detectado como puerto de entrada **y** salida `Numark ORBIT`. **Aún no se le ha enviado nada** (ver "Pendiente"). |

## Puertos MIDI

- Windows Vista/7/10: el puerto se llama **`Numark ORBIT`** (entrada y salida).
- Windows XP: el editor buscaba **`USB Audio Device`** (nombre genérico del driver de XP).
- La detección automática puede buscar "ORBIT" en el nombre del puerto.

## Cabecera común

```
F0 00 01 3F 2B <comando> ...  F7
   └──────┘ └┘
   Numark   Orbit (id. de modelo 0x2B)
```

`00 01 3F` es el identificador de fabricante MIDI de Numark.

## Mensajes

| Dirección | Bytes | Tamaño | Significado |
|---|---|---|---|
| PC → Orbit | `F0 00 01 3F 2B 01 00 00 F7` | 9 | **Pedir** la configuración actual |
| Orbit → PC | `F0 00 01 3F 2B 02 01 70` + 240 bytes + `F7` | 249 | **Respuesta**: volcado completo de la configuración |
| PC → Orbit | `F0 00 01 3F 2B 03 01 70` + 240 bytes + `F7` | 249 | **Escribir** una configuración completa |

- No hay escritura parcial: siempre se envía el bloque entero de 240 bytes.
- El editor valida la respuesta comprobando que mida exactamente 249 bytes y que los 8 primeros sean
  `F0 00 01 3F 2B 02 01 70`.
- **Cómo verifica el editor una escritura**: envía el comando 03, espera 100 ms, envía la petición 01
  y compara los 240 bytes recibidos con los enviados. Si no llega respuesta en 5 s, lo da por fallido.
  Es decir, el Orbit no parece mandar un "OK" propio; la comprobación es una relectura.
- Los bytes `01 70` tras el comando son fijos en todos los mensajes; su significado no se conoce
  (¿versión de formato?, ¿ranura de memoria?).

## Estructura de los 240 bytes de datos

El orden es siempre banco 1 → banco 4.

### 1) Pads: 4 bancos × 16 pads × 3 bytes = 192 bytes (posiciones 0–191)

| Byte | Contenido |
|---|---|
| 0 | `modo × 16 + canal` → bits 0–3 = canal MIDI (0–15 = canales 1–16); bit 4 = modo (0 = Momentáneo, 1 = Toggle) |
| 1 | Número de nota (0–127) |
| 2 | Color del LED (ver tabla de colores) |

Posición del pad *p* (1–16) del banco *b* (1–4): `((b-1)*16 + (p-1)) * 3`.

### 2) Knobs: 4 bancos × 4 knobs × 2 bytes = 32 bytes (posiciones 192–223)

| Byte | Contenido |
|---|---|
| 0 | `modo × 16 + canal` → bit 4 = modo (0 = Absoluto, 1 = Relativo) |
| 1 | Número de CC (0–127) |

### 3) Acelerómetro: 4 bancos × 2 ejes × 2 bytes = 16 bytes (posiciones 224–239)

| Byte | Contenido |
|---|---|
| 0 | Canal (0–15) |
| 1 | Número de CC |

Eje 1 = izquierda-derecha, eje 2 = arriba-abajo.

### Colores de los LEDs

Cada color usa 2 bits por componente (intensidad 0–3): `valor = R×16 + G×4 + B`.
El editor ofrece 12 colores:

| Valor | R G B | Color aproximado |
|---|---|---|
| 0 | 0 0 0 | apagado |
| 63 | 3 3 3 | blanco |
| 48 | 3 0 0 | rojo |
| 12 | 0 3 0 | verde |
| 3 | 0 0 3 | azul |
| 60 | 3 3 0 | amarillo |
| 52 | 3 1 0 | naranja |
| 44 | 2 3 0 | lima |
| 15 | 0 3 3 | cian |
| 51 | 3 0 3 | magenta |
| 49 | 3 0 1 | rosa |
| 19 | 1 0 3 | violeta |

## Configuración de fábrica (según el editor)

- Pads: banco *b* → canal *b*, notas 36–51 (C1–D#2), modo momentáneo, color 0.
- Knobs: banco *b* → canal *b*, CC 1, 2, 3 y 4; el knob 4 aparece con el bit de modo activado (relativo).
- Acelerómetro: banco *b* → canal *b*, CC 9 (izq-der) y CC 10 (arriba-abajo).

## Lo que NO cubre este protocolo (según el editor)

Los botones de banco de pads, los botones K1–K4 y los botones laterales (shoulder) **no** son
configurables desde el editor; solo pads, knobs y acelerómetro.

## Pendiente de confirmar con el Orbit real

1. ✅ **Lectura confirmada (2026-10-19, por cable USB)**: el Orbit respondió al comando 01 con 249 bytes,
   cabecera `F0 00 01 3F 2B 02 01 70`, sin mensajes extra. El contenido es idéntico, byte a byte, a la
   configuración de fábrica descrita arriba (incluido el bit de modo en el knob 4: `10 04`, `11 04`…).
   Copia de seguridad guardada en `research/dump_actual.syx`.
2. ✅ **Escritura confirmada (2026-10-19, por cable USB, con autorización)**:
   - Reenviar el volcado de fábrica → relectura idéntica.
   - Cambiar solo el color del pad 1 del banco 1 a 48 (rojo) → relectura idéntica y el LED del pad de
     **arriba a la izquierda** se ve rojo. Esto confirma la codificación del color y que el pad 1 es el
     de arriba a la izquierda.
   - Restaurar el volcado de fábrica → relectura idéntica.
   - **Importante (tiempos)**: si se envía un mensaje justo después de que el Orbit termine de mandar un
     volcado, el mensaje se pierde. Con una escritura, además, el Orbit deja de responder durante más de
     15 s. Una lectura enviada así se responde tarde (~1,75 s). Basta esperar **0,5 s** después de
     recibir antes de enviar (`midi_win.QUIET_AFTER_RECEIVE`). La respuesta a una lectura llega en
     ~0,25 s, y tras una escritura el Orbit acepta la lectura de verificación a los 0,1 s.
3. Que la configuración escrita **se conserva al desconectar** (memoria interna).
4. ✅ **Bit de modo confirmado (2026-10-19, `research/monitor_toggle_knobs.txt`)**:
   - Pad en toggle (0x10): cada pulsación envía un solo mensaje, alternando NoteOn 127 / NoteOff 0.
     Pad momentáneo: NoteOn 127 al pulsar, NoteOff 0 al soltar.
   - Knob absoluto: CC con el valor 0–127 (en pasos de 2). Knob relativo (0x10): CC 1 al girar a la
     derecha y CC 127 (−1) a la izquierda.
   - **Botones de banco y K (2026-10-20, `monitor_bancos_k.txt`)**: el botón de banco *n* envía
     CC 1 por el canal 16 con valor *n*, y el botón K*n* envía CC 2 por el canal 16 con valor *n*. Si se
     pulsa dos veces seguidas el mismo botón, el segundo mensaje no se envía. No son configurables.
   - **El PC no puede cambiar el banco ni el K del Orbit**: enviarle esos mismos CC no cambia nada
     (`herramientas/prueba_banco_k.py`). La app hace lo contrario: sigue el banco y el K que elijas
     en el Orbit.
5. ✅ **Brillo confirmado (2026-10-19)**: el Orbit muestra cualquier valor 0–63. Rojo, verde, azul y
   blanco a niveles 1, 2 y 3 se distinguen claramente, así que se puede elegir el brillo de cada pad.
   **LEDs en vivo** (`herramientas/prueba_leds_vivo.py`): un NoteOn enviado AL Orbit con la nota de un
   pad colorea ese pad usando la velocidad como color (36 vel 3 = azul, 12 = verde, 48 = rojo). Los
   LEDs del acelerómetro, de la rueda y de los botones K **no** cambiaron con CC 9/10, CC 1–4 (canal 1)
   ni CC 2 (canal 16). No hay color para ellos en los 240 bytes, así que parecen fijos en el firmware.
6. Si el comando funciona igual por el **receptor inalámbrico** que por cable USB.
7. Qué significan `01 70` y si el firmware responde a otros comandos (no se probará nada desconocido sin
   preguntar).
8. ✅ Tipo de mensaje de los pads en toggle: ver punto 4 (alternan NoteOn 127 / NoteOff 0).
