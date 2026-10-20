# Diagnostic: send the factory mapping (same as what the Orbit already holds), then send a read
# request every 0.5 s and log when, and with what, the Orbit answers. Uses only commands 01 and 03.
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from orbit_editor import midi_win, presets, protocol

config = presets.load(sys.argv[1])
assert config == protocol.factory_config(), "only the factory mapping may be used for this test"
with midi_win.open_orbit() as port:
    port.drain()
    if "--leer-antes" in sys.argv:
        from orbit_editor import device
        t = time.monotonic()
        device.read_config(port)
        print(f"backup read took {time.monotonic() - t:.2f}s")
    t0 = time.monotonic()
    port.send(protocol.build_write_message(config))
    print(f"{time.monotonic() - t0:6.2f}s  write sent")
    next_request, answered = t0 + 0.1, None
    while time.monotonic() - t0 < 15 and answered is None:
        if time.monotonic() >= next_request:
            port.send(protocol.READ_REQUEST)
            print(f"{time.monotonic() - t0:6.2f}s  read request")
            next_request += 0.5
        msg = port.receive(0.05)
        if msg is not None:
            print(f"{time.monotonic() - t0:6.2f}s  received {len(msg)} bytes: {msg[:8].hex(' ')}...")
            if len(msg) == protocol.MESSAGE_LEN and msg[5] == protocol.CMD_DUMP:
                answered = msg
    if answered:
        print("read back == sent:", protocol.parse_message(answered) == config)
