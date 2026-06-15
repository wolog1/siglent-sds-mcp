from __future__ import annotations

import socket
import threading

from siglent_sds_mcp.tcp_transport import RawTcpTransport


def test_ieee4882_binary_block_parser_with_socketpair() -> None:
    client, server = socket.socketpair()
    transport = RawTcpTransport("127.0.0.1")
    transport._socket = client  # noqa: SLF001 - unit test injects socketpair

    def responder() -> None:
        try:
            _ = server.recv(1024)
            server.sendall(b"#500004hello")
        finally:
            server.close()

    thread = threading.Thread(target=responder)
    thread.start()
    try:
        block = transport.query_binary("C1:WF? DAT2")
        assert block.framing == "ieee4882"
        assert block.data == b"hell"
    finally:
        client.close()
        thread.join(timeout=1)


def test_text_query_with_socketpair() -> None:
    client, server = socket.socketpair()
    transport = RawTcpTransport("127.0.0.1")
    transport._socket = client  # noqa: SLF001 - unit test injects socketpair

    def responder() -> None:
        try:
            _ = server.recv(1024)
            server.sendall(b"SIGLENT,SDS824X HD,123,1.0\n")
        finally:
            server.close()

    thread = threading.Thread(target=responder)
    thread.start()
    try:
        assert transport.query("*IDN?") == "SIGLENT,SDS824X HD,123,1.0"
    finally:
        client.close()
        thread.join(timeout=1)
