"""Test doubles: a fake Orbit (port level) and a fake winmm.dll. No MIDI device is needed."""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orbit_editor import midi_win, protocol


class FakeOrbit:
    """A port (send/receive/drain/close) that behaves like the Orbit described in PROTOCOLO.md."""

    def __init__(self, config=None, respond=True, apply_writes=True, noise=(), corrupt=False):
        self.config = config or protocol.factory_config()
        self.respond, self.apply_writes = respond, apply_writes
        self.noise, self.corrupt = list(noise), corrupt
        self.sent, self.inbox = [], []
        self.shorts = []          # (status, data1, data2) notes/CCs sent to the Orbit
        self.closed = False
        self.on_short = None

    def send_short(self, status, data1=0, data2=0):
        self.shorts.append((status, data1, data2))

    def send(self, data):
        self.sent.append(bytes(data))
        if data == protocol.READ_REQUEST and self.respond:
            self.inbox.extend(self.noise)
            dump = bytearray(protocol.build_dump_message(self.config))
            if self.corrupt:
                dump[8] = 0x7F  # undefined bits in the first pad's mode/channel byte
            self.inbox.append(bytes(dump))
        elif data[5] == protocol.CMD_WRITE and self.apply_writes:
            self.config = protocol.parse_message(data, allowed=(protocol.CMD_WRITE,))

    def receive(self, timeout):
        return self.inbox.pop(0) if self.inbox else None

    def drain(self):
        self.inbox.clear()

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def writes(self):
        return [m for m in self.sent if m[5] == protocol.CMD_WRITE]


class FakeWinmm:
    """Stands in for winmm.dll. Arguments passed with ctypes.byref() are reached through ._obj.

    on_send(fake, data) is called for every SysEx sent, and can answer with fake.deliver().
    """

    def __init__(self, ins=("Numark ORBIT",), outs=("Numark ORBIT",), on_send=None,
                 in_open=0, out_open=0, long_msg=0, still_playing=0):
        self.ins, self.outs = list(ins), list(outs)
        self.on_send = on_send
        self.in_open_res, self.out_open_res, self.long_msg_res = in_open, out_open, long_msg
        self.still_playing = still_playing
        self.callback = None
        self.available = []       # input headers the "driver" may fill
        self.prepared_in = []
        self.sent = []
        self.shorts = []          # packed short messages sent with midiOutShortMsg
        self.short_res = 0
        self.added = self.out_resets = 0
        self.in_closed = self.out_closed = 0
        self.out_prepared = self.out_unprepared = 0
        self.in_unprepared = 0
        self.opened_in = self.opened_out = None

    # --- device lists
    def midiInGetNumDevs(self):
        return len(self.ins)

    def midiOutGetNumDevs(self):
        return len(self.outs)

    def midiInGetDevCapsW(self, i, caps_ref, size):
        caps_ref._obj.szPname = self.ins[i]
        return 0

    def midiOutGetDevCapsW(self, i, caps_ref, size):
        caps_ref._obj.szPname = self.outs[i]
        return 0

    # --- input
    def midiInOpen(self, handle_ref, index, callback, instance, flags):
        if self.in_open_res:
            return self.in_open_res
        handle_ref._obj.value = 0x100
        self.callback, self.opened_in = callback, index
        return 0

    def midiInPrepareHeader(self, h, hdr_ref, size):
        self.prepared_in.append(hdr_ref._obj)
        return 0

    def midiInAddBuffer(self, h, hdr_ref, size):
        self.available.append(hdr_ref._obj)
        self.added += 1
        return 0

    def midiInStart(self, h):
        return 0

    def midiInStop(self, h):
        return 0

    def midiInReset(self, h):
        # The real driver hands every queued buffer back with 0 bytes recorded.
        while self.available:
            hdr = self.available.pop(0)
            hdr.dwBytesRecorded = 0
            self.callback(0x100, midi_win.MIM_LONGDATA, 0, ctypes.addressof(hdr), 0)
        return 0

    def midiInUnprepareHeader(self, h, hdr_ref, size):
        self.in_unprepared += 1
        return 0

    def midiInClose(self, h):
        self.in_closed += 1
        return 0

    def deliver(self, data, chunk=None):
        """Simulate bytes arriving from the device, in buffers of at most `chunk` bytes."""
        chunk = chunk or len(data)
        for start in range(0, len(data), chunk):
            piece = data[start:start + chunk]
            hdr = self.available.pop(0)
            ctypes.memmove(hdr.lpData, piece, len(piece))
            hdr.dwBytesRecorded = len(piece)
            self.callback(0x100, midi_win.MIM_LONGDATA, 0, ctypes.addressof(hdr), 0)

    # --- output
    def midiOutOpen(self, handle_ref, index, callback, instance, flags):
        if self.out_open_res:
            return self.out_open_res
        handle_ref._obj.value = 0x200
        self.opened_out = index
        return 0

    def midiOutPrepareHeader(self, h, hdr_ref, size):
        self.out_prepared += 1
        return 0

    def midiOutLongMsg(self, h, hdr_ref, size):
        if self.long_msg_res:
            return self.long_msg_res
        hdr = hdr_ref._obj
        data = ctypes.string_at(hdr.lpData, hdr.dwBufferLength)
        self.sent.append(data)
        if self.on_send:
            self.on_send(self, data)
        return 0

    def midiOutShortMsg(self, h, packed):
        self.shorts.append(packed)
        return self.short_res

    def midiOutUnprepareHeader(self, h, hdr_ref, size):
        if self.still_playing:
            self.still_playing -= 1
            return midi_win.MIDIERR_STILLPLAYING
        self.out_unprepared += 1
        return 0

    def midiOutReset(self, h):
        self.out_resets += 1
        self.still_playing = 0
        return 0

    def midiOutClose(self, h):
        self.out_closed += 1
        return 0


def orbit_replies(fake, data):
    """on_send handler: answer a read request with the factory dump."""
    if data == protocol.READ_REQUEST:
        fake.deliver(protocol.build_dump_message(protocol.factory_config()))
