from __future__ import annotations

import pytest

from siglent_sds_mcp.scope_driver import SiglentSDSDriver, UartCaptureSetup


class FakeSession:
    def __init__(self) -> None:
        self.timeout = 1000
        self.writes: list[str] = []

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        if command == "*IDN?":
            return "SIGLENT,SDS824X HD,FAKE,1.0"
        return "0"

    def read_raw(self) -> bytes:
        return b""

    def close(self) -> None:
        pass


def test_idn() -> None:
    scope = SiglentSDSDriver(FakeSession())
    assert "SDS824X HD" in scope.idn()


def test_blocks_dangerous_scpi() -> None:
    scope = SiglentSDSDriver(FakeSession())
    with pytest.raises(PermissionError):
        scope.write("*RST")


def test_setup_uart_capture_writes_expected_commands() -> None:
    fake = FakeSession()
    scope = SiglentSDSDriver(fake)
    result = scope.setup_uart_capture(UartCaptureSetup(channel=1, baudrate=2_000_000))
    assert result["bit_time_ns"] == 500.0
    assert ":CHANnel1:SCALe 1.0" in fake.writes
    assert ":TIMebase:SCALe 1e-06" in fake.writes
    assert ":TRIGger:EDGE:LEVel 1.5" in fake.writes
