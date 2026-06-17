from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from siglent_sds_mcp import uart_capture
from siglent_sds_mcp.uart_capture import capture_uart_auto


FALLBACK_WAVEDESC_DT_S = 1e-8


def _uart_dat2_bytes(
    payload: bytes,
    *,
    baudrate: int = 115200,
    dt_s: float = FALLBACK_WAVEDESC_DT_S,
) -> bytes:
    samples_per_bit = max(1, round((1.0 / baudrate) / dt_s))
    codes: list[int] = []

    def append_level(level: int, bits: int = 1) -> None:
        code = 90 if level else 0
        for _ in range(bits * samples_per_bit):
            codes.append(code)

    append_level(1, 4)
    for byte in payload:
        append_level(0)  # start bit
        for bit_index in range(8):
            append_level((byte >> bit_index) & 1)
        append_level(1)  # stop bit
    append_level(1, 4)
    return bytes(codes)


def test_capture_uart_auto_explicit_baud_does_not_require_decode_parity_assignment(
    monkeypatch,
) -> None:
    monkeypatch.setattr(uart_capture.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(uart_capture, "arm_until_valid", lambda *args, **kwargs: True)

    transport = MagicMock()

    def fake_query(command: str) -> str:
        if command.endswith("PAVA? MAX"):
            return "MAX,6.0000E-01"
        if command.endswith("PAVA? MIN"):
            return "MIN,0.0000E+00"
        if command.endswith("PAVA? PKPK"):
            return "PKPK,6.0000E-01"
        if command == "SAST?":
            return "Stop"
        return "0"

    def fake_query_binary(command: str):
        if command.endswith("WF? DESC"):
            return SimpleNamespace(data=b"short descriptor uses defaults")
        if command.endswith("WF? DAT2"):
            return SimpleNamespace(data=_uart_dat2_bytes(b"A", baudrate=115200))
        raise AssertionError(f"unexpected binary command: {command}")

    transport.query.side_effect = fake_query
    transport.query_binary.side_effect = fake_query_binary

    result = capture_uart_auto(
        transport,
        channel="C1",
        baudrate=115200,
        probe_attn=1.0,
        max_bytes=1,
        timeout_s=1.0,
        min_pkpk_v=0.1,
    )

    assert result.ok is True
    assert result.decoded_bytes == [0x41]
    assert result.decoded_hex == "41"
    assert result.measured_baud is not None
