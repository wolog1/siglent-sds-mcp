from __future__ import annotations

from siglent_sds_mcp.auto_setup import choose_timebase, choose_vdiv


def test_choose_vdiv_targets_about_five_divisions() -> None:
    assert choose_vdiv(3.3) == "1V"
    assert choose_vdiv(0.2) == "50mV"
    assert choose_vdiv(12.0) == "5V"


def test_choose_timebase_for_uart_edges() -> None:
    assert choose_timebase(0.5e-6, signal_hint="uart") in {"1US", "2US"}
    assert choose_timebase(None, signal_hint="modbus") == "100US"
    assert choose_timebase(None, signal_hint="unknown") == "1MS"
