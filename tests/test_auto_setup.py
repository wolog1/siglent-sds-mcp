"""Test auto_setup helper functions and mock adapter behavior."""
from __future__ import annotations

import pytest

from siglent_sds_mcp.sds_tcp_adapter import (
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


class TestAutoSetupTriggerLevel:
    """Verify that set_trigger_level=False prevents any TRLV command."""

    def test_set_trigger_level_false_no_trlv(self) -> None:
        from unittest.mock import MagicMock
        from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter

        transport = MagicMock()
        transport.query.side_effect = lambda cmd: {
            "C1:VDIV?": "1.00E+00",
            "C1:OFST?": "0.00E+00",
            "C1:ATTN?": "1",
            "TDIV?": "1.00E-03",
            "SARA?": "5.00E+08",
            "SAST?": "Stop",
            "TRMD?": "AUTO",
            "C1:PAVA? PKPK": "PKPK,5.0000E-01",
            "C1:PAVA? MEAN": "MEAN,1.6500E+00",
            "C1:PAVA? FREQ": "FREQ,1.0000E+03",
            "C1:PAVA? PER": "PER,1.0000E-03",
            "C1:PAVA? MAX": "MAX,3.3000E+00",
            "C1:PAVA? MIN": "MIN,0.0000E+00",
        }.get(cmd, "")

        adapter = SDS800XHDTcpAdapter(transport)
        adapter.auto_setup("C1", settle_s=0.0, set_trigger_level=False)

        written_commands: list[str] = []
        for call in transport.write.call_args_list:
            written_commands.append(call.args[0])

        # 断言：没有任何命令包含 TRLV
        trlv_commands = [c for c in written_commands if "TRLV" in c]
        assert len(trlv_commands) == 0, f"Unexpected TRLV commands: {trlv_commands}"

    def test_set_trigger_level_true_sends_trlv(self) -> None:
        from unittest.mock import MagicMock
        from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter

        transport = MagicMock()
        transport.query.side_effect = lambda cmd: {
            "C1:VDIV?": "1.00E+00",
            "C1:OFST?": "0.00E+00",
            "C1:ATTN?": "1",
            "TDIV?": "1.00E-03",
            "SARA?": "5.00E+08",
            "SAST?": "Stop",
            "TRMD?": "AUTO",
            "C1:PAVA? PKPK": "PKPK,5.0000E-01",
            "C1:PAVA? MEAN": "MEAN,1.6500E+00",
            "C1:PAVA? FREQ": "FREQ,1.0000E+03",
            "C1:PAVA? PER": "PER,1.0000E-03",
            "C1:PAVA? MAX": "MAX,3.3000E+00",
            "C1:PAVA? MIN": "MIN,0.0000E+00",
        }.get(cmd, "")

        adapter = SDS800XHDTcpAdapter(transport)
        adapter.auto_setup("C1", settle_s=0.0, set_trigger_level=True)

        written_commands: list[str] = []
        for call in transport.write.call_args_list:
            written_commands.append(call.args[0])

        trlv_commands = [c for c in written_commands if "TRLV" in c]
        assert len(trlv_commands) > 0, "Expected TRLV commands but none found"

    def test_default_set_trigger_level_is_false(self) -> None:
        import inspect
        from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter

        sig = inspect.signature(SDS800XHDTcpAdapter.auto_setup)
        param = sig.parameters["set_trigger_level"]
        assert param.default is False, f"Expected default=False, got {param.default}"
