from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import Literal


class ScpiTcpError(RuntimeError):
    """Raised when raw TCP SCPI transport fails."""


@dataclass(slots=True)
class BinaryBlock:
    """Parsed binary response data."""

    data: bytes
    framing: Literal["ieee4882", "raw-bmp", "unknown"]


class RawTcpTransport:
    """Raw TCP SCPI transport for SIGLENT LAN socket control.

    Many SIGLENT SDS oscilloscopes expose a SCPI socket service, commonly on port 5025.
    This class is intentionally small and testable. It serializes access with a lock because
    oscilloscopes process SCPI commands sequentially.

    The exact SDS824X HD port and command behavior must be verified on real hardware.
    """

    def __init__(self, host: str, port: int = 5025, timeout_s: float = 5.0):
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self._socket: socket.socket | None = None
        self._lock = threading.RLock()
        self._last_tail_bytes: bytes | None = None  # diagnostic: unexpected bytes after binary payload

    def connect(self) -> None:
        with self._lock:
            self.close()
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
            sock.settimeout(self.timeout_s)
            self._socket = sock

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                finally:
                    self._socket = None

    def is_connected(self) -> bool:
        return self._socket is not None

    def write(self, command: str) -> None:
        data = _normalize_command(command).encode("ascii") + b"\n"
        with self._lock:
            sock = self._require_socket()
            sock.sendall(data)

    def query(self, command: str) -> str:
        data = _normalize_command(command).encode("ascii") + b"\n"
        with self._lock:
            sock = self._require_socket()
            # 发送前清空套接字中可能残留的过期响应字节，避免响应错位。
            self._flush_input(sock)
            sock.sendall(data)
            return self._read_line(sock).decode("utf-8", errors="replace").strip()

    def query_binary(self, command: str, timeout_s: float | None = None) -> BinaryBlock:
        data = _normalize_command(command).encode("ascii") + b"\n"
        with self._lock:
            sock = self._require_socket()
            old_timeout = sock.gettimeout()
            if timeout_s is not None:
                sock.settimeout(timeout_s)
            try:
                # 发送前清空残留字节，避免上一次响应污染本次读取。
                self._flush_input(sock)
                sock.sendall(data)
                # SIGLENT 在二进制块前可能带有 ASCII 前缀（例如 "DAT2," 或
                # "C1:WF DAT2,"）。需要跳过前缀，定位到真正的块起始标记：
                #   - 截图 SCDP   : 以 "BM" 开头的原始 BMP
                #   - 波形 WF? DAT2: 以 IEEE 488.2 "#<n><len>" 块开头
                kind, marker = self._read_to_binary_marker(sock)
                if kind == "bmp":
                    return BinaryBlock(data=self._read_raw_bmp(sock, marker), framing="raw-bmp")
                if kind == "ieee":
                    return BinaryBlock(data=self._read_ieee4882_block(sock, marker), framing="ieee4882")

                # 未识别响应：读取剩余内容用于诊断。
                rest = self._read_until_timeout(sock)
                return BinaryBlock(data=marker + rest, framing="unknown")
            finally:
                sock.settimeout(old_timeout)

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise ScpiTcpError("not connected")
        return self._socket

    @staticmethod
    def _flush_input(sock: socket.socket) -> bytes:
        """非阻塞地丢弃套接字接收缓冲区中的残留字节。

        SIGLENT 的二进制响应（如 BMP 截图、WF 波形）后常带有一个收尾换行符，
        若未读走会污染下一条查询，导致响应整体错位。发送新命令前调用本方法，
        可彻底规避此类错位问题。返回被丢弃的字节，便于诊断。
        """
        old_timeout = sock.gettimeout()
        sock.setblocking(False)
        drained: list[bytes] = []
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                drained.append(chunk)
        except (BlockingIOError, OSError):
            pass
        finally:
            sock.settimeout(old_timeout)
        return b"".join(drained)

    def _read_to_binary_marker(self, sock: socket.socket, max_prefix: int = 256) -> tuple[str, bytes]:
        """跳过二进制块前的 ASCII 前缀，定位到块起始标记。

        返回 (kind, marker)：kind 为 "bmp"/"ieee"/"unknown"，marker 为已读入的
        起始字节（"BM" 或 "#"）。若超出 max_prefix 仍未找到标记，返回 unknown。
        """
        buf = b""
        while len(buf) < max_prefix:
            ch = sock.recv(1)
            if not ch:
                raise ScpiTcpError("connection closed before binary marker")
            buf += ch
            if buf[-2:] == b"BM":
                return ("bmp", b"BM")
            if ch == b"#":
                return ("ieee", b"#")
        return ("unknown", buf)

    @staticmethod
    def _read_line(sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(1)
            if not chunk:
                raise ScpiTcpError("connection closed while reading line")
            if chunk == b"\n":
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _read_exact(sock: socket.socket, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ScpiTcpError(f"connection closed with {remaining} bytes remaining")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_ieee4882_block(self, sock: socket.socket, first: bytes) -> bytes:
        if len(first) < 2:
            first += self._read_exact(sock, 2 - len(first))
        digit_count_byte = first[1:2]
        if not digit_count_byte.isdigit():
            raise ScpiTcpError(f"invalid IEEE 488.2 block header: {first!r}")
        digit_count = int(digit_count_byte)
        if digit_count <= 0 or digit_count > 9:
            raise ScpiTcpError(f"unsupported IEEE 488.2 digit count: {digit_count}")
        length_digits = self._read_exact(sock, digit_count)
        try:
            data_len = int(length_digits.decode("ascii"))
        except ValueError as exc:
            raise ScpiTcpError(f"invalid IEEE 488.2 length: {length_digits!r}") from exc
        payload = self._read_exact(sock, data_len)
        # Consume trailing newline(s) — SIGLENT appends \n after binary blocks.
        # Only consume actual newline bytes; if something else arrives, leave it
        # in the socket buffer for the next read (do not silently discard).
        try:
            sock.settimeout(0.05)
            tail = sock.recv(2)
            if tail and tail not in (b"\n", b"\r\n"):
                # Not a newline — put it back conceptually by logging.
                # We cannot pushback to a TCP socket, so record for diagnostics.
                self._last_tail_bytes = tail  # noqa: SLF001 — diagnostic-only store
        except (TimeoutError, socket.timeout):
            pass
        finally:
            sock.settimeout(self.timeout_s)
        return payload

    def _read_raw_bmp(self, sock: socket.socket, first: bytes) -> bytes:
        header = first + self._read_exact(sock, 54 - len(first))
        if len(header) < 54:
            raise ScpiTcpError("incomplete BMP header")
        file_size = int.from_bytes(header[2:6], byteorder="little", signed=False)
        if file_size <= 54 or file_size > 100_000_000:
            raise ScpiTcpError(f"invalid BMP file size: {file_size}")
        rest = self._read_exact(sock, file_size - len(header))
        # Consume trailing newline(s) — SIGLENT appends \n after BMP data.
        # Only consume actual newline bytes; unexpected bytes are recorded, not discarded.
        try:
            sock.settimeout(0.1)
            tail = sock.recv(2)
            if tail and tail not in (b"\n", b"\r\n"):
                self._last_tail_bytes = tail  # noqa: SLF001 — diagnostic-only store
        except (TimeoutError, socket.timeout):
            pass
        finally:
            sock.settimeout(self.timeout_s)
        return header + rest

    @staticmethod
    def _read_until_timeout(sock: socket.socket) -> bytes:
        """Read until timeout or EOF — drains trailing bytes after binary payload.

        Returns all data read.  Break on timeout (no more data) or EOF (peer
        closed gracefully).  Does NOT silently discard bytes.
        """
        chunks: list[bytes] = []
        old_timeout = sock.gettimeout()
        sock.settimeout(0.2)
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:  # EOF — peer closed connection
                    break
                chunks.append(chunk)
        except (TimeoutError, socket.timeout):
            pass  # expected — no more data within timeout
        finally:
            sock.settimeout(old_timeout)
        return b"".join(chunks)


def _normalize_command(command: str) -> str:
    command = command.strip()
    if not command:
        raise ValueError("SCPI command must not be empty")
    return command
