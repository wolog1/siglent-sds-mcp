from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter
from siglent_sds_mcp.tcp_transport import RawTcpTransport


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture and analyze a 2 Mbps UART waveform over TCP SCPI")
    parser.add_argument("host", help="Oscilloscope IP address")
    parser.add_argument("--port", type=int, default=5025)
    parser.add_argument("--channel", default="C1", choices=["C1", "C2", "C3", "C4"])
    parser.add_argument("--logic-level", default="3.3V TTL", choices=["3.3V TTL", "5V TTL"])
    parser.add_argument("--max-points", type=int, default=5000)
    args = parser.parse_args()

    transport = RawTcpTransport(args.host, args.port, timeout_s=5.0)
    try:
        transport.connect()
        scope = SDS800XHDTcpAdapter(transport)
        print(scope.identify())
        result = scope.capture_uart_2mbps(
            channel=args.channel,
            logic_level=args.logic_level,
            max_points=args.max_points,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        transport.close()


if __name__ == "__main__":
    main()
