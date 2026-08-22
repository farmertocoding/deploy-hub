"""The ws-probe's extended-length read loops break on an empty read (2.5 re-review).

`_WS_PROBE_PY` runs on the target with the site's python3; a peer that closes
mid-header must produce a prompt failure, not a recv(b"") spin that only the
60 s transport timeout ends.
"""
from __future__ import annotations

import socket as socket_module

import pytest

HANDSHAKE = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"
FIN_TEXT = 0x81


class _PeerClosedSocket:
    """Scripted recv chunks, then a closed peer (recv returns b'' forever).

    A loop that keeps calling recv after the first b"" is the spin this test
    exists to forbid; the cap turns it into a hard failure instead of a hang.
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.reads_after_close = 0

    def sendall(self, data):
        pass

    def recv(self, _n):
        if self._chunks:
            return self._chunks.pop(0)
        self.reads_after_close += 1
        if self.reads_after_close > 2:
            raise AssertionError("read loop kept calling recv after the peer closed")
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _probe_main():
    from deploys.steps import _WS_PROBE_PY

    namespace = {"__name__": "ws_probe"}
    exec(compile(_WS_PROBE_PY, "ws-probe.py", "exec"), namespace)  # noqa: S102
    return namespace["main"]


@pytest.mark.parametrize(
    ("length_byte", "partial_length"),
    [(0x7E, b""), (0x7F, b"\x00\x00\x00")],
    ids=["ext16", "ext64"],
)
def test_extended_length_read_breaks_on_empty_read(monkeypatch, length_byte, partial_length):
    """Peer closes inside the 126/127 extended-length header: probe returns 3.

    What would make this fail: `while len(data) < n: data += sock.recv(...)`
    without the empty-read break its sibling loops have — recv yields b""
    forever and the probe spins until the transport timeout kills it.
    """
    frame_start = bytes([FIN_TEXT, length_byte]) + partial_length
    sock = _PeerClosedSocket([HANDSHAKE + frame_start])
    monkeypatch.setattr(socket_module, "create_connection", lambda *a, **kw: sock)

    rc = _probe_main()("127.0.0.1", "80", "/ws", "site.example.test")

    assert rc == 3
    assert sock.reads_after_close == 1
