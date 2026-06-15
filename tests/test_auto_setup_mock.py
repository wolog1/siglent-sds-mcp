from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

from siglent_sds_mcp.auto_setup import auto_find_waveform
from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter, WaveformResult


def _write_wave_csv(path: Path, voltages: list[float], dt: float = 1e-6) -> str:
    p = str(path)
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "voltage_v"])
        for i, v in enumerate(voltages):
            writer.writerow([i * dt, v])
    return p


def _make_waveform_result(csv_path: str) -> WaveformResult:
    return WaveformResult(
        csv_path=csv_path,
        metadata_path=csv_path.replace(".csv", ".json"),
        metadata={"channel": "C1", "binary": {"bytes": 1000}},
    )


def _mock_scope(csv_path: str) -> MagicMock:
    mock_scope = MagicMock(spec=SDS800XHDTcpAdapter)
    mock_scope.transport = MagicMock()
    mock_scope.get_waveform.return_value = _make_waveform_result(csv_path)
    mock_scope.screenshot.return_value = {
        "path": "shot.bmp",
        "bytes": 1000,
        "framing": "raw-bmp",
    }
    mock_scope.get_channel.return_value = {
        "channel": "C1",
        "volts_per_div": "1V",
        "offset": "1.65V",
        "trace": "ON",
    }
    mock_scope.get_acquisition_status.return_value = {
        "trigger_mode": "STOP",
        "acquisition_status": "Stopped",
        "timebase": "1MS",
    }
    return mock_scope


class TestAutoSetupMock:
    def test_selects_active_channel(self, tmp_path: Path) -> None:
        c1_path = _write_wave_csv(
            tmp_path / "c1.csv",
            [3.3 if (i // 10) % 2 == 0 else 0.0 for i in range(200)],
        )
        c2_path = _write_wave_csv(tmp_path / "c2.csv", [0.01 for _ in range(200)])

        mock_scope = MagicMock(spec=SDS800XHDTcpAdapter)
        mock_scope.transport = MagicMock()

        def fake_get_waveform(channel, max_points=5000, **kwargs):
            path = c1_path if channel == "C1" else c2_path
            return _make_waveform_result(path)

        mock_scope.get_waveform.side_effect = fake_get_waveform
        mock_scope.screenshot.return_value = {
            "path": str(tmp_path / "shot.bmp"),
            "bytes": 1000,
            "framing": "raw-bmp",
        }
        mock_scope.get_channel.return_value = {"channel": "C1", "trace": "ON"}
        mock_scope.get_acquisition_status.return_value = {"trigger_mode": "STOP"}

        result = auto_find_waveform(
            mock_scope,
            channels=["C1", "C2"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is True
        assert result.selected_channel == "C1"
        assert result.confidence == "high"
        assert result.recommended_vdiv is not None
        assert result.coarse_stats is not None
        assert result.final_stats is not None
        assert result.screen_hold is True

    def test_no_active_channel(self, tmp_path: Path) -> None:
        flat = _write_wave_csv(tmp_path / "flat.csv", [0.0 for _ in range(100)])
        mock_scope = _mock_scope(flat)

        result = auto_find_waveform(
            mock_scope,
            channels=["C1", "C2"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is False
        assert result.confidence == "low"
        assert result.screen_hold is False

    def test_coarse_and_final_stats_present(self, tmp_path: Path) -> None:
        c1_path = _write_wave_csv(
            tmp_path / "signal.csv",
            [5.0 if (i // 5) % 2 == 0 else 0.0 for i in range(500)],
        )
        mock_scope = _mock_scope(c1_path)

        result = auto_find_waveform(
            mock_scope,
            channels=["C1"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is True
        assert result.coarse_stats is not None
        assert result.final_stats is not None
        assert result.offset_direction_status == (
            "verified_on_sds824xhd: display_offset_uses_waveform_mean"
        )
        assert float(result.coarse_stats["v_pp"]) > 4.0
        assert float(result.final_stats["v_pp"]) > 4.0

    def test_uart_hint_selects_neg_slope_without_trigger_level_by_default(
        self,
        tmp_path: Path,
    ) -> None:
        c1_path = _write_wave_csv(
            tmp_path / "uart.csv",
            [3.3 if (i // 8) % 2 == 0 else 0.0 for i in range(160)],
            dt=2e-6,
        )
        mock_scope = _mock_scope(c1_path)

        result = auto_find_waveform(
            mock_scope,
            channels=["C1"],
            signal_hint="uart",
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is True
        acq_calls = [
            c
            for c in mock_scope.configure_acquisition.call_args_list
            if "trigger_slope" in c.kwargs
        ]
        assert any(c.kwargs.get("trigger_slope") == "NEG" for c in acq_calls)
        assert all(c.kwargs.get("trigger_level") is None for c in acq_calls)
        assert result.trigger_level_command_sent is False

    def test_can_send_trigger_level_when_explicitly_requested(self, tmp_path: Path) -> None:
        c1_path = _write_wave_csv(
            tmp_path / "signal.csv",
            [3.3 if (i // 10) % 2 == 0 else 0.0 for i in range(200)],
        )
        mock_scope = _mock_scope(c1_path)

        result = auto_find_waveform(
            mock_scope,
            channels=["C1"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
            set_trigger_level=True,
        )

        assert result.trigger_level_command_sent is True
        assert any(
            c.kwargs.get("trigger_level") is not None
            for c in mock_scope.configure_acquisition.call_args_list
            if "trigger_level" in c.kwargs
        )

    def test_screenshot_and_csv_leave_scope_stopped_by_default(self, tmp_path: Path) -> None:
        c1_path = _write_wave_csv(
            tmp_path / "signal.csv",
            [3.3 if (i // 10) % 2 == 0 else 0.0 for i in range(200)],
        )
        mock_scope = _mock_scope(c1_path)

        result = auto_find_waveform(
            mock_scope,
            channels=["C1"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is True
        assert result.screenshot_path is not None
        assert result.final_waveform_csv is not None
        assert result.final_stats is not None
        assert result.leave_stopped is True
        assert result.screen_hold is True

        final_wf_call = mock_scope.get_waveform.call_args_list[-1]
        assert final_wf_call.kwargs.get("restore_trmd") is False
        mock_scope.screenshot.assert_called_once()
        arm_calls = [
            c
            for c in mock_scope.transport.write.call_args_list
            if c.args and c.args[0] == "ARM"
        ]
        assert arm_calls == []

    def test_restart_after_capture_when_leave_stopped_false(self, tmp_path: Path) -> None:
        c1_path = _write_wave_csv(
            tmp_path / "signal.csv",
            [3.3 if (i // 10) % 2 == 0 else 0.0 for i in range(200)],
        )
        mock_scope = _mock_scope(c1_path)

        result = auto_find_waveform(
            mock_scope,
            channels=["C1"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
            leave_stopped=False,
        )

        assert result.leave_stopped is False
        assert result.screen_hold is False
        arm_calls = [
            c
            for c in mock_scope.transport.write.call_args_list
            if c.args and c.args[0] == "ARM"
        ]
        assert len(arm_calls) >= 1

    def test_probe_parameter_is_applied(self, tmp_path: Path) -> None:
        c1_path = _write_wave_csv(
            tmp_path / "signal.csv",
            [3.3 if (i // 10) % 2 == 0 else 0.0 for i in range(200)],
        )
        mock_scope = _mock_scope(c1_path)

        result = auto_find_waveform(
            mock_scope,
            channels=["C1"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
            probe=1.0,
        )

        assert result.probe == 1.0
        assert any(
            c.kwargs.get("probe") == 1.0
            for c in mock_scope.configure_channel.call_args_list
        )
