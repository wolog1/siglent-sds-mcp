from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.auto_setup import auto_find_waveform
from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter
from siglent_sds_mcp.tcp_transport import RawTcpTransport


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatically find and display an unknown waveform")
    parser.add_argument("host", help="Oscilloscope IP address")
    parser.add_argument("--port", type=int, default=5025)
    parser.add_argument("--channels", nargs="+", default=["C1", "C2", "C3", "C4"])
    parser.add_argument(
        "--signal-hint",
        choices=["unknown", "uart", "rs485", "modbus", "pwm", "clock"],
        default="unknown",
    )
    parser.add_argument("--coarse-timebase", default="1MS")
    parser.add_argument("--initial-vdiv", default="1V")
    parser.add_argument("--max-points", type=int, default=2000)
    parser.add_argument("--noise-floor", type=float, default=0.05)
    args = parser.parse_args()

    transport = RawTcpTransport(args.host, args.port, timeout_s=5.0)
    try:
        transport.connect()
        scope = SDS800XHDTcpAdapter(transport)
        print(scope.identify())
        result = auto_find_waveform(
            scope,
            channels=args.channels,
            signal_hint=args.signal_hint,
            coarse_timebase=args.coarse_timebase,
            initial_vdiv=args.initial_vdiv,
            max_points=args.max_points,
            noise_floor_v=args.noise_floor,
        )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    finally:
        transport.close()


if __name__ == "__main__":
    main()
