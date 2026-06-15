# Capture recipe: Modbus RTU over RS485

## Goal

Capture Modbus RTU physical waveform evidence over RS485 and correlate it with request/response timing.

This recipe is intended for field troubleshooting of:

- no response
- intermittent response
- CRC error
- frame truncation
- wrong baudrate/parity
- RS485 direction-control problems
- bus termination or grounding issues

## Recommended channels

| Channel | Signal | Purpose |
|---|---|---|
| CH1 | RS485 A | single-ended A trace |
| CH2 | RS485 B | single-ended B trace |
| Math/offline | CH1 - CH2 | differential voltage |
| CH3 optional | DE/RE direction control | gateway transmit/receive timing |
| CH4 optional | UART TTL TX/RX before transceiver | compare MCU-side and bus-side data |

## Timebase recommendations

For common Modbus RTU baudrates:

| Baudrate | Bit time | Starting timebase |
|---:|---:|---:|
| 9600 | 104.17 us | 1 ms/div to 5 ms/div |
| 19200 | 52.08 us | 500 us/div to 2 ms/div |
| 115200 | 8.68 us | 100 us/div to 500 us/div |
| 2 Mbps | 500 ns | 1 us/div to 5 us/div |

## Modbus RTU frame timing

A Modbus RTU frame is separated by silence. The standard framing rule is based on character time.

For 8N1, one character is 10 bits:

```text
Tchar = 10 / baudrate
3.5 char silence = 35 / baudrate
```

Examples:

```text
9600 baud:  Tchar ≈ 1.0417 ms, 3.5 chars ≈ 3.65 ms
115200 baud: Tchar ≈ 86.8 us, 3.5 chars ≈ 304 us
```

For parity formats such as 8E1, one character is usually 11 bits:

```text
Tchar = 11 / baudrate
3.5 char silence = 38.5 / baudrate
```

## MCP workflow target

```text
connect_tcp(host="<scope-ip>")
identify_tcp()
configure_channel_tcp(channel="C1", vdiv="1V", offset="0V", coupling="D1M", trace=true, probe=10)
configure_channel_tcp(channel="C2", vdiv="1V", offset="0V", coupling="D1M", trace=true, probe=10)
configure_acquisition_tcp(timebase="1MS", trigger_source="C1", trigger_level="2.5V", trigger_slope="NEG", command="single")
screenshot_tcp()
get_waveform_tcp(channel="C1")
get_waveform_tcp(channel="C2")
analyze_rs485_pair_csv_file(csv_a_path="<C1 csv>", csv_b_path="<C2 csv>", baudrate=9600)
```

## What to look for

### Healthy bus evidence

- A and B are complementary.
- Vdiff crosses clearly through zero.
- Differential voltage magnitude exceeds a typical ±200 mV receiver threshold.
- Request and response are separated by realistic turnaround delay.
- Bus returns to stable idle state after transmission.

### Common problem signatures

| Symptom | Likely cause |
|---|---|
| A/B not complementary | wiring/probe error or failed transceiver |
| very small Vdiff | termination/wiring issue, wrong probe point, bus not active |
| strong ringing | missing/incorrect termination, long stubs, grounding problem |
| request present but no response | slave address/baud/parity/wiring/device power issue |
| response starts but truncates | direction control, timeout, collision, firmware receive buffer issue |
| repeated CRC errors | baud/parity mismatch, noise, truncation, byte loss |

## Evidence package

Save:

```text
screen image artifact
CH1 A waveform CSV
CH2 B waveform CSV
RS485 analysis JSON
field notes: baudrate, parity, slave id, request frame, response frame
```

## Engineering note

The oscilloscope waveform confirms physical-layer behavior. It does not by itself prove Modbus frame correctness unless the captured waveform is decoded or correlated with serial logs.
