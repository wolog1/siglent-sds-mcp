from __future__ import annotations

import pytest

from siglent_sds_mcp.modbus_timing import calculate_modbus_rtu_timing


def test_modbus_9600_8n1_timing() -> None:
    timing = calculate_modbus_rtu_timing(baudrate=9600, data_bits=8, parity="N", stop_bits=1)
    assert timing.bits_per_char == 10
    assert timing.char_time_s == pytest.approx(10 / 9600)
    assert timing.silence_3_5_char_s == pytest.approx(35 / 9600)


def test_modbus_9600_8e1_timing() -> None:
    timing = calculate_modbus_rtu_timing(baudrate=9600, data_bits=8, parity="E", stop_bits=1)
    assert timing.bits_per_char == 11
    assert timing.char_time_s == pytest.approx(11 / 9600)
    assert timing.silence_3_5_char_s == pytest.approx(38.5 / 9600)


def test_invalid_modbus_timing_args() -> None:
    with pytest.raises(ValueError):
        calculate_modbus_rtu_timing(baudrate=0)
    with pytest.raises(ValueError):
        calculate_modbus_rtu_timing(baudrate=9600, parity="X")  # type: ignore[arg-type]
