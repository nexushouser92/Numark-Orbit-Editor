# READ-ONLY test of the Numark Orbit (Windows, winmm through ctypes, no dependencies).
# Sends only the read request F0 00 01 3F 2B 01 00 00 F7 and saves the reply.
# Never sends the write command (03).
# Usage:  python -I read_orbit.py output.syx
import ctypes
import sys
import time
from ctypes import wintypes

READ_REQUEST = bytes([0xF0, 0x00, 0x01, 0x3F, 0x2B, 0x01, 0x00, 0x00, 0xF7])
MIM_DATA, MIM_LONGDATA = 0x3C3, 0x3C4
CALLBACK_FUNCTION = 0x30000
MIDIERR_STILLPLAYING = 65

w = ctypes.windll.winmm


class MIDIHDR(ctypes.Structure):
    _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
                ("dwFlags", wintypes.DWORD), ("lpNext", ctypes.c_void_p),
                ("reserved", ctypes.c_size_t), ("dwOffset", wintypes.DWORD),
                ("dwReserved", ctypes.c_size_t * 8)]


class CAPS(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("ver", wintypes.UINT),
                ("name", ctypes.c_wchar * 32), ("rest", ctypes.c_byte * 16)]


def find(num_devs, get_caps):
    for i in range(num_devs()):
        c = CAPS()
        get_caps(i, ctypes.byref(c), ctypes.sizeof(c))
        if "ORBIT" in c.name.upper():
            return i
    return None


def main(output):
    in_id = find(w.midiInGetNumDevs, w.midiInGetDevCapsW)
    out_id = find(w.midiOutGetNumDevs, w.midiOutGetDevCapsW)
    if in_id is None or out_id is None:
        sys.exit("MIDI port 'Numark ORBIT' not found.")

    received, short = [], []
    CB = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t,
                            ctypes.c_size_t, ctypes.c_size_t)

    def callback(h, msg, inst, p1, p2):
        if msg == MIM_LONGDATA:
            hdr = ctypes.cast(p1, ctypes.POINTER(MIDIHDR)).contents
            received.append(ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded))
        elif msg == MIM_DATA:
            short.append(p1)

    cbf = CB(callback)
    hin = wintypes.HANDLE()
    r = w.midiInOpen(ctypes.byref(hin), in_id, cbf, 0, CALLBACK_FUNCTION)
    if r:
        sys.exit(f"midiInOpen failed ({r}); is another program using the Orbit?")
    buffers = []
    for _ in range(4):
        b = ctypes.create_string_buffer(1024)
        h = MIDIHDR(lpData=ctypes.cast(b, ctypes.c_void_p), dwBufferLength=1024)
        w.midiInPrepareHeader(hin, ctypes.byref(h), ctypes.sizeof(h))
        w.midiInAddBuffer(hin, ctypes.byref(h), ctypes.sizeof(h))
        buffers.append((b, h))
    w.midiInStart(hin)

    hout = wintypes.HANDLE()
    r = w.midiOutOpen(ctypes.byref(hout), out_id, 0, 0, 0)
    if r:
        sys.exit(f"midiOutOpen failed ({r})")
    ob = ctypes.create_string_buffer(READ_REQUEST, len(READ_REQUEST))
    oh = MIDIHDR(lpData=ctypes.cast(ob, ctypes.c_void_p), dwBufferLength=len(READ_REQUEST))
    w.midiOutPrepareHeader(hout, ctypes.byref(oh), ctypes.sizeof(oh))
    w.midiOutLongMsg(hout, ctypes.byref(oh), ctypes.sizeof(oh))

    start = time.time()
    while time.time() - start < 3 and not received:
        time.sleep(0.05)
    time.sleep(0.3)

    while w.midiOutUnprepareHeader(hout, ctypes.byref(oh), ctypes.sizeof(oh)) == MIDIERR_STILLPLAYING:
        time.sleep(0.01)
    w.midiOutClose(hout)
    w.midiInStop(hin)
    w.midiInReset(hin)
    for _, h in buffers:
        w.midiInUnprepareHeader(hin, ctypes.byref(h), ctypes.sizeof(h))
    w.midiInClose(hin)

    data = b"".join(received)
    print(f"Short messages: {len(short)}  SysEx bytes: {len(data)}")
    print(data.hex(" "))
    if data:
        with open(output, "wb") as f:
            f.write(data)
        print("Saved to", output)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "orbit_dump.syx")
