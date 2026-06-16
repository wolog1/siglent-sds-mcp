from __future__ import annotations

import csv
from pathlib import Path

from siglent_sds_mcp.uart_analyzer import analyze_uart_csv


def _write_uart_csv(
    path: Path,
    payload: bytes,
    *,
    baudrate: int = 115200,
    high_v: float = 5.2,
    low_v: float = 4.95,
    sample_per_bit: int = 16,
    idle_bits: int = 4,
) -> None:
    bit_time = 1.0 / baudrate
    dt = bit_time / sample_per_bit
    samples: list[tuple[float, float]] = []
    t = 0.0

    def append_bit(level: int, bits: int = 1) -> None:
        nonlocal t
        voltage = high_v if level else low_v
        for _ in range(bits * sample_per_bit):
            samples.append((t, voltage))
            t += dt

    append_bit(1, idle_bits)
    for byte in payload:
        append_bit(0)  # start
        for bit_index in range(8):
            append_bit((byte >> bit_index) & 1)
        append_bit(1)  # stop
    append_bit(1, idle_bits)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "voltage_v"])
        writer.writerows(samples)


def test_decode_single_uart_byte_0x55(tmp_path: Path) -> None:
    csv_path = tmp_path / "uart_55.csv"
    _write_uart_csv(csv_path, b"\x55")

    result = analyze_uart_csv(csv_path, baudrate=115200)

    assert result.verdict == "ok"
    assert result.decoded_bytes == [0x55]
    assert result.decoded_hex == "55"
    assert result.frames[0].stop_ok is True
    assert result.frames[0].bits == [1, 0, 1, 0, 1, 0, 1, 0]
    assert result.threshold_method == "auto_histogram"


def test_decode_uart_ascii_message(tmp_path: Path) -> None:
    csv_path = tmp_path / "uart_hi.csv"
    _write_uart_csv(csv_path, b"Hi")

    result = analyze_uart_csv(csv_path, baudrate=115200)

    assert result.verdict == "ok"
    assert result.decoded_bytes == [0x48, 0x69]
    assert result.decoded_hex == "48 69"
    assert result.decoded_ascii == "Hi"


def test_low_vpp_uart_still_decodes_with_warning(tmp_path: Path) -> None:
    csv_path = tmp_path / "uart_low_vpp.csv"
    _write_uart_csv(csv_path, b"A", high_v=5.2, low_v=5.0)

    result = analyze_uart_csv(csv_path, baudrate=115200)

    assert result.decoded_hex == "41"
    assert result.estimated_vpp is not None
    assert result.estimated_vpp < 0.25


def test_decode_with_5pct_baud_deviation(tmp_path: Path) -> None:
    """5% crystal deviation: actual baud 121026 but caller passes 115200.

    The run-length estimator should recover the measured bit time and decode
    correctly, emitting a warning about the deviation.
    """
    csv_path = tmp_path / "uart_5pct_dev.csv"
    # actual bit time is 5% shorter than 115200 nominal → ~121026 baud
    actual_baudrate = int(115200 * 1.05)
    _write_uart_csv(csv_path, b"jintainshigehaorizhi\r\n", baudrate=actual_baudrate,
                    high_v=3.3, low_v=0.0, sample_per_bit=20)

    result = analyze_uart_csv(csv_path, baudrate=115200)

    assert result.decoded_bytes == list(b"jintainshigehaorizhi\r\n"), (
        f"decoded: {result.decoded_ascii!r}"
    )
    assert result.verdict in ("ok", "partial_decode")
    # warning must mention measured bit time
    assert any("measured bit time" in w for w in result.warnings)
