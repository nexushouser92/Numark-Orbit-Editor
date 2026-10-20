# Conectar el Orbit a la PC sin el receptor USB original: investigación (2026-10-20)

## Conclusión corta

**El Orbit no tiene Bluetooth.** Su conexión inalámbrica es una radio propia de **2,4 GHz** que solo
habla con su receptor USB emparejado (como un ratón inalámbrico). Ni el manual, ni las tiendas, ni las
reseñas mencionan Bluetooth: todos hablan de un "receptor USB inalámbrico" a 2,4 GHz con unos 30 m de
alcance. Por eso Windows no puede "verlo" con el Bluetooth del PC, y nada que hagamos en nuestro
programa lo cambia.

## Opciones reales

| Opción | Cómo | Ventajas | Inconvenientes |
|---|---|---|---|
| 1. Cable mini-USB | Ya funciona hoy | Sin latencia; también carga la batería | Con cable |
| 2. Otro receptor original de Numark | Comprar uno (segunda mano o recambio) y emparejarlo con el procedimiento del manual (abajo) | Inalámbrico "de fábrica", sin cambios en nuestro programa | Hay que encontrar el recambio; el Orbit está descatalogado |
| 3. Adaptador USB→Bluetooth MIDI (p. ej. **CME WIDI Uhost**) | Se conecta al puerto mini-USB del Orbit y convierte el cable en **Bluetooth MIDI (BLE)** | Inalámbrico de verdad por Bluetooth, sin el receptor de Numark | Es otro aparato que hay que comprar; en Windows 10 hace falta el driver **KORG BLE-MIDI** para que los programas MIDI normales lo vean; hay que confirmar la alimentación (el Orbit no da corriente por su puerto) y la latencia |
| 4. Clonar el receptor (proyecto avanzado) | Identificar el chip de radio (fotos internas en la ficha FCC) y emular el receptor con un módulo de 2,4 GHz y un microcontrolador | Sin comprar recambio | Hace falta electrónica, analizar la radio y probablemente tener el receptor original para estudiarlo. Semanas de trabajo y sin garantía |

**Recomendación:** si tienes el receptor original, sigue usándolo (o el cable). Si lo has perdido y
quieres algo inalámbrico, la opción 3 es la más práctica. Antes de comprar, convendría confirmar con
CME o con alguien que lo haya probado que el WIDI Uhost alimenta y reconoce al Orbit, porque el Orbit
es "class compliant": en este PC aparece como `Numark ORBIT` sin driver propio.

### Nuestro programa con la opción 3

El editor habla por `winmm`, la API MIDI clásica de Windows. Un dispositivo Bluetooth MIDI no aparece
ahí directamente en Windows 10; con el driver KORG BLE-MIDI sí aparece como un puerto MIDI normal. Si el
nombre del puerto no contiene "ORBIT", habría que añadir en la app una opción para elegir el puerto a
mano (es poco trabajo). El SysEx de lectura/escritura (249 bytes) debería pasar por Bluetooth MIDI,
pero hay que comprobarlo.

## Datos útiles del manual del Orbit

- **Emparejar un receptor:** con el Orbit apagado y el receptor desconectado, mantén los selectores
  de banco 1 y 4 y enciende el Orbit. Pulsa el pad de abajo a la derecha ("b") y K1 parpadea.
  Conecta el receptor al PC en menos de 10 s y K2 parpadea. Pulsa el pad de encima ("c") y K1–K4
  parpadean una vez: emparejado.
- **Cable ↔ inalámbrico:** para usar cable, desconecta el receptor y conecta el mini-USB. Para volver a
  inalámbrico, desconecta el cable, apaga el Orbit, conecta el receptor y enciéndelo.
- **Colores desde el propio Orbit:** mantén un selector de banco 3 s y pulsa un botón lateral
  (shoulder). Elige pads y cambia el color con los botones laterales. Para guardar, mantén un selector
  de banco y pulsa un botón lateral. Para volver a los colores de fábrica: enciéndelo con los
  selectores 1 y 4 pulsados y pulsa el pad de arriba a la izquierda ("a").
- Batería: unas 8 h de uso y 3 h de carga. Se pone en ahorro de energía tras 3 min sin uso.

## Fuentes

- Manual del Orbit (copia en manualslib): https://www.manualslib.tech/guide/693215/numark-orbit-wireless-dj-controller-manual.html
- Procedimiento de emparejado (foro VirtualDJ): https://virtualdj.com/forums/181793/VirtualDJ_Plugins/Numark_Orbit_def_%26_mapper.html
- Reseña DJ TechTools (2,4 GHz, cable o receptor): https://djtechtools.com/2013/07/03/review-numark-orbit-wireless-midi-controller/
- Especificaciones de tienda (2,4 GHz, 30 m): https://www.zzounds.com/item--NUMORBIT
- CME WIDI Uhost: https://www.cme-pro.com/widi-uhost/
