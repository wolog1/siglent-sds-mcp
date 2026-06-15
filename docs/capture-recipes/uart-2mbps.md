# Capture recipe: 2 Mbps UART

## Goal

Capture and analyze a 2 Mbps UART waveform using SDS824X HD through MCP.

## Electrical assumptions

Typical UART 8N1:

```text
idle: high
start bit: low
data bits: LSB first
stop bit: high
```

For 2 Mbps:

```text
bit time = 1 / 2,000,000 = 500 ns
8N1 frame = 10 bits = 5 us
```

## Recommended oscilloscope setup

### TTL UART, 3.3 V

| Item | Recommended value |
|---|---|
| Probe | 10X |
| Coupling | DC |
| Vertical scale | 1 V/div |
| Timebase | 1 us/div to start |
| Trigger type | Edge |
| Trigger source | TXD/RXD channel |
| Trigger slope | Falling edge |
| Trigger level | about 1.5 V |
| Acquisition | Single for evidence capture |

### TTL UART, 5 V

| Item | Recommended value |
|---|---|
| Vertical scale | 1 V/div or 2 V/div |
| Trigger level | about 2.5 V |

## Expected artifacts

```text
artifacts/screenshots/<timestamp>_uart_2mbps.png
artifacts/waveforms/<timestamp>_uart_2mbps_ch1.csv
artifacts/waveforms/<timestamp>_uart_2mbps_analysis.json
```

## Analyzer checks

The offline analyzer should check:

- voltage high level
- voltage low level
- Vpp
- threshold crossing count
- median edge interval
- estimated bit time
- timing error against 500 ns
- obvious voltage-level warnings

## Practical waveform patterns

A repeated `0x55` test pattern is useful because it produces frequent transitions:

```text
0x55 = 01010101
```

For UART, remember start/stop bits are included, so the captured edge pattern may include frame boundaries.

## MCP workflow target

```text
connect
  -> identify
  -> configure_uart_capture(channel=1, baudrate=2000000, logic_level="3.3V TTL")
  -> single_capture
  -> screenshot
  -> get_waveform(channel=1)
  -> analyze_uart_csv_file
```

## Safety notes

Do not enable arbitrary SCPI writes for this recipe. Use a preset tool so the AI only changes temporary channel/timebase/trigger parameters.
