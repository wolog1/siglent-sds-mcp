from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.modbus_timing import calculate_modbus_rtu_timing


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate Modbus RTU character and silence timing")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--data-bits", type=int, default=8)
    parser.add_argument("--parity", choices=["N", "E", "O"], default="N")
    parser.add_argument("--stop-bits", type=int, default=1)
    args = parser.parse_args()

    timing = calculate_modbus_rtu_timing(
        baudrate=args.baudrate,
        data_bits=args.data_bits,
        parity=args.parity,
        stop_bits=args.stop_bits,
    )
    print(json.dumps(timing.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
