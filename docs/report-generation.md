# Report generation

## Goal

Generate a Markdown field report from oscilloscope capture artifacts and analysis summaries.

The report generator is intended to turn a field test into a shareable evidence package:

```text
screen image artifact
waveform CSV files
waveform metadata JSON files
UART analysis JSON
RS485 analysis JSON
Modbus RTU timing JSON
field notes
```

## MCP tool

```text
generate_report
```

Main parameters:

| Parameter | Purpose |
|---|---|
| `title` | Report title |
| `output_path` | Markdown output path |
| `scope_idn` | Instrument identity string from `identify_tcp` |
| `scenario` | Test scenario, for example `2 Mbps UART` or `RS485 Modbus RTU` |
| `screenshot_path` | Screen image artifact path |
| `waveform_csv_paths` | List of waveform CSV paths |
| `waveform_metadata_paths` | List of waveform metadata JSON paths |
| `uart_analysis_json_path` | UART analysis JSON path |
| `rs485_analysis_json_path` | RS485 analysis JSON path |
| `modbus_timing_json_path` | Modbus RTU timing JSON path |
| `notes` | Free-form field notes |

## Command-line example

```bash
python examples/generate_report.py \
  --title "RS485 Modbus RTU field capture" \
  --output artifacts/reports/rs485_modbus_report.md \
  --scope-idn "SIGLENT,SDS824X HD,..." \
  --scenario "RS485 Modbus RTU 9600 8N1" \
  --screen artifacts/screenshots/capture.bmp \
  --waveform-csv artifacts/waveforms/ch1_a.csv \
  --waveform-csv artifacts/waveforms/ch2_b.csv \
  --rs485-analysis artifacts/waveforms/rs485_analysis.json \
  --modbus-timing artifacts/waveforms/modbus_timing.json \
  --notes "CH1=A, CH2=B, 120 ohm termination installed at bus end."
```

## Suggested full workflow

### UART

```text
connect_tcp
identify_tcp
capture_uart_2mbps_tcp
convert returned analysis to JSON if needed
generate_report
```

### RS485 / Modbus RTU

```text
connect_tcp
identify_tcp
capture_rs485_pair_tcp.py or separate get_waveform_tcp for C1/C2
analyze_rs485_pair_csv_file
modbus_rtu_timing
generate_report
```

## Report contents

Generated Markdown includes:

1. basic information
2. field notes
3. artifact list
4. UART analysis section
5. RS485 differential analysis section
6. Modbus RTU timing section
7. engineering interpretation checklist
8. SDS824X HD compatibility note

## Artifact policy

Generated reports are ignored by git under:

```text
artifacts/reports/*
```

Only commit sanitized example reports intentionally.
