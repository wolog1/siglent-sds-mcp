from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Literal

from .artifacts import default_artifact_paths, ensure_parent, write_json
from .sds_tcp_adapter import (
    CODES_PER_DIV,
    Channel,
    SDS800XHDTcpAdapter,
    WaveDescriptor,
    WaveformResult,
    _channel,
    _parse_sample_rate,
    _parse_time,
    _parse_voltage,
    _parse_wavedesc,
    _siglent_byte_to_voltage,
)

WaveformCaptureMode = Literal["immediate", "configured"]


def get_waveform_with_mode(
    scope: SDS800XHDTcpAdapter,
    channel: Channel,
    csv_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
    max_points: int = 5000,
    *,
    capture_mode: WaveformCaptureMode = "immediate",
    restore_trmd: bool = True,
) -> WaveformResult:
    """Capture waveform data with explicit WFSU policy.

    SDS824X HD field validation showed that issuing WFSU after STOP can cause the
    instrument to refresh/replace the stopped frame before `WF? DAT2`. For
    intermittent signals such as UART bursts, `capture_mode="immediate"` skips
    WFSU and reads DAT2 directly from the current stopped frame.

    Use `capture_mode="configured"` only for stable/repetitive signals where the
    caller explicitly wants the WFSU-selected waveform memory settings.
    """

    if capture_mode not in {"immediate", "configured"}:
        raise ValueError("capture_mode must be 'immediate' or 'configured'")

    ch = _channel(channel)
    paths = default_artifact_paths(f"waveform_{ch.lower()}")
    csv_out = ensure_parent(csv_path or paths["waveform_csv"])
    metadata_out = ensure_parent(metadata_path or paths["metadata_json"])

    vdiv_raw = scope.transport.query(f"{ch}:VDIV?")
    ofst_raw = scope.transport.query(f"{ch}:OFST?")
    attn_raw = scope.transport.query(f"{ch}:ATTN?")
    tdiv_raw = scope.transport.query("TDIV?")
    sara_raw = scope.transport.query("SARA?")
    trdl_raw = _query_or_none(scope, "TRDL?")

    vdiv = _parse_voltage(vdiv_raw)
    offset = _parse_voltage(ofst_raw)
    tdiv = _parse_time(tdiv_raw)
    sample_rate = _parse_sample_rate(sara_raw)
    trdl_s = _parse_time(trdl_raw) if trdl_raw else None

    prev_trmd = scope.transport.query("TRMD?")
    scope.transport.write("STOP")
    stopped = _wait_stopped(scope)

    commands_sent: list[str] = ["STOP"]
    wfsu_command: str | None = None
    warnings: list[str] = []
    if capture_mode == "configured":
        wfsu_command = "WFSU SP,1,NP,0,FP,0"
        scope.transport.write(wfsu_command)
        commands_sent.append(wfsu_command)
        warnings.append(
            "configured mode sent WFSU after STOP; on SDS824X HD this may replace "
            "the stopped frame for intermittent signals"
        )
    else:
        warnings.append(
            "immediate mode skipped WFSU to preserve the current stopped frame before WF? DAT2"
        )

    block = scope.transport.query_binary(f"{ch}:WF? DAT2", timeout_s=30.0)
    commands_sent.append(f"{ch}:WF? DAT2")

    wavedesc: WaveDescriptor | None = None
    desc_error: str | None = None
    try:
        desc_block = scope.transport.query_binary(f"{ch}:WF? DESC", timeout_s=10.0)
        wavedesc = _parse_wavedesc(desc_block.data)
        commands_sent.append(f"{ch}:WF? DESC")
        if wavedesc is None:
            desc_error = "parse_failed: WAVEDESC signature not found or sanity check failed"
    except Exception as exc:  # noqa: BLE001
        desc_error = f"query_failed: {exc!r}"
        warnings.append(f"WAVEDESC unavailable; timebase fallback may be less accurate: {desc_error}")

    raw = block.data
    total_points = len(raw)
    codes_per_div = (
        wavedesc.codes_per_div
        if wavedesc is not None and wavedesc.codes_per_div > 0
        else CODES_PER_DIV
    )
    gain_v_per_code = vdiv / codes_per_div
    offset_v = offset
    voltages = [_siglent_byte_to_voltage(byte, gain_v_per_code, offset_v) for byte in raw]

    if wavedesc is not None and wavedesc.horiz_interval > 0.0:
        time_interval = wavedesc.horiz_interval
        start_time = -wavedesc.horiz_offset
        time_source = "wavedesc"
    elif sample_rate > 0:
        time_interval = 1.0 / sample_rate
        start_time = -(total_points / 2.0) * time_interval
        time_source = "fallback_sara_centered"
        warnings.append(
            "time interval fell back to SARA; UART/protocol decode may be wrong if "
            "SARA does not match DAT2 memory interval"
        )
    else:
        time_interval = 0.0
        start_time = -(tdiv * 14) / 2 if tdiv > 0 else 0.0
        time_source = "fallback_tdiv"
        warnings.append("time interval fell back to TDIV estimate; protocol decode is low confidence")

    returned_points = _write_waveform_csv(
        csv_out,
        voltages=voltages,
        start_time=start_time,
        time_interval=time_interval,
        max_points=max_points,
    )

    if restore_trmd:
        try:
            scope.transport.write(f"TRMD {prev_trmd}")
            commands_sent.append(f"TRMD {prev_trmd}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"failed to restore TRMD {prev_trmd!r}: {exc!r}")

    wavedesc_info: dict[str, Any] = (
        {
            "vertical_gain_vdiv": wavedesc.vertical_gain_vdiv,
            "max_value": wavedesc.max_value,
            "codes_per_div": wavedesc.codes_per_div,
            "gain_v_per_code": wavedesc.gain_v_per_code,
            "vertical_offset": wavedesc.vertical_offset,
            "horiz_interval": wavedesc.horiz_interval,
            "horiz_offset": wavedesc.horiz_offset,
            "wave_array_count": wavedesc.wave_array_count,
            "raw_bytes": wavedesc.raw_bytes,
            "source": wavedesc.source,
        }
        if wavedesc is not None
        else {"source": "unavailable", "error": desc_error}
    )

    metadata: dict[str, Any] = {
        "channel": ch,
        "capture": {
            "mode": capture_mode,
            "wfsu_sent": wfsu_command is not None,
            "wfsu_command": wfsu_command,
            "stopped_before_read": stopped,
            "restore_trmd": restore_trmd,
            "commands_sent": commands_sent,
        },
        "raw_responses": {
            "vdiv": vdiv_raw,
            "offset": ofst_raw,
            "probe_attenuation": attn_raw,
            "timebase": tdiv_raw,
            "sample_rate": sara_raw,
            "trigger_delay": trdl_raw,
        },
        "parsed": {
            "vdiv_v": vdiv,
            "offset_v": offset,
            "timebase_s_per_div": tdiv,
            "sample_rate_sps": sample_rate,
            "time_interval_s": time_interval,
            "time_source": time_source,
            "start_time_s": start_time,
            "trdl_s": trdl_s,
            "effective_start_s": start_time,
            "effective_end_s": start_time + max(0, total_points - 1) * time_interval,
        },
        "wavedesc": wavedesc_info,
        "decode": {
            "source": "wavedesc_cpd__panel_vdiv_ofst" if wavedesc else "fallback_codes_per_div",
            "vertical_gain_v_per_code": gain_v_per_code,
            "vertical_offset_v": offset_v,
            "time_source": time_source,
            "dt_source": time_source,
            "codes_per_div_fallback": CODES_PER_DIV,
        },
        "binary": {"bytes": len(raw), "framing": block.framing},
        "points": {
            "total": total_points,
            "returned": returned_points,
            "decimation": "minmax_envelope",
        },
        "warnings": warnings,
        "status": "candidate_implementation_requires_sds824xhd_validation",
    }
    write_json(metadata_out, metadata)
    return WaveformResult(csv_path=str(csv_out), metadata_path=str(metadata_out), metadata=metadata)


def _wait_stopped(scope: SDS800XHDTcpAdapter, timeout_s: float = 3.0) -> bool:
    waited = 0.0
    while waited < timeout_s:
        try:
            sast = scope.transport.query("SAST?").strip()
            if sast in {"Stop", "Trig'd"}:
                return True
        except Exception:  # noqa: BLE001
            pass
        import time

        time.sleep(0.05)
        waited += 0.05
    return False


def _query_or_none(scope: SDS800XHDTcpAdapter, command: str) -> str | None:
    try:
        return scope.transport.query(command)
    except Exception:  # noqa: BLE001
        return None


def _write_waveform_csv(
    csv_out: Path,
    *,
    voltages: list[float],
    start_time: float,
    time_interval: float,
    max_points: int,
) -> int:
    total_points = len(voltages)
    returned_points = 0
    with csv_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "voltage_v"])
        if max_points <= 0 or total_points <= max_points:
            for i, voltage in enumerate(voltages):
                writer.writerow([start_time + i * time_interval, voltage])
                returned_points += 1
        else:
            bucket = max(1, (2 * total_points + max_points - 1) // max_points)
            for base in range(0, total_points, bucket):
                end = min(base + bucket, total_points)
                i_min = base
                i_max = base
                for i in range(base, end):
                    if voltages[i] < voltages[i_min]:
                        i_min = i
                    if voltages[i] > voltages[i_max]:
                        i_max = i
                lo, hi = (i_min, i_max) if i_min <= i_max else (i_max, i_min)
                writer.writerow([start_time + lo * time_interval, voltages[lo]])
                returned_points += 1
                if hi != lo:
                    writer.writerow([start_time + hi * time_interval, voltages[hi]])
                    returned_points += 1
    return returned_points
