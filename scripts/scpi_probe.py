from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

from siglent_sds_mcp.tcp_transport import RawTcpTransport


DEFAULT_COMMANDS = [
    "*IDN?",
    "CHDR?",
    "C1:VDIV?",
    "C1:OFST?",
    "TDIV?",
    "SARA?",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe candidate SCPI queries on SDS824X HD")
    parser.add_argument("host", help="Oscilloscope IP address")
    parser.add_argument("--port", type=int, default=5025)
    parser.add_argument("--command", action="append", help="SCPI query to execute; may be repeated")
    parser.add_argument(
        "--output",
        default="artifacts/verification/scpi_probe.csv",
        help="CSV output path",
    )
    args = parser.parse_args()

    commands = args.command or DEFAULT_COMMANDS
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    transport = RawTcpTransport(args.host, args.port)
    rows: list[dict[str, str]] = []
    try:
        transport.connect()
        for command in commands:
            now = dt.datetime.now(dt.UTC).isoformat()
            try:
                response = transport.query(command)
                status = "ok"
            except Exception as exc:  # noqa: BLE001 - diagnostic script
                response = repr(exc)
                status = "error"
            rows.append(
                {
                    "timestamp": now,
                    "host": args.host,
                    "port": str(args.port),
                    "command": command,
                    "status": status,
                    "response": response,
                }
            )
    finally:
        transport.close()

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "host", "port", "command", "status", "response"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output}")


if __name__ == "__main__":
    main()
