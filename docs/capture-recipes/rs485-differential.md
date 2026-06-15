# Capture recipe: RS485 differential waveform

## Goal

Capture RS485 A/B differential waveform evidence using SDS824X HD through MCP.

RS485 diagnosis should focus on differential voltage:

```text
Vdiff = VA - VB
```

Single-ended A-to-GND or B-to-GND traces can help, but they are not the final logic judgment.

## Preferred probe setup

### Best

```text
Differential probe across A and B
```

### Practical two-channel method

```text
CH1 -> RS485 A
CH2 -> RS485 B
Math -> CH1 - CH2
GND -> device signal reference, only if safe
```

## Recommended oscilloscope setup

| Item | Recommended value |
|---|---|
| Probe | 10X passive probes or differential probe |
| Coupling | DC |
| CH1/CH2 vertical scale | start with 1 V/div |
| Timebase | based on baudrate; for 2 Mbps start with 1 us/div |
| Trigger | edge trigger on A/B or Math if supported |
| Termination | confirm bus-end 120 ohm termination externally |

## MCP workflow target

```text
connect
  -> identify
  -> configure_rs485_capture(channel_a=1, channel_b=2, baudrate=2000000)
  -> single_capture
  -> screenshot
  -> get_waveform(channel=1)
  -> get_waveform(channel=2)
  -> analyze_rs485_pair_csv
```

## Analyzer checks

- VA range
- VB range
- Vdiff range
- differential threshold crossing
- approximate bit timing
- common-mode anomaly warning
- missing termination symptoms: ringing/overshoot hints

## Engineering notes

For Modbus RTU/RS485 field troubleshooting, capture should include:

- request frame region
- response frame region
- turn-around delay
- idle bus state
- DE/RE direction control if exposed on another channel

If the instrument supports math waveform export, the MCP can export Math = CH1 - CH2 directly. Otherwise compute Vdiff offline from CH1/CH2 CSV files.
