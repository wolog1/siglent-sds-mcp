from __future__ import annotations

import pytest

from siglent_sds_mcp.sds_tcp_adapter import (
    _parse_voltage,
    _parse_time,
    _parse_sample_rate,
    _parse_number_with_units,
)


class TestParseVoltage:
    def test_bare_number(self) -> None:
        assert _parse_voltage("1.00E-01") == 0.1
        assert _parse_voltage("5.0") == 5.0
        assert _parse_voltage("-1.60E-01") == -0.16

    def test_millivolt(self) -> None:
        assert _parse_voltage("500mV") == 0.5
        assert _parse_voltage("50mV") == 0.05
        assert _parse_voltage("1mV") == 0.001

    def test_volt(self) -> None:
        assert _parse_voltage("1V") == 1.0
        assert _parse_voltage("10V") == 10.0
        assert _parse_voltage("0.5V") == 0.5

    def test_megavolt(self) -> None:
        assert _parse_voltage("1MV") == 1e6
        assert _parse_voltage("2.5MV") == 2.5e6

    def test_kilovolt(self) -> None:
        assert _parse_voltage("1KV") == 1e3
        assert _parse_voltage("3.3KV") == 3300.0

    def test_microvolt(self) -> None:
        assert _parse_voltage("500uV") == 5e-4
        assert _parse_voltage("500μV") == 5e-4

    def test_mv_not_mv_distinction(self) -> None:
        """mV (millivolt) must NOT be parsed as MV (megavolt)."""
        assert _parse_voltage("500mV") == 0.5  # not 500e6!
        assert _parse_voltage("1MV") == 1e6    # uppercase M is mega

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_voltage("")


class TestParseTime:
    def test_bare_scientific(self) -> None:
        assert _parse_time("5.00E-06") == 5e-6
        assert _parse_time("1.00E-03") == 0.001

    def test_milliseconds_scope_convention(self) -> None:
        """Scope returns MS = milliseconds, NOT megaseconds."""
        assert _parse_time("1MS") == 0.001
        assert _parse_time("500MS") == 0.5
        assert _parse_time("100MS") == 0.1

    def test_microseconds(self) -> None:
        assert _parse_time("500US") == 5e-4
        assert _parse_time("500μS") == 5e-4
        assert _parse_time("1US") == 1e-6

    def test_nanoseconds(self) -> None:
        assert _parse_time("50NS") == pytest.approx(5e-8)
        assert _parse_time("1NS") == pytest.approx(1e-9)

    def test_seconds(self) -> None:
        assert _parse_time("1S") == 1.0
        assert _parse_time("0.5S") == 0.5

    def test_kiloseconds(self) -> None:
        assert _parse_time("1KS") == 1000.0

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_time("")


class TestParseSampleRate:
    def test_bare_scientific(self) -> None:
        assert _parse_sample_rate("2.00E+09") == 2e9
        assert _parse_sample_rate("1.00E+09") == 1e9

    def test_with_sa_s_suffix(self) -> None:
        assert _parse_sample_rate("500MSa/s") == 5e8
        assert _parse_sample_rate("2GSa/s") == 2e9
        assert _parse_sample_rate("1KSa/s") == 1e3

    def test_without_suffix(self) -> None:
        assert _parse_sample_rate("500M") == 5e8
        assert _parse_sample_rate("2G") == 2e9
        assert _parse_sample_rate("1K") == 1e3

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_sample_rate("")


class TestParseNumberWithUnitsLegacy:
    def test_bare_number(self) -> None:
        assert _parse_number_with_units("42") == 42.0
        assert _parse_number_with_units("3.14") == 3.14
        assert _parse_number_with_units("1.00E-01") == 0.1

    def test_ms_time_fallback(self) -> None:
        """Legacy parser treats MS as milliseconds (time context)."""
        assert _parse_number_with_units("1MS") == 0.001

    def test_msa_sample_rate(self) -> None:
        assert _parse_number_with_units("500MSA") == 5e8

    def test_generic_prefixes(self) -> None:
        assert _parse_number_with_units("5K") == 5000.0
        assert _parse_number_with_units("2M") == 2e6
        assert _parse_number_with_units("1G") == 1e9

    def test_last_resort_numeric_prefix(self) -> None:
        assert _parse_number_with_units("5.0XYZ") == 5.0
