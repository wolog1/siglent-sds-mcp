from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal

from .sds_tcp_adapter import (
    Channel,
    SDS800XHDTcpAdapter,
)


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

SignalHint = Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"]
MIN_PERIODIC_SIGNAL_VPP = 0.005


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
    min_signal_vpp: float = MIN_PERIODIC_SIGNAL_VPP,
) -> AutoSetupResult:
    """Find, range, and optionally hold an active waveform on screen.

    Internally delegates to :meth:`SDS800XHDTcpAdapter.auto_setup` for the
    robust tdiv-scan + multi-sample measurement pipeline, then applies
    user-configurable thresholds (``noise_floor_v`` / ``min_signal_vpp``) and
    post-capture behaviour (``leave_stopped`` / ``set_trigger_level``).
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
            min_signal_vpp=min_signal_vpp,
            settle_s=settle_s,
            probe=probe,
            leave_stopped=leave_stopped,
            set_trigger_level=set_trigger_level,
        )
        attempts.append(result)
        if bool(result.get("signal_detected")):
            # Break circular reference: the last entry in attempts *is* result,
            # so injecting attempts back into result creates a cycle.
            scan_attempts = list(attempts)
            scan_attempts[-1] = {k: v for k, v in result.items() if k != "scan_attempts"}
            result["scan_attempts"] = scan_attempts
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
    min_signal_vpp: float,
    settle_s: float,
    probe: float,
    leave_stopped: bool,
    set_trigger_level: bool,
) -> dict[str, object]:
    """Run the robust ``auto_setup`` pipeline and apply threshold / post-capture rules."""

    # Ensure probe attenuation is set before the underlying auto_setup runs.
    scope.configure_channel(channel, probe=probe)
    time.sleep(0.05)

    raw = scope.auto_setup(
        channel,
        target_cycles=4.0,
        settle_s=settle_s,
        set_trigger_level=set_trigger_level,
    )

    pkpk = float(raw.get("measurements", {}).get("pkpk_v") or 0.0)
    freq = _as_float(raw.get("measurements", {}).get("frequency_hz"))
    per = _as_float(raw.get("measurements", {}).get("period_s"))

    if not bool(raw.get("signal_detected")):
        return {
            "channel": channel,
            "signal_detected": False,
            "confidence": "low",
            "measurements": raw.get("measurements", {}),
            "periodic_evidence": False,
            "noise_floor_v": noise_floor_v,
            "min_signal_vpp": min_signal_vpp,
            "probe_steps": raw.get("probe_steps", []),
            "reason": "auto_setup reported no detectable signal",
        }

    periodic_evidence = _has_periodic_evidence(frequency_hz=freq, period_s=per)
    detection = _classify_signal(
        pkpk_v=pkpk,
        noise_floor_v=noise_floor_v,
        min_signal_vpp=min_signal_vpp,
        periodic_evidence=periodic_evidence,
    )

    if not bool(detection["signal_detected"]):
        return {
            "channel": channel,
            "signal_detected": False,
            "confidence": "low",
            "measurements": raw.get("measurements", {}),
            "periodic_evidence": periodic_evidence,
            "noise_floor_v": noise_floor_v,
            "min_signal_vpp": min_signal_vpp,
            "probe_steps": raw.get("probe_steps", []),
            "reason": detection["reason"],
        }

    # Post-capture behaviour.
    # When leave_stopped=True we freeze the current frame with STOP and do NOT
    # touch any acquisition settings afterwards (no TRMD AUTO, no ARM).  This
    # guarantees the screen stays on the final waveform.
    if leave_stopped:
        scope.transport.write("STOP")
        time.sleep(0.05)
    else:
        scope.transport.write("ARM")
        time.sleep(0.05)

    final_status = scope.get_acquisition_status()
    final_channel = scope.get_channel(channel)

    return {
        "channel": channel,
        "signal_detected": True,
        "confidence": detection["confidence"],
        "reason": detection["reason"],
        "screen_hold": leave_stopped,
        "leave_stopped": leave_stopped,
        "trigger_level_command_sent": set_trigger_level,
        "probe": probe,
        "noise_floor_v": noise_floor_v,
        "min_signal_vpp": min_signal_vpp,
        "periodic_evidence": periodic_evidence,
        "final_settings": raw.get("final_settings", {}),
        "measurements": raw.get("measurements", {}),
        "final_panel_state": {
            "channel": final_channel,
            "acquisition": final_status,
        },
        "probe_steps": raw.get("probe_steps", []),
        "screenshot": raw.get("screenshot"),
    }


def _classify_signal(
    *,
    pkpk_v: float,
    noise_floor_v: float,
    min_signal_vpp: float,
    periodic_evidence: bool,
) -> dict[str, object]:
    if pkpk_v >= noise_floor_v:
        return {
            "signal_detected": True,
            "confidence": "high" if pkpk_v >= noise_floor_v * 10 else "medium",
            "reason": "pkpk above noise_floor_v",
        }
    if periodic_evidence and pkpk_v >= min_signal_vpp:
        return {
            "signal_detected": True,
            "confidence": "low",
            "reason": "periodic signal accepted below noise_floor_v because frequency/period is valid",
        }
    return {
        "signal_detected": False,
        "confidence": "low",
        "reason": "pkpk below thresholds and no valid periodic evidence",
    }


def _has_periodic_evidence(frequency_hz: float | None, period_s: float | None) -> bool:
    if frequency_hz is not None and math.isfinite(frequency_hz) and frequency_hz > 0:
        return True
    return bool(period_s is not None and math.isfinite(period_s) and period_s > 0)


def _trigger_slope(signal_hint: SignalHint) -> Literal["POS", "NEG"]:
    return "NEG" if signal_hint in {"uart", "rs485", "modbus"} else "POS"
