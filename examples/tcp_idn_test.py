from __future__ import annotations

import argparse

from siglent_sds_mcp.tcp_transport import RawTcpTransport


def main() -> None:
    parser = argparse.ArgumentParser(description="Query *IDN? over raw TCP SCPI socket")
    parser.add_argument("host", help="Oscilloscope IP address, for example 192.168.1.100")
    parser.add_argument("--port", type=int, default=5025, help="SCPI TCP port, default: 5025")
    args = parser.parse_args()

    transport = RawTcpTransport(args.host, args.port)
    try:
        transport.connect()
        print(transport.query("*IDN?"))
    finally:
        transport.close()


if __name__ == "__main__":
    main()
