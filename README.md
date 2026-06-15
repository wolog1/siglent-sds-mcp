# siglent-sds-mcp

MCP server for controlling a SIGLENT SDS824X HD oscilloscope via SCPI.

This repository is being built with a **knowledge-first adaptation workflow**:

1. collect SDS824X HD / SDS800X HD official documents;
2. build a command compatibility matrix;
3. compare against the upstream open-source SIGLENT SDS MCP implementation;
4. verify commands against the SDS800X HD Programming Guide and real SDS824X HD hardware;
5. expose only verified, safe high-level MCP tools to AI clients.

The first engineering goal is to let an AI tool safely configure the oscilloscope, capture a 2 Mbps UART/RS485 waveform, fetch a screenshot and waveform samples, then return a quantitative signal-quality summary.

## Target device

- SIGLENT SDS824X HD / SDS800X HD family
- Remote control through SCPI
- Preferred field transport: LAN raw TCP socket, typically port 5025 after verification
- Optional fallback: USBTMC / VISA / PyVISA where needed
- Typical field use: UART, RS485, Modbus, SPI/I2C bring-up and waveform evidence collection

## Reference project

This project intentionally references:

- `MagnusJohansson/siglent-sds-mcp`

The upstream project is valuable because it already implements a SIGLENT SDS MCP server with raw TCP transport, query queue, binary block parsing, screenshot conversion and waveform reconstruction.

Important boundary:

- upstream target/tested model: SDS1104X-E class;
- this project target: SDS824X HD / SDS800X HD family;
- therefore, upstream commands are treated as candidates, not final truth.

See:

- [`docs/upstream-reference.md`](docs/upstream-reference.md)
- [`docs/sds824x-hd-knowledge-base.md`](docs/sds824x-hd-knowledge-base.md)
- [`docs/sds824x-hd-command-matrix.md`](docs/sds824x-hd-command-matrix.md)

## Architecture

```text
AI / MCP Client
   |
   v
MCP Server: siglent-sds-mcp
   |
   v
Scope Service Layer
   |
   +-- Raw TCP 5025 Transport      preferred for LAN field use
   |
   +-- PyVISA / USBTMC Transport   optional fallback
   |
   v
SDS800X HD Command Adapter
   |
   v
SIGLENT SDS824X HD oscilloscope
```

## MVP tool set

| Tool | Purpose |
|---|---|
| `connect` | Connect to oscilloscope over LAN socket or VISA resource. |
| `identify` | Query `*IDN?` and confirm instrument model/firmware. |
| `configure_uart_capture` | Configure channel, timebase and edge trigger for UART capture. |
| `single_capture` | Run single acquisition. |
| `screenshot` | Capture scope screen after SDS824X HD command verification. |
| `get_waveform` | Export waveform samples after SDS824X HD command verification. |
| `analyze_uart_csv_file` | Analyze UART bit width, voltage level and rough signal quality from CSV. |

## Safety model

This project intentionally exposes high-level tools first. Raw SCPI write access is disabled by default because an AI client could otherwise reset the instrument, overwrite settings, or change network configuration.

Default allowed operations:

- identity query
- run/stop/single acquisition
- temporary channel/timebase/trigger setup
- measurement query
- screenshot/waveform fetch
- offline waveform analysis

Default blocked operations:

- `*RST`
- factory reset
- firmware update
- network configuration changes
- file deletion/formatting
- arbitrary SCPI writes without explicit development mode

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run tests:

```bash
pytest -q
```

Run the MCP server over stdio:

```bash
python -m siglent_sds_mcp.server
```

## First field scenario: 2 Mbps UART

For 2 Mbps UART:

- 1 bit = 500 ns
- 8N1 byte frame = 10 bits = about 5 us
- recommended timebase: about 1 us/div
- recommended sample rate: at least hundreds of MS/s for waveform analysis
- TTL trigger level: about 1.5 V for 3.3 V UART, 2.5 V for 5 V UART

The initial UART tool should produce:

```text
screenshot.png
waveform.csv
analysis.json
```

with a summary such as voltage level, estimated bit width, bit timing error, edge count and obvious signal-quality warnings.

## Repository layout

```text
src/siglent_sds_mcp/
  server.py          MCP tools
  scope_driver.py    SCPI driver scaffold
  transport.py       PyVISA transport wrapper, to be extended with raw TCP
  uart_analyzer.py   Offline UART CSV analyzer

docs/
  upstream-reference.md
  sds824x-hd-knowledge-base.md
  sds824x-hd-command-matrix.md

examples/
  idn_test.py
  capture_uart_2mbps.py

tests/
  test_scope_driver_mock.py
  test_uart_analyzer.py
```

## Project status

Early scaffold.

Important: waveform and screenshot commands must be verified against the SDS800X HD Programming Guide and the actual SDS824X HD firmware revision before production use. The current waveform export method intentionally remains conservative until real command behavior is verified.
