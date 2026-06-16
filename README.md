# siglent-sds-mcp

MCP server for controlling a SIGLENT SDS824X HD oscilloscope via SCPI over raw TCP.

**Project status**: SDS824X HD hardware-tested alpha. Core measurement-driven auto setup is functional on real hardware.

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

## Auto setup — one-command screen setup

The main feature: point at an unknown signal and let the scope measurement engine find usable VDIV / OFST / TDIV settings. The command also saves a screenshot artifact from the final setup path.

```bash
# Backwards-compatible CLI name; internally uses measurement-driven auto setup
python examples/auto_find_waveform_tcp.py <scope-ip> --channels C1 C2 C3 C4

# With signal-type hint for better trigger slope policy
python examples/auto_find_waveform_tcp.py <scope-ip> --signal-hint uart

# Direct TTL wiring / 1X probe
python examples/auto_find_waveform_tcp.py <scope-ip> \
    --channels C1 \
    --signal-hint clock \
    --probe 1

# Weak periodic signal policy
python examples/auto_find_waveform_tcp.py <scope-ip> \
    --channels C1 \
    --signal-hint clock \
    --noise-floor 0.05 \
    --min-signal-vpp 0.005

# Restart acquisition after capture only when explicitly requested
python examples/auto_find_waveform_tcp.py <scope-ip> --restart-after-capture
```

Default behavior: `leave_stopped=true`. The tool intentionally leaves the scope stopped on the final visible frame. The return object includes `screen_hold`, `final_panel_state`, `measurements`, `final_settings`, `probe_steps`, `screenshot`, and `compatibility_parameters`.

Compatibility note: `coarse_timebase`, `initial_vdiv`, `max_points`, and `refine_attempts` are accepted by the historical `auto_find_waveform` API so older MCP/CLI callers do not break. The current measurement-driven adapter path owns the actual scanning and refinement logic, so those compatibility fields are reported in JSON but are not directly used by the measurement path.

## Waveform capture modes

`get_waveform_tcp` defaults to `capture_mode="immediate"`.

```text
STOP -> WF? DAT2
```

This intentionally skips `WFSU`. SDS824X HD field debugging showed that sending `WFSU SP,1,NP,0,FP,0` after STOP can refresh/replace the stopped frame before `WF? DAT2`, which loses intermittent UART/RS485 bursts and often returns an IDLE frame instead.

For stable/repetitive signals only, callers may request the legacy configured path:

```text
STOP -> WFSU SP,1,NP,0,FP,0 -> WF? DAT2
```

Use it through MCP by setting:

```json
{
  "capture_mode": "configured"
}
```

The metadata records `capture.mode`, `capture.wfsu_sent`, `decode.dt_source`, `parsed.trdl_s`, `parsed.effective_start_s`, `parsed.effective_end_s`, and warnings when fallback timing is used.

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
  │  waveform capture (WAVEDESC adaptive decode + envelope decimation) /
  │  measurement-driven auto_setup
  ▼
waveform_capture.py — immediate/configured WF? DAT2 capture modes
  │  immediate mode preserves stopped frames by skipping WFSU
  ▼
tcp_transport.py — RawTcpTransport
  │  socket-level SCPI, IEEE 488.2 binary block parser,
  │  thread-safe (RLock), pre-query socket flush
  ▼
auto_setup.py — compatibility wrapper for historical auto_find_waveform API

SIGLENT SDS824X HD oscilloscope (LAN port 5025)
```

## Command verification pipeline

```
candidate → official-doc → tested → implemented → safe-tool
```

Tracked in `docs/sds824x-hd-command-matrix.md`. Do NOT expose an untested command as a default MCP tool.

## Key design decisions

### Measurement-driven auto setup

`SDS800XHDTcpAdapter.auto_setup()` uses scope measurements (`PKPK`, `MEAN`, `FREQ`, `PER`, `MAX`, `MIN`) to select display settings. This avoids relying on a separate offline CSV analyzer for first-pass screen setup.

### Weak periodic signal policy

`noise_floor_v` is treated as the strong-signal threshold. A lower-amplitude signal can still be accepted when the scope reports a valid `FREQ` or `PER` and `PKPK >= min_signal_vpp`. This handles real field observations such as a stable 7.89 kHz signal with only about 22.5 mV peak-to-peak.

### WAVEDESC adaptive decode

`WF? DAT2` returns 8-bit signed bytes. Voltage decode queries `WF? DESC` for the WAVEDESC descriptor and uses the descriptor-derived `codes_per_div` with current panel `VDIV? / OFST?` for decoding.

### Timebase and dt policy

DAT2 timing should use WAVEDESC `HORIZ_INTERVAL` whenever available. `SARA?` is recorded as metadata and only used as a fallback. Metadata warnings are emitted when `dt_source` falls back to SARA or TDIV because UART/protocol decoding can be wrong if the fallback does not match the DAT2 memory interval.

### Min/max envelope decimation

When `max_points` < raw sample count, each bucket outputs min + max voltages instead of naive stride-sampling. Preserves glitches/spikes stride would miss.

### ARM/STOP behaviour

`get_waveform_tcp` immediate mode freezes the current frame with STOP and reads DAT2 directly. This is the default for intermittent signals. The older WFSU path is available only through `capture_mode="configured"`.

### Trigger level policy

`C?:TRLV <level>` is a known issue on SDS824X HD firmware `4.8.12.1.1.6.5`. Display-oriented auto setup does not depend on this command by default. `set_trigger_level=true` must be requested explicitly.

## Project structure

```
src/siglent_sds_mcp/
  server.py              — MCP tools, auto-reconnect, FastMCP
  sds_tcp_adapter.py     — Command adapter, WAVEDESC decode, envelope, auto_setup
  waveform_capture.py    — WF? DAT2 capture modes, immediate skips WFSU
  tcp_transport.py       — Raw TCP socket, lock, binary block parser
  auto_setup.py          — Compatibility wrapper for auto_find_waveform API
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

tests/   — pytest, parser tests, TCP transport tests, auto setup helper tests
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
pytest -q
```

Key test areas:
- `test_unit_parsing.py` — `_parse_voltage`, `_parse_time`, `_parse_sample_rate`
- `test_wavedesc.py` / `test_wavedesc_parser.py` — synthetic WAVEDESC decode, ASCII prefix handling
- `test_tcp_binary_prefix.py` — `query_binary` IEEE 488.2 / BMP prefix skipping
- `test_auto_setup.py` — `_pick_vdiv`, `_pick_tdiv`, measurement parser and SCPI number formatting
- `test_auto_find_compat.py` — weak periodic detection, screen hold, screenshot artifact, compatibility parameters
- `test_waveform_capture_modes.py` — immediate mode skips WFSU; configured mode sends WFSU with warning
- `test_tcp_transport_parser.py` — socketpair binary block parsing

## Target device

- **SIGLENT SDS824X HD** / SDS800X HD family
- SCPI over raw TCP, port 5025
- Firmware verified: 4.8.12.1.1.6.5

## Reference

- `MagnusJohansson/siglent-sds-mcp` — upstream SIGLENT SDS MCP reference (SDS1104X-E class)
- [`docs/upstream-reference.md`](docs/upstream-reference.md)
