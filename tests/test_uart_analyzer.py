from __future__ import annotations

import csv
from pathlib import Path

from siglent_sds_mcp.uart_analyzer import analyze_uart_csv


def test_analyze_uart_csv_2mbps_square_wave(tmp_path: Path) -> None:
    path = tmp_path / "uart.csv"
    bit_time = 0.5e-6
    samples_per_bit = 20
    dt = bit_time / samples_per_bit

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "voltage_v"])
        for i in range(20 * samples_per_bit):
            bit_index = i // samples_per_bit
            voltage = 3.3 if bit_index % 2 == 0 else 0.0
            writer.writerow([i * dt, voltage])

    result = analyze_uart_csv(path, baudrate=2_000_000)
    # The square wave is not a real UART stream; at least one frame decodes
    # correctly, but the waveform is truncated before the stop bit of a second
    # frame.  Accept either "ok" or "partial_decode" here.
    assert result.verdict in ("ok", "partial_decode")
    assert result.edge_count >= 5
    assert result.estimated_vpp is not None
    assert result.estimated_vpp > 3.0
    assert result.bit_time_error_percent is not None
    assert abs(result.bit_time_error_percent) < 10.0
