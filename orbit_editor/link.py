"""Keeps the Orbit linked while the editor is open.

- Looks for the Orbit every POLL_INTERVAL seconds and opens it as soon as it appears.
- On linking, writes the editor's mapping if it has changes waiting, otherwise reads the Orbit's.
- push(config) schedules a write WRITE_DELAY seconds after the latest change (live preview without
  writing the Orbit's memory on every click), then verifies it by reading back.
- Notes/CCs coming from the Orbit are reported as ("midi", (status, data1, data2)) events.
- If the Orbit is unplugged, the port is closed and the search starts again.

All device work happens in step(), called from one worker thread (or directly by tests).
The window reads the results from `events`, a queue of (kind, payload):
  ("searching", error or None) ("linked", None) ("config", OrbitConfig) ("writing", None)
  ("written", OrbitConfig) ("write_failed", error) ("midi", (status, d1, d2))
"""
import copy
import queue
import threading
import time

from . import device, midi_win

POLL_INTERVAL = 1.0
WRITE_DELAY = 0.5


class OrbitLink:
    def __init__(self, opener=midi_win.open_orbit, lister=midi_win.list_ports, clock=time.monotonic,
                 write_delay=WRITE_DELAY):
        self.opener, self.lister, self.clock = opener, lister, clock
        self.write_delay = write_delay
        self.events = queue.Queue()
        self.port = None
        self._lock = threading.Lock()
        self._pending = None        # mapping waiting to be written
        self._due = 0.0             # when it may be written
        self._want_read = False
        self._next_poll = 0.0
        self._stop = threading.Event()
        self._thread = None
        self.listener = None        # listener(status, d1, d2) gets notes/CCs right away (the sequencer)
        self._sysex = threading.Lock()  # held while reading/writing: no pad colors may be sent then

    # ------------------------------------------------------------- called by the window
    @property
    def linked(self):
        return self.port is not None

    def push(self, config):
        """Write this mapping soon; a newer push before then replaces it."""
        with self._lock:
            self._pending = copy.deepcopy(config)
            self._due = self.clock() + self.write_delay

    def flush(self):
        """Write the waiting mapping (if any) without further delay."""
        with self._lock:
            self._due = 0.0

    def request_read(self):
        self._want_read = True

    def send_short(self, status, data1, data2):
        """Send a note/CC to the Orbit (lights a pad live). False, without waiting, if it is not linked,
        a mapping is being read or written (the Orbit garbles a dump when notes arrive meanwhile), or
        sending failed."""
        if not self._sysex.acquire(blocking=False):
            return False
        try:
            port = self.port
            if port is None:
                return False
            port.send_short(status, data1, data2)
        except (midi_win.MidiError, OSError):
            return False
        finally:
            self._sysex.release()
        return True

    @property
    def has_pending(self):
        return self._pending is not None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout=3.0):
        """Write anything still waiting, then close the port."""
        self.flush()
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        if self.linked and self._pending is not None:
            self.step()
        self._close()

    # ------------------------------------------------------------- worker
    def _run(self):
        while not self._stop.is_set():
            self.step()
            self._stop.wait(0.05)

    def step(self):
        now = self.clock()
        if self.port is None:
            if now >= self._next_poll:
                self._next_poll = now + POLL_INTERVAL
                self._try_link()
            return
        if now >= self._next_poll:
            self._next_poll = now + POLL_INTERVAL
            if not self._present():
                self._drop(None)
                return
        if self._want_read:
            self._want_read = False
            self._read()
            if self.port is None:
                return
        with self._lock:
            config = self._pending if self._pending is not None and now >= self._due else None
        if config is not None:
            self._write(config)

    def _present(self):
        try:
            ins, outs = self.lister()
        except OSError:
            return False
        return midi_win.find_port(ins) is not None and midi_win.find_port(outs) is not None

    def _try_link(self):
        if not self._present():
            return
        try:
            port = self.opener()
        except (midi_win.MidiError, OSError) as e:
            self.events.put(("searching", e))
            return
        port.on_short = self._on_short
        self.port = port
        self.events.put(("linked", None))
        if self._pending is not None:
            self.flush()  # the editor changed things while the Orbit was away: apply them now
        else:
            self._read()

    def _on_short(self, status, data1, data2):
        listener = self.listener
        if listener is not None:
            listener(status, data1, data2)
        self.events.put(("midi", (status, data1, data2)))

    def _read(self):
        try:
            with self._sysex:
                config = device.read_config(self.port)
        except (device.DeviceError, midi_win.MidiError, OSError) as e:
            self._drop(e)
            return
        self.events.put(("config", config))

    def _write(self, config):
        self.events.put(("writing", None))
        try:
            with self._sysex:
                device.write_config(self.port, config)
        except device.VerifyError as e:
            self._clear_pending(config)
            self.events.put(("write_failed", e))
            return
        except (device.DeviceError, midi_win.MidiError, OSError) as e:
            self.events.put(("write_failed", e))
            self._drop(e)  # keep the mapping waiting: it is written again once the Orbit is back
            return
        self._clear_pending(config)
        self.events.put(("written", config))

    def _clear_pending(self, written):
        with self._lock:
            if self._pending is written:  # unless a newer change arrived meanwhile
                self._pending = None

    def _drop(self, error):
        self._close()
        self._next_poll = self.clock() + POLL_INTERVAL
        self.events.put(("searching", error))

    def _close(self):
        port, self.port = self.port, None
        if port is not None:
            port.on_short = None
            try:
                port.close()
            except (midi_win.MidiError, OSError):
                pass
