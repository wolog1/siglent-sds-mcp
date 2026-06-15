from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(slots=True)
class WaveformStats:
    csv_path: str
    points: int
    t_min: float | None
    t_max: float | None
    v_min: float | None
    v_max: float | None
    v_mean: float | None
    v_pp: float | None
    threshold_v: float | None
    edge_count: int
    median_edge_interval_s: float | None
    median_edge_interval_ns: float | None
    sample_interval_s: float | None
    sample_rate_sps: float | None
    clipping_hint: bool
    active_hint: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "csv_path": self.csv_path,
            "points": self.points,
            "t_min": self.t_min,
            "t_max": self.t_max,
            "v_min": self.v_min,
            "v_max": self.v_max,
            "v_mean": self.v_mean,
            "v_pp": self.v_pp,
            "threshold_v": self.threshold_v,
            "edge_count": self.edge_count,
            "median_edge_interval_s": self.median_edge_interval_s,
            "median_edge_interval_ns": self.median_edge_interval_ns,
            "sample_interval_s": self.sample_interval_s,
            "sample_rate_sps": self.sample_rate_sps,
            "clipping_hint": self.clipping_hint,
            "active_hint": self.active_hint,
        }


def analyze_waveform_csv(csv_path: str | Path, noise_floor_v: float = 0.05) -> WaveformStats:
    """Compute basic waveform statistics from a `time_s,voltage_v` CSV file."""

    path = Path(csv_path)
    samples = _load_samples(path)
    if len(samples) < 2:
        return WaveformStats(
            csv_path=str(path),
            points=len(samples),
            t_min=None,
            t_max=None,
            v_min=None,
            v_max=None,
            v_mean=None,
            v_pp=None,
            threshold_v=None,
            edge_count=0,
            median_edge_interval_s=None,
            median_edge_interval_ns=None,
            sample_interval_s=None,
            sample_rate_sps=None,
            clipping_hint=False,
            active_hint=False,
        )

    times = [t for t, _ in samples]
    voltages = [v for _, v in samples]
    v_min = min(voltages)
    v_max = max(voltages)
    v_pp = v_max - v_min
    v_mean = sum(voltages) / len(voltages)
    threshold = v_min + v_pp / 2.0

    edge_times = _detect_threshold_edges(samples, threshold)
    intervals = [b - a for a, b in zip(edge_times, edge_times[1:]) if b > a]
    med_edge = median(intervals) if intervals else None

    time_steps = [b - a for a, b in zip(times, times[1:]) if b > a]
    sample_interval = median(time_steps) if time_steps else None
    sample_rate = 1.0 / sample_interval if sample_interval and sample_interval > 0 else None

    # A rough hint: if many points sit close to extrema, the waveform may be clipped or the
    # vertical range may be too small. This is not a proof, only an auto-ranging hint.
    clipping_hint = False
    if v_pp > 0:
        low_band = v_min + v_pp * 0.02
        high_band = v_max - v_pp * 0.02
        low_count = sum(1 for v in voltages if v <= low_band)
        high_count = sum(1 for v in voltages if v >= high_band)
        clipping_hint = (low_count + high_count) / len(voltages) > 0.25

    return WaveformStats(
        csv_path=str(path),
        points=len(samples),
        t_min=min(times),
        t_max=max(times),
        v_min=v_min,
        v_max=v_max,
        v_mean=v_mean,
        v_pp=v_pp,
        threshold_v=threshold,
        edge_count=len(edge_times),
        median_edge_interval_s=med_edge,
        median_edge_interval_ns=med_edge * 1e9 if med_edge is not None else None,
        sample_interval_s=sample_interval,
        sample_rate_sps=sample_rate,
        clipping_hint=clipping_hint,
        active_hint=v_pp >= noise_floor_v,
    )


def _load_samples(path: Path) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "time_s" not in reader.fieldnames or "voltage_v" not in reader.fieldnames:
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
