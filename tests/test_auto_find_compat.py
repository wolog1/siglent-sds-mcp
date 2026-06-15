from __future__ import annotations

from unittest.mock import MagicMock

from siglent_sds_mcp.auto_setup import auto_find_waveform
from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter


def _mock_scope(pkpk: float = 0.5, freq: float = 1000.0, period: float = 1e-3) -> MagicMock:
    scope = MagicMock(spec=SDS800XHDTcpAdapter)
    scope.transport = MagicMock()

    values = {
        "PKPK": f"PKPK,{pkpk:.4E}",
        "MEAN": "MEAN,1.6500E+00",
        "MAX": "MAX,3.3000E+00",
        "MIN": "MIN,0.0000E+00",
        "FREQ": f"FREQ,{freq:.4E}",
        "PER": f"PER,{period:.4E}",
    }

    def fake_measure(channel: str, parameter: str) -> dict[str, str]:
        return {"value": values[parameter]}

    scope.measure.side_effect = fake_measure
    scope.get_acquisition_status.return_value = {"trigger_mode": "STOP", "acquisition_status": "Stop"}
    scope.get_channel.return_value = {"channel": "C1", "trace": "ON", "volts_per_div": "100mV"}
    return scope


def test_auto_find_waveform_wrapper_detects_signal_and_holds_screen() -> None:
    scope = _mock_scope(pkpk=0.5)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        signal_hint="clock",
        settle_s=0.0,
        probe=1.0,
    )

    assert result.found is True
    assert result.selected_channel == "C1"
    assert result.screen_hold is True
    assert result.leave_stopped is True
    assert result.probe == 1.0
    assert result.result["signal_detected"] is True
    assert result.result["trigger_level_command_sent"] is False
    scope.transport.write.assert_any_call("STOP")
    assert not any(call.args and call.args[0] == "ARM" for call in scope.transport.write.call_args_list)


def test_low_amplitude_periodic_signal_is_accepted() -> None:
    scope = _mock_scope(pkpk=0.0225, freq=7890.0, period=0.000484)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        signal_hint="clock",
        settle_s=0.0,
        noise_floor_v=0.05,
    )

    assert result.found is True
    assert result.confidence == "low"
    assert result.result["signal_detected"] is True
    assert result.result["periodic_evidence"] is True
    assert result.result["min_signal_vpp"] == 0.005
    assert result.result["reason"] == (
        "periodic signal accepted below noise_floor_v because frequency/period is valid"
    )


def test_auto_find_waveform_wrapper_can_restart_when_requested() -> None:
    scope = _mock_scope(pkpk=0.5)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        settle_s=0.0,
        leave_stopped=False,
    )

    assert result.found is True
    assert result.screen_hold is False
    scope.transport.write.assert_any_call("ARM")


def test_auto_find_waveform_wrapper_reports_no_signal() -> None:
    scope = _mock_scope(pkpk=0.001)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        settle_s=0.0,
        noise_floor_v=0.05,
    )

    assert result.found is False
    assert result.confidence == "low"
    assert result.result["scan_attempts"][0]["signal_detected"] is False
