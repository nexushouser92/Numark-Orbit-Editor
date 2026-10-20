# Connecting the Orbit without its USB receiver: research (2026-10-20)

## Short answer

**The Orbit has no Bluetooth.** Its wireless link is a proprietary **2.4 GHz** radio that only talks
to its paired USB receiver, like a wireless mouse. The manual, store listings and reviews never
mention Bluetooth; they all describe a "wireless USB receiver" at 2.4 GHz with about 30 m (100 ft) of
range. So Windows cannot see it through the PC's Bluetooth, and nothing in this program can change
that.

## Real options

| Option | How | Pros | Cons |
|---|---|---|---|
| 1. Mini-USB cable | Works today | No latency; also charges the battery | Wired |
| 2. Another original Numark receiver | Buy one (used or as a spare part) and pair it with the manual's procedure (below) | Wireless as designed; no change in this program | The spare has to be found; the Orbit is discontinued |
| 3. USB → Bluetooth MIDI adapter (e.g. **CME WIDI Uhost**) | Plugs into the Orbit's mini-USB port and turns the cable into **Bluetooth MIDI (BLE)** | Real Bluetooth wireless, no Numark receiver | Another device to buy; on Windows 10 the **KORG BLE-MIDI** driver is needed for ordinary MIDI programs to see it; power (the Orbit does not supply power on its port) and latency need checking |
| 4. Clone the receiver (advanced) | Identify the radio chip (internal photos in the FCC filing) and emulate the receiver with a 2.4 GHz module and a microcontroller | No spare to buy | Needs electronics, radio analysis and probably an original receiver to study. Weeks of work, no guarantee |

**Recommendation:** keep using the original receiver or the cable. Without the receiver, option 3 is
the most practical wireless choice. Before buying, check with CME or someone who tried it that the
WIDI Uhost powers and recognizes the Orbit. The Orbit is class compliant: Windows shows it as
`Numark ORBIT` with no driver of its own.

### This program with option 3

The editor uses `winmm`, Windows' classic MIDI API. A Bluetooth MIDI device does not show up there
directly on Windows 10; with the KORG BLE-MIDI driver it shows up as an ordinary MIDI port. If the
port name does not contain "ORBIT", the app would need a manual port choice (a small change). The
249-byte read/write SysEx should pass through Bluetooth MIDI, but that needs testing.

## Useful facts from the Orbit manual

- **Pairing a receiver:** with the Orbit off and the receiver unplugged, hold pad bank buttons 1 and 4
  and turn the Orbit on. Press the bottom-right pad ("b"): K1 flashes. Plug the receiver into the PC
  within 10 s: K2 flashes. Press the pad above it ("c"): K1–K4 flash once, and they are paired.
- **Cable ↔ wireless:** for the cable, unplug the receiver and connect the mini-USB cable. To go back
  to wireless, unplug the cable, turn the Orbit off, plug in the receiver and turn it on.
- **Colors on the Orbit itself:** hold a pad bank button for 3 s and press a shoulder button. Select
  pads and change their color with the shoulder buttons. To save, hold a pad bank button and press a
  shoulder button. Factory colors: turn it on holding pad bank buttons 1 and 4 and press the top-left
  pad ("a").
- Battery: about 8 h of use and 3 h to charge. It goes to power saving after 3 min without use.

## Sources

- Orbit manual (copy on manualslib): https://www.manualslib.tech/guide/693215/numark-orbit-wireless-dj-controller-manual.html
- Pairing procedure (VirtualDJ forum): https://virtualdj.com/forums/181793/VirtualDJ_Plugins/Numark_Orbit_def_%26_mapper.html
- DJ TechTools review (2.4 GHz, cable or receiver): https://djtechtools.com/2013/07/03/review-numark-orbit-wireless-midi-controller/
- Store specifications (2.4 GHz, 30 m): https://www.zzounds.com/item--NUMORBIT
- CME WIDI Uhost: https://www.cme-pro.com/widi-uhost/
