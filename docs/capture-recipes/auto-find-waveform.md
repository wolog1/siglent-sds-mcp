# Capture recipe: auto-find waveform

## Goal

Automatically find and display a waveform even when the user does not know the signal parameters.

The workflow is intended for field debugging where the engineer may not know:

- active channel
- voltage amplitude
- signal frequency or baudrate
- trigger level
- suitable timebase

## MCP tool

```text
auto_find_waveform_tcp
```

## What it does

```text
scan C1/C2/C3/C4
  -> configure broad initial range
  -> export small waveform CSV
  -> compute Vpp / threshold / edge count / edge interval
  -> choose best active channel
  -> set VDIV and OFST
  -> set TDIV and edge trigger level
  -> capture screen image
  -> export final waveform CSV and metadata
  -> write JSON summary
```

## Example MCP call

```json
{
  "channels": ["C1", "C2", "C3", "C4"],
  "signal_hint": "uart",
  "coarse_timebase": "1MS",
  "initial_vdiv": "1V",
  "max_points": 2000,
  "noise_floor_v": 0.05
}
```

## Command-line example

```bash
python examples/auto_find_waveform_tcp.py <scope-ip> --signal-hint uart
```

For RS485/Modbus:

```bash
python examples/auto_find_waveform_tcp.py <scope-ip> --channels C1 C2 --signal-hint modbus --coarse-timebase 1MS
```

## Output fields

| Field | Meaning |
|---|---|
| `found` | Whether an active waveform was found |
| `selected_channel` | Best channel selected by Vpp and edge score |
| `recommended_vdiv` | Vertical scale chosen for display |
| `recommended_offset` | Offset chosen to center waveform |
| `recommended_timebase` | Timebase chosen from edge interval estimate |
| `trigger_level` | Trigger level near waveform midpoint |
| `screenshot_path` | Captured screen artifact |
| `final_waveform_csv` | Final waveform CSV after auto setup |
| `report_json_path` | JSON summary of the auto setup run |

## Practical limitations

This is a first-pass auto-ranging tool, not a full protocol decoder.

It works best when:

- signal is repetitive or present during scan;
- channel is connected correctly;
- waveform amplitude is above noise floor;
- probe attenuation is known or 10X is acceptable;
- one of the scanned channels has a clear edge or Vpp.

It may need manual help when:

- signal is one-shot and not present during scan;
- amplitude is very small;
- signal is slow but coarse timebase is too short;
- channel is saturated or over-range;
- coupling/probe setting is wrong;
- RS485 A/B must be interpreted differentially.

## Next improvements

- poll acquisition status instead of using fixed settle delays;
- add real Auto Setup SCPI command if confirmed in SDS800X HD Programming Guide;
- add protocol-specific presets for UART, RS485, Modbus, SPI and I2C;
- add time-aligned RS485 dual-channel auto setup;
- refresh README after hardware validation.
