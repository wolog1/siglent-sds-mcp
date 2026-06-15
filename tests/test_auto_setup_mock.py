from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

from siglent_sds_mcp.auto_setup import auto_find_waveform
from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter, WaveformResult


def _write_wave_csv(path: Path, voltages: list[float], dt: float = 1e-6) -> str:
    """Write a synthetic waveform CSV and return the path."""
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


class TestAutoSetupMock:
    def test_selects_active_channel(self, tmp_path: Path) -> None:
        """C1 has a 3.3V square wave, C2 is flat — C1 should win."""
        # Build mock waveform CSVs
        c1_path = _write_wave_csv(
            tmp_path / "c1.csv",
            [3.3 if (i // 10) % 2 == 0 else 0.0 for i in range(200)],
        )
        c2_path = _write_wave_csv(
            tmp_path / "c2.csv",
            [0.01 for _ in range(200)],  # flat ~noise
        )

        mock_scope = MagicMock(spec=SDS800XHDTcpAdapter)
        mock_scope.identify.return_value = "SIGLENT,SDS824X HD,MOCK,1.0"
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

        result = auto_find_waveform(
            mock_scope,
            channels=["C1", "C2"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is True
        assert result.selected_channel == "C1"
        assert result.confidence == "high"  # Vpp >> noise floor, edges >> 4
        assert result.recommended_vdiv is not None
        assert result.coarse_stats is not None
        assert result.final_stats is not None

    def test_no_active_channel(self, tmp_path: Path) -> None:
        """Both channels flat — found=False."""
        flat = _write_wave_csv(tmp_path / "flat.csv", [0.0 for _ in range(100)])

        mock_scope = MagicMock(spec=SDS800XHDTcpAdapter)
        mock_scope.transport = MagicMock()
        mock_scope.get_waveform.return_value = _make_waveform_result(flat)
        mock_scope.screenshot.return_value = {
            "path": str(tmp_path / "shot.bmp"),
            "bytes": 1000,
            "framing": "raw-bmp",
        }

        result = auto_find_waveform(
            mock_scope,
            channels=["C1", "C2"],
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is False
        assert result.confidence == "low"

    def test_coarse_and_final_stats_present(self, tmp_path: Path) -> None:
        """Verify both coarse_stats and final_stats are populated."""
        c1_path = _write_wave_csv(
            tmp_path / "signal.csv",
            [5.0 if (i // 5) % 2 == 0 else 0.0 for i in range(500)],
        )

        mock_scope = MagicMock(spec=SDS800XHDTcpAdapter)
        mock_scope.transport = MagicMock()
        mock_scope.get_waveform.return_value = _make_waveform_result(c1_path)
        mock_scope.screenshot.return_value = {
            "path": str(tmp_path / "shot.bmp"),
            "bytes": 1000,
            "framing": "raw-bmp",
        }

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
        assert result.offset_direction_status == "needs_hardware_validation"

        # Both should have Vpp for the same signal
        coarse_vpp = result.coarse_stats.get("v_pp")
        final_vpp = result.final_stats.get("v_pp")
        assert coarse_vpp is not None
        assert final_vpp is not None
        assert float(coarse_vpp) > 4.0
        assert float(final_vpp) > 4.0

    def test_uart_hint_selects_neg_slope_and_appropriate_timebase(self, tmp_path: Path) -> None:
        """UART hint should use NEG slope and shorter timebase."""
        # 115200 baud → ~8.68us per bit, edge interval ~8.68us
        # Write a slow square wave with known edge interval
        c1_path = _write_wave_csv(
            tmp_path / "uart.csv",
            [3.3 if (i // 8) % 2 == 0 else 0.0 for i in range(160)],
            dt=2e-6,  # 2us per sample
        )

        mock_scope = MagicMock(spec=SDS800XHDTcpAdapter)
        mock_scope.transport = MagicMock()
        mock_scope.get_waveform.return_value = _make_waveform_result(c1_path)
        mock_scope.screenshot.return_value = {
            "path": str(tmp_path / "shot.bmp"),
            "bytes": 1000,
            "framing": "raw-bmp",
        }

        result = auto_find_waveform(
            mock_scope,
            channels=["C1"],
            signal_hint="uart",
            max_points=2000,
            noise_floor_v=0.05,
            settle_s=0.0,
        )

        assert result.found is True

        # Verify configure_acquisition was called with NEG slope
        acq_calls = [
            c for c in mock_scope.configure_acquisition.call_args_list
            if "trigger_slope" in c.kwargs
        ]
        assert any(c.kwargs.get("trigger_slope") == "NEG" for c in acq_calls)

    def test_screenshot_and_csv_from_same_stop_frame(self, tmp_path: Path) -> None:
        """Screenshot happens after get_waveform(restore_trmd=False) keeps scope stopped."""
        c1_path = _write_wave_csv(
            tmp_path / "signal.csv",
            [3.3 if (i // 10) % 2 == 0 else 0.0 for i in range(200)],
        )

        mock_scope = MagicMock(spec=SDS800XHDTcpAdapter)
        mock_scope.transport = MagicMock()
        mock_scope.get_waveform.return_value = _make_waveform_result(c1_path)
        mock_scope.screenshot.return_value = {
            "path": str(tmp_path / "shot.bmp"),
            "bytes": 1000,
            "framing": "raw-bmp",
        }

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

        # Verify call order: get_waveform (STOPs internally, stays stopped) →
        # screenshot (same frame) → ARM (restart)
        from unittest.mock import call as mc

        # get_waveform called twice: coarse scan + final (with restore_trmd=False)
        wf_calls = mock_scope.get_waveform.call_args_list
        final_wf_call = wf_calls[-1]
        assert final_wf_call.kwargs.get("restore_trmd") is False

        # screenshot() called after the final get_waveform
        mock_scope.screenshot.assert_called_once()

        # ARM is called at the very end to restart acquisition
        arm_calls = [c for c in mock_scope.transport.write.call_args_list
                     if c.args and c.args[0] == "ARM"]
        assert len(arm_calls) >= 1, "ARM should restart acquisition after captures"
