from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter
from siglent_sds_mcp.tcp_transport import RawTcpTransport


def main() -> None:
    parser = argparse.ArgumentParser(description="Export waveform CSV over TCP SCPI")
    parser.add_argument("host", help="Oscilloscope IP address")
    parser.add_argument("--port", type=int, default=5025)
    parser.add_argument("--channel", default="C1", choices=["C1", "C2", "C3", "C4"])
    parser.add_argument("--max-points", type=int, default=5000)
    parser.add_argument("--csv", default=None, help="CSV output path")
    parser.add_argument("--metadata", default=None, help="Metadata JSON output path")
    args = parser.parse_args()

    transport = RawTcpTransport(args.host, args.port, timeout_s=5.0)
    try:
        transport.connect()
        scope = SDS800XHDTcpAdapter(transport)
        print(scope.identify())
        result = scope.get_waveform(
            channel=args.channel,
            csv_path=args.csv,
            metadata_path=args.metadata,
            max_points=args.max_points,
        )
        print(json.dumps({"csv_path": result.csv_path, "metadata_path": result.metadata_path, "metadata": result.metadata}, indent=2, ensure_ascii=False))
    finally:
        transport.close()


if __name__ == "__main__":
    main()
