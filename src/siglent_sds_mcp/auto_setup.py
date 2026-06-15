from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .artifacts import default_artifact_paths, ensure_parent, write_json
from .sds_tcp_adapter import Channel, SDS800XHDTcpAdapter
from .waveform_stats import WaveformStats, analyze_waveform_csv

SignalHint = Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"]

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
    final_waveform_csv: str | None = None
    final_metadata_path: str | None = None
    screenshot_path: str | None = None
    report_json_path: str | None = None
    notes: list[str] = field(default_factory=list)

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
            "final_waveform_csv": self.final_waveform_csv,
            "final_metadata_path": self.final_metadata_path,
            "screenshot_path": self.screenshot_path,
            "report_json_path": self.report_json_path,
            "notes": self.notes,
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
) -> AutoSetupResult:
    """Find and auto-range an unknown waveform using existing SDS TCP adapter tools.

    The first version is intentionally conservative:
    - scan enabled candidate channels with broad settings;
    - choose the most active channel by Vpp and edge count;
    - adjust vertical scale, offset, timebase and edge trigger;
    - save a screen image and final waveform artifacts.
    """

    candidate_channels: list[Channel] = channels or ["C1", "C2", "C3", "C4"]
    probes: list[ChannelProbe] = []
    notes: list[str] = []

    scope.configure_acquisition(trigger_mode="AUTO", timebase=coarse_timebase, command="auto")

    for channel in candidate_channels:
        try:
            scope.configure_channel(
                channel=channel,
                vdiv=initial_vdiv,
                offset="0V",
                coupling="D1M",
                trace=True,
                probe=10,
            )
            time.sleep(settle_s)
            wf = scope.get_waveform(channel=channel, max_points=max_points)
            stats = analyze_waveform_csv(wf.csv_path, noise_floor_v=noise_floor_v)
            score = _score_waveform(stats)
            probes.append(
                ChannelProbe(
                    channel=channel,
                    waveform_csv=wf.csv_path,
                    metadata_path=wf.metadata_path,
                    stats=stats.to_dict(),
                    score=score,
                )
            )
        except Exception as exc:  # noqa: BLE001 - auto probing should continue on other channels
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

    valid = [probe for probe in probes if probe.stats is not None and probe.score >= 0.0]
    if not valid:
        result = AutoSetupResult(
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
        )
        return _write_auto_result(result)

    best = max(valid, key=lambda item: item.score)
    best_stats = best.stats or {}
    vpp = _float_or_none(best_stats.get("v_pp"))
    vmean = _float_or_none(best_stats.get("v_mean"))
    threshold = _float_or_none(best_stats.get("threshold_v"))
    edge_count = int(best_stats.get("edge_count") or 0)
    edge_interval = _float_or_none(best_stats.get("median_edge_interval_s"))

    if not vpp or vpp < noise_floor_v:
        result = AutoSetupResult(
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
        )
        return _write_auto_result(result)

    recommended_vdiv = choose_vdiv(vpp)
    recommended_offset = _format_volts(vmean or 0.0)
    recommended_timebase = choose_timebase(edge_interval, signal_hint=signal_hint)
    trigger_level = _format_volts(threshold if threshold is not None else (vmean or 0.0))
    confidence = _confidence(vpp=vpp, edge_count=edge_count, noise_floor_v=noise_floor_v)

    notes.append(f"Selected {best.channel}: Vpp={vpp:.6g} V, edges={edge_count}.")
    notes.append(f"Vertical setup: VDIV={recommended_vdiv}, OFST={recommended_offset}.")
    if recommended_timebase:
        notes.append(f"Timebase setup: TDIV={recommended_timebase}.")
    notes.append(f"Trigger level set near waveform midpoint: {trigger_level}.")

    scope.configure_channel(
        channel=best.channel,
        vdiv=recommended_vdiv,
        offset=recommended_offset,
        coupling="D1M",
        trace=True,
        probe=10,
    )
    scope.configure_acquisition(
        timebase=recommended_timebase,
        trigger_mode="AUTO",
        trigger_source=best.channel,
        trigger_level=trigger_level,
        trigger_slope="NEG" if signal_hint in {"uart", "rs485", "modbus"} else "POS",
        command="auto",
    )
    time.sleep(settle_s)

    final_wf = scope.get_waveform(channel=best.channel, max_points=max_points)
    shot = scope.screenshot(default_artifact_paths("auto_find_waveform")["screenshot_raw"])

    result = AutoSetupResult(
        found=True,
        selected_channel=best.channel,
        signal_hint=signal_hint,
        confidence=confidence,
        recommended_vdiv=recommended_vdiv,
        recommended_offset=recommended_offset,
        recommended_timebase=recommended_timebase,
        trigger_level=trigger_level,
        probes=probes,
        final_waveform_csv=final_wf.csv_path,
        final_metadata_path=final_wf.metadata_path,
        screenshot_path=str(shot.get("path")) if shot.get("path") else None,
        notes=notes,
    )
    return _write_auto_result(result)


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


def _write_auto_result(result: AutoSetupResult) -> AutoSetupResult:
    path = ensure_parent(default_artifact_paths("auto_find_waveform")["analysis_json"])
    write_json(path, result.to_dict())
    result.report_json_path = str(path)
    return result
