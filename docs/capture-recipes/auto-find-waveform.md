# Capture recipe: auto-find waveform

## Goal

Automatically find, range, and **leave a waveform visible on the oscilloscope screen** even when the user does not know the signal parameters.

The workflow is intended for field debugging where the engineer may not know:

- active channel
- voltage amplitude
- signal frequency or baudrate
- trigger level
- suitable timebase
- probe attenuation

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
  -> calculate VDIV / OFST / TDIV
  -> refine display settings for up to N attempts
  -> capture a fresh frame and keep scope STOPPED
  -> capture screen image from the same stopped frame
  -> analyze final CSV and collect final panel state
  -> write JSON summary
```

The default behavior is **screen hold**:

```text
leave_stopped = true
screen_hold = true
```

This means the command should finish with the final waveform still visible on the scope display.
Use `leave_stopped=false` only when a caller explicitly wants the scope to resume acquisition.

## Example MCP call

```json
{
  "channels": ["C1", "C2", "C3", "C4"],
  "signal_hint": "uart",
  "coarse_timebase": "1MS",
  "initial_vdiv": "1V",
  "max_points": 2000,
  "noise_floor_v": 0.05,
  "probe": 10,
  "refine_attempts": 3,
  "leave_stopped": true,
  "set_trigger_level": false
}
```

## Command-line example

```bash
python examples/auto_find_waveform_tcp.py <scope-ip> --signal-hint uart
```

For direct TTL wiring or a 1X probe:

```bash
python examples/auto_find_waveform_tcp.py <scope-ip> \
  --channels C1 \
  --signal-hint clock \
  --probe 1 \
  --refine-attempts 3
```

For RS485/Modbus single-ended probing:

```bash
python examples/auto_find_waveform_tcp.py <scope-ip> \
  --channels C1 C2 \
  --signal-hint modbus \
  --coarse-timebase 1MS
```

To restart acquisition after capture instead of holding the screen:

```bash
python examples/auto_find_waveform_tcp.py <scope-ip> --restart-after-capture
```

## Output fields

| Field | Meaning |
|---|---|
| `found` | Whether an active waveform was found |
| `selected_channel` | Best channel selected by Vpp and edge score |
| `recommended_vdiv` | Final vertical scale chosen for display |
| `recommended_offset` | Final offset chosen to center waveform |
| `recommended_timebase` | Final timebase chosen from edge interval estimate |
| `trigger_level` | Diagnostic trigger level near waveform midpoint |
| `trigger_level_command_sent` | Whether `C?:TRLV` was actually sent |
| `leave_stopped` | Whether acquisition was left stopped after capture |
| `screen_hold` | Whether the tool intentionally holds the final frame on screen |
| `refine_history` | Per-attempt VDIV/OFST/TDIV and visibility diagnostics |
| `final_panel_state` | Final channel/acquisition query responses |
| `screenshot_path` | Captured screen artifact |
| `final_waveform_csv` | Final waveform CSV after auto setup |
| `report_json_path` | JSON summary of the auto setup run |

## Trigger-level policy

`set_trigger_level` defaults to `false` because `C?:TRLV <level>` is a known issue on SDS824X HD firmware `4.8.12.1.1.6.5`. AUTO-mode capture is used as the default display-oriented path.

## Practical limitations

This is an auto-ranging/display tool, not a full protocol decoder.

It works best when:

- signal is repetitive or present during scan;
- channel is connected correctly;
- waveform amplitude is above noise floor;
- probe attenuation is configured correctly with `--probe`;
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
- add time-aligned RS485 dual-channel auto setup.
