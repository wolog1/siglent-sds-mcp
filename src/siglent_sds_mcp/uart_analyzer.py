from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Literal

ThresholdMethod = Literal["auto_histogram", "midpoint"]


@dataclass(slots=True)
class UartFrame:
    start_time_s: float
    byte: int | None
    bits: list[int]
    stop_bit: int | None
    stop_ok: bool
    framing_ok: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "start_time_s": self.start_time_s,
            "start_time_us": self.start_time_s * 1e6,
            "byte": self.byte,
            "byte_hex": f"0x{self.byte:02X}" if self.byte is not None else None,
            "bits": self.bits,
            "stop_bit": self.stop_bit,
            "stop_ok": self.stop_ok,
            "framing_ok": self.framing_ok,
            "reason": self.reason,
        }


@dataclass(slots=True)
class UartAnalysisResult:
    csv_path: str
    baudrate: int
    expected_bit_time_s: float
    estimated_high_v: float | None
    estimated_low_v: float | None
    estimated_vpp: float | None
    threshold_v: float | None
    threshold_method: ThresholdMethod | None
    idle_state: int | None
    edge_count: int
    median_edge_interval_s: float | None
    median_edge_interval_ns: float | None
    bit_time_error_percent: float | None
    decoded_bytes: list[int] = field(default_factory=list)
    decoded_hex: str = ""
    decoded_ascii: str = ""
    frames: list[UartFrame] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verdict: str = "unknown"

    def to_dict(self) -> dict[str, object]:
        return {
            "csv_path": self.csv_path,
            "baudrate": self.baudrate,
            "expected_bit_time_s": self.expected_bit_time_s,
            "estimated_high_v": self.estimated_high_v,
            "estimated_low_v": self.estimated_low_v,
            "estimated_vpp": self.estimated_vpp,
            "threshold_v": self.threshold_v,
            "threshold_method": self.threshold_method,
            "idle_state": self.idle_state,
            "edge_count": self.edge_count,
            "median_edge_interval_s": self.median_edge_interval_s,
            "median_edge_interval_ns": self.median_edge_interval_ns,
            "bit_time_error_percent": self.bit_time_error_percent,
            "decoded_bytes": self.decoded_bytes,
            "decoded_hex": self.decoded_hex,
            "decoded_ascii": self.decoded_ascii,
            "frames": [frame.to_dict() for frame in self.frames],
            "warnings": self.warnings,
            "verdict": self.verdict,
        }


def analyze_uart_csv(csv_path: str | Path, baudrate: int = 2_000_000) -> UartAnalysisResult:
    """Analyze and decode a two-column UART waveform CSV: time_s, voltage_v.

    Assumptions: 8 data bits, no parity, 1 stop bit (8N1), idle-high UART.
    The analyzer still returns timing/voltage diagnostics for compatibility,
    but now also performs start-bit detection and LSB-first byte decoding.
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
            threshold_method=None,
            idle_state=None,
            edge_count=0,
            median_edge_interval_s=None,
            median_edge_interval_ns=None,
            bit_time_error_percent=None,
            verdict="not_enough_samples",
        )

    voltages = [v for _, v in samples]
    low_v, high_v, threshold, threshold_method, threshold_warnings = _estimate_levels_and_threshold(
        voltages
    )
    vpp = high_v - low_v
    logic = [(t, 1 if v >= threshold else 0) for t, v in samples]
    idle_state = _estimate_idle_state(logic)

    edge_times = _detect_threshold_edges(samples, threshold)
    intervals = [b - a for a, b in zip(edge_times, edge_times[1:]) if b > a]
    med_interval = median(intervals) if intervals else None
    error_percent = None
    warnings = list(threshold_warnings)

    if med_interval is not None:
        error_percent = (med_interval - expected_bit_time_s) / expected_bit_time_s * 100.0
        if abs(error_percent) > 20.0:
            warnings.append(
                "median edge interval differs from UART bit time; this is expected for "
                "non-0x55 data but can indicate wrong dt/baudrate"
            )

    if idle_state != 1:
        warnings.append("estimated idle state is not high; UART polarity may be inverted or frame truncated")

    frames = _decode_uart_8n1(logic, expected_bit_time_s, idle_high=True)
    decoded_bytes = [frame.byte for frame in frames if frame.byte is not None and frame.framing_ok]
    decoded_hex = " ".join(f"{byte:02X}" for byte in decoded_bytes)
    decoded_ascii = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in decoded_bytes)

    if not frames:
        verdict = "no_uart_frames_detected"
    elif decoded_bytes and all(frame.framing_ok for frame in frames if frame.byte is not None):
        verdict = "ok"
    elif decoded_bytes:
        verdict = "partial_decode"
    else:
        verdict = "framing_suspect"

    if vpp <= 0:
        verdict = "voltage_suspect"
        warnings.append("waveform has no voltage span")
    elif vpp < 0.05:
        warnings.append("low Vpp signal; decode relies on threshold statistics and may be fragile")

    return UartAnalysisResult(
        csv_path=str(path),
        baudrate=baudrate,
        expected_bit_time_s=expected_bit_time_s,
        estimated_high_v=high_v,
        estimated_low_v=low_v,
        estimated_vpp=vpp,
        threshold_v=threshold,
        threshold_method=threshold_method,
        idle_state=idle_state,
        edge_count=len(edge_times),
        median_edge_interval_s=med_interval,
        median_edge_interval_ns=med_interval * 1e9 if med_interval is not None else None,
        bit_time_error_percent=error_percent,
        decoded_bytes=decoded_bytes,
        decoded_hex=decoded_hex,
        decoded_ascii=decoded_ascii,
        frames=frames,
        warnings=warnings,
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
    samples.sort(key=lambda item: item[0])
    return samples


def _estimate_levels_and_threshold(
    voltages: list[float],
) -> tuple[float, float, float, ThresholdMethod, list[str]]:
    warnings: list[str] = []
    low_v = min(voltages)
    high_v = max(voltages)
    vpp = high_v - low_v
    if vpp <= 0:
        return low_v, high_v, low_v, "midpoint", ["constant waveform; threshold equals sample value"]

    bins = min(128, max(16, int(len(voltages) ** 0.5)))
    counts = [0] * bins
    for voltage in voltages:
        idx = int((voltage - low_v) / vpp * (bins - 1))
        counts[max(0, min(bins - 1, idx))] += 1

    peak_indices = sorted(range(bins), key=lambda idx: counts[idx], reverse=True)
    first = peak_indices[0]
    second = None
    min_separation = max(2, bins // 8)
    for idx in peak_indices[1:]:
        if abs(idx - first) >= min_separation:
            second = idx
            break

    if second is None:
        threshold = low_v + vpp / 2.0
        warnings.append("histogram did not find two separated peaks; using min/max midpoint")
        return low_v, high_v, threshold, "midpoint", warnings

    low_peak_idx, high_peak_idx = sorted([first, second])
    low_level = _bin_center(low_v, vpp, bins, low_peak_idx)
    high_level = _bin_center(low_v, vpp, bins, high_peak_idx)
    threshold = (low_level + high_level) / 2.0
    return low_level, high_level, threshold, "auto_histogram", warnings


def _bin_center(low_v: float, vpp: float, bins: int, idx: int) -> float:
    return low_v + (idx + 0.5) * vpp / bins


def _estimate_idle_state(logic: list[tuple[float, int]]) -> int | None:
    if not logic:
        return None
    head = logic[: max(1, min(len(logic), len(logic) // 20 or 1))]
    tail = logic[-max(1, min(len(logic), len(logic) // 20 or 1)):]
    ones = sum(state for _, state in head + tail)
    return 1 if ones >= len(head + tail) / 2 else 0


def _decode_uart_8n1(
    logic: list[tuple[float, int]],
    bit_time_s: float,
    *,
    idle_high: bool = True,
) -> list[UartFrame]:
    frames: list[UartFrame] = []
    if len(logic) < 2 or bit_time_s <= 0:
        return frames

    idle = 1 if idle_high else 0
    start_level = 0 if idle_high else 1
    i = 1
    while i < len(logic):
        prev_state = logic[i - 1][1]
        state = logic[i][1]
        if prev_state == idle and state == start_level:
            start_t = logic[i][0]
            bits: list[int] = []
            ok = True
            reason = "ok"
            for bit_index in range(8):
                sample_t = start_t + (1.5 + bit_index) * bit_time_s
                bit = _sample_logic_at(logic, sample_t)
                if bit is None:
                    ok = False
                    reason = "data bit sample outside waveform"
                    break
                bits.append(bit)
            stop_bit = None
            if ok:
                stop_t = start_t + 9.5 * bit_time_s
                stop_bit = _sample_logic_at(logic, stop_t)
                if stop_bit is None:
                    ok = False
                    reason = "stop bit sample outside waveform"
                elif stop_bit != idle:
                    ok = False
                    reason = "stop bit not idle level"

            byte = None
            if bits:
                byte = sum(bit << bit_index for bit_index, bit in enumerate(bits))
            frames.append(
                UartFrame(
                    start_time_s=start_t,
                    byte=byte if len(bits) == 8 else None,
                    bits=bits,
                    stop_bit=stop_bit,
                    stop_ok=stop_bit == idle if stop_bit is not None else False,
                    framing_ok=ok and len(bits) == 8,
                    reason=reason,
                )
            )
            i = _first_index_after(logic, start_t + 10.0 * bit_time_s, start=i)
        else:
            i += 1
    return frames


def _sample_logic_at(logic: list[tuple[float, int]], sample_t: float) -> int | None:
    if sample_t < logic[0][0] or sample_t > logic[-1][0]:
        return None
    lo = 0
    hi = len(logic) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if logic[mid][0] <= sample_t:
            lo = mid + 1
        else:
            hi = mid - 1
    return logic[max(0, hi)][1]


def _first_index_after(logic: list[tuple[float, int]], t: float, *, start: int = 0) -> int:
    idx = max(0, start)
    while idx < len(logic) and logic[idx][0] <= t:
        idx += 1
    return idx


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
