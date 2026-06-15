from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(slots=True)
class Rs485AnalysisResult:
    csv_a_path: str
    csv_b_path: str
    baudrate: int
    expected_bit_time_s: float
    points: int
    va_min: float | None
    va_max: float | None
    vb_min: float | None
    vb_max: float | None
    vdiff_min: float | None
    vdiff_max: float | None
    vdiff_vpp: float | None
    common_mode_min: float | None
    common_mode_max: float | None
    threshold_v: float
    edge_count: int
    median_edge_interval_s: float | None
    median_edge_interval_ns: float | None
    bit_time_error_percent: float | None
    verdict: str
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "csv_a_path": self.csv_a_path,
            "csv_b_path": self.csv_b_path,
            "baudrate": self.baudrate,
            "expected_bit_time_s": self.expected_bit_time_s,
            "points": self.points,
            "va_min": self.va_min,
            "va_max": self.va_max,
            "vb_min": self.vb_min,
            "vb_max": self.vb_max,
            "vdiff_min": self.vdiff_min,
            "vdiff_max": self.vdiff_max,
            "vdiff_vpp": self.vdiff_vpp,
            "common_mode_min": self.common_mode_min,
            "common_mode_max": self.common_mode_max,
            "threshold_v": self.threshold_v,
            "edge_count": self.edge_count,
            "median_edge_interval_s": self.median_edge_interval_s,
            "median_edge_interval_ns": self.median_edge_interval_ns,
            "bit_time_error_percent": self.bit_time_error_percent,
            "verdict": self.verdict,
            "warnings": self.warnings,
        }


def analyze_rs485_pair_csv(
    csv_a_path: str | Path,
    csv_b_path: str | Path,
    baudrate: int = 2_000_000,
    threshold_v: float = 0.0,
) -> Rs485AnalysisResult:
    """Analyze two waveform CSV files as RS485 A/B and compute Vdiff = VA - VB.

    Each CSV must contain `time_s` and `voltage_v` columns. The analyzer pairs samples
    by index. For real use, export both channels using the same capture settings.
    """

    path_a = Path(csv_a_path)
    path_b = Path(csv_b_path)
    a_samples = _load_samples(path_a)
    b_samples = _load_samples(path_b)
    n = min(len(a_samples), len(b_samples))
    expected_bit_time_s = 1.0 / baudrate

    if n < 4:
        return Rs485AnalysisResult(
            csv_a_path=str(path_a),
            csv_b_path=str(path_b),
            baudrate=baudrate,
            expected_bit_time_s=expected_bit_time_s,
            points=n,
            va_min=None,
            va_max=None,
            vb_min=None,
            vb_max=None,
            vdiff_min=None,
            vdiff_max=None,
            vdiff_vpp=None,
            common_mode_min=None,
            common_mode_max=None,
            threshold_v=threshold_v,
            edge_count=0,
            median_edge_interval_s=None,
            median_edge_interval_ns=None,
            bit_time_error_percent=None,
            verdict="not_enough_samples",
            warnings=["Need at least 4 paired samples."],
        )

    times = [a_samples[i][0] for i in range(n)]
    va = [a_samples[i][1] for i in range(n)]
    vb = [b_samples[i][1] for i in range(n)]
    vdiff = [va[i] - vb[i] for i in range(n)]
    common_mode = [(va[i] + vb[i]) / 2.0 for i in range(n)]

    edge_times = _detect_threshold_edges(list(zip(times, vdiff)), threshold_v)
    intervals = [b - a for a, b in zip(edge_times, edge_times[1:]) if b > a]
    med_interval = median(intervals) if intervals else None
    error_percent = None
    warnings: list[str] = []

    if med_interval is not None:
        error_percent = (med_interval - expected_bit_time_s) / expected_bit_time_s * 100.0
        if abs(error_percent) > 10.0:
            warnings.append("Median transition interval deviates from expected bit time by more than 10%.")
    else:
        warnings.append("No Vdiff threshold crossing detected.")

    vdiff_min = min(vdiff)
    vdiff_max = max(vdiff)
    vdiff_vpp = vdiff_max - vdiff_min
    if vdiff_vpp < 0.4:
        warnings.append("Differential swing is very small; check wiring, termination, probe setup or bus activity.")
    if max(abs(vdiff_min), abs(vdiff_max)) < 0.2:
        warnings.append("Differential voltage does not clearly exceed a typical ±200 mV RS485 receiver threshold.")

    cm_min = min(common_mode)
    cm_max = max(common_mode)
    if cm_min < -7.0 or cm_max > 12.0:
        warnings.append("Common-mode voltage appears outside the typical RS485 receiver range; verify grounding and measurement reference.")

    verdict = "ok" if not warnings else "suspect"

    return Rs485AnalysisResult(
        csv_a_path=str(path_a),
        csv_b_path=str(path_b),
        baudrate=baudrate,
        expected_bit_time_s=expected_bit_time_s,
        points=n,
        va_min=min(va),
        va_max=max(va),
        vb_min=min(vb),
        vb_max=max(vb),
        vdiff_min=vdiff_min,
        vdiff_max=vdiff_max,
        vdiff_vpp=vdiff_vpp,
        common_mode_min=cm_min,
        common_mode_max=cm_max,
        threshold_v=threshold_v,
        edge_count=len(edge_times),
        median_edge_interval_s=med_interval,
        median_edge_interval_ns=med_interval * 1e9 if med_interval is not None else None,
        bit_time_error_percent=error_percent,
        verdict=verdict,
        warnings=warnings,
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
            dv = v - prev_v
            if abs(dv) > 1e-15:
                ratio = (threshold - prev_v) / dv
                edge_t = prev_t + ratio * (t - prev_t)
            else:
                edge_t = t
            edges.append(edge_t)
        prev_t, prev_v, prev_state = t, v, state
    return edges
