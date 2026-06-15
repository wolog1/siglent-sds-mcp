from __future__ import annotations

import csv
from pathlib import Path

from siglent_sds_mcp.waveform_stats import analyze_waveform_csv


def test_analyze_waveform_csv_detects_active_square_wave(tmp_path: Path) -> None:
    path = tmp_path / "wave.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "voltage_v"])
        for i in range(100):
            writer.writerow([i * 1e-6, 3.3 if (i // 5) % 2 == 0 else 0.0])

    stats = analyze_waveform_csv(path)
    assert stats.points == 100
    assert stats.active_hint is True
    assert stats.v_pp is not None
    assert stats.v_pp > 3.0
    assert stats.edge_count > 5
    assert stats.sample_rate_sps is not None


def test_analyze_waveform_csv_marks_flat_signal_inactive(tmp_path: Path) -> None:
    path = tmp_path / "flat.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "voltage_v"])
        for i in range(20):
            writer.writerow([i * 1e-6, 1.2])

    stats = analyze_waveform_csv(path, noise_floor_v=0.05)
    assert stats.active_hint is False
    assert stats.v_pp == 0.0
    assert stats.edge_count == 0
