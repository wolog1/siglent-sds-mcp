from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifacts import ensure_parent, utc_timestamp


@dataclass(slots=True)
class ReportInput:
    title: str = "SIGLENT SDS field capture report"
    output_path: str = "artifacts/reports/report.md"
    scope_idn: str | None = None
    scenario: str | None = None
    screenshot_path: str | None = None
    waveform_csv_paths: list[str] = field(default_factory=list)
    waveform_metadata_paths: list[str] = field(default_factory=list)
    uart_analysis_json_path: str | None = None
    rs485_analysis_json_path: str | None = None
    modbus_timing_json_path: str | None = None
    notes: str | None = None


def generate_markdown_report(report: ReportInput) -> dict[str, Any]:
    """Generate a Markdown field report from captured artifacts and JSON summaries."""

    output = ensure_parent(report.output_path)
    lines: list[str] = []
    lines.append(f"# {report.title}")
    lines.append("")
    lines.append(f"Generated UTC: `{utc_timestamp()}`")
    lines.append("")

    lines.append("## 1. Basic information")
    lines.append("")
    lines.append(f"- Scenario: `{report.scenario or 'not specified'}`")
    lines.append(f"- Instrument: `{report.scope_idn or 'not specified'}`")
    lines.append("")

    if report.notes:
        lines.append("## 2. Field notes")
        lines.append("")
        lines.append(report.notes.strip())
        lines.append("")

    lines.append("## 3. Artifacts")
    lines.append("")
    if report.screenshot_path:
        lines.append(f"- Screen image: `{report.screenshot_path}`")
    if report.waveform_csv_paths:
        lines.append("- Waveform CSV files:")
        for path in report.waveform_csv_paths:
            lines.append(f"  - `{path}`")
    if report.waveform_metadata_paths:
        lines.append("- Waveform metadata JSON files:")
        for path in report.waveform_metadata_paths:
            lines.append(f"  - `{path}`")
    if not any([report.screenshot_path, report.waveform_csv_paths, report.waveform_metadata_paths]):
        lines.append("- No artifacts listed.")
    lines.append("")

    _append_json_section(lines, "4. UART analysis", report.uart_analysis_json_path)
    _append_json_section(lines, "5. RS485 differential analysis", report.rs485_analysis_json_path)
    _append_json_section(lines, "6. Modbus RTU timing", report.modbus_timing_json_path)

    lines.append("## 7. Engineering interpretation checklist")
    lines.append("")
    lines.append("- [ ] Confirm probe attenuation and channel coupling match the report.")
    lines.append("- [ ] Confirm waveform timebase is appropriate for the configured baudrate.")
    lines.append("- [ ] Confirm signal level is consistent with TTL/RS485 expectations.")
    lines.append("- [ ] Confirm exported CSV corresponds to the same acquisition as the screen image.")
    lines.append("- [ ] If Modbus RTU is involved, compare request/response gap against 3.5-character timing.")
    lines.append("- [ ] If RS485 is involved, check differential swing and common-mode warnings.")
    lines.append("")

    lines.append("## 8. Compatibility note")
    lines.append("")
    lines.append(
        "This report may contain results from candidate SDS-style SCPI commands. "
        "For SDS824X HD stable compatibility, command behavior must be verified against "
        "the SDS800X HD Programming Guide and real instrument firmware."
    )
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "report_path": str(output)}


def _append_json_section(lines: list[str], title: str, json_path: str | None) -> None:
    lines.append(f"## {title}")
    lines.append("")
    if not json_path:
        lines.append("No JSON summary provided.")
        lines.append("")
        return

    path = Path(json_path)
    lines.append(f"Source: `{path}`")
    lines.append("")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report should preserve failure context
        lines.append(f"Could not read JSON summary: `{exc!r}`")
        lines.append("")
        return

    lines.append(_json_to_markdown_summary(data))
    lines.append("")


def _json_to_markdown_summary(data: Any) -> str:
    if not isinstance(data, dict):
        return "```json\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"

    preferred_keys = [
        "verdict",
        "baudrate",
        "expected_bit_time_s",
        "estimated_vpp",
        "vdiff_vpp",
        "edge_count",
        "median_edge_interval_ns",
        "bit_time_error_percent",
        "warnings",
        "char_time_us",
        "silence_3_5_char_us",
    ]
    rows = []
    for key in preferred_keys:
        if key in data:
            rows.append((key, data[key]))

    if not rows:
        return "```json\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"

    lines = ["| Field | Value |", "|---|---|"]
    for key, value in rows:
        if isinstance(value, (dict, list)):
            rendered = "`" + json.dumps(value, ensure_ascii=False) + "`"
        else:
            rendered = f"`{value}`"
        lines.append(f"| {key} | {rendered} |")
    return "\n".join(lines)
