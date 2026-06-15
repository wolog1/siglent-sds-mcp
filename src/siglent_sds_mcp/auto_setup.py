from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .sds_tcp_adapter import Channel, SDS800XHDTcpAdapter

SignalHint = Literal["unknown", "uart", "rs485", "modbus", "pwm", "clock"]


@dataclass(slots=True)
class AutoSetupResult:
    """Compatibility result object for the historical auto_find_waveform API.

    The main implementation now lives in `SDS800XHDTcpAdapter.auto_setup()`.
    This wrapper keeps older MCP/CLI entry points working while the project
    converges on one implementation.
    """

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
    coarse_timebase: str = "1MS",  # kept for API compatibility
    initial_vdiv: str = "1V",  # kept for API compatibility
    max_points: int = 2000,  # kept for API compatibility
    noise_floor_v: float = 0.05,  # kept for API compatibility
    settle_s: float = 0.6,
    probe: float = 10.0,
    refine_attempts: int = 3,  # kept for API compatibility
    leave_stopped: bool = True,
    set_trigger_level: bool = False,
) -> AutoSetupResult:
    """Compatibility wrapper around `SDS800XHDTcpAdapter.auto_setup()`.

    It scans candidate channels one by one and returns the first detected signal.
    The wrapped adapter method is measurement-driven and leaves the screen stopped
    by default when `leave_stopped=True`.
    """

    candidate_channels: list[Channel] = channels or ["C1", "C2", "C3", "C4"]
    attempts: list[dict[str, object]] = []

    for channel in candidate_channels:
        result = scope.auto_setup(
            channel=channel,
            settle_s=settle_s,
            screenshot_path=None,
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
                confidence="medium",
                screen_hold=leave_stopped,
                leave_stopped=leave_stopped,
                trigger_level_command_sent=set_trigger_level,
                probe=probe,
                result=result,
                notes=[
                    "auto_find_waveform compatibility wrapper used adapter.auto_setup().",
                    "coarse_timebase, initial_vdiv, max_points, noise_floor_v and refine_attempts "
                    "are accepted for backwards compatibility but not directly used by the "
                    "measurement-driven adapter path.",
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
