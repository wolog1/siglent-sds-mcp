from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from .artifacts import default_artifact_paths, ensure_parent, write_json
from .sds_tcp_adapter import Channel, SDS800XHDTcpAdapter
from .waveform_stats import WaveformStats, analyze_waveform_csv

SignalHint = Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"]
OFFSET_STATUS = "verified_on_sds824xhd: display_offset_uses_waveform_mean"

_VDIV_STEPS: list[tuple[float, str]] = [
    (0.001, "1mV"),
    (0.002, "2mV"),
    (0.005, "5mV"),
    (0.010, "10mV"),
    (0.020, "20mV"),
    (0.050, "50mV"),
    (0.100, "100mV"),
    (0.200, "200mV"),
    (0.500, "500mV"),
    (1.0, "1V"),
    (2.0, "2V"),
    (5.0, "5V"),
    (10.0, "10V"),
]

_TDIV_STEPS: list[tuple[float, str]] = [
    (1e-9, "1NS"),
    (2e-9, "2NS"),
    (5e-9, "5NS"),
    (10e-9, "10NS"),
    (20e-9, "20NS"),
    (50e-9, "50NS"),
    (100e-9, "100NS"),
    (200e-9, "200NS"),
    (500e-9, "500NS"),
    (1e-6, "1US"),
    (2e-6, "2US"),
    (5e-6, "5US"),
    (10e-6, "10US"),
    (20e-6, "20US"),
    (50e-6, "50US"),
    (100e-6, "100US"),
    (200e-6, "200US"),
    (500e-6, "500US"),
    (1e-3, "1MS"),
    (2e-3, "2MS"),
    (5e-3, "5MS"),
    (10e-3, "10MS"),
    (20e-3, "20MS"),
    (50e-3, "50MS"),
    (100e-3, "100MS"),
    (200e-3, "200MS"),
    (500e-3, "500MS"),
    (1.0, "1S"),
]


@dataclass(slots=True)
class ChannelProbe:
    channel: Channel
    waveform_csv: str | None
    metadata_path: str | None
    stats: dict[str, object] | None
    score: float
    error: str | None = None


@dataclass(slots=True)
class AutoSetupResult:
    found: bool
    selected_channel: Channel | None
    signal_hint: SignalHint
    confidence: str
    recommended_vdiv: str | None
    recommended_offset: str | None
    recommended_timebase: str | None
    trigger_level: str | None
    probes: list[ChannelProbe] = field(default_factory=list)
    coarse_stats: dict[str, object] | None = None
    final_stats: dict[str, object] | None = None
    final_panel_state: dict[str, object] | None = None
    refine_history: list[dict[str, object]] = field(default_factory=list)
    final_waveform_csv: str | None = None
    final_metadata_path: str | None = None
    screenshot_path: str | None = None
    report_json_path: str | None = None
    notes: list[str] = field(default_factory=list)
    offset_direction_status: str = OFFSET_STATUS
    leave_stopped: bool = True
    screen_hold: bool = True
    trigger_level_command_sent: bool = False
    probe: float = 10.0

    def to_dict(self) -> dict[str, object]:
        return {
            "found": self.found,
            "selected_channel": self.selected_channel,
            "signal_hint": self.signal_hint,
            "confidence": self.confidence,
            "recommended_vdiv": self.recommended_vdiv,
            "recommended_offset": self.recommended_offset,
            "recommended_timebase": self.recommended_timebase,
            "trigger_level": self.trigger_level,
            "probes": [asdict(probe) for probe in self.probes],
            "coarse_stats": self.coarse_stats,
            "final_stats": self.final_stats,
            "final_panel_state": self.final_panel_state,
            "refine_history": self.refine_history,
            "final_waveform_csv": self.final_waveform_csv,
            "final_metadata_path": self.final_metadata_path,
            "screenshot_path": self.screenshot_path,
            "report_json_path": self.report_json_path,
            "notes": self.notes,
            "offset_direction_status": self.offset_direction_status,
            "leave_stopped": self.leave_stopped,
            "screen_hold": self.screen_hold,
            "trigger_level_command_sent": self.trigger_level_command_sent,
            "probe": self.probe,
        }


def auto_find_waveform(
    scope: SDS800XHDTcpAdapter,
    channels: list[Channel] | None = None,
    signal_hint: SignalHint = "unknown",
    coarse_timebase: str = "1MS",
    initial_vdiv: str = "1V",
    max_points: int = 2000,
    noise_floor_v: float = 0.05,
    settle_s: float = 0.15,
    probe: float = 10.0,
    refine_attempts: int = 3,
    leave_stopped: bool = True,
    set_trigger_level: bool = False,
) -> AutoSetupResult:
    """Find, auto-range and leave an unknown waveform visible on screen."""

    candidate_channels: list[Channel] = channels or ["C1", "C2", "C3", "C4"]
    probes: list[ChannelProbe] = []
    notes: list[str] = []
    trigger_level_command_sent = False

    scope.configure_acquisition(trigger_mode="AUTO", timebase=coarse_timebase, command="auto")

    for channel in candidate_channels:
        try:
            scope.configure_channel(
                channel=channel,
                vdiv=initial_vdiv,
                offset="0V",
                coupling="D1M",
                trace=True,
                probe=probe,
            )
            time.sleep(settle_s)
            wf = scope.get_waveform(channel=channel, max_points=max_points)
            stats = analyze_waveform_csv(wf.csv_path, noise_floor_v=noise_floor_v)
            probes.append(
                ChannelProbe(
                    channel=channel,
                    waveform_csv=wf.csv_path,
                    metadata_path=wf.metadata_path,
                    stats=stats.to_dict(),
                    score=_score_waveform(stats),
                )
            )
        except Exception as exc:  # noqa: BLE001
            probes.append(
                ChannelProbe(
                    channel=channel,
                    waveform_csv=None,
                    metadata_path=None,
                    stats=None,
                    score=-1.0,
                    error=repr(exc),
                )
            )

    valid = [item for item in probes if item.stats is not None and item.score >= 0.0]
    if not valid:
        return _write_auto_result(
            AutoSetupResult(
                found=False,
                selected_channel=None,
                signal_hint=signal_hint,
                confidence="none",
                recommended_vdiv=None,
                recommended_offset=None,
                recommended_timebase=None,
                trigger_level=None,
                probes=probes,
                notes=["No channel could be probed successfully."],
                leave_stopped=leave_stopped,
                screen_hold=False,
                probe=probe,
            )
        )

    best = max(valid, key=lambda item: item.score)
    best_stats = best.stats or {}
    vpp = _float_or_none(best_stats.get("v_pp"))
    vmean = _float_or_none(best_stats.get("v_mean"))
    threshold = _float_or_none(best_stats.get("threshold_v"))
    edge_count = int(best_stats.get("edge_count") or 0)
    edge_interval = _float_or_none(best_stats.get("median_edge_interval_s"))

    if not vpp or vpp < noise_floor_v:
        return _write_auto_result(
            AutoSetupResult(
                found=False,
                selected_channel=best.channel,
                signal_hint=signal_hint,
                confidence="low",
                recommended_vdiv=None,
                recommended_offset=None,
                recommended_timebase=None,
                trigger_level=None,
                probes=probes,
                notes=["No obvious active waveform found above noise floor."],
                leave_stopped=leave_stopped,
                screen_hold=False,
                probe=probe,
            )
        )

    current_vdiv = choose_vdiv(vpp)
    current_offset = _format_volts(vmean or 0.0)
    current_timebase = choose_timebase(edge_interval, signal_hint=signal_hint)
    trigger_level = _format_volts(threshold if threshold is not None else (vmean or 0.0))
    confidence = _confidence(vpp=vpp, edge_count=edge_count, noise_floor_v=noise_floor_v)
    coarse_stats = best.stats
    refine_history: list[dict[str, object]] = []

    notes.append(f"Selected {best.channel}: Vpp={vpp:.6g} V, edges={edge_count}.")
    notes.append(f"Initial vertical setup: VDIV={current_vdiv}, OFST={current_offset}.")
    notes.append(f"Initial timebase setup: TDIV={current_timebase}.")
    notes.append(
        "Trigger level is calculated but not sent by default because C?:TRLV is a "
        "known issue on SDS824X HD firmware 4.8.12.1.1.6."
    )

    final_wf = None
    final_stats: dict[str, object] | None = None
    final_vdiv = current_vdiv
    final_offset = current_offset
    final_timebase = current_timebase

    for attempt in range(1, max(1, refine_attempts) + 1):
        scope.configure_channel(
            channel=best.channel,
            vdiv=current_vdiv,
            offset=current_offset,
            coupling="D1M",
            trace=True,
            probe=probe,
        )
        scope.configure_acquisition(
            timebase=current_timebase,
            trigger_mode="AUTO",
            trigger_source=best.channel,
            trigger_level=trigger_level if set_trigger_level else None,
            trigger_slope="NEG" if signal_hint in {"uart", "rs485", "modbus"} else "POS",
            command="auto",
        )
        trigger_level_command_sent = trigger_level_command_sent or set_trigger_level
        time.sleep(settle_s)

        final_wf = scope.get_waveform(
            channel=best.channel,
            max_points=max_points,
            restore_trmd=False,
        )
        final_stats_raw = analyze_waveform_csv(final_wf.csv_path, noise_floor_v=noise_floor_v)
        final_stats = final_stats_raw.to_dict()

        final_vpp = _float_or_none(final_stats.get("v_pp"))
        final_mean = _float_or_none(final_stats.get("v_mean"))
        final_edge_interval = _float_or_none(final_stats.get("median_edge_interval_s"))
        current_vdiv_value = _vdiv_label_to_value(current_vdiv)
        vertical_divisions = _vertical_divisions(final_vpp, current_vdiv_value)
        visible_hint = _visible_hint(final_vpp, vertical_divisions, noise_floor_v)

        refine_history.append(
            {
                "attempt": attempt,
                "vdiv": current_vdiv,
                "offset": current_offset,
                "timebase": current_timebase,
                "vpp": final_vpp,
                "vertical_divisions": vertical_divisions,
                "edge_count": final_stats.get("edge_count"),
                "visible_hint": visible_hint,
            }
        )

        final_vdiv = current_vdiv
        final_offset = current_offset
        final_timebase = current_timebase
        if visible_hint:
            notes.append(
                f"Refine attempt {attempt}: waveform visible, Vpp={final_vpp:.6g} V, "
                f"vertical_divisions={vertical_divisions:.3g}."
            )
            break

        if final_vpp and final_vpp >= noise_floor_v:
            current_vdiv = choose_vdiv(final_vpp)
        if final_mean is not None:
            current_offset = _format_volts(final_mean)
        current_timebase = choose_timebase(final_edge_interval, signal_hint=signal_hint)
        notes.append(
            f"Refine attempt {attempt}: adjusted to VDIV={current_vdiv}, "
            f"OFST={current_offset}, TDIV={current_timebase}."
        )

    if final_wf is None or final_stats is None:
        return _write_auto_result(
            AutoSetupResult(
                found=False,
                selected_channel=best.channel,
                signal_hint=signal_hint,
                confidence="low",
                recommended_vdiv=final_vdiv,
                recommended_offset=final_offset,
                recommended_timebase=final_timebase,
                trigger_level=trigger_level,
                probes=probes,
                coarse_stats=coarse_stats,
                refine_history=refine_history,
                notes=notes + ["Final waveform capture did not complete."],
                leave_stopped=leave_stopped,
                screen_hold=False,
                trigger_level_command_sent=trigger_level_command_sent,
                probe=probe,
            )
        )

    shot = scope.screenshot(default_artifact_paths("auto_find_waveform")["screenshot_raw"])
    final_panel_state = _collect_final_panel_state(scope, best.channel)
    final_vpp = _float_or_none(final_stats.get("v_pp"))
    screen_hold = leave_stopped

    if final_vpp and final_vpp >= noise_floor_v:
        notes.append(
            f"Final waveform: Vpp={final_vpp:.6g} V, edges={final_stats.get('edge_count')}, "
            "captured on stopped frame."
        )
    else:
        notes.append("Warning: final waveform still near noise floor after auto-setup.")

    if leave_stopped:
        notes.append("Screen hold enabled: leaving scope stopped on the final visible frame.")
    else:
        try:
            scope.transport.write("ARM")
            screen_hold = False
            notes.append("Restarted acquisition after capture because leave_stopped=False.")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Warning: failed to restart acquisition after capture: {exc!r}")

    return _write_auto_result(
        AutoSetupResult(
            found=True,
            selected_channel=best.channel,
            signal_hint=signal_hint,
            confidence=confidence,
            recommended_vdiv=final_vdiv,
            recommended_offset=final_offset,
            recommended_timebase=final_timebase,
            trigger_level=trigger_level,
            probes=probes,
            coarse_stats=coarse_stats,
            final_stats=final_stats,
            final_panel_state=final_panel_state,
            refine_history=refine_history,
            final_waveform_csv=final_wf.csv_path,
            final_metadata_path=final_wf.metadata_path,
            screenshot_path=str(shot.get("path")) if shot.get("path") else None,
            notes=notes,
            offset_direction_status=OFFSET_STATUS,
            leave_stopped=leave_stopped,
            screen_hold=screen_hold,
            trigger_level_command_sent=trigger_level_command_sent,
            probe=probe,
        )
    )


def choose_vdiv(vpp: float, target_divisions: float = 5.0) -> str:
    if vpp <= 0:
        return "1V"
    desired = vpp / target_divisions
    for value, label in _VDIV_STEPS:
        if value >= desired:
            return label
    return _VDIV_STEPS[-1][1]


def choose_timebase(edge_interval_s: float | None, signal_hint: SignalHint = "unknown") -> str:
    if edge_interval_s is None or edge_interval_s <= 0:
        if signal_hint in {"uart", "rs485", "modbus"}:
            return "100US"
        return "1MS"

    if signal_hint in {"uart", "rs485", "modbus"}:
        desired_span = edge_interval_s * 30.0
    elif signal_hint in {"clock", "pwm"}:
        desired_span = edge_interval_s * 20.0
    else:
        desired_span = edge_interval_s * 25.0

    desired_tdiv = desired_span / 14.0
    for value, label in _TDIV_STEPS:
        if value >= desired_tdiv:
            return label
    return _TDIV_STEPS[-1][1]


def _score_waveform(stats: WaveformStats) -> float:
    if not stats.v_pp:
        return 0.0
    edge_bonus = min(stats.edge_count, 100) * 0.01
    active_bonus = 1.0 if stats.active_hint else 0.0
    clipping_penalty = 0.25 if stats.clipping_hint else 0.0
    return stats.v_pp + edge_bonus + active_bonus - clipping_penalty


def _confidence(vpp: float, edge_count: int, noise_floor_v: float) -> str:
    if vpp >= noise_floor_v * 10 and edge_count >= 4:
        return "high"
    if vpp >= noise_floor_v * 5 or edge_count >= 2:
        return "medium"
    return "low"


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_volts(value: float) -> str:
    if abs(value) < 1e-9:
        return "0V"
    return f"{value:.6g}V"


def _vdiv_label_to_value(label: str) -> float | None:
    for value, item_label in _VDIV_STEPS:
        if item_label == label:
            return value
    return None


def _vertical_divisions(vpp: float | None, vdiv: float | None) -> float | None:
    if not vpp or not vdiv:
        return None
    return vpp / vdiv


def _visible_hint(
    vpp: float | None,
    vertical_divisions: float | None,
    noise_floor_v: float,
) -> bool:
    return bool(
        vpp
        and vpp >= noise_floor_v
        and vertical_divisions
        and 1.0 <= vertical_divisions <= 7.5
    )


def _collect_final_panel_state(scope: SDS800XHDTcpAdapter, channel: Channel) -> dict[str, object]:
    panel: dict[str, object] = {"channel": channel}
    try:
        panel["channel_state"] = _jsonable_dict(scope.get_channel(channel))
    except Exception as exc:  # noqa: BLE001
        panel["channel_state_error"] = repr(exc)
    try:
        panel["acquisition_state"] = _jsonable_dict(scope.get_acquisition_status())
    except Exception as exc:  # noqa: BLE001
        panel["acquisition_state_error"] = repr(exc)
    return panel


def _jsonable_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"value": repr(value)}
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[str(key)] = item
        elif isinstance(item, list):
            result[str(key)] = [
                x if isinstance(x, (str, int, float, bool)) or x is None else repr(x)
                for x in item
            ]
        elif isinstance(item, dict):
            result[str(key)] = _jsonable_dict(item)
        else:
            result[str(key)] = repr(item)
    return result


def _write_auto_result(result: AutoSetupResult) -> AutoSetupResult:
    path = ensure_parent(default_artifact_paths("auto_find_waveform")["analysis_json"])
    result.report_json_path = str(path)
    write_json(path, result.to_dict())
    return result
