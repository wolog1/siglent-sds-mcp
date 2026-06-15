# siglent-sds-mcp

MCP server for controlling a SIGLENT SDS824X HD oscilloscope via SCPI over raw TCP.

**Project status**: SDS824X HD hardware-tested alpha. Core auto-find-waveform pipeline is functional on real hardware.

## Quick start

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Test
pytest -q

# Run MCP server (stdio, for AI client config)
python -m siglent_sds_mcp.server

# Quick connectivity probe
python examples/tcp_idn_test.py <scope-ip>
```

## Auto-find waveform — one-command capture

The headline feature: point at an unknown signal and get a screenshot + waveform CSV with automatic vertical/horizontal/trigger setup.

```bash
python examples/auto_find_waveform_tcp.py <scope-ip> --channels C1 C2 C3 C4

# With signal-type hint for better timebase selection
python examples/auto_find_waveform_tcp.py <scope-ip> --signal-hint uart

# Tune capture parameters
python examples/auto_find_waveform_tcp.py <scope-ip> \
    --channels C1 C2 \
    --coarse-timebase 1MS \
    --initial-vdiv 1V \
    --max-points 5000 \
    --noise-floor 0.05
```

Output: `found`, `selected_channel`, `recommended_vdiv/offset/timebase`, `screenshot_path`, `final_waveform_csv`, `coarse_stats` vs `final_stats`, JSON report.

## Architecture

```
MCP client (AI)
  │ MCP tool calls (stdio)
  ▼
server.py — FastMCP tools, auto-reconnect
  │
  ▼
sds_tcp_adapter.py — SDS800X HD command adapter
  │  channel / acquisition / trigger / measure / screenshot /
  │  waveform capture (WAVEDESC adaptive decode + envelope decimation)
  ▼
tcp_transport.py — RawTcpTransport
  │  socket-level SCPI, IEEE 488.2 binary block parser,
  │  thread-safe (RLock), pre-query socket flush
  ▼
auto_setup.py — auto_find_waveform
  │  channel scan → Vpp/edge scoring → VDIV/OFST/TDIV selection →
  │  screenshot + CSV from same STOP frame → final stats validation
  ▼
waveform_stats.py — edge detection, Vpp, threshold, clipping hint

SIGLENT SDS824X HD oscilloscope (LAN port 5025)
```

## Command verification pipeline

```
candidate → official-doc → tested → implemented → safe-tool
```

Tracked in `docs/sds824x-hd-command-matrix.md`. Do NOT expose an untested command as a default MCP tool.

## Key design decisions

### WAVEDESC adaptive decode

`WF? DAT2` returns 8-bit signed bytes. Voltage decode queries `WF? DESC` first for the WAVEDESC descriptor (little-endian struct with VERTICAL_GAIN, VERTICAL_OFFSET, HORIZ_INTERVAL, HORIZ_OFFSET at known offsets). Cross-validates WAVEDESC gain against `VDIV?` — falls back to `VDIV?/OFST?` if mismatch > 5%.

### Min/max envelope decimation

When `max_points` < raw sample count, each bucket outputs min + max voltages (with correct timestamps) instead of naive stride-sampling. Preserves glitches/spikes stride would miss.

### ARM/STOP behaviour (SDS824X HD verified)

- `STOP` alone: waveform memory readable, but may contain data from previous VDIV settings
- `ARM` then `STOP`: ARM resets acquisition to "armed, waiting" state — may not trigger in AUTO mode
- **Correct**: `TRMD AUTO` + wait ≥200ms + `STOP` — ensures waveform reflects current panel settings

### Screenshot/CSV same-frame guarantee

`auto_find_waveform` final capture: `STOP → screenshot → get_waveform(restore_trmd=False) → analyze final stats → ARM`. Screenshot and CSV are always from the same acquisition frame.

## Project structure

```
src/siglent_sds_mcp/
  server.py              — 16+ MCP tools, auto-reconnect, FastMCP
  sds_tcp_adapter.py     — Command adapter, WAVEDESC decode, envelope, capture
  tcp_transport.py       — Raw TCP socket, lock, binary block parser
  auto_setup.py          — auto_find_waveform: scan → score → configure → capture
  waveform_stats.py      — Edge detection, Vpp, threshold, clipping hint
  uart_analyzer.py       — Offline UART CSV analyzer
  rs485_analyzer.py      — RS485 differential pair analyzer
  modbus_timing.py       — Modbus RTU timing calculator
  report.py              — Markdown field report generator
  artifacts.py           — Timestamped artifact paths, JSON writer
  transport.py           — PyVISA fallback (legacy, not wired into MCP)
  scope_driver.py        — SiglentSDSDriver with safety gate (legacy)

docs/
  architecture.md                  — Layered design, UART capture reference
  sds824x-hd-command-matrix.md     — Per-command verification status
  sds824x-hd-knowledge-base.md     — Instrument-specific knowledge
  verification-workflow.md         — Hardware verification procedure

tests/   — pytest, socketpair transport tests, mock scope, CSV analysis
examples/ — auto_find_waveform_tcp, TCP IDN probe, waveform/RS485 capture
```

## Safety model

| Allowed | Blocked |
|---------|---------|
| `*IDN?`, run/stop/single | `*RST`, factory reset |
| Channel/timebase/trigger setup | Firmware update |
| Measurement query | Network config changes |
| Screenshot/waveform fetch | File deletion/formatting |
| Offline waveform analysis | Arbitrary SCPI writes |

Raw SCPI writes are NOT exposed as MCP tools. `safe_scpi_query_tcp` only accepts `?`-suffixed commands.

## Test coverage

```bash
pytest -q          # 61 tests
```

Key test areas:
- `test_unit_parsing.py` — 24 tests: `_parse_voltage`, `_parse_time`, `_parse_sample_rate` (mV≠MV, MS=milliseconds)
- `test_wavedesc.py` / `test_wavedesc_parser.py` — synthetic WAVEDESC decode, ASCII prefix handling
- `test_tcp_binary_prefix.py` — `query_binary` IEEE 488.2 / BMP prefix skipping
- `test_auto_setup_mock.py` — mock scope channel selection, NEG slope, coarse/final stats
- `test_waveform_stats.py` — edge detection, active/inactive classification
- `test_tcp_transport_parser.py` — socketpair binary block parsing

## Target device

- **SIGLENT SDS824X HD** / SDS800X HD family
- SCPI over raw TCP, port 5025
- Firmware verified: 4.8.12.1.1.6.5

## Reference

- `MagnusJohansson/siglent-sds-mcp` — upstream SIGLENT SDS MCP reference (SDS1104X-E class)
- [`docs/upstream-reference.md`](docs/upstream-reference.md)
