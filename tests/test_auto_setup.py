"""Test auto_setup helper functions and mock adapter behavior."""
from __future__ import annotations

import pytest

from siglent_sds_mcp.sds_tcp_adapter import (
    _VDIV_STEPS_V,
    _TDIV_STEPS_S,
    _pick_vdiv,
    _pick_tdiv,
    _parse_meas_value,
    _fmt_sci,
)


class TestPickVdiv:
    def test_exact_fit(self) -> None:
        # 600mV PKPK → 需要 >=100mV/div (6格)
        assert _pick_vdiv(0.6) == 0.1

    def test_just_above_step(self) -> None:
        # 110mV → 需要 >=20mV/div
        assert _pick_vdiv(0.11) == 20e-3

    def test_zero_pkpk_fallback(self) -> None:
        assert _pick_vdiv(0.0) == 20e-3

    def test_max_range(self) -> None:
        assert _pick_vdiv(50.0) == 5.0


class TestPickTdiv:
    def test_1mhz_square(self) -> None:
        # 1MHz 周期=1µs, 4个周期/14格 → 需要 >=286ns/div → 500ns
        assert _pick_tdiv(1e-6, cycles=4.0) == 500e-9

    def test_62mhz_signal(self) -> None:
        # 62MHz 周期=16.1ns, 4周期/14格 → 需要 >=4.6ns/div → 5ns
        assert _pick_tdiv(16.1e-9, cycles=4.0) == 5e-9

    def test_low_freq(self) -> None:
        # 1kHz 周期=1ms, 4周期/14格 → 286µs/div → 500µs
        assert _pick_tdiv(1e-3, cycles=4.0) == 500e-6

    def test_zero_period_fallback(self) -> None:
        assert _pick_tdiv(0.0) == 5e-6


class TestParseMeasValue:
    def test_valid(self) -> None:
        assert _parse_meas_value("PKPK,2.04E-02") == pytest.approx(0.0204)

    def test_asterisk_invalid(self) -> None:
        assert _parse_meas_value("FREQ,****") is None

    def test_empty(self) -> None:
        assert _parse_meas_value("") is None

    def test_no_comma(self) -> None:
        assert _parse_meas_value("2.04E-02") == pytest.approx(0.0204)


class TestFmtSci:
    def test_millivolt(self) -> None:
        assert _fmt_sci(0.02) == "2.0000E-02"

    def test_microsecond(self) -> None:
        assert _fmt_sci(500e-9) == "5.0000E-07"

    def test_negative(self) -> None:
        assert _fmt_sci(-0.16) == "-1.6000E-01"
