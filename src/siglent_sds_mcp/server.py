from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .auto_setup import auto_find_waveform
from .modbus_timing import calculate_modbus_rtu_timing
from .report import ReportInput, generate_markdown_report
from .rs485_analyzer import analyze_rs485_pair_csv
from .sds_tcp_adapter import SDS800XHDTcpAdapter
from .tcp_transport import RawTcpTransport
from .uart_analyzer import analyze_uart_csv

mcp = FastMCP("siglent-sds-mcp", json_response=True)

_tcp: RawTcpTransport | None = None
_tcp_host: str | None = None
_tcp_port: int = 5025
_tcp_timeout_s: float = 5.0


@mcp.tool()
def connect_tcp(
    host: str,
    port: int = 5025,
    timeout_s: float = 5.0,
    header_off: bool = True,
) -> dict[str, Any]:
    """Connect to the oscilloscope through raw TCP SCPI socket."""

    global _tcp, _tcp_host, _tcp_port, _tcp_timeout_s
    if _tcp is not None:
        _tcp.close()
    _tcp = RawTcpTransport(host=host, port=port, timeout_s=timeout_s)
    _tcp.connect()
    _tcp_host = host
    _tcp_port = port
    _tcp_timeout_s = timeout_s
    result: dict[str, Any] = {"ok": True, "transport": "tcp", "host": host, "port": port}
    if header_off:
        result["header_off"] = _tcp_adapter().try_header_off()
    return result


@mcp.tool()
def disconnect_tcp() -> dict[str, Any]:
    """Disconnect the current raw TCP oscilloscope session."""

    global _tcp, _tcp_host
    if _tcp is not None:
        _tcp.close()
        _tcp = None
    _tcp_host = None
    return {"ok": True}


@mcp.tool()
def identify_tcp() -> dict[str, Any]:
    """Query *IDN? through the connected raw TCP session."""

    return {"ok": True, "idn": _tcp_adapter().identify()}


@mcp.tool()
def safe_scpi_query_tcp(command: str) -> dict[str, Any]:
    """Send a read-only SCPI query ending in '?' through raw TCP."""

    command = command.strip()
    if not command.endswith("?"):
        raise ValueError("safe_scpi_query_tcp only accepts commands ending with '?'")
    transport = _require_tcp()
    return {"ok": True, "command": command, "response": transport.query(command)}


@mcp.tool()
def get_channel_tcp(channel: Literal["C1", "C2", "C3", "C4"] = "C1") -> dict[str, Any]:
    """Query a channel configuration through the TCP adapter."""

    return _tcp_adapter().get_channel(channel)


@mcp.tool()
def configure_channel_tcp(
    channel: Literal["C1", "C2", "C3", "C4"] = "C1",
    vdiv: str | None = None,
    offset: str | None = None,
    coupling: Literal["A1M", "A50", "D1M", "D50", "GND"] | None = None,
    bandwidth_limit: bool | None = None,
    trace: bool | None = None,
    probe: float | None = None,
) -> dict[str, Any]:
    """Configure a channel using SDS-style TCP SCPI candidate commands."""

    return _tcp_adapter().configure_channel(
        channel=channel,
        vdiv=vdiv,
        offset=offset,
        coupling=coupling,
        bandwidth_limit=bandwidth_limit,
        trace=trace,
        probe=probe,
    )


@mcp.tool()
def configure_acquisition_tcp(
    command: Literal["run", "stop", "single", "auto"] | None = None,
    timebase: str | None = None,
    trigger_mode: Literal["AUTO", "NORM", "SINGLE", "STOP"] | None = None,
    trigger_source: Literal["C1", "C2", "C3", "C4"] | None = None,
    trigger_level: str | None = None,
    trigger_slope: Literal["POS", "NEG", "WINDOW"] | None = None,
    trigger_delay: str | None = None,
) -> dict[str, Any]:
    """Configure acquisition/timebase/trigger using SDS-style candidate commands."""

    return _tcp_adapter().configure_acquisition(
        command=command,
        timebase=timebase,
        trigger_mode=trigger_mode,
        trigger_source=trigger_source,
        trigger_level=trigger_level,
        trigger_slope=trigger_slope,
        trigger_delay=trigger_delay,
    )


@mcp.tool()
def get_acquisition_status_tcp() -> dict[str, Any]:
    """Query acquisition state, timebase, sample rate and trigger status."""

    return _tcp_adapter().get_acquisition_status()


@mcp.tool()
def measure_tcp(
    channel: Literal["C1", "C2", "C3", "C4"] = "C1",
    parameter: Literal[
        "PKPK",
        "MAX",
        "MIN",
        "AMPL",
        "TOP",
        "BASE",
        "CMEAN",
        "MEAN",
        "RMS",
        "CRMS",
        "OVSN",
        "FPRE",
        "OVSP",
        "RPRE",
        "PER",
        "FREQ",
        "PWID",
        "NWID",
        "RISE",
        "FALL",
        "WID",
        "DUTY",
        "NDUTY",
        "ALL",
    ] = "PKPK",
) -> dict[str, Any]:
    """Take a measurement using SDS-style candidate commands."""

    return _tcp_adapter().measure(channel=channel, parameter=parameter)


def _run_auto_setup(
    channel_list: list[Literal["C1", "C2", "C3", "C4"]],
    signal_hint: Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"],
    coarse_timebase: str,
    initial_vdiv: str,
    max_points: int,
    noise_floor_v: float,
    min_signal_vpp: float,
    settle_s: float,
    probe: float,
    refine_attempts: int,
    leave_stopped: bool,
    set_trigger_level: bool,
) -> dict[str, object]:
    result = auto_find_waveform(
        _tcp_adapter(),
        channels=list(channel_list),
        signal_hint=signal_hint,
        coarse_timebase=coarse_timebase,
        initial_vdiv=initial_vdiv,
        max_points=max_points,
        noise_floor_v=noise_floor_v,
        min_signal_vpp=min_signal_vpp,
        settle_s=settle_s,
        probe=probe,
        refine_attempts=refine_attempts,
        leave_stopped=leave_stopped,
        set_trigger_level=set_trigger_level,
    )
    return result.to_dict()


@mcp.tool()
def auto_setup_tcp(
    channel: Literal["C1", "C2", "C3", "C4"] = "C1",
    signal_hint: Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"] = "unknown",
    settle_s: float = 0.6,
    noise_floor_v: float = 0.05,
    min_signal_vpp: float = 0.005,
    probe: float = 10.0,
    leave_stopped: bool = True,
    set_trigger_level: bool = False,
    noise_floor_v: float = 0.05,
    min_signal_vpp: float = 0.005,
) -> dict[str, object]:
    """Auto setup one channel and leave the waveform visible by default."""

    return _run_auto_setup(
        channel_list=[channel],
        signal_hint=signal_hint,
        coarse_timebase="1MS",
        initial_vdiv="1V",
        max_points=2000,
        noise_floor_v=noise_floor_v,
        min_signal_vpp=min_signal_vpp,
        settle_s=settle_s,
        probe=probe,
        refine_attempts=1,
        leave_stopped=leave_stopped,
        set_trigger_level=set_trigger_level,
    )


@mcp.tool()
def screenshot_tcp(
    output_path: str | None = None,
    include_base64: bool = False,
) -> dict[str, Any]:
    """Capture a screen image through candidate `SCDP` command."""

    return _tcp_adapter().screenshot(output_path=output_path, include_base64=include_base64)


@mcp.tool()
def get_waveform_tcp(
    channel: Literal["C1", "C2", "C3", "C4"] = "C1",
    csv_path: str | None = None,
    metadata_path: str | None = None,
    max_points: int = 5000,
) -> dict[str, Any]:
    """Download waveform data through candidate SDS waveform commands and save CSV."""

    result = _tcp_adapter().get_waveform(
        channel=channel,
        csv_path=csv_path,
        metadata_path=metadata_path,
        max_points=max_points,
    )
    return {
        "csv_path": result.csv_path,
        "metadata_path": result.metadata_path,
        "metadata": result.metadata,
    }


@mcp.tool()
def capture_uart_2mbps_tcp(
    channel: Literal["C1", "C2", "C3", "C4"] = "C1",
    logic_level: Literal["3.3V TTL", "5V TTL"] = "3.3V TTL",
    max_points: int = 5000,
) -> dict[str, Any]:
    """One-shot candidate workflow for 2 Mbps UART capture and CSV analysis."""

    return _tcp_adapter().capture_uart_2mbps(
        channel=channel,
        logic_level=logic_level,
        max_points=max_points,
    )


@mcp.tool()
def auto_find_waveform_tcp(
    channels: list[Literal["C1", "C2", "C3", "C4"]] | None = None,
    signal_hint: Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"] = "unknown",
    coarse_timebase: str = "1MS",
    initial_vdiv: str = "1V",
    max_points: int = 2000,
    noise_floor_v: float = 0.05,
    min_signal_vpp: float = 0.005,
    probe: float = 10.0,
    refine_attempts: int = 3,
    leave_stopped: bool = True,
    set_trigger_level: bool = False,
) -> dict[str, object]:
    """Backwards-compatible multi-channel auto setup entry point."""

    return _run_auto_setup(
        channel_list=list(channels) if channels else ["C1", "C2", "C3", "C4"],
        signal_hint=signal_hint,
        coarse_timebase=coarse_timebase,
        initial_vdiv=initial_vdiv,
        max_points=max_points,
        noise_floor_v=noise_floor_v,
        min_signal_vpp=min_signal_vpp,
        settle_s=0.6,
        probe=probe,
        refine_attempts=refine_attempts,
        leave_stopped=leave_stopped,
        set_trigger_level=set_trigger_level,
    )


@mcp.tool()
def analyze_uart_csv_file(csv_path: str, baudrate: int = 2_000_000) -> dict[str, Any]:
    """Analyze a two-column UART waveform CSV: time_s, voltage_v."""

    return analyze_uart_csv(Path(csv_path), baudrate=baudrate).to_dict()


@mcp.tool()
def analyze_rs485_pair_csv_file(
    csv_a_path: str,
    csv_b_path: str,
    baudrate: int = 2_000_000,
    threshold_v: float = 0.0,
) -> dict[str, Any]:
    """Analyze two CSV waveforms as RS485 A/B and compute Vdiff = VA - VB."""

    return analyze_rs485_pair_csv(
        Path(csv_a_path),
        Path(csv_b_path),
        baudrate=baudrate,
        threshold_v=threshold_v,
    ).to_dict()


@mcp.tool()
def modbus_rtu_timing(
    baudrate: int = 9600,
    data_bits: int = 8,
    parity: Literal["N", "E", "O"] = "N",
    stop_bits: int = 1,
) -> dict[str, object]:
    """Calculate Modbus RTU character time and silence intervals."""

    return calculate_modbus_rtu_timing(
        baudrate=baudrate,
        data_bits=data_bits,
        parity=parity,
        stop_bits=stop_bits,
    ).to_dict()


@mcp.tool()
def generate_report(
    title: str = "SIGLENT SDS field capture report",
    output_path: str = "artifacts/reports/report.md",
    scope_idn: str | None = None,
    scenario: str | None = None,
    screenshot_path: str | None = None,
    waveform_csv_paths: list[str] | None = None,
    waveform_metadata_paths: list[str] | None = None,
    uart_analysis_json_path: str | None = None,
    rs485_analysis_json_path: str | None = None,
    modbus_timing_json_path: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Generate a Markdown field report from captured artifacts and JSON summaries."""

    return generate_markdown_report(
        ReportInput(
            title=title,
            output_path=output_path,
            scope_idn=scope_idn,
            scenario=scenario,
            screenshot_path=screenshot_path,
            waveform_csv_paths=waveform_csv_paths or [],
            waveform_metadata_paths=waveform_metadata_paths or [],
            uart_analysis_json_path=uart_analysis_json_path,
            rs485_analysis_json_path=rs485_analysis_json_path,
            modbus_timing_json_path=modbus_timing_json_path,
            notes=notes,
        )
    )


@mcp.tool()
def project_status() -> dict[str, Any]:
    """Return implementation status and verification boundary."""

    return {
        "status": "hardware-tested-alpha",
        "target": "SIGLENT SDS824X HD / SDS800X HD",
        "firmware_verified": "4.8.12.1.1.6.5",
        "transport": "raw TCP SCPI socket, port 5025",
        "verified_on_hardware": [
            "TCP 5025 connection",
            "*IDN? identity query",
            "CHDR OFF header suppression",
            "SCDP screen capture returning BMP/raw image bytes",
            "WF? DAT2 waveform data read with WFSU SP,1,NP,0,FP,0",
            "WF? DESC WAVEDESC descriptor read and adaptive decode",
            "measurement-driven auto_setup can find and range active signals",
            "low-amplitude periodic signals accepted with valid FREQ/PER evidence",
        ],
        "known_issues": [
            "C?:TRLV may not take effect on firmware 4.8.12.1.1.6.5; "
            "auto setup does not depend on trigger level by default.",
            "get_waveform acquisition sequencing is hardware-sensitive; verify after changes.",
        ],
        "default_auto_setup_behavior": {
            "leave_stopped": True,
            "screen_hold": "scope remains stopped on final visible frame",
            "noise_floor_v": 0.05,
            "min_signal_vpp": 0.005,
            "set_trigger_level": False,
            "probe": 10.0,
        },
        "tcp_tools": [
            "connect_tcp",
            "disconnect_tcp",
            "identify_tcp",
            "safe_scpi_query_tcp",
            "get_channel_tcp",
            "configure_channel_tcp",
            "configure_acquisition_tcp",
            "get_acquisition_status_tcp",
            "measure_tcp",
            "auto_setup_tcp",
            "screenshot_tcp",
            "get_waveform_tcp",
            "capture_uart_2mbps_tcp",
            "auto_find_waveform_tcp",
            "analyze_uart_csv_file",
            "analyze_rs485_pair_csv_file",
            "modbus_rtu_timing",
            "generate_report",
        ],
        "status_note": "Hardware-tested alpha; auto setup accepts weak periodic signals.",
    }


def _require_tcp() -> RawTcpTransport:
    """返回已连接的 RawTcpTransport，必要时自动重连。"""
    global _tcp
    if _tcp_host is None:
        raise RuntimeError("not connected; call connect_tcp first")
    if _tcp is None or not _tcp.is_connected():
        try:
            transport = RawTcpTransport(host=_tcp_host, port=_tcp_port, timeout_s=_tcp_timeout_s)
            transport.connect()
            _tcp = transport
            try:
                _tcp.write("CHDR OFF")
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:
            raise RuntimeError(
                f"auto-reconnect to {_tcp_host}:{_tcp_port} failed: {exc!r}"
            ) from exc
    return _tcp


def _tcp_adapter() -> SDS800XHDTcpAdapter:
    return SDS800XHDTcpAdapter(_require_tcp())


def main() -> None:
    """Run the MCP server over stdio by default."""

    mcp.run()


if __name__ == "__main__":
    main()
