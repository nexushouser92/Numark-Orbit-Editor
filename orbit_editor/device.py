"""Talk to the Orbit through any port with send/receive/drain (see midi_win.py)."""
import time

from . import protocol
from .protocol import ProtocolError

READ_TIMEOUT = 3.0
VERIFY_DELAY = 0.1   # the official editor waits 100 ms before reading back
DUMP_PREFIX = protocol.HEADER + bytes([protocol.CMD_DUMP])


class DeviceError(Exception):
    """The Orbit did not answer, or answered with something unexpected."""


class VerifyError(DeviceError):
    """After writing, the Orbit reported a mapping different from the one sent."""

    def __init__(self, sent, received):
        super().__init__("the mapping read back from the Orbit differs from the one sent")
        self.sent, self.received = sent, received


def read_config(port, timeout=READ_TIMEOUT):
    """Ask the Orbit for its mapping (command 01) and return it as an OrbitConfig."""
    port.drain()
    port.send(protocol.READ_REQUEST)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        message = port.receive(remaining) if remaining > 0 else None
        if message is None:
            raise DeviceError("the Orbit did not answer the read request")
        if message[:len(DUMP_PREFIX)] != DUMP_PREFIX:
            continue  # some other SysEx: keep waiting for the dump
        try:
            return protocol.parse_message(message)
        except ProtocolError as e:
            raise DeviceError(f"invalid answer from the Orbit: {e}") from None


def write_config(port, config, verify=True, timeout=READ_TIMEOUT, sleep=time.sleep):
    """Send a full mapping (command 03). With verify, read it back and compare.

    Returns the mapping read back (or None without verify). Raises VerifyError on a mismatch.
    """
    message = protocol.build_write_message(config)  # validates before anything is sent
    port.drain()
    port.send(message)
    if not verify:
        return None
    sleep(VERIFY_DELAY)
    received = read_config(port, timeout)
    if protocol.encode_payload(received) != protocol.encode_payload(config):
        raise VerifyError(config, received)
    return received
