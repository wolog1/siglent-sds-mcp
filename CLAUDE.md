# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & dev commands

```bash
# Create venv and install editable + dev deps
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Run all tests
pytest -q

# Run a single test file
pytest tests/test_uart_analyzer.py -q

# Run a single test function
pytest tests/test_tcp_transport_parser.py::test_ieee4882_binary_block_parser_with_socketpair -q

# Lint
ruff check src tests examples scripts

# Type check
mypy src

# Run the MCP server (stdio transport, for MCP client config)
python -m siglent_sds_mcp.server

# Quick TCP connectivity probe (no MCP)
python examples/tcp_idn_test.py <scope-ip>
```

## Architecture

```
MCP client (AI)
  │ MCP tool calls (stdio)
  ▼
server.py — FastMCP tools, parameter validation, auto-reconnect glue
  │ Python API
  ▼
sds_tcp_adapter.py — SDS800X HD command adapter (channel/acquisition/trigger/measure/
  │                   screenshot/waveform/capture workflows)
  ▼
tcp_transport.py — RawTcpTransport: socket-level SCPI write/query/query_binary,
                    BinaryBlock parser (IEEE 488.2 + raw BMP), thread-safe with lock
  ▼
SIGLENT SDS824X HD oscilloscope (LAN port 5025)
```

**Legacy path** (PyVISA/USBTMC, scaffold only, not the main transport):
`transport.py` → `scope_driver.py` — kept for future fallback, not wired into MCP tools.

## Key design decisions

### WAVEDESC adaptive decoding (`sds_tcp_adapter.py:62-107`)

Waveform binary data (`WF? DAT2`) is 8-bit signed byte-encoded. Voltage decoding needs `codes_per_div` and `vertical_gain`. Instead of hardcoding device-specific constants, the adapter queries `WF? DESC` first to read the WAVEDESC binary descriptor (little-endian struct at known offsets). Key fields:

| Offset | Field | Type | Use |
|--------|-------|------|-----|
| 116 | WAVE_ARRAY_COUNT | int32 | sample count |
| 156 | VERTICAL_GAIN | float32 | V/div |
| 160 | VERTICAL_OFFSET | float32 | vertical offset V |
| 164 | MAX_VALUE | float32 | codes_per_div × 256 |
| 176 | HORIZ_INTERVAL | float32 | s/sample |
| 180 | HORIZ_OFFSET | float64 | trigger offset s (=TRDL) |

Formula: `codes_per_div = MAX_VALUE / 256; voltage = code × (VDIV / codes_per_div) - VERTICAL_OFFSET`

Falls back to `CODES_PER_DIV=30` (SDS824X HD measured) when WAVEDESC is unavailable.

### Min/max envelope decimation (`sds_tcp_adapter.py:372-393`)

When requested `max_points` < raw sample count, each bucket outputs its min and max voltage (with correct timestamps) instead of naive stride-sampling. This preserves glitches/spikes that stride would miss.

### Auto-reconnect (`server.py:313-341`)

`_require_tcp()` caches host/port/timeout from the last `connect_tcp` call. If the socket is dead (MCP process restart, scope reboot), it transparently reconnects and sends `CHDR OFF`. No explicit reconnect tool needed.

### BinaryBlock parsing (`tcp_transport.py:126-142`)

`query_binary()` skips ASCII prefixes (like `"C1:WF DAT2,"`) by scanning for either `BM` (raw BMP screenshot) or `#` (IEEE 488.2 block header). After reading the binary payload, it drains trailing newlines to prevent response pollution on the next query.

### Pre-query socket flush (`tcp_transport.py:103-124`)

Before every `query()` and `query_binary()`, the transport non-blocking drains the socket buffer. This prevents stale bytes from a previous binary response's trailing newline from corrupting the next ASCII query response.

## SCPI command verification pipeline

Commands progress through states before MCP exposure:

```
candidate → official-doc → tested → implemented → safe-tool
```

The command matrix is tracked in `docs/sds824x-hd-command-matrix.md`. All SDS800X HD commands live in `sds_tcp_adapter.py`. Do NOT promote a command to a default MCP tool without hardware verification.

## Safety model

**Blocked by default** (in `scope_driver.py` `DANGEROUS_SCPI_PREFIXES`):
- `*RST`, factory reset, firmware update, network config changes, file deletion

**Allowed by default**: identity query, run/stop/single, channel/timebase/trigger setup, measurement query, screenshot/waveform fetch, offline analysis.

Raw SCPI writes are NOT exposed as MCP tools. The `safe_scpi_query_tcp` tool only accepts commands ending in `?`.

## Project structure

```
src/siglent_sds_mcp/
  server.py          — 16 MCP tools, auto-reconnect, FastMCP entry point
  sds_tcp_adapter.py — SDS800X HD command adapter (WAVEDESC decode, envelope, capture workflows)
  tcp_transport.py   — RawTcpTransport (socket, lock, binary block parser, socket flush)
  uart_analyzer.py   — Offline UART CSV analyzer (edge detection, timing, verdict)
  rs485_analyzer.py  — RS485 differential pair analyzer (Vdiff, common-mode, edge detection)
  modbus_timing.py   — Modbus RTU character/silence timing calculator
  report.py          — Markdown field report generator from captured artifacts
  artifacts.py       — Timestamped artifact path helpers, JSON writer
  transport.py       — PyVISA/VisaTransport wrapper (legacy/fallback path)
  scope_driver.py    — SiglentSDSDriver with safety gate (legacy/fallback path)

docs/
  architecture.md                  — Layered design doc, UART capture reference values
  sds824x-hd-command-matrix.md     — Per-command verification status tracker
  sds824x-hd-knowledge-base.md     — Instrument-specific knowledge
  verification-workflow.md         — Hardware verification procedure
  upstream-reference.md            — Notes on MagnusJohansson/siglent-sds-mcp reference

tests/   — pytest, uses socketpair for transport tests, tmp_path for CSV analyzer tests
examples/ — Standalone scripts (TCP IDN probe, waveform capture, RS485 capture, report gen)
scripts/  — SCPI probe, UART decode helpers
```

## Coding conventions

- Python 3.10+, `from __future__ import annotations` in every file
- `dataclass(slots=True)` for data objects with `.to_dict()` for JSON serialization
- Thread-safe transport: `RawTcpTransport` uses `threading.RLock` for all socket I/O
- No broad except clauses — use `# noqa: BLE001` with a comment explaining why the broad catch is intentional
- Channel parameter uses `Literal["C1","C2","C3","C4"]` in MCP tool signatures for type safety
- Artifact paths auto-generated with UTC timestamps via `artifacts.default_artifact_paths(prefix)`
