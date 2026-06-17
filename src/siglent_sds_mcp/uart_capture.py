"""End-to-end UART waveform capture and auto-decode.

This module is intentionally separate from the generic waveform CSV capture path.
It configures the oscilloscope for a UART falling-edge trigger, captures a stopped
frame, reads WAVEDESC + DAT2 directly, and decodes the captured frame.
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
_TDIV_DIVISIONS = 14
_VDIV_STEPS_V: tuple[float, ...] = (
    0.001, 0.002, 0.005,
    0.01, 0.02, 0.05,
    0.1, 0.2, 0.5,
    1.0, 2.0, 5.0, 10.0,
)

Channel = Literal["C1", "C2", "C3", "C4"]
ParityMode = Literal["8N1", "8O1", "8E1"]


def best_tdiv_for_uart(baudrate: int, max_bytes: int = 32) -> float:
    """Return the smallest standard TDIV that fits a UART message.

    UART 8N1 uses 10 bits per byte. We use a 2x safety margin and divide by
    the SDS800X HD 14 horizontal divisions.
    """

    if baudrate <= 0:
        return 50e-3
    bit_time = 1.0 / baudrate
    total_s = max_bytes * 10 * bit_time * 2.0
    tdiv_needed = total_s / _TDIV_DIVISIONS
    for step in _TDIV_STEPS_S:
        if step >= tdiv_needed:
            return step
    return _TDIV_STEPS_S[-1]


def best_vdiv_ofst(vmax: float, vmin: float) -> tuple[float, float]:
    """Compute VDIV and OFST so the signal fills about 6 vertical divisions.

    For SDS824X HD field validation, the panel OFST value is treated as the
    voltage at screen centre. This matches the measurement-driven auto_setup
    path, where OFST is set to the measured waveform centre.
    """

    vpp = vmax - vmin
    mid = (vmax + vmin) / 2.0
    vdiv_ideal = vpp / 6.0 if vpp > 0 else 1.0
    vdiv = next((v for v in _VDIV_STEPS_V if v >= vdiv_ideal), _VDIV_STEPS_V[-1])
    # Siglent OFST: positive shifts waveform down, so use -mid to centre
    ofst = max(-4.0 * vdiv, min(4.0 * vdiv, -mid))
    return vdiv, ofst


def verify_cpd(
    cpd: float,
    vgain: float,
    codes: list[int],
    measured_vmax: float | None,
    measured_vmin: float | None,
    voff: float,
) -> tuple[float, str]:
    """Validate codes-per-div against scope-measured Vpp.

    If the raw-code-derived Vpp differs from scope measurement by more than 2x,
    derive a better CPD from the measured MAX/MIN.
    """

    if not codes:
        return cpd, "no codes"
    if measured_vmax is None or measured_vmin is None:
        return cpd, "no measurement reference"

    measured_vpp = measured_vmax - measured_vmin
    if measured_vpp <= 0:
        return cpd, "measured Vpp <= 0"

    code_span = max(codes) - min(codes)
    if code_span <= 0:
        return cpd, "zero code span, cannot re-derive"

    computed_vpp = code_span * vgain / cpd
    if computed_vpp > 0:
        ratio = computed_vpp / measured_vpp
        if 0.5 <= ratio <= 2.0:
            return cpd, "ok"

    new_cpd = code_span * vgain / measured_vpp
    return new_cpd, f"re-derived cpd={new_cpd:.1f} from measured Vpp={measured_vpp:.3f} V"


@dataclass(slots=True)
class UartCaptureResult:
    """Full result of one capture-and-decode cycle."""

    ok: bool
    channel: str
    detected_baud: int | None
    measured_baud: int | None
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


def _scpi_cmd(transport: object, cmd: str, delay: float = 0.08) -> None:
    transport.write(cmd)  # type: ignore[attr-defined]
    time.sleep(delay)


def _scpi_qry(transport: object, cmd: str, delay: float = 0.15) -> str:
    time.sleep(delay)
    return transport.query(cmd).strip()  # type: ignore[attr-defined]


def _scpi_qry_float(transport: object, cmd: str) -> float | None:
    raw = _scpi_qry(transport, cmd)
    try:
        return float(raw.split(",")[-1])
    except (ValueError, IndexError):
        return None


def arm_until_valid(
    transport: object,
    *,
    min_pkpk_v: float = 1.0,
    timeout_s: float = 60.0,
    max_attempts: int = 8,
    poll_interval_s: float = 0.4,
    channel: str = "C1",
) -> bool:
    """Arm in SINGLE mode until a stopped frame with sufficient PKPK is captured."""

    deadline = time.monotonic() + timeout_s
    for _ in range(max_attempts):
        _scpi_cmd(transport, "ARM", delay=0.25)
        while time.monotonic() < deadline:
            time.sleep(poll_interval_s)
            try:
                st = _scpi_qry(transport, "SAST?")
            except Exception:  # noqa: BLE001
                continue
            if "Stop" in st or "STOP" in st:
                break
        else:
            return False

        pkpk = _scpi_qry_float(transport, f"{channel}:PAVA? PKPK")
        if pkpk is not None and pkpk >= min_pkpk_v:
            return True
    return False


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
    """Capture a UART waveform and decode it automatically."""

    from .uart_analyzer import (
        _decode_uart_8n1,
        _estimate_bit_time_from_runs,
        _estimate_levels_and_threshold,
        auto_detect_baudrate,
    )

    warnings: list[str] = []
    notes: list[str] = []
    decode_parity: ParityMode | None = "8N1"

    _scpi_cmd(transport, "CHDR OFF")
    _scpi_cmd(transport, "STOP", delay=0.2)

    _scpi_cmd(transport, f"{channel}:ATTN {probe_attn:.0f}")
    _scpi_cmd(transport, f"{channel}:VDIV 2.0000E+00V")
    _scpi_cmd(transport, f"{channel}:OFST 0.0000E+00V")
    _scpi_cmd(transport, "TDIV 1.0000E-02")
    _scpi_cmd(transport, "TRMD AUTO")
    _scpi_cmd(transport, "ARM")
    time.sleep(1.5)

    meas_max = _scpi_qry_float(transport, f"{channel}:PAVA? MAX")
    meas_min = _scpi_qry_float(transport, f"{channel}:PAVA? MIN")
    meas_pkpk = _scpi_qry_float(transport, f"{channel}:PAVA? PKPK")
    notes.append(
        f"AUTO measurement: MAX={meas_max} V  MIN={meas_min} V  PKPK={meas_pkpk} V"
    )

    if meas_max is not None and meas_min is not None and (meas_max - meas_min) > 0.1:
        vdiv, ofst = best_vdiv_ofst(meas_max, meas_min)
    else:
        vdiv, ofst = 2.0, 2.5
        warnings.append("could not measure MAX/MIN; using default VDIV=2V OFST=2.5V")

    _scpi_cmd(transport, f"{channel}:VDIV {vdiv:.4E}V")
    _scpi_cmd(transport, f"{channel}:OFST {ofst:.4E}V")
    notes.append(f"VDIV={vdiv:.4g} V/div  OFST={ofst:.4g} V (auto-ranged)")

    if baudrate > 0:
        tdiv = best_tdiv_for_uart(baudrate, max_bytes=max_bytes)
        notes.append(
            f"TDIV={tdiv * 1e3:.3g} ms/div "
            f"(from supplied baud={baudrate}, {max_bytes} B)"
        )
    else:
        tdiv = 5e-3
        notes.append("TDIV=5 ms/div (wide capture for baud detection)")
    _scpi_cmd(transport, f"TDIV {tdiv:.4E}")

    _scpi_cmd(transport, f"TRSE EDGE,SR,{channel},DC")
    trig_level = (
        (meas_max + meas_min) / 2.0
        if (meas_max is not None and meas_min is not None)
        else 2.5
    )
    _scpi_cmd(transport, f"{channel}:TRLV {trig_level:.4E}V")
    _scpi_cmd(transport, "TRSL NEG")
    _scpi_cmd(transport, "TRMD SINGLE")

    triggered = arm_until_valid(
        transport,
        min_pkpk_v=min_pkpk_v,
        timeout_s=timeout_s,
        max_attempts=max_trigger_attempts,
        channel=channel,
    )
    if not triggered:
        return _failed_result(
            channel=channel,
            tdiv=tdiv,
            warnings=warnings + ["trigger timeout: no valid signal captured"],
            notes=notes,
        )

    meas_max = _scpi_qry_float(transport, f"{channel}:PAVA? MAX")
    meas_min = _scpi_qry_float(transport, f"{channel}:PAVA? MIN")

    def _read_waveform() -> tuple[float, float, float, float, list[int]]:
        desc_b = transport.query_binary(f"{channel}:WF? DESC")  # type: ignore[attr-defined]
        desc_r = desc_b.data if hasattr(desc_b, "data") else bytes(desc_b)
        dt_, vgain_, voff_, cpd_ = _parse_wavedesc_minimal(desc_r)
        dat2_b = transport.query_binary(f"{channel}:WF? DAT2")  # type: ignore[attr-defined]
        dat2_r = dat2_b.data if hasattr(dat2_b, "data") else bytes(dat2_b)
        codes_ = [b if b <= 127 else b - 256 for b in dat2_r]
        return dt_, vgain_, voff_, cpd_, codes_

    dt, vgain, voff, cpd, codes = _read_waveform()
    notes.append(
        f"WAVEDESC: dt={dt:.3e} s  vgain={vgain:.4f}  voff={voff:.3f} V  cpd={cpd:.1f}"
    )

    if not codes:
        return _failed_result(
            channel=channel,
            tdiv=tdiv,
            dt=dt,
            warnings=warnings + ["DAT2 read returned empty data"],
            notes=notes,
        )

    cpd, cpd_note = verify_cpd(cpd, vgain, codes, meas_max, meas_min, voff)
    notes.append(f"cpd check: {cpd_note}")
    voltages = [c * (vgain / cpd) - voff for c in codes]
    low_v, high_v, threshold_v, _, thr_warns = _estimate_levels_and_threshold(voltages)
    warnings.extend(thr_warns)
    vpp_v = high_v - low_v

    if vpp_v < 0.1:
        return _failed_result(
            channel=channel,
            tdiv=tdiv,
            dt=dt,
            vpp=vpp_v,
            threshold=threshold_v,
            warnings=warnings + [f"Vpp={vpp_v:.3f} V too small; likely captured idle segment"],
            notes=notes,
        )

    binary = [1 if v >= threshold_v else 0 for v in voltages]
    samples_for_detect = [(i * dt, float(binary[i])) for i in range(len(binary))]
    detection = auto_detect_baudrate(samples_for_detect)
    warnings.extend(detection.warnings)
    notes.append(
        f"baud detection: {detection.detected_baud} baud (confidence={detection.confidence})"
    )

    # Default parity, will be overridden by P2b if candidates tested
    decode_parity = "8N1"

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
        warnings.append("baud detection failed; falling back to 9600")

    if baudrate == 0 and decode_baud != 9600:
        tdiv2 = best_tdiv_for_uart(decode_baud, max_bytes=max_bytes)
        if tdiv2 < tdiv * 0.9:
            notes.append(
                f"P4 phase-2: re-capturing at TDIV={tdiv2 * 1e3:.3g} ms/div "
                f"(optimal for {decode_baud} baud)"
            )
            _scpi_cmd(transport, f"TDIV {tdiv2:.4E}")
            tdiv = tdiv2
            if arm_until_valid(
                transport,
                min_pkpk_v=min_pkpk_v,
                timeout_s=min(timeout_s, 30.0),
                max_attempts=3,
                channel=channel,
            ):
                meas_max = _scpi_qry_float(transport, f"{channel}:PAVA? MAX")
                meas_min = _scpi_qry_float(transport, f"{channel}:PAVA? MIN")
                dt, vgain, voff, cpd2, codes = _read_waveform()
                cpd, cpd_note2 = verify_cpd(cpd2, vgain, codes, meas_max, meas_min, voff)
                notes.append(f"phase-2 WAVEDESC: dt={dt:.3e} s  cpd check: {cpd_note2}")
                voltages = [c * (vgain / cpd) - voff for c in codes]
                low_v, high_v, threshold_v, _, thr_warns2 = _estimate_levels_and_threshold(voltages)
                warnings.extend(thr_warns2)
                vpp_v = high_v - low_v
                binary = [1 if v >= threshold_v else 0 for v in voltages]
            else:
                notes.append("phase-2 re-trigger failed; using phase-1 data")

    if baudrate == 0 and detection.detected_baud and detection.candidates:
        candidates = detection.candidates
        if len(candidates) > 1 or detection.confidence in ("low", "medium"):
            trial_logic = [(i * dt, float(binary[i])) for i in range(len(binary))]
            best_baud = detection.detected_baud
            best_rate = 0.0
            best_parity: ParityMode | None = decode_parity
            trial_notes: list[str] = []
            for cand in candidates[:5]:
                trial_baud = int(cand["baud"])
                trial_bt = 1.0 / trial_baud
                rate_8n1 = _stop_ok_rate(_decode_uart_8n1(trial_logic, trial_bt, idle_high=True))
                rate_8o1 = _stop_ok_rate(
                    _decode_uart_8n1(trial_logic, trial_bt, idle_high=True, parity="odd")
                )
                rate_8e1 = _stop_ok_rate(
                    _decode_uart_8n1(trial_logic, trial_bt, idle_high=True, parity="even")
                )
                best_rate_for_baud = rate_8n1
                best_parity_for_baud: ParityMode = "8N1"
                if rate_8o1 > best_rate_for_baud:
                    best_rate_for_baud = rate_8o1
                    best_parity_for_baud = "8O1"
                if rate_8e1 > best_rate_for_baud:
                    best_rate_for_baud = rate_8e1
                    best_parity_for_baud = "8E1"
                trial_notes.append(
                    f"  {trial_baud} baud 8N1={rate_8n1:.1%} "
                    f"8O1={rate_8o1:.1%} 8E1={rate_8e1:.1%} -> {best_parity_for_baud}"
                )
                if best_rate_for_baud > best_rate:
                    best_rate = best_rate_for_baud
                    best_baud = trial_baud
                    best_parity = best_parity_for_baud

            if best_rate < 0.1 and detection.measured_bit_time_s:
                non_std_baud = int(round(1.0 / detection.measured_bit_time_s))
                non_std_bt = detection.measured_bit_time_s
                rate_8n1 = _stop_ok_rate(_decode_uart_8n1(trial_logic, non_std_bt, idle_high=True))
                rate_8o1 = _stop_ok_rate(
                    _decode_uart_8n1(trial_logic, non_std_bt, idle_high=True, parity="odd")
                )
                rate_8e1 = _stop_ok_rate(
                    _decode_uart_8n1(trial_logic, non_std_bt, idle_high=True, parity="even")
                )
                non_std_rate = rate_8n1
                parity_str: ParityMode = "8N1"
                if rate_8o1 > non_std_rate:
                    non_std_rate = rate_8o1
                    parity_str = "8O1"
                if rate_8e1 > non_std_rate:
                    non_std_rate = rate_8e1
                    parity_str = "8E1"
                trial_notes.append(
                    f"  non-std {non_std_baud} baud 8N1={rate_8n1:.1%} "
                    f"8O1={rate_8o1:.1%} 8E1={rate_8e1:.1%} -> {parity_str}"
                )
                if non_std_rate > best_rate:
                    best_rate = non_std_rate
                    best_baud = non_std_baud
                    best_parity = parity_str
                    notes.append(
                        f"P2b: using non-standard {best_baud} baud {parity_str} "
                        f"(stop_ok={best_rate:.1%})"
                    )
            if best_baud != detection.detected_baud:
                notes.append(
                    f"P2b verify: selected {best_baud} baud {best_parity} "
                    f"(stop_ok={best_rate:.1%}) over detected {detection.detected_baud}"
                )
            notes.extend(trial_notes)
            decode_baud = best_baud
            decode_parity = best_parity or "8N1"

    logic = [(i * dt, binary[i]) for i in range(len(binary))]
    nominal_bt = 1.0 / decode_baud
    actual_bt = _estimate_bit_time_from_runs(logic, nominal_bt)
    measured_baud = int(round(1.0 / actual_bt))

    parity_param = _parity_to_param(decode_parity)
    frames = _decode_uart_8n1(logic, actual_bt, idle_high=True, parity=parity_param)
    good = [f for f in frames if f.framing_ok and f.byte is not None]
    decoded_bytes = [int(f.byte) for f in good]
    decoded_hex = " ".join(f"{b:02X}" for b in decoded_bytes)
    decoded_ascii = "".join(chr(b) if 0x20 <= b <= 0x7E else f"\\x{b:02x}" for b in decoded_bytes)
    stop_ok_rate = _stop_ok_rate(frames)

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


def _failed_result(
    *,
    channel: str,
    tdiv: float | None,
    warnings: list[str],
    notes: list[str],
    dt: float | None = None,
    vpp: float | None = None,
    threshold: float | None = None,
) -> UartCaptureResult:
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
        vpp_v=vpp,
        threshold_v=threshold,
        dt_s=dt,
        tdiv_s=tdiv,
        baud_confidence="none",
        warnings=warnings,
        notes=notes,
    )


def _stop_ok_rate(frames: list[object]) -> float:
    return sum(bool(getattr(frame, "stop_ok", False)) for frame in frames) / len(frames) if frames else 0.0


def _parity_to_param(parity: ParityMode | None) -> str | None:
    if parity == "8O1":
        return "odd"
    if parity == "8E1":
        return "even"
    return None


def _parse_wavedesc_minimal(raw: bytes) -> tuple[float, float, float, float]:
    """Extract (dt, vgain, voff, cpd) from a raw WAVEDESC binary block."""

    defaults = (1e-8, 0.2, 0.0, 30.0)
    if not raw or len(raw) < 184:
        return defaults
    try:
        marker = raw.find(b"WAVEDESC")
        if marker < 0:
            return defaults
        desc = raw[marker:]
        if len(desc) < 184:
            return defaults
        vgain = struct.unpack_from("<f", desc, 156)[0]
        voff = struct.unpack_from("<f", desc, 160)[0]
        max_v = struct.unpack_from("<f", desc, 164)[0]
        dt = struct.unpack_from("<f", desc, 176)[0]
        cpd = max_v / 256.0 if max_v > 0 else 30.0
        if dt <= 0 or vgain <= 0:
            return defaults
        return dt, vgain, voff, cpd
    except struct.error:
        return defaults
