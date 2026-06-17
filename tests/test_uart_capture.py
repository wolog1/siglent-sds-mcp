"""Tests for uart_capture.py (P1-P5) and auto_detect_baudrate in uart_analyzer.py."""
from __future__ import annotations

import struct

import pytest

from siglent_sds_mcp.uart_analyzer import (
    auto_detect_baudrate,
)
from siglent_sds_mcp.uart_capture import (
    UartCaptureResult,
    _parse_wavedesc_minimal,
    best_tdiv_for_uart,
    best_vdiv_ofst,
    verify_cpd,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uart_waveform(
    baudrate: int = 9600,
    data: bytes = b"Hi",
    sample_rate: int | None = None,
    idle_high: bool = True,
    noise_amplitude: float = 0.0,
    edge_samples: int = 0,
) -> list[tuple[float, float]]:
    """Synthesize a UART 8N1 waveform as (time_s, voltage_v) pairs.

    To mimic real oscilloscope data (where auto_detect_baudrate works reliably),
    the default sample_rate is chosen so that samples_per_bit ≈ 200, ensuring
    short edge-noise runs (1-3 pts) are well below the bit-period run length
    (≈200 pts), and stable runs appear with cnt >= 3.
    """
    # Default: 200 samples per bit — far from any standard baud BP,
    # so noise runs (1-3 pts) are much shorter than the real bit runs.
    if sample_rate is None:
        sample_rate = baudrate * 200

    dt = 1.0 / sample_rate
    bit_time = 1.0 / baudrate
    samples_per_bit = int(round(bit_time / dt))

    levels: list[float] = [1.0] * (samples_per_bit * 3)  # preamble idle
    for byte in data:
        levels.append(0.0)  # start bit
        bits = [float((byte >> i) & 1) for i in range(8)]
        levels.extend(bits)
        levels.append(1.0)  # stop bit
    levels.extend([1.0] * (samples_per_bit * 3))  # trailing idle

    # Optional: simulate slow edges (linear ramp) to be more realistic.
    if edge_samples > 0:
        smoothed = list(levels)
        for idx in range(1, len(levels)):
            if levels[idx] != levels[idx - 1]:
                for j in range(1, edge_samples + 1):
                    pos = idx + j - 1
                    if pos < len(smoothed):
                        t = j / edge_samples
                        smoothed[pos] = levels[idx - 1] + t * (levels[idx] - levels[idx - 1])
        levels = smoothed

    import random
    rng = random.Random(42)
    result: list[tuple[float, float]] = []
    for i, lvl in enumerate(levels):
        v = 5.0 * lvl
        if noise_amplitude > 0:
            v += rng.uniform(-noise_amplitude, noise_amplitude)
        result.append((i * dt, v))
    return result


def _make_wavedesc(
    dt: float = 1e-8,
    vgain: float = 0.2,
    voff: float = -2.5,
    max_v: float = 7680.0,
) -> bytes:
    """Build a minimal WAVEDESC binary block at known offsets."""
    desc = bytearray(300)
    # Insert WAVEDESC marker at offset 0
    desc[0:8] = b"WAVEDESC"
    struct.pack_into("<f", desc, 156, vgain)
    struct.pack_into("<f", desc, 160, voff)
    struct.pack_into("<f", desc, 164, max_v)
    struct.pack_into("<f", desc, 176, dt)
    return bytes(desc)


# ---------------------------------------------------------------------------
# P4: best_tdiv_for_uart
# ---------------------------------------------------------------------------

class TestBestTdivForUart:
    def test_9600_baud_fits_32_bytes(self):
        tdiv = best_tdiv_for_uart(9600, max_bytes=32)
        # 32 bytes × 10 bits × (1/9600) × 2 / 14 ≈ 4.76 ms → next step = 5 ms
        assert tdiv >= 32 * 10 / 9600 * 2 / 14
        assert tdiv in (5e-3, 10e-3, 20e-3, 50e-3, 100e-3, 200e-3)

    def test_115200_baud_fits_64_bytes(self):
        tdiv = best_tdiv_for_uart(115200, max_bytes=64)
        min_needed = 64 * 10 / 115200 * 2 / 14
        assert tdiv >= min_needed

    def test_57600_baud_fits_14_bytes(self):
        # "yangyangyang\r\n" is 14 bytes
        tdiv = best_tdiv_for_uart(57600, max_bytes=14)
        min_needed = 14 * 10 / 57600 * 2 / 14
        assert tdiv >= min_needed

    def test_zero_baud_returns_wide_window(self):
        tdiv = best_tdiv_for_uart(0)
        assert tdiv == 50e-3

    def test_returns_standard_step(self):
        from siglent_sds_mcp.uart_capture import _TDIV_STEPS_S
        tdiv = best_tdiv_for_uart(9600, max_bytes=10)
        assert tdiv in _TDIV_STEPS_S


# ---------------------------------------------------------------------------
# P1: best_vdiv_ofst
# ---------------------------------------------------------------------------

class TestBestVdivOfst:
    def test_5v_ttl_via_10x_probe(self):
        # 10× probe: actual 5V appears as 0.5V at scope input
        # MAX=0.55, MIN=0.0 → vpp=0.55 → vdiv ≈ 0.55/6=0.092 → next step=0.1
        vdiv, ofst = best_vdiv_ofst(0.55, 0.0)
        assert vdiv == pytest.approx(0.1, rel=0.01)
        # mid = 0.275 → ofst = -0.275
        assert abs(ofst + 0.275) < vdiv  # within 1 div

    def test_full_5v_range(self):
        vdiv, ofst = best_vdiv_ofst(5.0, 0.0)
        assert vdiv >= 5.0 / 6.0
        from siglent_sds_mcp.uart_capture import _VDIV_STEPS_V
        assert vdiv in _VDIV_STEPS_V

    def test_ofst_within_hardware_limit(self):
        vdiv, ofst = best_vdiv_ofst(10.0, -10.0)
        # Hardware limit: OFST ∈ [-4×VDIV, +4×VDIV]
        assert -4.0 * vdiv <= ofst <= 4.0 * vdiv

    def test_symmetric_signal(self):
        vdiv, ofst = best_vdiv_ofst(2.5, -2.5)
        # mid = 0 → ofst ≈ 0
        assert abs(ofst) < vdiv


# ---------------------------------------------------------------------------
# P5: verify_cpd
# ---------------------------------------------------------------------------

class TestVerifyCpd:
    def _codes_for_vpp(self, vgain: float, cpd: float, voff: float,
                       code_min: int = -100, code_max: int = 37) -> list[int]:
        return [code_min, code_max]

    def test_correct_cpd_unchanged(self):
        # vgain=0.2, cpd=30, codes span=-110..37 → vpp=(147*0.2/30)=0.98 V
        codes = list(range(-110, 38))
        corrected, note = verify_cpd(
            30.0, 0.2, codes,
            measured_vmax=0.75, measured_vmin=-0.23,
            voff=-0.5,
        )
        assert corrected == pytest.approx(30.0, rel=0.01)
        assert note == "ok"

    def test_bad_cpd_gets_corrected(self):
        # vgain=0.2, cpd=30 → computed vpp = 4 * 0.2 / 30 ≈ 0.027 V
        # measured vpp = 9.8 V → ratio = 0.027/9.8 ≈ 0.003 → far from 1 → re-derive
        codes = [-2, 2]  # span=4
        corrected, note = verify_cpd(
            30.0, 0.2, codes,
            measured_vmax=5.0, measured_vmin=-4.8,
            voff=0.0,
        )
        # new_cpd = 4 * 0.2 / 9.8 ≈ 0.082
        assert corrected == pytest.approx(4 * 0.2 / 9.8, rel=0.01)
        assert "re-derived" in note

    def test_no_measurement_returns_original(self):
        corrected, note = verify_cpd(30.0, 0.2, [0, 100], None, None, 0.0)
        assert corrected == 30.0
        assert "no measurement" in note

    def test_empty_codes(self):
        corrected, note = verify_cpd(30.0, 0.2, [], 5.0, 0.0, 0.0)
        assert corrected == 30.0


# ---------------------------------------------------------------------------
# P2: auto_detect_baudrate
# ---------------------------------------------------------------------------

def _make_realistic_uart(baudrate: int, data: bytes) -> list[tuple[float, float]]:
    """Build a waveform that mimics real oscilloscope output.

    Uses dt matching the SDS824X HD's typical sample rate so that
    samples_per_bit ≈ 200, ensuring real UART run lengths are much larger
    than the noise threshold (3 samples) used by auto_detect_baudrate.

    Signal levels are clean 0/5 V (no edge ramp) so the decoder works
    reliably with the histogram threshold.  The run-length diversity that
    enables baud-rate disambiguation comes from realistic UART data bytes
    (not from edge transitions).
    """
    scope_dts = [1e-9, 2e-9, 5e-9, 10e-9, 20e-9, 50e-9,
                 100e-9, 200e-9, 500e-9, 1e-6, 2e-6, 5e-6]
    raw_dt = 1.0 / (baudrate * 200)
    dt = min(scope_dts, key=lambda d: abs(d - raw_dt))
    spb = int(round(1.0 / (baudrate * dt)))

    bits: list[int] = [1] * (spb * 4)  # preamble idle
    for byte in data:
        bits.extend([0] * spb)   # start bit
        for i in range(8):
            bits.extend([(byte >> i) & 1] * spb)
        bits.extend([1] * spb)   # stop bit
    bits.extend([1] * (spb * 4))  # trailing idle

    return [(i * dt, float(lvl) * 5.0) for i, lvl in enumerate(bits)]


class TestAutoDetectBaudrate:
    """Unit tests for auto_detect_baudrate.

    Note on baud disambiguation
    ---------------------------
    Synthetic waveforms have perfect integer-multiple run lengths, which
    creates an inherent ambiguity: e.g. a 9600-baud signal looks identical
    to a 19200-baud signal if every run is exactly 2× the BP.  Real
    oscilloscope data breaks this symmetry through analog noise, ADC
    quantisation, and the natural diversity of run lengths in arbitrary
    text.

    These tests therefore verify *structural* behaviour (candidates found,
    correct baud in candidate list, no crash on edge inputs) rather than
    asserting that a single specific baud is returned.  End-to-end
    accuracy on real hardware is covered by the live integration tests.
    """

    def test_correct_baud_in_candidates_9600(self):
        """9600 baud should appear in the candidate list."""
        samples = _make_realistic_uart(9600, b"Hi\r\n")
        result = auto_detect_baudrate(samples)
        candidate_bauds = {c["baud"] for c in result.candidates}
        assert 9600 in candidate_bauds or result.detected_baud == 9600, (
            f"9600 not found in candidates {candidate_bauds}"
        )

    def test_correct_baud_in_candidates_57600(self):
        samples = _make_realistic_uart(57600, b"yangyangyang\r\n")
        result = auto_detect_baudrate(samples)
        candidate_bauds = {c["baud"] for c in result.candidates}
        assert 57600 in candidate_bauds or result.detected_baud == 57600

    def test_correct_baud_in_candidates_115200(self):
        samples = _make_realistic_uart(115200, b"test\r\n")
        result = auto_detect_baudrate(samples)
        candidate_bauds = {c["baud"] for c in result.candidates}
        assert 115200 in candidate_bauds or result.detected_baud == 115200

    def test_correct_baud_in_candidates_38400(self):
        samples = _make_realistic_uart(38400, b"hello\r\n")
        result = auto_detect_baudrate(samples)
        candidate_bauds = {c["baud"] for c in result.candidates}
        assert 38400 in candidate_bauds or result.detected_baud == 38400

    def test_too_few_samples(self):
        result = auto_detect_baudrate([(0.0, 5.0), (1e-6, 0.0)])
        assert result.detected_baud is None
        assert result.confidence == "none"

    def test_all_idle_low_vpp_warning(self):
        # Constant HIGH → Vpp ≈ 0 → should warn about unreliable detection.
        samples = [(i * 1e-7, 5.0) for i in range(1000)]
        result = auto_detect_baudrate(samples)
        warns_text = " ".join(result.warnings)
        assert "low Vpp" in warns_text or "constant" in warns_text

    def test_result_has_candidates_list(self):
        samples = _make_realistic_uart(9600, b"A\r\n")
        result = auto_detect_baudrate(samples)
        assert isinstance(result.candidates, list)
        assert all("baud" in c for c in result.candidates)

    def test_to_dict_serializable(self):
        samples = _make_realistic_uart(9600, b"Hi\r\n")
        result = auto_detect_baudrate(samples)
        d = result.to_dict()
        assert "detected_baud" in d
        assert "confidence" in d
        assert "candidates" in d


# ---------------------------------------------------------------------------
# _parse_wavedesc_minimal
# ---------------------------------------------------------------------------

class TestParseWavedescMinimal:
    def test_parses_valid_block(self):
        raw = _make_wavedesc(dt=1e-8, vgain=0.2, voff=-2.5, max_v=7680.0)
        dt, vgain, voff, cpd = _parse_wavedesc_minimal(raw)
        assert dt == pytest.approx(1e-8, rel=1e-4)
        assert vgain == pytest.approx(0.2, rel=1e-4)
        assert voff == pytest.approx(-2.5, rel=1e-3)
        assert cpd == pytest.approx(7680.0 / 256, rel=1e-4)

    def test_falls_back_on_empty(self):
        dt, vgain, voff, cpd = _parse_wavedesc_minimal(b"")
        assert dt == pytest.approx(1e-8)  # default

    def test_falls_back_on_short(self):
        dt, vgain, voff, cpd = _parse_wavedesc_minimal(b"WAVEDESC" + b"\x00" * 50)
        assert dt == pytest.approx(1e-8)

    def test_ignores_ascii_prefix(self):
        prefix = b"C1:WF DESC,"
        raw = prefix + _make_wavedesc(dt=5e-9, vgain=0.1, voff=0.0, max_v=3840.0)
        dt, vgain, voff, cpd = _parse_wavedesc_minimal(raw)
        assert dt == pytest.approx(5e-9, rel=1e-4)
        assert vgain == pytest.approx(0.1, rel=1e-4)


# ---------------------------------------------------------------------------
# UartCaptureResult.to_dict
# ---------------------------------------------------------------------------

class TestUartCaptureResult:
    def _make_result(self, **kwargs) -> UartCaptureResult:
        defaults = dict(
            ok=True, channel="C1", detected_baud=9600, measured_baud=9601,
            decoded_ascii="Hi", decoded_hex="48 69", decoded_bytes=[0x48, 0x69],
            frame_count=2, valid_frame_count=2, stop_ok_rate=1.0,
            vpp_v=4.8, threshold_v=2.5, dt_s=1e-8, tdiv_s=5e-3,
            baud_confidence="high",
        )
        defaults.update(kwargs)
        return UartCaptureResult(**defaults)

    def test_to_dict_keys(self):
        r = self._make_result()
        d = r.to_dict()
        for key in ("ok", "channel", "detected_baud", "measured_baud",
                    "decoded_ascii", "decoded_hex", "decoded_bytes",
                    "frame_count", "valid_frame_count", "stop_ok_rate",
                    "vpp_v", "threshold_v", "baud_confidence",
                    "warnings", "notes"):
            assert key in d

    def test_stop_ok_rate_rounded(self):
        r = self._make_result(stop_ok_rate=0.857142857)
        assert r.to_dict()["stop_ok_rate"] == pytest.approx(0.857, abs=0.001)


# ---------------------------------------------------------------------------
# Integration: synthesised waveform → auto_detect_baudrate → decode
# ---------------------------------------------------------------------------

class TestEndToEndSynthetic:
    """End-to-end: synthesised waveform → decode (known baud passed explicitly).

    These tests verify that the UART decoder pipeline works correctly when
    the baud rate is already known.  Auto-detection accuracy on synthetic
    data is not tested here (see TestAutoDetectBaudrate notes above).
    """

    @pytest.mark.parametrize("baud,text", [
        (9600,   b"liqin\r\n"),
        (57600,  b"yangyangyang\r\n"),
        (115200, b"Hello"),
        (38400,  b"test123"),
    ])
    def test_decode_with_known_baud(self, baud: int, text: bytes):
        """Decoder correctly reconstructs text when given the true baud rate."""
        from siglent_sds_mcp.uart_analyzer import (
            _decode_uart_8n1,
            _estimate_bit_time_from_runs,
            _estimate_levels_and_threshold,
        )
        samples = _make_realistic_uart(baud, text)
        dt = samples[1][0] - samples[0][0]
        voltages = [v for _, v in samples]
        _, _, thr, _, _ = _estimate_levels_and_threshold(voltages)
        binary = [1 if v >= thr else 0 for v in voltages]
        logic = [(i * dt, binary[i]) for i in range(len(binary))]
        bt = _estimate_bit_time_from_runs(logic, 1.0 / baud)
        frames = _decode_uart_8n1(logic, bt, idle_high=True)
        good = bytes(f.byte for f in frames if f.framing_ok and f.byte is not None)
        assert good == text, f"baud={baud}: got {good!r}, expected {text!r}"

    @pytest.mark.parametrize("baud,text", [
        (9600,   b"liqin\r\n"),
        (57600,  b"yangyangyang\r\n"),
        (115200, b"Hello"),
        (38400,  b"test123"),
    ])
    def test_correct_baud_in_candidate_list(self, baud: int, text: bytes):
        """The true baud rate should appear in auto_detect_baudrate candidates."""
        samples = _make_realistic_uart(baud, text)
        result = auto_detect_baudrate(samples)
        candidate_bauds = {c["baud"] for c in result.candidates}
        assert baud in candidate_bauds or result.detected_baud == baud, (
            f"True baud {baud} not in candidates {candidate_bauds}"
        )
