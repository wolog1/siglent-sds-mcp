from __future__ import annotations

import socket
import threading

import pytest

from siglent_sds_mcp.tcp_transport import RawTcpTransport


def _responder(server: socket.socket, payload: bytes) -> None:
    try:
        _ = server.recv(4096)
        server.sendall(payload)
    finally:
        server.close()


def _make_pair(payload: bytes) -> tuple[RawTcpTransport, threading.Thread, socket.socket]:
    client, server = socket.socketpair()
    transport = RawTcpTransport("127.0.0.1")
    transport._socket = client  # noqa: SLF001
    thread = threading.Thread(target=_responder, args=(server, payload))
    thread.start()
    return transport, thread, client


class TestQueryBinaryPrefix:
    def test_dat2_with_channel_prefix(self) -> None:
        """C1:WF DAT2,#9000005000<5000 bytes>"""
        transport, thread, client = _make_pair(b"C1:WF DAT2,#9000005000" + b"x" * 5000)
        try:
            block = transport.query_binary("C1:WF? DAT2")
            assert block.framing == "ieee4882"
            assert len(block.data) == 5000
        finally:
            client.close()
            thread.join(timeout=1)

    def test_dat2_without_prefix(self) -> None:
        """#9000005000<5000 bytes> — bare IEEE block, no prefix."""
        transport, thread, client = _make_pair(b"#9000005000" + b"x" * 5000)
        try:
            block = transport.query_binary("C1:WF? DAT2")
            assert block.framing == "ieee4882"
            assert len(block.data) == 5000
        finally:
            client.close()
            thread.join(timeout=1)

    def test_bmp_prefix(self) -> None:
        """Raw BMP screenshot after ASCII prefix."""
        # Valid minimal BMP: 54-byte header, file_size in bytes 2-6 (LE).
        bmp_header = bytearray(54)
        bmp_header[0:2] = b"BM"
        bmp_header[2:6] = (54 + 16).to_bytes(4, "little")  # header + 16 bytes pixel data
        transport, thread, client = _make_pair(b"SCDP," + bytes(bmp_header) + b"\x00" * 16)
        try:
            block = transport.query_binary("SCDP")
            assert block.framing == "raw-bmp"
            assert block.data[:2] == b"BM"
            assert len(block.data) == 54 + 16
        finally:
            client.close()
            thread.join(timeout=1)

    def test_wavedesc_prefix(self) -> None:
        """C1:WF DESC,#<n><len><WAVEDESC bytes> with ASCII prefix."""
        # #500346 = 5 length digits "00346" = 346 bytes payload
        desc_payload = b"WAVEDESC\x00" + b"\x00" * (346 - 9)  # "WAVEDESC\0" = 9 bytes
        transport, thread, client = _make_pair(b"C1:WF DESC,#500346" + desc_payload)
        try:
            block = transport.query_binary("C1:WF? DESC")
            assert block.framing == "ieee4882"
            assert block.data[:9] == b"WAVEDESC\x00"
            assert len(block.data) == 346
        finally:
            client.close()
            thread.join(timeout=1)

    def test_connection_closed_before_marker(self) -> None:
        """Empty response raises ScpiTcpError."""
        client, server = socket.socketpair()
        transport = RawTcpTransport("127.0.0.1")
        transport._socket = client  # noqa: SLF001
        server.close()  # no data to read
        with pytest.raises(Exception):
            transport.query_binary("C1:WF? DAT2")
        client.close()
