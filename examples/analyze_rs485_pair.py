from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.rs485_analyzer import analyze_rs485_pair_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze RS485 A/B waveform CSV files")
    parser.add_argument("csv_a", help="CSV exported from RS485 A channel")
    parser.add_argument("csv_b", help="CSV exported from RS485 B channel")
    parser.add_argument("--baudrate", type=int, default=2_000_000)
    parser.add_argument("--threshold", type=float, default=0.0, help="Vdiff threshold in volts")
    args = parser.parse_args()

    result = analyze_rs485_pair_csv(
        args.csv_a,
        args.csv_b,
        baudrate=args.baudrate,
        threshold_v=args.threshold,
    )
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
