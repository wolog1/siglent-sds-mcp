from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.rs485_analyzer import analyze_rs485_pair_csv
from siglent_sds_mcp.sds_tcp_adapter import SDS800XHDTcpAdapter
from siglent_sds_mcp.tcp_transport import RawTcpTransport


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture RS485 A/B waveforms and analyze differential signal")
    parser.add_argument("host", help="Oscilloscope IP address")
    parser.add_argument("--port", type=int, default=5025)
    parser.add_argument("--channel-a", default="C1", choices=["C1", "C2", "C3", "C4"])
    parser.add_argument("--channel-b", default="C2", choices=["C1", "C2", "C3", "C4"])
    parser.add_argument("--baudrate", type=int, default=2_000_000)
    parser.add_argument("--timebase", default="1US")
    parser.add_argument("--trigger-level", default="2.5V")
    parser.add_argument("--max-points", type=int, default=5000)
    args = parser.parse_args()

    transport = RawTcpTransport(args.host, args.port, timeout_s=5.0)
    try:
        transport.connect()
        scope = SDS800XHDTcpAdapter(transport)
        print(scope.identify())

        setup_a = scope.configure_channel(
            channel=args.channel_a,
            vdiv="1V",
            offset="0V",
            coupling="D1M",
            trace=True,
            probe=10,
        )
        setup_b = scope.configure_channel(
            channel=args.channel_b,
            vdiv="1V",
            offset="0V",
            coupling="D1M",
            trace=True,
            probe=10,
        )
        acquisition = scope.configure_acquisition(
            command="single",
            timebase=args.timebase,
            trigger_mode="SINGLE",
            trigger_source=args.channel_a,
            trigger_level=args.trigger_level,
            trigger_slope="NEG",
        )

        screen = scope.screenshot()
        wave_a = scope.get_waveform(channel=args.channel_a, max_points=args.max_points)
        wave_b = scope.get_waveform(channel=args.channel_b, max_points=args.max_points)
        analysis = analyze_rs485_pair_csv(wave_a.csv_path, wave_b.csv_path, baudrate=args.baudrate)

        print(
            json.dumps(
                {
                    "setup_a": setup_a,
                    "setup_b": setup_b,
                    "acquisition": acquisition,
                    "screen": screen,
                    "waveform_a": {"csv_path": wave_a.csv_path, "metadata_path": wave_a.metadata_path},
                    "waveform_b": {"csv_path": wave_b.csv_path, "metadata_path": wave_b.metadata_path},
                    "analysis": analysis.to_dict(),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    finally:
        transport.close()


if __name__ == "__main__":
    main()
