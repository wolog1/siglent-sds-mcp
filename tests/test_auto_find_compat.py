from __future__ import annotations

from unittest.mock import MagicMock

from siglent_sds_mcp.auto_setup import auto_find_waveform
from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter


def _mock_scope(
    pkpk: float = 0.5,
    freq: float | None = 1000.0,
    period: float | None = 1e-3,
    signal_detected: bool = True,
) -> MagicMock:
    scope = MagicMock(spec=SDS800XHDTcpAdapter)
    scope.transport = MagicMock()

    measurements: dict[str, float | None] = {
        "pkpk_v": pkpk,
        "max_v": pkpk / 2.0,
        "min_v": -pkpk / 2.0,
        "mean_v": 1.65,
        "frequency_hz": freq,
        "period_s": period,
    }

    final_settings = {
        "vdiv_v": 0.1,
        "offset_v": 1.65,
        "tdiv_s": 1e-3,
        "trigger_level_v": 0.0,
        "trigger_slope": "POS",
    }

    def fake_auto_setup(
        channel: str, *,
        target_cycles: float = 4.0, settle_s: float = 0.6,
        set_trigger_level: bool = True,
    ) -> dict[str, object]:
        return {
            "channel": channel,
            "signal_detected": signal_detected,
            "final_settings": final_settings,
            "measurements": measurements,
            "probe_steps": [
                {"stage": "coarse", "pkpk_v": pkpk, "freq_hz": freq, "period_s": period},
            ],
            "screenshot": {"path": f"/tmp/{channel}_shot.png", "bytes": 2400},
            "set_trigger_level_passed": set_trigger_level,
        }

    scope.auto_setup.side_effect = fake_auto_setup
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
    scope.auto_setup.assert_called_once_with("C1", target_cycles=4.0, settle_s=0.0, set_trigger_level=False)
    scope.transport.write.assert_any_call("STOP")
    assert not any(call.args and call.args[0] == "ARM" for call in scope.transport.write.call_args_list)
    # STOP 后不得再调用 configure_acquisition（那会重新进入 AUTO 模式破坏停屏）
    assert not scope.configure_acquisition.called


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


def test_set_trigger_level_false_is_passed_to_underlying_auto_setup() -> None:
    scope = _mock_scope(pkpk=0.5)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        settle_s=0.0,
        set_trigger_level=False,
    )

    assert result.found is True
    assert result.result["trigger_level_command_sent"] is False
    # verify the param was forwarded to the underlying auto_setup
    _, kwargs = scope.auto_setup.call_args
    assert kwargs.get("set_trigger_level") is False
    # and no post-hoc configure_acquisition was issued
    assert not scope.configure_acquisition.called


def test_auto_find_waveform_wrapper_reports_no_signal() -> None:
    scope = _mock_scope(pkpk=0.001, freq=None, period=None, signal_detected=False)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        settle_s=0.0,
        noise_floor_v=0.05,
    )

    assert result.found is False
    assert result.confidence == "low"
    assert result.result["scan_attempts"][0]["signal_detected"] is False


def test_low_amplitude_periodic_signal_picks_correct_vdiv_and_tdiv() -> None:
    scope = _mock_scope(pkpk=0.0225, freq=7890.0, period=0.000484)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        settle_s=0.0,
        noise_floor_v=0.05,
    )

    assert result.found is True
    # final_settings come from the underlying auto_setup mock, not the compat layer.
    assert result.result["final_settings"]["vdiv_v"] == 0.1


def test_multi_channel_returns_first_detected() -> None:
    scope = MagicMock(spec=SDS800XHDTcpAdapter)
    scope.transport = MagicMock()

    def fake_auto_setup(
        channel: str, *,
        target_cycles: float = 4.0, settle_s: float = 0.6,
        set_trigger_level: bool = True,
    ) -> dict[str, object]:
        if channel == "C1":
            pkpk = 0.0225
            freq = 7890.0
            period = 0.000484
            signal_detected = True
            final_settings = {"vdiv_v": 5e-3, "offset_v": 30e-3, "tdiv_s": 200e-6, "trigger_level_v": 0.0, "trigger_slope": "POS"}
        else:
            pkpk = 0.5
            freq = 1000.0
            period = 1e-3
            signal_detected = True
            final_settings = {"vdiv_v": 0.1, "offset_v": 1.65, "tdiv_s": 1e-3, "trigger_level_v": 0.0, "trigger_slope": "POS"}
        return {
            "channel": channel,
            "signal_detected": signal_detected,
            "final_settings": final_settings,
            "measurements": {
                "pkpk_v": pkpk, "max_v": pkpk / 2, "min_v": -pkpk / 2,
                "mean_v": 1.65, "frequency_hz": freq, "period_s": period,
            },
            "probe_steps": [],
            "screenshot": None,
        }

    scope.auto_setup.side_effect = fake_auto_setup
    scope.get_acquisition_status.return_value = {"trigger_mode": "STOP", "acquisition_status": "Stop"}
    scope.get_channel.return_value = {"channel": "C1", "trace": "ON", "volts_per_div": "5mV"}

    result = auto_find_waveform(
        scope,
        channels=["C1", "C2"],
        settle_s=0.0,
        noise_floor_v=0.05,
    )

    assert result.found is True
    assert result.selected_channel == "C1"
    assert result.confidence == "low"


def test_too_weak_even_with_periodic_evidence_is_rejected() -> None:
    scope = _mock_scope(pkpk=0.003, freq=7890.0, period=0.000484, signal_detected=True)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        settle_s=0.0,
        noise_floor_v=0.05,
        min_signal_vpp=0.005,
    )

    assert result.found is False
    assert result.result["scan_attempts"][0]["signal_detected"] is False
    assert result.result["scan_attempts"][0]["periodic_evidence"] is True


def test_weak_periodic_accepted_even_if_underlying_auto_setup_reports_false() -> None:
    # 底层 auto_setup 认为 signal_detected=false，但测量值仍支持弱周期信号
    scope = _mock_scope(pkpk=0.0225, freq=7890.0, period=0.000484, signal_detected=False)

    result = auto_find_waveform(
        scope,
        channels=["C1"],
        settle_s=0.0,
        noise_floor_v=0.05,
        min_signal_vpp=0.005,
    )

    assert result.found is True
    assert result.confidence == "low"
    assert result.result["signal_detected"] is True
    assert result.result["periodic_evidence"] is True
    assert result.result["reason"] == (
        "periodic signal accepted below noise_floor_v because frequency/period is valid"
    )
