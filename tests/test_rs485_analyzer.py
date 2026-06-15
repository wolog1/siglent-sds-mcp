from __future__ import annotations

import csv
from pathlib import Path

from siglent_sds_mcp.rs485_analyzer import analyze_rs485_pair_csv


def test_analyze_rs485_pair_2mbps_differential_square_wave(tmp_path: Path) -> None:
    a_path = tmp_path / "a.csv"
    b_path = tmp_path / "b.csv"
    bit_time = 0.5e-6
    samples_per_bit = 20
    dt = bit_time / samples_per_bit

    with a_path.open("w", newline="", encoding="utf-8") as fa, b_path.open(
        "w", newline="", encoding="utf-8"
    ) as fb:
        writer_a = csv.writer(fa)
        writer_b = csv.writer(fb)
        writer_a.writerow(["time_s", "voltage_v"])
        writer_b.writerow(["time_s", "voltage_v"])
        for i in range(20 * samples_per_bit):
            bit_index = i // samples_per_bit
            state = bit_index % 2 == 0
            va = 3.2 if state else 1.0
            vb = 1.0 if state else 3.2
            t = i * dt
            writer_a.writerow([t, va])
            writer_b.writerow([t, vb])

    result = analyze_rs485_pair_csv(a_path, b_path, baudrate=2_000_000)
    assert result.verdict == "ok"
    assert result.edge_count >= 5
    assert result.vdiff_vpp is not None
    assert result.vdiff_vpp > 4.0
    assert result.bit_time_error_percent is not None
    assert abs(result.bit_time_error_percent) < 10.0


def test_analyze_rs485_pair_warns_on_small_differential(tmp_path: Path) -> None:
    a_path = tmp_path / "a_small.csv"
    b_path = tmp_path / "b_small.csv"
    with a_path.open("w", newline="", encoding="utf-8") as fa, b_path.open(
        "w", newline="", encoding="utf-8"
    ) as fb:
        writer_a = csv.writer(fa)
        writer_b = csv.writer(fb)
        writer_a.writerow(["time_s", "voltage_v"])
        writer_b.writerow(["time_s", "voltage_v"])
        for i in range(10):
            t = i * 1e-6
            writer_a.writerow([t, 2.5])
            writer_b.writerow([t, 2.45])

    result = analyze_rs485_pair_csv(a_path, b_path, baudrate=9600)
    assert result.verdict == "suspect"
    assert result.warnings
