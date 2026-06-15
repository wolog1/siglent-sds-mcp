from __future__ import annotations

import argparse
import json

from siglent_sds_mcp.report import ReportInput, generate_markdown_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Markdown field report from capture artifacts")
    parser.add_argument("--title", default="SIGLENT SDS field capture report")
    parser.add_argument("--output", default="artifacts/reports/report.md")
    parser.add_argument("--scope-idn", default=None)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--screen", default=None, help="Screen image artifact path")
    parser.add_argument("--waveform-csv", action="append", default=[])
    parser.add_argument("--waveform-metadata", action="append", default=[])
    parser.add_argument("--uart-analysis", default=None)
    parser.add_argument("--rs485-analysis", default=None)
    parser.add_argument("--modbus-timing", default=None)
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    result = generate_markdown_report(
        ReportInput(
            title=args.title,
            output_path=args.output,
            scope_idn=args.scope_idn,
            scenario=args.scenario,
            screenshot_path=args.screen,
            waveform_csv_paths=args.waveform_csv,
            waveform_metadata_paths=args.waveform_metadata,
            uart_analysis_json_path=args.uart_analysis,
            rs485_analysis_json_path=args.rs485_analysis,
            modbus_timing_json_path=args.modbus_timing,
            notes=args.notes,
        )
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
