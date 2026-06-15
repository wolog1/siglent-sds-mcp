from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from .sds_tcp_adapter import (
    Channel,
    MeasureParameter,
    SDS800XHDTcpAdapter,
    _fmt_sci,
    _parse_meas_value,
    _pick_tdiv,
    _pick_vdiv,
)

SignalHint = Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"]


@dataclass(slots=True)
class AutoSetupResult:
    """Compatibility result object for the historical auto_find_waveform API."""

    found: bool
    selected_channel: Channel | None
    signal_hint: SignalHint
    confidence: str
    screen_hold: bool
    leave_stopped: bool
    trigger_level_command_sent: bool
    probe: float
    result: dict[str, object]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "found": self.found,
            "selected_channel": self.selected_channel,
            "signal_hint": self.signal_hint,
            "confidence": self.confidence,
            "screen_hold": self.screen_hold,
            "leave_stopped": self.leave_stopped,
            "trigger_level_command_sent": self.trigger_level_command_sent,
            "probe": self.probe,
            "result": self.result,
            "notes": self.notes,
        }


def auto_find_waveform(
    scope: SDS800XHDTcpAdapter,
    channels: list[Channel] | None = None,
    signal_hint: SignalHint = "unknown",
    coarse_timebase: str = "1MS",
    initial_vdiv: str = "1V",
    max_points: int = 2000,  # accepted for API compatibility
    noise_floor_v: float = 0.05,
    settle_s: float = 0.6,
    probe: float = 10.0,
    refine_attempts: int = 3,  # accepted for API compatibility
    leave_stopped: bool = True,
    set_trigger_level: bool = False,
) -> AutoSetupResult:
    """Find, range, and optionally hold an active waveform on screen.

    This compatibility implementation no longer depends on the removed
    `waveform_stats.py`. It uses the SDS measurement engine first, which is the
    current hardware-tested direction for SDS824X HD auto setup.
    """

    candidate_channels: list[Channel] = channels or ["C1", "C2", "C3", "C4"]
    attempts: list[dict[str, object]] = []

    for channel in candidate_channels:
        result = _auto_setup_one_channel(
            scope=scope,
            channel=channel,
            signal_hint=signal_hint,
            coarse_timebase=coarse_timebase,
            initial_vdiv=initial_vdiv,
            noise_floor_v=noise_floor_v,
            settle_s=settle_s,
            probe=probe,
            leave_stopped=leave_stopped,
            set_trigger_level=set_trigger_level,
        )
        attempts.append(result)
        if bool(result.get("signal_detected")):
            result["scan_attempts"] = attempts
            return AutoSetupResult(
                found=True,
                selected_channel=channel,
                signal_hint=signal_hint,
                confidence=str(result.get("confidence", "medium")),
                screen_hold=leave_stopped,
                leave_stopped=leave_stopped,
                trigger_level_command_sent=set_trigger_level,
                probe=probe,
                result=result,
                notes=[
                    "auto_find_waveform compatibility wrapper used measurement-driven auto setup.",
                    "max_points and refine_attempts are accepted for backwards compatibility; "
                    "the current path relies on scope measurements and final screen hold.",
                ],
            )

    return AutoSetupResult(
        found=False,
        selected_channel=None,
        signal_hint=signal_hint,
        confidence="low",
        screen_hold=False,
        leave_stopped=leave_stopped,
        trigger_level_command_sent=set_trigger_level,
        probe=probe,
        result={"scan_attempts": attempts},
        notes=["No active waveform detected on scanned channels."],
    )


def _auto_setup_one_channel(
    *,
    scope: SDS800XHDTcpAdapter,
    channel: Channel,
    signal_hint: SignalHint,
    coarse_timebase: str,
    initial_vdiv: str,
    noise_floor_v: float,
    settle_s: float,
    probe: float,
    leave_stopped: bool,
    set_trigger_level: bool,
) -> dict[str, object]:
    steps: list[dict[str, object]] = []

    scope.configure_channel(
        channel=channel,
        vdiv=initial_vdiv,
        offset="0V",
        coupling="D1M",
        trace=True,
        probe=probe,
    )
    scope.configure_acquisition(
        command="auto",
        timebase=coarse_timebase,
        trigger_mode="AUTO",
        trigger_source=channel,
        trigger_slope=_trigger_slope(signal_hint),
    )
    time.sleep(settle_s)

    coarse = _measure_summary(scope, channel)
    coarse_pkpk = float(coarse.get("pkpk_v") or 0.0)
    dc_v = float(coarse.get("mean_v") or 0.0)
    steps.append({"stage": "coarse", **coarse})

    if coarse_pkpk < noise_floor_v:
        return {
            "channel": channel,
            "signal_detected": False,
            "confidence": "low",
            "measurements": coarse,
            "probe_steps": steps,
            "reason": "pkpk below noise_floor_v during coarse measurement",
        }

    final_vdiv = _pick_vdiv(max(coarse_pkpk, noise_floor_v))
    final_ofst = _clamp(dc_v, -final_vdiv * 6.0, final_vdiv * 6.0)

    frequency_hz = _as_float(coarse.get("frequency_hz"))
    period_s = _as_float(coarse.get("period_s"))
    if period_s is None and frequency_hz and frequency_hz > 0:
        period_s = 1.0 / frequency_hz
    final_tdiv = _pick_tdiv(period_s or 0.0)

    vmax = _as_float(coarse.get("max_v"))
    vmin = _as_float(coarse.get("min_v"))
    trig_level = (vmax + vmin) / 2.0 if vmax is not None and vmin is not None else dc_v

    scope.configure_channel(
        channel=channel,
        vdiv=_fmt_sci(final_vdiv),
        offset=_fmt_sci(final_ofst),
        coupling="D1M",
        trace=True,
        probe=probe,
    )
    scope.configure_acquisition(
        command="auto",
        timebase=_fmt_sci(final_tdiv),
        trigger_mode="AUTO",
        trigger_source=channel,
        trigger_level=_fmt_sci(trig_level) if set_trigger_level else None,
        trigger_slope=_trigger_slope(signal_hint),
    )
    time.sleep(settle_s)

    # Product goal: leave waveform visible. Use AUTO to acquire a fresh frame,
    # then STOP and do not ARM again unless explicitly requested.
    scope.transport.write("STOP")
    time.sleep(0.05)
    final_status = scope.get_acquisition_status()
    final_channel = scope.get_channel(channel)

    if not leave_stopped:
        scope.transport.write("ARM")

    return {
        "channel": channel,
        "signal_detected": True,
        "confidence": "medium" if coarse_pkpk < noise_floor_v * 10 else "high",
        "screen_hold": leave_stopped,
        "leave_stopped": leave_stopped,
        "trigger_level_command_sent": set_trigger_level,
        "probe": probe,
        "final_settings": {
            "vdiv_v": final_vdiv,
            "offset_v": final_ofst,
            "tdiv_s": final_tdiv,
            "trigger_level_v": trig_level,
            "trigger_slope": _trigger_slope(signal_hint),
        },
        "measurements": {
            **coarse,
            "period_s": period_s,
        },
        "final_panel_state": {
            "channel": final_channel,
            "acquisition": final_status,
        },
        "probe_steps": steps,
    }


def _measure_summary(scope: SDS800XHDTcpAdapter, channel: Channel) -> dict[str, float | None]:
    values = {
        "pkpk_v": _measure(scope, channel, "PKPK"),
        "mean_v": _measure(scope, channel, "MEAN"),
        "max_v": _measure(scope, channel, "MAX"),
        "min_v": _measure(scope, channel, "MIN"),
        "frequency_hz": _measure(scope, channel, "FREQ"),
        "period_s": _measure(scope, channel, "PER"),
    }
    return values


def _measure(
    scope: SDS800XHDTcpAdapter,
    channel: Channel,
    parameter: MeasureParameter,
) -> float | None:
    try:
        return _parse_meas_value(scope.measure(channel, parameter)["value"])
    except Exception:  # noqa: BLE001 - measurement probing should degrade gracefully
        return None


def _trigger_slope(signal_hint: SignalHint) -> Literal["POS", "NEG"]:
    return "NEG" if signal_hint in {"uart", "rs485", "modbus"} else "POS"


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
