from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter
from siglent_sds_mcp.tcp_transport import RawTcpTransport


def main() -> None:
    parser = argparse.ArgumentParser(description="Save oscilloscope screen image over TCP SCPI")
    parser.add_argument("host", help="Oscilloscope IP address")
    parser.add_argument("--port", type=int, default=5025)
    parser.add_argument("--output", default=None, help="Output path under artifacts/screenshots by default")
    args = parser.parse_args()

    transport = RawTcpTransport(args.host, args.port, timeout_s=5.0)
    try:
        transport.connect()
        scope = SDS800XHDTcpAdapter(transport)
        print(scope.identify())
        result = scope.screenshot(output_path=args.output)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        transport.close()


if __name__ == "__main__":
    main()
