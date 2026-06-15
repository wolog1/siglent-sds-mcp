from __future__ import annotations

import struct

import pytest

from siglent_sds_mcp.sds_tcp_adapter import _parse_wavedesc


def test_parse_synthetic_wavedesc_descriptor() -> None:
    data = bytearray(256)
    data[0:8] = b"WAVEDESC"
    struct.pack_into("<i", data, 116, 1000)       # WAVE_ARRAY_COUNT
    struct.pack_into("<f", data, 156, 1.0)        # VERTICAL_GAIN = V/div
    struct.pack_into("<f", data, 160, 0.25)       # VERTICAL_OFFSET
    struct.pack_into("<f", data, 164, 7680.0)     # MAX_VALUE = 30 * 256
    struct.pack_into("<f", data, 176, 1e-9)       # HORIZ_INTERVAL
    struct.pack_into("<d", data, 180, 5e-6)       # HORIZ_OFFSET

    desc = _parse_wavedesc(bytes(data))
    assert desc is not None
    assert desc.wave_array_count == 1000
    assert desc.vertical_gain_vdiv == pytest.approx(1.0)
    assert desc.vertical_offset == pytest.approx(0.25)
    assert desc.max_value == pytest.approx(7680.0)
    assert desc.codes_per_div == pytest.approx(30.0)
    assert desc.gain_v_per_code == pytest.approx(1.0 / 30.0)
    assert desc.horiz_interval == pytest.approx(1e-9)
    assert desc.horiz_offset == pytest.approx(5e-6)


def test_parse_wavedesc_returns_none_without_signature() -> None:
    assert _parse_wavedesc(b"not a descriptor") is None
