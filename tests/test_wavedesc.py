from __future__ import annotations

import struct

import pytest

from siglent_sds_mcp.sds_tcp_adapter import _parse_wavedesc

# WAVEDESC binary layout (little-endian):
#   offset 0:    WAVEDESC\0 signature
#   offset 116:  int32   WAVE_ARRAY_COUNT
#   offset 156:  float32 VERTICAL_GAIN (V/div)
#   offset 160:  float32 VERTICAL_OFFSET (V)
#   offset 164:  float32 MAX_VALUE (ADC full-scale code)
#   offset 176:  float32 HORIZ_INTERVAL (s/sample)
#   offset 180:  float64 HORIZ_OFFSET (s) = TRDL

_WAVEDESC_SIG = b"WAVEDESC"
_MIN_LEN = 180 + 8  # offset + size of float64


def _build_desc(
    wave_array_count: int = 2000,
    vertical_gain: float = 1.0,
    vertical_offset: float = 0.0,
    max_value: float = 7680.0,
    horiz_interval: float = 1e-9,
    horiz_offset: float = 0.0,
) -> bytes:
    """Build a minimal synthetic WAVEDESC for testing."""
    buf = bytearray(_MIN_LEN)
    buf[0:8] = _WAVEDESC_SIG
    struct.pack_into("<i", buf, 116, wave_array_count)
    struct.pack_into("<f", buf, 156, vertical_gain)
    struct.pack_into("<f", buf, 160, vertical_offset)
    struct.pack_into("<f", buf, 164, max_value)
    struct.pack_into("<f", buf, 176, horiz_interval)
    struct.pack_into("<d", buf, 180, horiz_offset)
    return bytes(buf)


class TestParseWavedesc:
    def test_basic_decode(self) -> None:
        desc = _build_desc(
            wave_array_count=5000,
            vertical_gain=0.5,
            vertical_offset=-0.1,
            max_value=7680.0,
            horiz_interval=5e-10,
            horiz_offset=2e-6,
        )
        result = _parse_wavedesc(desc)
        assert result is not None
        assert result.wave_array_count == 5000
        assert result.vertical_gain_vdiv == pytest.approx(0.5)
        assert result.vertical_offset == pytest.approx(-0.1)
        assert result.max_value == pytest.approx(7680.0)
        assert result.codes_per_div == pytest.approx(30.0)  # 7680/256
        assert result.gain_v_per_code == pytest.approx(0.5 / 30.0)
        assert result.horiz_interval == pytest.approx(5e-10)
        assert result.horiz_offset == pytest.approx(2e-6)

    def test_with_ascii_prefix(self) -> None:
        """WAVEDESC preceded by 'C1:WF DESC,' ASCII prefix."""
        desc = _build_desc(wave_array_count=1000, vertical_gain=0.1)
        prefixed = b"C1:WF DESC," + desc
        result = _parse_wavedesc(prefixed)
        assert result is not None
        assert result.wave_array_count == 1000
        assert result.vertical_gain_vdiv == pytest.approx(0.1)

    def test_missing_signature_returns_none(self) -> None:
        data = b"\x00" * _MIN_LEN
        assert _parse_wavedesc(data) is None

    def test_too_short_returns_none(self) -> None:
        assert _parse_wavedesc(b"WAVEDESC") is None  # only 8 bytes

    def test_zero_gain_returns_none(self) -> None:
        desc = _build_desc(vertical_gain=0.0)
        assert _parse_wavedesc(desc) is None

    def test_zero_max_value_returns_none(self) -> None:
        desc = _build_desc(max_value=0.0)
        assert _parse_wavedesc(desc) is None

    def test_codes_per_div_from_different_max_value(self) -> None:
        """MAX_VALUE=25600 → codes_per_div=100."""
        desc = _build_desc(max_value=25600.0, vertical_gain=1.0)
        result = _parse_wavedesc(desc)
        assert result is not None
        assert result.codes_per_div == pytest.approx(100.0)
        assert result.gain_v_per_code == pytest.approx(0.01)  # 1.0/100
