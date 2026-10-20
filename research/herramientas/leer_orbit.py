# Prueba de SOLO LECTURA del Numark Orbit (Windows, winmm vía ctypes, sin dependencias).
# Envía únicamente la petición F0 00 01 3F 2B 01 00 00 F7 y guarda la respuesta.
# No envía nunca el comando de escritura (03).
# Uso:  python -I leer_orbit.py salida.syx
import ctypes
import sys
import time
from ctypes import wintypes

PETICION_LECTURA = bytes([0xF0, 0x00, 0x01, 0x3F, 0x2B, 0x01, 0x00, 0x00, 0xF7])
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
                ("name", ctypes.c_wchar * 32), ("resto", ctypes.c_byte * 16)]


def buscar(num_devs, get_caps):
    for i in range(num_devs()):
        c = CAPS()
        get_caps(i, ctypes.byref(c), ctypes.sizeof(c))
        if "ORBIT" in c.name.upper():
            return i
    return None


def main(salida):
    iid = buscar(w.midiInGetNumDevs, w.midiInGetDevCapsW)
    oid = buscar(w.midiOutGetNumDevs, w.midiOutGetDevCapsW)
    if iid is None or oid is None:
        sys.exit("No se encuentra el puerto 'Numark ORBIT'.")

    recibido, cortos = [], []
    CB = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t,
                            ctypes.c_size_t, ctypes.c_size_t)

    def callback(h, msg, inst, p1, p2):
        if msg == MIM_LONGDATA:
            hdr = ctypes.cast(p1, ctypes.POINTER(MIDIHDR)).contents
            recibido.append(ctypes.string_at(hdr.lpData, hdr.dwBytesRecorded))
        elif msg == MIM_DATA:
            cortos.append(p1)

    cbf = CB(callback)
    hin = wintypes.HANDLE()
    r = w.midiInOpen(ctypes.byref(hin), iid, cbf, 0, CALLBACK_FUNCTION)
    if r:
        sys.exit(f"midiInOpen falló ({r}); ¿otro programa usa el Orbit?")
    buffers = []
    for _ in range(4):
        b = ctypes.create_string_buffer(1024)
        h = MIDIHDR(lpData=ctypes.cast(b, ctypes.c_void_p), dwBufferLength=1024)
        w.midiInPrepareHeader(hin, ctypes.byref(h), ctypes.sizeof(h))
        w.midiInAddBuffer(hin, ctypes.byref(h), ctypes.sizeof(h))
        buffers.append((b, h))
    w.midiInStart(hin)

    hout = wintypes.HANDLE()
    r = w.midiOutOpen(ctypes.byref(hout), oid, 0, 0, 0)
    if r:
        sys.exit(f"midiOutOpen falló ({r})")
    ob = ctypes.create_string_buffer(PETICION_LECTURA, len(PETICION_LECTURA))
    oh = MIDIHDR(lpData=ctypes.cast(ob, ctypes.c_void_p), dwBufferLength=len(PETICION_LECTURA))
    w.midiOutPrepareHeader(hout, ctypes.byref(oh), ctypes.sizeof(oh))
    w.midiOutLongMsg(hout, ctypes.byref(oh), ctypes.sizeof(oh))

    inicio = time.time()
    while time.time() - inicio < 3 and not recibido:
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

    datos = b"".join(recibido)
    print(f"Mensajes cortos: {len(cortos)}  Bytes SysEx: {len(datos)}")
    print(datos.hex(" "))
    if datos:
        with open(salida, "wb") as f:
            f.write(datos)
        print("Guardado en", salida)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dump_orbit.syx")
