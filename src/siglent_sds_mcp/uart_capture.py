"""uart_capture.py — End-to-end UART waveform capture and auto-decode.

Fixes implemented
-----------------
P1  VDIV/OFST auto-ranging: measures MAX/MIN in AUTO mode first, then
    computes the best VDIV and OFST so the signal fills ~6 vertical
    divisions.  Falls back gracefully when measurements are unavailable.

P2  Baud-rate auto-detection: calls ``auto_detect_baudrate()`` from
    ``uart_analyzer`` to infer the baud rate from run-length statistics
    before decoding.  The caller may still supply an explicit baudrate;
    the detected value is used when baudrate=0 (auto).

P3  Noise-trigger retry: after each SINGLE trigger, verifies PKPK > 1 V
    (configurable).  If the trigger fires on noise the function re-ARMs
    automatically, up to *max_trigger_attempts* times.

P4  TDIV auto-calculation: given a target message length estimate and
    baudrate, selects the narrowest standard TDIV that fits the message
    with a 2× safety margin, keeping the sample count manageable.

P5  cpd (codes-per-div) sanity-check: after reading WAVEDESC, checks
    whether the computed Vpp matches the measured Vpp.  If the two differ
    by more than 50 % the function re-derives cpd from the measured MAX/MIN
    values so that voltage conversion is correct.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import Literal

# Standard TDIV steps (seconds/div) supported by SDS800X HD.
_TDIV_STEPS_S: tuple[float, ...] = (
    1e-9, 2e-9, 5e-9, 10e-9, 20e-9, 50e-9,
    100e-9, 200e-9, 500e-9,
    1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6,
    100e-6, 200e-6, 500e-6,
    1e-3, 2e-3, 5e-3, 10e-3, 20e-3, 50e-3,
    100e-3, 200e-3,
)
_TDIV_DIVISIONS = 14          # SDS800X HD horizontal grid count
_VDIV_STEPS_V: tuple[float, ...] = (
    0.001, 0.002, 0.005,
    0.01, 0.02, 0.05,
    0.1, 0.2, 0.5,
    1.0, 2.0, 5.0, 10.0,
)
_VDIV_DIVISIONS = 8           # vertical grid count


Channel = Literal["C1", "C2", "C3", "C4"]


# ---------------------------------------------------------------------------
# P4: TDIV auto-calculation
# ---------------------------------------------------------------------------

def best_tdiv_for_uart(baudrate: int, max_bytes: int = 32) -> float:
    """Return the smallest standard TDIV (s/div) that fits *max_bytes* of
    UART data at *baudrate* with a 2× safety margin.

    A UART byte is 10 bits (start + 8 data + stop).  The full window is
    ``max_bytes × 10 × bit_time × 2`` seconds, divided by the number of
    horizontal divisions to get s/div.

    Falls back to 50 ms/div when the calculated value exceeds available
    steps.
    """
    if baudrate <= 0:
        # Unknown baud rate: use a wide window that covers most cases.
        return 50e-3
    bit_time = 1.0 / baudrate
    total_s = max_bytes * 10 * bit_time * 2.0
    tdiv_needed = total_s / _TDIV_DIVISIONS
    for step in _TDIV_STEPS_S:
        if step >= tdiv_needed:
            return step
    return _TDIV_STEPS_S[-1]


# ---------------------------------------------------------------------------
# P1: VDIV/OFST auto-ranging helpers
# ---------------------------------------------------------------------------

def best_vdiv_ofst(vmax: float, vmin: float) -> tuple[float, float]:
    """Compute VDIV and OFST so the signal fills ~6 of 8 vertical divisions.

    Returns (vdiv_v, ofst_v).  OFST on Siglent is the voltage at the
    *centre* of the screen (positive = shift waveform down).
    """
    vpp = vmax - vmin
    mid = (vmax + vmin) / 2.0
    # Fill 6 divisions with Vpp.
    vdiv_ideal = vpp / 6.0 if vpp > 0 else 1.0
    # Choose the nearest standard step that is >= vdiv_ideal.
    vdiv = next((v for v in _VDIV_STEPS_V if v >= vdiv_ideal), _VDIV_STEPS_V[-1])
    # OFST = -(mid voltage) so the waveform is centred.
    # Clamp to ±4 × VDIV (scope hardware limit).
    ofst = max(-4.0 * vdiv, min(4.0 * vdiv, -mid))
    return vdiv, ofst


# ---------------------------------------------------------------------------
# P5: cpd sanity-check / re-derivation
# ---------------------------------------------------------------------------

def verify_cpd(
    cpd: float,
    vgain: float,
    codes: list[int],
    measured_vmax: float | None,
    measured_vmin: float | None,
    voff: float,
) -> tuple[float, str]:
    """Validate *cpd* (codes-per-div) against a scope-measured Vpp.

    If the Vpp inferred from raw codes differs from the measured Vpp by
    more than 50 %, re-derives cpd from the measured extremes.

    Returns (corrected_cpd, note).
    """
    if not codes:
        return cpd, "no codes"
    if measured_vmax is None or measured_vmin is None:
        return cpd, "no measurement reference"

    measured_vpp = measured_vmax - measured_vmin
    if measured_vpp <= 0:
        return cpd, "measured Vpp <= 0"

    code_max = max(codes)
    code_min = min(codes)
    computed_vpp = (code_max - code_min) * vgain / cpd

    if measured_vpp > 0 and computed_vpp > 0:
        ratio = computed_vpp / measured_vpp
        if 0.5 <= ratio <= 2.0:
            return cpd, "ok"

    # Re-derive cpd from measured MAX/MIN:
    # voltage = code × (vgain / cpd) - voff
    # → cpd = code_span × vgain / (measured_vpp)
    code_span = code_max - code_min
    if code_span <= 0:
        return cpd, "zero code span, cannot re-derive"
    new_cpd = code_span * vgain / measured_vpp
    return new_cpd, f"re-derived cpd={new_cpd:.1f} from measured Vpp={measured_vpp:.3f} V"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class UartCaptureResult:
    """Full result of one capture-and-decode cycle."""

    ok: bool
    channel: str
    detected_baud: int | None
    measured_baud: int | None       # after run-length refinement
    decoded_ascii: str
    decoded_hex: str
    decoded_bytes: list[int]
    frame_count: int
    valid_frame_count: int
    stop_ok_rate: float
    vpp_v: float | None
    threshold_v: float | None
    dt_s: float | None
    tdiv_s: float | None
    baud_confidence: str
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "channel": self.channel,
            "detected_baud": self.detected_baud,
            "measured_baud": self.measured_baud,
            "decoded_ascii": self.decoded_ascii,
            "decoded_hex": self.decoded_hex,
            "decoded_bytes": self.decoded_bytes,
            "frame_count": self.frame_count,
            "valid_frame_count": self.valid_frame_count,
            "stop_ok_rate": round(self.stop_ok_rate, 3),
            "vpp_v": self.vpp_v,
            "threshold_v": self.threshold_v,
            "dt_s": self.dt_s,
            "tdiv_s": self.tdiv_s,
            "baud_confidence": self.baud_confidence,
            "warnings": self.warnings,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Low-level SCPI helpers (work with a raw socket-like object)
# ---------------------------------------------------------------------------

def _scpi_cmd(transport: object, cmd: str, delay: float = 0.08) -> None:
    transport.write(cmd)  # type: ignore[attr-defined]
    time.sleep(delay)


def _scpi_qry(transport: object, cmd: str, delay: float = 0.15) -> str:
    return transport.query(cmd).strip()  # type: ignore[attr-defined]


def _scpi_qry_float(transport: object, cmd: str) -> float | None:
    raw = _scpi_qry(transport, cmd)
    try:
        # Response format: "KEY,VALUE" e.g. "PKPK,9.82E+00"
        val = raw.split(",")[-1]
        return float(val)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# P3: Noise-trigger retry — arm_until_valid()
# ---------------------------------------------------------------------------

def arm_until_valid(
    transport: object,
    *,
    min_pkpk_v: float = 1.0,
    timeout_s: float = 60.0,
    max_attempts: int = 8,
    poll_interval_s: float = 0.4,
    channel: str = "C1",
) -> bool:
    """ARM the scope in SINGLE mode and wait until a genuine trigger fires.

    A trigger is considered genuine when PKPK > *min_pkpk_v*.  Noise
    triggers (PKPK ≤ threshold) cause an automatic re-ARM.

    Returns True when a valid trigger is captured, False on timeout.
    """
    deadline = time.monotonic() + timeout_s
    for attempt in range(max_attempts):
        _scpi_cmd(transport, "ARM", delay=0.25)
        # Poll until Stop or deadline.
        while time.monotonic() < deadline:
            time.sleep(poll_interval_s)
            st = _scpi_qry(transport, "SAST?")
            if "Stop" in st or "STOP" in st:
                break
        else:
            return False  # deadline reached

        pkpk = _scpi_qry_float(transport, f"{channel}:PAVA? PKPK")
        if pkpk is not None and pkpk >= min_pkpk_v:
            return True
        # Noise trigger — re-ARM.

    return False


# ---------------------------------------------------------------------------
# Main capture function
# ---------------------------------------------------------------------------

def capture_uart_auto(
    transport: object,
    *,
    channel: Channel = "C1",
    baudrate: int = 0,
    probe_attn: float = 10.0,
    max_bytes: int = 64,
    timeout_s: float = 60.0,
    max_trigger_attempts: int = 8,
    min_pkpk_v: float = 1.0,
) -> UartCaptureResult:
    """Capture a UART waveform and decode it automatically.

    Parameters
    ----------
    transport:
        Any object with ``.write(cmd)``, ``.query(cmd)``, and
        ``.query_binary(cmd)`` methods (``RawTcpTransport`` or compatible).
    channel:
        Oscilloscope channel to capture from.
    baudrate:
        Nominal baud rate.  Pass 0 to let the function auto-detect it.
    probe_attn:
        Probe attenuation factor (1 or 10).
    max_bytes:
        Maximum expected message length in bytes (used for TDIV sizing).
    timeout_s:
        Maximum seconds to wait for a valid trigger.
    max_trigger_attempts:
        Maximum ARM attempts before giving up.
    min_pkpk_v:
        Minimum PKPK (V) to accept a trigger as genuine (P3).
    """
    from .uart_analyzer import (
        auto_detect_baudrate,
        _estimate_levels_and_threshold,
        _estimate_bit_time_from_runs,
        _decode_uart_8n1,
    )

    warnings: list[str] = []
    notes: list[str] = []

    _scpi_cmd(transport, "CHDR OFF")
    _scpi_cmd(transport, "STOP", delay=0.2)

    # ── P1 step 1: measure signal in AUTO mode to get MAX/MIN ──────────────
    _scpi_cmd(transport, f"{channel}:ATTN {probe_attn:.0f}")
    _scpi_cmd(transport, f"{channel}:VDIV 2.0000E+00V")
    _scpi_cmd(transport, f"{channel}:OFST 0.0000E+00V")
    _scpi_cmd(transport, "TDIV 1.0000E-02")   # 10 ms/div
    _scpi_cmd(transport, "TRMD AUTO")
    _scpi_cmd(transport, "ARM")
    time.sleep(1.5)  # let AUTO mode stabilise

    meas_max = _scpi_qry_float(transport, f"{channel}:PAVA? MAX")
    meas_min = _scpi_qry_float(transport, f"{channel}:PAVA? MIN")
    meas_pkpk = _scpi_qry_float(transport, f"{channel}:PAVA? PKPK")

    notes.append(
        f"AUTO measurement: MAX={meas_max} V  MIN={meas_min} V  "
        f"PKPK={meas_pkpk} V"
    )

    # ── P1 step 2: compute best VDIV/OFST ─────────────────────────────────
    if meas_max is not None and meas_min is not None and (meas_max - meas_min) > 0.1:
        vdiv, ofst = best_vdiv_ofst(meas_max, meas_min)
    else:
        # Fallback: 5 V TTL with 10× probe → 0.5 V signal, 2 V/div centred
        vdiv, ofst = 2.0, -2.5
        warnings.append(
            "could not measure MAX/MIN; using default VDIV=2V OFST=-2.5V"
        )

    _scpi_cmd(transport, f"{channel}:VDIV {vdiv:.4E}V")
    time.sleep(0.1)
    _scpi_cmd(transport, f"{channel}:OFST {ofst:.4E}V")
    time.sleep(0.1)
    notes.append(f"VDIV={vdiv:.4g} V/div  OFST={ofst:.4g} V (auto-ranged)")

    # ── P4 phase-1: wide TDIV for initial capture + baud detection ────────
    # When baudrate is unknown (0) we use a wide 5ms/div window to catch the
    # first frame, detect the baud rate, then re-capture with the optimal TDIV.
    if baudrate > 0:
        tdiv = best_tdiv_for_uart(baudrate, max_bytes=max_bytes)
        notes.append(f"TDIV={tdiv * 1e3:.3g} ms/div (from supplied baud={baudrate}, {max_bytes} B)")
    else:
        tdiv = 5e-3   # 5 ms/div wide capture for baud snooping
        notes.append("TDIV=5 ms/div (wide capture for baud detection)")
    _scpi_cmd(transport, f"TDIV {tdiv:.4E}")

    # ── Trigger setup ──────────────────────────────────────────────────────
    # TRSE syntax: TRSE EDGE,SR,<channel>,DC  (source = channel)
    _scpi_cmd(transport, f"TRSE EDGE,SR,{channel},DC")
    trig_level = (meas_max + meas_min) / 2.0 if (meas_max is not None and meas_min is not None) else 2.5
    _scpi_cmd(transport, f"{channel}:TRLV {trig_level:.4E}V")
    _scpi_cmd(transport, "TRSL NEG")
    _scpi_cmd(transport, "TRMD SINGLE")

    # ── P3: ARM with noise-trigger retry ───────────────────────────────────
    triggered = arm_until_valid(
        transport,
        min_pkpk_v=min_pkpk_v,
        timeout_s=timeout_s,
        max_attempts=max_trigger_attempts,
        channel=channel,
    )

    if not triggered:
        return UartCaptureResult(
            ok=False,
            channel=channel,
            detected_baud=None,
            measured_baud=None,
            decoded_ascii="",
            decoded_hex="",
            decoded_bytes=[],
            frame_count=0,
            valid_frame_count=0,
            stop_ok_rate=0.0,
            vpp_v=None,
            threshold_v=None,
            dt_s=None,
            tdiv_s=tdiv,
            baud_confidence="none",
            warnings=warnings + ["trigger timeout: no valid signal captured"],
            notes=notes,
        )

    # Re-read measurements after trigger for P5
    meas_max = _scpi_qry_float(transport, f"{channel}:PAVA? MAX")
    meas_min = _scpi_qry_float(transport, f"{channel}:PAVA? MIN")

    def _read_waveform() -> tuple[float, float, float, float, list[int]]:
        """Read WAVEDESC + DAT2, return (dt, vgain, voff, cpd, codes)."""
        desc_b = transport.query_binary(f"{channel}:WF? DESC")  # type: ignore[attr-defined]
        desc_r = desc_b.data if hasattr(desc_b, "data") else bytes(desc_b)
        _dt, _vg, _vo, _cpd = _parse_wavedesc_minimal(desc_r)
        dat2_b = transport.query_binary(f"{channel}:WF? DAT2")  # type: ignore[attr-defined]
        dat2_r = dat2_b.data if hasattr(dat2_b, "data") else bytes(dat2_b)
        _codes = [b if b <= 127 else b - 256 for b in dat2_r]
        return _dt, _vg, _vo, _cpd, _codes

    # ── Read WAVEDESC + DAT2 (phase-1) ─────────────────────────────────────
    dt, vgain, voff, cpd, codes = _read_waveform()
    notes.append(f"WAVEDESC: dt={dt:.3e} s  vgain={vgain:.4f}  voff={voff:.3f} V  cpd={cpd:.1f}")

    if not codes:
        return UartCaptureResult(
            ok=False,
            channel=channel,
            detected_baud=None,
            measured_baud=None,
            decoded_ascii="",
            decoded_hex="",
            decoded_bytes=[],
            frame_count=0,
            valid_frame_count=0,
            stop_ok_rate=0.0,
            vpp_v=None,
            threshold_v=None,
            dt_s=dt,
            tdiv_s=tdiv,
            baud_confidence="none",
            warnings=warnings + ["DAT2 read returned empty data"],
            notes=notes,
        )

    # ── P5: verify / correct cpd ──────────────────────────────────────────
    cpd, cpd_note = verify_cpd(cpd, vgain, codes, meas_max, meas_min, voff)
    notes.append(f"cpd check: {cpd_note}")

    voltages = [c * (vgain / cpd) - voff for c in codes]

    # ── Threshold and binarise ────────────────────────────────────────────
    low_v, high_v, threshold_v, _, thr_warns = _estimate_levels_and_threshold(voltages)
    warnings.extend(thr_warns)
    vpp_v = high_v - low_v

    if vpp_v < 0.1:
        return UartCaptureResult(
            ok=False,
            channel=channel,
            detected_baud=None,
            measured_baud=None,
            decoded_ascii="",
            decoded_hex="",
            decoded_bytes=[],
            frame_count=0,
            valid_frame_count=0,
            stop_ok_rate=0.0,
            vpp_v=vpp_v,
            threshold_v=threshold_v,
            dt_s=dt,
            tdiv_s=tdiv,
            baud_confidence="none",
            warnings=warnings + [f"Vpp={vpp_v:.3f} V too small; likely captured idle segment"],
            notes=notes,
        )

    binary = [1 if v >= threshold_v else 0 for v in voltages]
    samples_for_detect = [(i * dt, float(binary[i])) for i in range(len(binary))]

    # ── P2: auto-detect baud rate ─────────────────────────────────────────
    detection = auto_detect_baudrate(samples_for_detect)
    warnings.extend(detection.warnings)
    notes.append(
        f"baud detection: {detection.detected_baud} baud "
        f"(confidence={detection.confidence})"
    )

    if baudrate > 0:
        decode_baud = baudrate
        if detection.detected_baud and detection.detected_baud != baudrate:
            notes.append(
                f"note: auto-detected baud {detection.detected_baud} differs from "
                f"supplied {baudrate}; using supplied value"
            )
    elif detection.detected_baud:
        decode_baud = detection.detected_baud
    else:
        decode_baud = 9600
        decode_parity = "8N1"
        warnings.append("baud detection failed; falling back to 9600")

    # ── P4 phase-2: re-capture with optimal TDIV if baud was auto-detected ─
    # When we detected a baud rate from the wide capture, recalculate the
    # optimal TDIV and re-ARM for a tighter, higher-resolution capture.
    if baudrate == 0 and decode_baud != 9600:
        tdiv2 = best_tdiv_for_uart(decode_baud, max_bytes=max_bytes)
        if tdiv2 < tdiv * 0.9:   # only re-capture if meaningfully narrower
            notes.append(
                f"P4 phase-2: re-capturing at TDIV={tdiv2 * 1e3:.3g} ms/div "
                f"(optimal for {decode_baud} baud)"
            )
            _scpi_cmd(transport, f"TDIV {tdiv2:.4E}")
            tdiv = tdiv2
            # Re-ARM (single attempt, valid trigger already confirmed)
            triggered2 = arm_until_valid(
                transport,
                min_pkpk_v=min_pkpk_v,
                timeout_s=min(timeout_s, 30.0),
                max_attempts=3,
                channel=channel,
            )
            if triggered2:
                meas_max = _scpi_qry_float(transport, f"{channel}:PAVA? MAX")
                meas_min = _scpi_qry_float(transport, f"{channel}:PAVA? MIN")
                dt, vgain, voff, cpd2, codes = _read_waveform()
                cpd2, cpd_note2 = verify_cpd(cpd2, vgain, codes, meas_max, meas_min, voff)
                cpd = cpd2
                notes.append(f"phase-2 WAVEDESC: dt={dt:.3e} s  cpd check: {cpd_note2}")
                voltages = [c * (vgain / cpd) - voff for c in codes]
                low_v, high_v, threshold_v, _, thr_warns2 = _estimate_levels_and_threshold(voltages)
                warnings.extend(thr_warns2)
                vpp_v = high_v - low_v
                binary = [1 if v >= threshold_v else 0 for v in voltages]
            else:
                notes.append("phase-2 re-trigger failed; using phase-1 data")

    # ── P2b: candidate verification (decode trial) ─────────────────────────
    # When multiple candidates exist or confidence is low/medium,
    # try decoding with each candidate (8N1 and 8O1) and pick the best.
    if baudrate == 0 and detection.detected_baud and detection.candidates:
        candidates = detection.candidates
        if len(candidates) > 1 or detection.confidence in ("low", "medium"):
            trial_logic = [(i * dt, float(binary[i])) for i in range(len(binary))]
            best_baud = detection.detected_baud
            best_rate = 0.0
            best_parity = None
            trial_notes = []
            for cand in candidates[:5]:  # test top 5 candidates
                trial_baud = int(cand["baud"])
                trial_bt = 1.0 / trial_baud
                # Try 8N1, 8O1, 8E1
                frames_8n1 = _decode_uart_8n1(trial_logic, trial_bt, idle_high=True, parity=None)
                rate_8n1 = sum(f.stop_ok for f in frames_8n1) / len(frames_8n1) if frames_8n1 else 0.0
                frames_8o1 = _decode_uart_8n1(trial_logic, trial_bt, idle_high=True, parity="odd")
                rate_8o1 = sum(f.stop_ok for f in frames_8o1) / len(frames_8o1) if frames_8o1 else 0.0
                frames_8e1 = _decode_uart_8n1(trial_logic, trial_bt, idle_high=True, parity="even")
                rate_8e1 = sum(f.stop_ok for f in frames_8e1) / len(frames_8e1) if frames_8e1 else 0.0
                # Pick best for this baud
                best_rate_for_baud = rate_8n1
                best_parity_for_baud = "8N1"
                if rate_8o1 > best_rate_for_baud:
                    best_rate_for_baud = rate_8o1
                    best_parity_for_baud = "8O1"
                if rate_8e1 > best_rate_for_baud:
                    best_rate_for_baud = rate_8e1
                    best_parity_for_baud = "8E1"
                trial_rate = best_rate_for_baud
                parity_str = best_parity_for_baud
                trial_notes.append(f"  {trial_baud} baud 8N1={rate_8n1:.1%} 8O1={rate_8o1:.1%} 8E1={rate_8e1:.1%} -> {parity_str}")
                if trial_rate > best_rate:
                    best_rate = trial_rate
                    best_baud = trial_baud
                    best_parity = parity_str
            if best_rate < 0.1 and detection.measured_bit_time_s:
                non_std_baud = int(round(1.0 / detection.measured_bit_time_s))
                non_std_bt = detection.measured_bit_time_s
                frames_8n1 = _decode_uart_8n1(trial_logic, non_std_bt, idle_high=True, parity=None)
                rate_8n1 = sum(f.stop_ok for f in frames_8n1) / len(frames_8n1) if frames_8n1 else 0.0
                frames_8o1 = _decode_uart_8n1(trial_logic, non_std_bt, idle_high=True, parity="odd")
                rate_8o1 = sum(f.stop_ok for f in frames_8o1) / len(frames_8o1) if frames_8o1 else 0.0
                frames_8e1 = _decode_uart_8n1(trial_logic, non_std_bt, idle_high=True, parity="even")
                rate_8e1 = sum(f.stop_ok for f in frames_8e1) / len(frames_8e1) if frames_8e1 else 0.0
                non_std_rate = rate_8n1
                parity_str = "8N1"
                if rate_8o1 > non_std_rate:
                    non_std_rate = rate_8o1
                    parity_str = "8O1"
                if rate_8e1 > non_std_rate:
                    non_std_rate = rate_8e1
                    parity_str = "8E1"
                trial_notes.append(f"  non-std {non_std_baud} baud 8N1={rate_8n1:.1%} 8O1={rate_8o1:.1%} 8E1={rate_8e1:.1%} -> {parity_str}")
                if non_std_rate > best_rate:
                    best_rate = non_std_rate
                    best_baud = non_std_baud
                    best_parity = parity_str
                    notes.append(f"P2b: using non-standard {best_baud} baud {parity_str} (stop_ok={best_rate:.1%})")
            if best_baud != detection.detected_baud:
                notes.append(
                    f"P2b verify: selected {best_baud} baud {best_parity} (stop_ok={best_rate:.1%}) "
                    f"over detected {detection.detected_baud}"
                )
            notes.extend(trial_notes)
            decode_baud = best_baud
            decode_parity = best_parity

    # ── Decode ────────────────────────────────────────────────────────────
    logic = [(i * dt, binary[i]) for i in range(len(binary))]
    nominal_bt = 1.0 / decode_baud
    actual_bt = _estimate_bit_time_from_runs(logic, nominal_bt)
    measured_baud = int(round(1.0 / actual_bt))

    if decode_parity == "8O1":
        parity_param = "odd"
    elif decode_parity == "8E1":
        parity_param = "even"
    else:
        parity_param = None
    frames = _decode_uart_8n1(logic, actual_bt, idle_high=True, parity=parity_param)
    good = [f for f in frames if f.framing_ok and f.byte is not None]
    decoded_bytes = [f.byte for f in good]  # type: ignore[misc]
    decoded_hex = " ".join(f"{b:02X}" for b in decoded_bytes)
    decoded_ascii = "".join(
        chr(b) if 0x20 <= b <= 0x7E else f"\\x{b:02x}" for b in decoded_bytes
    )
    stop_ok_rate = (
        sum(f.stop_ok for f in frames) / len(frames) if frames else 0.0
    )

    return UartCaptureResult(
        ok=bool(good),
        channel=channel,
        detected_baud=detection.detected_baud,
        measured_baud=measured_baud,
        decoded_ascii=decoded_ascii,
        decoded_hex=decoded_hex,
        decoded_bytes=decoded_bytes,
        frame_count=len(frames),
        valid_frame_count=len(good),
        stop_ok_rate=stop_ok_rate,
        vpp_v=vpp_v,
        threshold_v=threshold_v,
        dt_s=dt,
        tdiv_s=tdiv,
        baud_confidence=detection.confidence,
        warnings=warnings,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# WAVEDESC minimal parser (no external dependencies)
# ---------------------------------------------------------------------------

def _parse_wavedesc_minimal(raw: bytes) -> tuple[float, float, float, float]:
    """Extract (dt, vgain, voff, cpd) from a raw WAVEDESC binary block.

    Offsets match the Siglent SDS800X HD WAVEDESC layout used in
    ``sds_tcp_adapter._parse_wavedesc``.  Falls back to safe defaults on
    any parse error.
    """
    defaults = (1e-8, 0.2, 0.0, 30.0)
    if not raw or len(raw) < 184:
        return defaults
    try:
        # Find the start of the descriptor (skip IEEE 488.2 block header and
        # any ASCII prefix such as "C1:WF DESC,").
        marker = raw.find(b"WAVEDESC")
        if marker < 0:
            return defaults
        desc = raw[marker:]
        if len(desc) < 184:
            return defaults
        vgain = struct.unpack_from("<f", desc, 156)[0]
        voff  = struct.unpack_from("<f", desc, 160)[0]
        max_v = struct.unpack_from("<f", desc, 164)[0]
        dt    = struct.unpack_from("<f", desc, 176)[0]
        cpd   = max_v / 256.0 if max_v > 0 else 30.0
        if dt <= 0 or vgain <= 0:
            return defaults
        return dt, vgain, voff, cpd
    except struct.error:
        return defaults
