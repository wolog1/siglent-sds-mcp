from __future__ import annotations

import pytest

from siglent_sds_mcp.sds_tcp_adapter import _parse_sample_rate, _parse_time, _parse_voltage


def test_parse_voltage_units_are_case_sensitive() -> None:
    assert _parse_voltage("500mV") == pytest.approx(0.5)
    assert _parse_voltage("2V") == pytest.approx(2.0)
    assert _parse_voltage("1KV") == pytest.approx(1000.0)
    assert _parse_voltage("250uV") == pytest.approx(250e-6)


def test_parse_scope_time_units() -> None:
    assert _parse_time("1MS") == pytest.approx(1e-3)
    assert _parse_time("500US") == pytest.approx(500e-6)
    assert _parse_time("10NS") == pytest.approx(10e-9)
    assert _parse_time("1S") == pytest.approx(1.0)


def test_parse_sample_rate_units() -> None:
    assert _parse_sample_rate("500MSa/s") == pytest.approx(500_000_000.0)
    assert _parse_sample_rate("2GSa/s") == pytest.approx(2_000_000_000.0)
    assert _parse_sample_rate("1.25E+09") == pytest.approx(1_250_000_000.0)
