from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter
from siglent_sds_mcp.waveform_capture import get_waveform_with_mode


def _mock_scope() -> SDS800XHDTcpAdapter:
    transport = MagicMock()

    responses = {
        "C1:VDIV?": "1V",
        "C1:OFST?": "0V",
        "C1:ATTN?": "1",
        "TDIV?": "1MS",
        "SARA?": "1.0000E+06",
        "TRDL?": "0S",
        "TRMD?": "AUTO",
        "SAST?": "Stop",
    }
    transport.query.side_effect = lambda cmd: responses.get(cmd, "")

    def fake_query_binary(command: str, timeout_s: float = 30.0):
        if command == "C1:WF? DAT2":
            return SimpleNamespace(data=bytes([128, 130, 126, 128]), framing="raw")
        if command == "C1:WF? DESC":
            raise TimeoutError("no descriptor in unit test")
        raise AssertionError(f"unexpected binary command: {command}")

    transport.query_binary.side_effect = fake_query_binary
    return SDS800XHDTcpAdapter(transport)


def test_immediate_capture_skips_wfsu(tmp_path) -> None:
    scope = _mock_scope()

    result = get_waveform_with_mode(
        scope,
        "C1",
        csv_path=tmp_path / "wave.csv",
        metadata_path=tmp_path / "wave.json",
        capture_mode="immediate",
    )

    writes = [call.args[0] for call in scope.transport.write.call_args_list]
    assert "STOP" in writes
    assert not any(command.startswith("WFSU") for command in writes)
    assert result.metadata["capture"]["mode"] == "immediate"
    assert result.metadata["capture"]["wfsu_sent"] is False
    assert result.metadata["decode"]["dt_source"] == "fallback_sara_centered"
    assert any("skipped WFSU" in warning for warning in result.metadata["warnings"])


def test_configured_capture_sends_wfsu_and_warns(tmp_path) -> None:
    scope = _mock_scope()

    result = get_waveform_with_mode(
        scope,
        "C1",
        csv_path=tmp_path / "wave.csv",
        metadata_path=tmp_path / "wave.json",
        capture_mode="configured",
    )

    writes = [call.args[0] for call in scope.transport.write.call_args_list]
    assert "WFSU SP,1,NP,0,FP,0" in writes
    assert result.metadata["capture"]["mode"] == "configured"
    assert result.metadata["capture"]["wfsu_sent"] is True
    assert any("may replace" in warning for warning in result.metadata["warnings"])
