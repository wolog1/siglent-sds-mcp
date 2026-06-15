from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Parity = Literal["N", "E", "O"]


@dataclass(slots=True)
class ModbusTiming:
    baudrate: int
    data_bits: int
    parity: Parity
    stop_bits: int
    bits_per_char: int
    char_time_s: float
    silence_1_5_char_s: float
    silence_3_5_char_s: float

    def to_dict(self) -> dict[str, object]:
        return {
            "baudrate": self.baudrate,
            "data_bits": self.data_bits,
            "parity": self.parity,
            "stop_bits": self.stop_bits,
            "bits_per_char": self.bits_per_char,
            "char_time_s": self.char_time_s,
            "char_time_us": self.char_time_s * 1e6,
            "silence_1_5_char_s": self.silence_1_5_char_s,
            "silence_1_5_char_us": self.silence_1_5_char_s * 1e6,
            "silence_3_5_char_s": self.silence_3_5_char_s,
            "silence_3_5_char_us": self.silence_3_5_char_s * 1e6,
        }


def calculate_modbus_rtu_timing(
    baudrate: int,
    data_bits: int = 8,
    parity: Parity = "N",
    stop_bits: int = 1,
) -> ModbusTiming:
    """Calculate Modbus RTU character and silence timing.

    The formula is intentionally explicit so field engineers can check timing against
    oscilloscope captures and serial logs.
    """

    if baudrate <= 0:
        raise ValueError("baudrate must be positive")
    if data_bits <= 0:
        raise ValueError("data_bits must be positive")
    if stop_bits <= 0:
        raise ValueError("stop_bits must be positive")
    parity = parity.upper()  # type: ignore[assignment]
    if parity not in {"N", "E", "O"}:
        raise ValueError("parity must be N, E, or O")

    parity_bits = 0 if parity == "N" else 1
    bits_per_char = 1 + data_bits + parity_bits + stop_bits
    char_time_s = bits_per_char / baudrate
    return ModbusTiming(
        baudrate=baudrate,
        data_bits=data_bits,
        parity=parity,
        stop_bits=stop_bits,
        bits_per_char=bits_per_char,
        char_time_s=char_time_s,
        silence_1_5_char_s=char_time_s * 1.5,
        silence_3_5_char_s=char_time_s * 3.5,
    )
