from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Literal

ThresholdMethod = Literal["auto_histogram", "midpoint"]

# Standard UART baud rates in ascending order.
STANDARD_BAUDS: tuple[int, ...] = (
    1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400,
    57600, 76800, 115200, 230400, 460800, 500000, 921600,
    1000000, 1500000, 2000000,
)


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


@dataclass(slots=True)
class UartBaudrateDetection:
    """Result of automatic baud-rate detection from raw waveform samples."""

    detected_baud: int | None
    measured_bit_time_s: float | None
    confidence: str          # "high" | "medium" | "low" | "none"
    candidates: list[dict[str, object]]
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "detected_baud": self.detected_baud,
            "measured_bit_time_s": self.measured_bit_time_s,
            "confidence": self.confidence,
            "candidates": self.candidates,
            "warnings": self.warnings,
        }


def auto_detect_baudrate(
    samples: list[tuple[float, float]],
    *,
    noise_run_threshold: int = 3,
    min_stable_runs: int = 5,
) -> UartBaudrateDetection:
    """Infer UART baud rate from a raw waveform sample list.

    Algorithm
    ---------
    1. Binarise the signal using a histogram double-peak threshold.
    2. Build the run-length sequence (each entry = number of consecutive
       samples at the same logic level).
    3. The shortest *stable* run (occurring at least *noise_run_threshold*
       times) is the best candidate for a 1-bit period in sample units.
    4. Convert to seconds using the sample interval *dt* inferred from the
       first two timestamps.
    5. Score every standard baud rate by checking whether the shortest
       stable run equals *n × BP* for small integer *n* (1..11), then rank
       by how close ratio is to a whole number.

    Returns
    -------
    ``UartBaudrateDetection`` with the best guess and a ranked candidate list.
    """
    warnings: list[str] = []
    candidates: list[dict[str, object]] = []

    if len(samples) < 4:
        return UartBaudrateDetection(
            detected_baud=None,
            measured_bit_time_s=None,
            confidence="none",
            candidates=[],
            warnings=["too few samples"],
        )

    dt = samples[1][0] - samples[0][0]
    if dt <= 0:
        return UartBaudrateDetection(
            detected_baud=None,
            measured_bit_time_s=None,
            confidence="none",
            candidates=[],
            warnings=["non-positive sample interval"],
        )

    voltages = [v for _, v in samples]
    low_v, high_v, threshold, _, thr_warns = _estimate_levels_and_threshold(voltages)
    warnings.extend(thr_warns)
    vpp = high_v - low_v

    if vpp < 0.05:
        warnings.append(f"low Vpp={vpp:.3f} V; baud detection may be unreliable")

    binary = [1 if v >= threshold else 0 for v in voltages]

    # Build run-length table.
    run_lengths: list[int] = []
    idx = 0
    while idx < len(binary):
        level = binary[idx]
        j = idx
        while j < len(binary) and binary[j] == level:
            j += 1
        run_lengths.append(j - idx)
        idx = j

    if not run_lengths:
        return UartBaudrateDetection(
            detected_baud=None,
            measured_bit_time_s=None,
            confidence="none",
            candidates=[],
            warnings=warnings + ["no runs found"],
        )

    rc = Counter(run_lengths)

    # Physical lower bound: a UART bit at the fastest supported baud rate
    # (921600) occupies at least 0.5 / (921600 * dt) samples.  Any run
    # shorter than this cannot be a real UART bit and is treated as noise.
    fastest_baud = STANDARD_BAUDS[-1]   # 921600
    min_physical_run = max(1, int(0.5 / (fastest_baud * dt)))

    # Find the shortest run that is:
    #   (a) longer than the physical noise floor, AND
    #   (b) appears at least noise_run_threshold times (repeating bit patterns).
    stable_runs = sorted(
        r for r, cnt in rc.items()
        if r >= min_physical_run and cnt >= noise_run_threshold
    )
    if not stable_runs:
        # Relax (b): accept any run above the physical floor.
        stable_runs = sorted(r for r in rc if r >= min_physical_run)
    if not stable_runs:
        # Full fallback — signal may be idle or extremely noisy.
        stable_runs = sorted(rc.keys())
        warnings.append(
            f"no run length appears >= {noise_run_threshold} times above "
            f"physical noise floor ({min_physical_run} samples); "
            "baud detection confidence is low"
        )

    min_run = stable_runs[0]
    min_run_time_s = min_run * dt

    # ── Score every standard baud rate with a global fit metric ────────────
    # For each candidate baud, compute how well the *entire* run-length
    # distribution is explained by integer multiples of one bit period (BP).
    # A run of length R is "explained" if round(R / BP) ≥ 1 and
    # |R - round(R/BP)*BP| / BP < tol.  The score is the fraction of run
    # *occurrences* (weighted by run length, i.e. time) that are explained.
    # This is far more robust than looking only at min_run, because it
    # avoids integer-multiple ambiguity (e.g. confusing 57600 with 19200).
    MATCH_TOL = 0.12          # ±12 % of one bit period
    MAX_BITS_PER_RUN = 10     # only consider runs up to 10 bits long

    for baud in STANDARD_BAUDS:
        bp = 1.0 / (baud * dt)   # expected BP in samples (float)
        total_time = 0
        matched_time = 0
        for r, cnt in rc.items():
            n_bits = round(r / bp)
            if n_bits < 1 or n_bits > MAX_BITS_PER_RUN:
                continue
            total_time += r * cnt
            err_frac = abs(r - n_bits * bp) / bp
            if err_frac < MATCH_TOL:
                matched_time += r * cnt

        if total_time == 0:
            continue
        fit = matched_time / total_time   # 0..1, higher = better

        # Only add to candidates when min_run also aligns with this baud.
        min_n = round(min_run / bp)
        if min_n < 1 or min_n > MAX_BITS_PER_RUN:
            continue
        min_err_frac = abs(min_run - min_n * bp) / bp
        if min_err_frac >= MATCH_TOL:
            continue

        measured_bt = min_run / min_n * dt
        err_pct_val = min_err_frac * 100.0
        candidates.append({
            "baud": baud,
            "n_bits": min_n,
            "ratio": round(min_run / (min_n * bp), 4),
            "error_pct": round(err_pct_val, 2),
            "measured_bit_time_s": measured_bt,
            "fit_score": round(fit, 4),
        })

    if not candidates:
        warnings.append(
            f"shortest stable run {min_run} ({min_run_time_s * 1e6:.2f} µs) "
            "does not match any standard baud rate within ±15%"
        )
        return UartBaudrateDetection(
            detected_baud=None,
            measured_bit_time_s=min_run_time_s,
            confidence="none",
            candidates=[],
            warnings=warnings,
        )

    # Sort: best fit_score first, then prefer lower n_bits, then lower error.
    candidates.sort(key=lambda c: (-c["fit_score"], c["n_bits"], c["error_pct"]))
    best = candidates[0]
    best_baud: int = int(best["baud"])
    best_bt: float = float(best["measured_bit_time_s"])
    err_pct: float = float(best["error_pct"])
    fit_score: float = float(best["fit_score"])

    if fit_score >= 0.80 and best["n_bits"] == 1 and err_pct < 3.0:
        confidence = "high"
    elif fit_score >= 0.60 and err_pct < 8.0:
        confidence = "medium"
    else:
        confidence = "low"

    if len({c["baud"] for c in candidates}) > 1:
        alt_bauds = sorted({c["baud"] for c in candidates} - {best_baud})
        warnings.append(f"multiple baud rate candidates: {[best_baud] + alt_bauds}")

    return UartBaudrateDetection(
        detected_baud=best_baud,
        measured_bit_time_s=best_bt,
        confidence=confidence,
        candidates=candidates,
        warnings=warnings,
    )


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

    # Estimate actual bit time from run-length statistics.
    # Run-length = duration of a constant-level segment; each run is an integer
    # number of bit times.  Runs whose length is within ±15% of expected_bit_time_s
    # are treated as single-bit runs and averaged to obtain the measured bit time.
    # This compensates for crystal-tolerance deviations (commonly up to ±5%).
    actual_bit_time_s = _estimate_bit_time_from_runs(logic, expected_bit_time_s)
    if abs(actual_bit_time_s - expected_bit_time_s) / expected_bit_time_s > 0.03:
        actual_baud = int(round(1.0 / actual_bit_time_s))
        warnings.append(
            f"measured bit time {actual_bit_time_s * 1e6:.2f} µs differs from nominal "
            f"{expected_bit_time_s * 1e6:.2f} µs by "
            f"{(actual_bit_time_s - expected_bit_time_s) / expected_bit_time_s * 100:.1f}%; "
            f"using measured value (≈{actual_baud} baud) for decoding"
        )

    frames = _decode_uart_8n1(logic, actual_bit_time_s, idle_high=True)
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
            # Jump past D7 but not past the stop bit, so the loop can scan
            # forward and find the next HIGH→LOW start edge without risk of
            # the jump target landing exactly on (and thus skipping) the very
            # first sample of the following start bit.  9.0× lands mid-stop-bit
            # region, which is always safely before the next start-bit edge.
            i = _first_index_after(logic, start_t + 9.0 * bit_time_s, start=i)
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


def _estimate_bit_time_from_runs(
    logic: list[tuple[float, int]],
    expected_bit_time_s: float,
) -> float:
    """Estimate actual bit time by averaging single-bit run durations.

    Builds the run-length sequence from *logic* (list of (time, level) pairs
    with uniform spacing) and collects runs whose duration falls within ±15% of
    *expected_bit_time_s*.  These are single-bit runs; their mean duration is
    the measured bit time.  Falls back to *expected_bit_time_s* when fewer than
    3 single-bit runs are found (e.g. constant signal, too few edges).

    The returned value is snapped to the nearest integer multiple of the
    sample interval *dt* (inferred from the first two logic samples).  This
    prevents a tiny floating-point upward bias in the average from causing
    ``start_t + 10 * bit_time`` to overshoot the exact timestamp of the next
    start bit and skip it in ``_first_index_after``.
    """
    if len(logic) < 2:
        return expected_bit_time_s

    # Infer sample interval from the first two timestamps.
    dt = logic[1][0] - logic[0][0]

    lo = expected_bit_time_s * 0.85
    hi = expected_bit_time_s * 1.15

    single_bit_durations: list[float] = []
    run_start_t = logic[0][0]
    run_level = logic[0][1]
    for t, level in logic[1:]:
        if level != run_level:
            duration = t - run_start_t
            if lo <= duration <= hi:
                single_bit_durations.append(duration)
            run_start_t = t
            run_level = level
    # last run
    duration = logic[-1][0] - run_start_t
    if lo <= duration <= hi:
        single_bit_durations.append(duration)

    if len(single_bit_durations) < 3:
        return expected_bit_time_s

    raw_mean = sum(single_bit_durations) / len(single_bit_durations)

    # Snap to the nearest integer number of samples so that the inferred bit
    # time aligns with the sample grid.  This avoids a systematic upward bias
    # (from floating-point accumulation in the sample timestamps) causing the
    # jump target ``start_t + 10 * bit_time`` to overshoot the next start bit.
    if dt > 0:
        n_samples = round(raw_mean / dt)
        return n_samples * dt
    return raw_mean


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
