from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .transport import InstrumentSession, VisaTransport, normalize_scpi


DANGEROUS_SCPI_PREFIXES = (
    "*RST",
    ":SYST:FACT",
    ":SYSTem:FACTory",
    ":MMEM:DEL",
    ":MMEMory:DELete",
    ":SYSTem:COMM:LAN",
)


@dataclass(slots=True)
class ChannelSetup:
    channel: int = 1
    scale_v_per_div: float = 1.0
    offset_v: float = 0.0
    coupling: str = "DC"
    probe: str = "10X"


@dataclass(slots=True)
class UartCaptureSetup:
    channel: int = 1
    baudrate: int = 2_000_000
    logic_level: str = "3.3V TTL"
    trigger_level_v: float = 1.5
    time_scale_s_per_div: float = 1e-6
    vertical_scale_v_per_div: float = 1.0
    coupling: str = "DC"
    slope: str = "NEG"


class SiglentSDSDriver:
    """Conservative SIGLENT SDS800X HD SCPI driver scaffold.

    Notes:
    - Basic IEEE/common SCPI commands such as `*IDN?` are stable.
    - Model-specific waveform/screenshot commands must be verified with the SDS800X HD
      Programming Guide and the actual firmware revision before production use.
    """

    def __init__(self, session: InstrumentSession):
        self.session = session

    @classmethod
    def connect(cls, resource: str, timeout_ms: int = 5000, backend: str | None = None) -> "SiglentSDSDriver":
        return cls(VisaTransport(resource=resource, timeout_ms=timeout_ms, backend=backend).open())

    def close(self) -> None:
        self.session.close()

    def write(self, command: str, *, allow_unsafe: bool = False) -> None:
        command = normalize_scpi(command)
        if not allow_unsafe:
            upper = command.upper()
            if any(upper.startswith(prefix.upper()) for prefix in DANGEROUS_SCPI_PREFIXES):
                raise PermissionError(f"Blocked dangerous SCPI command: {command}")
        self.session.write(command)

    def query(self, command: str) -> str:
        command = normalize_scpi(command)
        if not command.endswith("?"):
            raise ValueError("query() only accepts SCPI query commands ending with '?'")
        return self.session.query(command).strip()

    def idn(self) -> str:
        return self.query("*IDN?")

    def run(self) -> None:
        self.write(":RUN")

    def stop(self) -> None:
        self.write(":STOP")

    def single(self) -> None:
        self.write(":SINGLE")

    def force_trigger(self) -> None:
        self.write(":TRIGger:FORCe")

    def setup_channel(self, setup: ChannelSetup) -> dict[str, Any]:
        ch = self._channel_name(setup.channel)
        coupling = setup.coupling.upper()
        if coupling not in {"DC", "AC", "GND"}:
            raise ValueError("coupling must be one of: DC, AC, GND")

        self.write(f":{ch}:DISPlay ON")
        self.write(f":{ch}:COUPling {coupling}")
        self.write(f":{ch}:SCALe {setup.scale_v_per_div}")
        self.write(f":{ch}:OFFSet {setup.offset_v}")
        # Probe command names differ slightly across families; verify with Programming Guide.
        # Kept out of MVP write sequence until confirmed.
        return {
            "channel": setup.channel,
            "scale_v_per_div": setup.scale_v_per_div,
            "offset_v": setup.offset_v,
            "coupling": coupling,
            "probe": setup.probe,
            "note": "Probe SCPI setting intentionally not sent until verified for SDS800X HD.",
        }

    def setup_timebase(self, scale_s_per_div: float, delay_s: float = 0.0) -> dict[str, float]:
        if scale_s_per_div <= 0:
            raise ValueError("scale_s_per_div must be positive")
        self.write(f":TIMebase:SCALe {scale_s_per_div}")
        self.write(f":TIMebase:DELay {delay_s}")
        return {"scale_s_per_div": scale_s_per_div, "delay_s": delay_s}

    def setup_edge_trigger(self, channel: int, level_v: float, slope: str = "NEG") -> dict[str, Any]:
        slope = slope.upper()
        if slope not in {"POS", "NEG", "EITHer", "EITHER"}:
            raise ValueError("slope must be POS, NEG, or EITHER")
        ch = self._channel_name(channel)
        self.write(":TRIGger:MODE EDGE")
        self.write(f":TRIGger:EDGE:SOURce {ch}")
        self.write(f":TRIGger:EDGE:SLOPe {slope}")
        self.write(f":TRIGger:EDGE:LEVel {level_v}")
        return {"channel": channel, "level_v": level_v, "slope": slope}

    def setup_uart_capture(self, setup: UartCaptureSetup) -> dict[str, Any]:
        ch = ChannelSetup(
            channel=setup.channel,
            scale_v_per_div=setup.vertical_scale_v_per_div,
            coupling=setup.coupling,
        )
        channel_result = self.setup_channel(ch)
        timebase_result = self.setup_timebase(setup.time_scale_s_per_div)
        trigger_result = self.setup_edge_trigger(setup.channel, setup.trigger_level_v, setup.slope)
        bit_time_s = 1.0 / setup.baudrate
        return {
            "channel": channel_result,
            "timebase": timebase_result,
            "trigger": trigger_result,
            "baudrate": setup.baudrate,
            "bit_time_s": bit_time_s,
            "bit_time_ns": bit_time_s * 1e9,
            "logic_level": setup.logic_level,
        }

    def measure_basic(self, channel: int = 1) -> dict[str, str]:
        ch = self._channel_name(channel)
        results: dict[str, str] = {"channel": ch}
        queries = {
            "vpp": f":MEASure:VPP? {ch}",
            "frequency": f":MEASure:FREQuency? {ch}",
            "period": f":MEASure:PERiod? {ch}",
        }
        for name, query in queries.items():
            try:
                results[name] = self.query(query)
            except Exception as exc:  # noqa: BLE001 - keep driver tolerant during bring-up
                results[name] = f"ERROR: {exc}"
        return results

    def fetch_waveform_csv(self, channel: int, output_path: str | Path, max_points: int | None = None) -> dict[str, Any]:
        """Fetch waveform samples and save a CSV.

        This method is intentionally conservative. SIGLENT SDS waveform binary block commands
        vary by generation and firmware. The current implementation writes a CSV header and
        documents the intended place for the SCPI block read. Replace the TODO section after
        command verification on a real SDS824X HD.
        """

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time_s", "voltage_v"])

        return {
            "path": str(path),
            "channel": channel,
            "max_points": max_points,
            "status": "placeholder",
            "todo": "Implement SDS800X HD waveform binary block query after SCPI command verification.",
        }

    def wait_after_single(self, seconds: float = 0.5) -> None:
        time.sleep(seconds)

    @staticmethod
    def _channel_name(channel: int) -> str:
        if channel not in {1, 2, 3, 4}:
            raise ValueError("channel must be 1, 2, 3, or 4")
        return f"CHANnel{channel}"
