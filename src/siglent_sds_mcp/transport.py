from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class InstrumentSession(Protocol):
    """Minimal instrument session protocol used by the driver."""

    timeout: int

    def write(self, command: str) -> object: ...

    def query(self, command: str) -> str: ...

    def read_raw(self) -> bytes: ...

    def close(self) -> object: ...


@dataclass(slots=True)
class VisaTransport:
    """Thin PyVISA transport wrapper.

    `resource` examples:
    - TCPIP0::192.168.1.100::INSTR
    - TCPIP0::192.168.1.100::inst0::INSTR
    - USB0::0xF4EC::0xEE38::<serial>::INSTR
    """

    resource: str
    timeout_ms: int = 5000
    backend: str | None = None

    def open(self) -> InstrumentSession:
        try:
            import pyvisa  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            raise RuntimeError("pyvisa is required. Install with: pip install pyvisa") from exc

        rm = pyvisa.ResourceManager(self.backend) if self.backend else pyvisa.ResourceManager()
        session = rm.open_resource(self.resource)
        session.timeout = self.timeout_ms
        return session  # type: ignore[return-value]


def normalize_scpi(command: str) -> str:
    """Normalize an SCPI command before sending it to the instrument."""

    command = command.strip()
    if not command:
        raise ValueError("SCPI command must not be empty")
    return command
