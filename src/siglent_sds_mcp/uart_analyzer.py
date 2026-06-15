from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(slots=True)
class UartAnalysisResult:
    csv_path: str
    baudrate: int
    expected_bit_time_s: float
    estimated_high_v: float | None
    estimated_low_v: float | None
    estimated_vpp: float | None
    threshold_v: float | None
    edge_count: int
    median_edge_interval_s: float | None
    median_edge_interval_ns: float | None
    bit_time_error_percent: float | None
    verdict: str

    def to_dict(self) -> dict[str, object]:
        return {
            "csv_path": self.csv_path,
            "baudrate": self.baudrate,
            "expected_bit_time_s": self.expected_bit_time_s,
            "estimated_high_v": self.estimated_high_v,
            "estimated_low_v": self.estimated_low_v,
            "estimated_vpp": self.estimated_vpp,
            "threshold_v": self.threshold_v,
            "edge_count": self.edge_count,
            "median_edge_interval_s": self.median_edge_interval_s,
            "median_edge_interval_ns": self.median_edge_interval_ns,
            "bit_time_error_percent": self.bit_time_error_percent,
            "verdict": self.verdict,
        }


def analyze_uart_csv(csv_path: str | Path, baudrate: int = 2_000_000) -> UartAnalysisResult:
    """Analyze a simple two-column waveform CSV: time_s, voltage_v.

    This is a rough first-pass analyzer. It estimates voltage levels and transition timing.
    Protocol decoding will be added later after waveform export is implemented and verified.
    """

    path = Path(csv_path)
    samples = _load_samples(path)
    expected_bit_time_s = 1.0 / baudrate

    if len(samples) < 4:
        return UartAnalysisResult(
            csv_path=str(path),
            baudrate=baudrate,
            expected_bit_time_s=expected_bit_time_s,
            estimated_high_v=None,
            estimated_low_v=None,
            estimated_vpp=None,
            threshold_v=None,
            edge_count=0,
            median_edge_interval_s=None,
            median_edge_interval_ns=None,
            bit_time_error_percent=None,
            verdict="not_enough_samples",
        )

    voltages = [v for _, v in samples]
    low_v = min(voltages)
    high_v = max(voltages)
    vpp = high_v - low_v
    threshold = low_v + vpp / 2.0

    edge_times = _detect_threshold_edges(samples, threshold)
    intervals = [b - a for a, b in zip(edge_times, edge_times[1:]) if b > a]
    med_interval = median(intervals) if intervals else None
    error_percent = None
    verdict = "ok"

    if med_interval is not None:
        # For a 0x55-like pattern, edge interval is about one bit time.
        error_percent = (med_interval - expected_bit_time_s) / expected_bit_time_s * 100.0
        if abs(error_percent) > 10.0:
            verdict = "timing_suspect"
    else:
        verdict = "no_edges_detected"

    if vpp < 1.5:
        verdict = "voltage_suspect"

    return UartAnalysisResult(
        csv_path=str(path),
        baudrate=baudrate,
        expected_bit_time_s=expected_bit_time_s,
        estimated_high_v=high_v,
        estimated_low_v=low_v,
        estimated_vpp=vpp,
        threshold_v=threshold,
        edge_count=len(edge_times),
        median_edge_interval_s=med_interval,
        median_edge_interval_ns=med_interval * 1e9 if med_interval is not None else None,
        bit_time_error_percent=error_percent,
        verdict=verdict,
    )


def _load_samples(path: Path) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if "time_s" not in fields or "voltage_v" not in fields:
            raise ValueError("CSV must contain time_s and voltage_v columns")
        for row in reader:
            samples.append((float(row["time_s"]), float(row["voltage_v"])))
    return samples


def _detect_threshold_edges(samples: list[tuple[float, float]], threshold: float) -> list[float]:
    edges: list[float] = []
    prev_t, prev_v = samples[0]
    prev_state = prev_v >= threshold
    for t, v in samples[1:]:
        state = v >= threshold
        if state != prev_state:
            # Linear interpolation around threshold crossing.
            dv = v - prev_v
            if abs(dv) > 1e-15:
                ratio = (threshold - prev_v) / dv
                edge_t = prev_t + ratio * (t - prev_t)
            else:
                edge_t = t
            edges.append(edge_t)
        prev_t, prev_v, prev_state = t, v, state
    return edges
