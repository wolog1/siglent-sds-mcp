# SDS824X HD command compatibility matrix

This matrix tracks SCPI commands before they are exposed to AI/MCP tools.

Status values:

- `candidate`: seen in upstream project or other SDS family examples
- `official-doc`: confirmed in SDS800X HD Programming Guide
- `tested`: tested on real SDS824X HD hardware
- `implemented`: implemented in this repository
- `safe-tool`: exposed as default MCP tool
- `blocked`: intentionally blocked or unsafe
- `known-issue`: tested but behaviour is incomplete, firmware-dependent, or not yet understood

## Connection and identity

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Identify instrument | `*IDN?` | SCPI common command | tested / implemented / safe-tool | Verified on SDS824X HD firmware 4.8.12.1.1.6.5. |
| Header off | `CHDR OFF` | Upstream project | tested / implemented | Used after TCP connect/reconnect to reduce response header noise. |
| TCP socket port | `5025` | Upstream project / SIGLENT LAN socket convention | tested / implemented | Raw TCP socket path verified on SDS824X HD. |

## Acquisition

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Run | `ARM` | SDS/SIGLENT style candidate | tested / implemented | Used to restart acquisition after auto-find capture. |
| Stop | `STOP` | SDS/SIGLENT style candidate | tested / implemented | Required before reliable waveform memory read. |
| Auto trigger/acquisition mode | `TRMD AUTO` | SDS/SIGLENT style candidate | tested / implemented | Verified practical sequence: `TRMD AUTO` + wait + `STOP`. |
| Single | `TRMD SINGLE` | SDS/SIGLENT style candidate | implemented | Used by UART helper; final reliability still lower than AUTO+STOP path. |
| Force trigger | `TRIG FORCE` / `:TRIGger:FORCe` | Generic SCPI candidate | candidate | Verify before implementing. |

## Channel setup

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Channel trace/display | `C1:TRA ON` | Upstream / SDS style | implemented | Used by auto setup. Continue validating C2/C3/C4 behaviour. |
| Vertical division | `C1:VDIV 1V`, `C1:VDIV?` | Upstream / SDS style | tested / implemented | Used for setup and WAVEDESC cross-check. |
| Vertical offset | `C1:OFST 0V`, `C1:OFST?` | Upstream / SDS style | tested / implemented | `OFST=vmean` display-centering direction still marked needs_hardware_validation with a known 3.3V square wave. |
| Coupling | `C1:CPL D1M` | Candidate | implemented | Used by auto setup. Token mapping should be confirmed against official guide. |
| Bandwidth limit | `BWL C1,ON/OFF` | SDS style candidate | implemented | Verify firmware-specific behaviour before treating as stable. |
| Probe ratio | `C1:ATTN 10` | SDS style candidate | implemented | Used by auto setup. Verify exact accepted values. |

## Timebase and trigger

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Time division query | `TDIV?` | Upstream project | tested / implemented | Used for waveform wait estimate and fallback time axis. |
| Time division set | `TDIV 1MS`, `TDIV 1US` | SDS style candidate | tested / implemented | Auto-find uses this for display timebase. |
| Sample rate query | `SARA?` | Upstream project | tested / implemented | Used for fallback time axis. |
| Trigger mode | `TRMD AUTO`, `TRMD SINGLE` | SDS style candidate | tested / implemented | AUTO+wait+STOP is the current reliable waveform-read path. |
| Edge trigger source | source via `C1:TRLV` / `C1:TRSL` commands | SDS style candidate | implemented | Source-specific trigger setup needs more firmware validation. |
| Edge trigger slope | `C1:TRSL POS/NEG` | SDS style candidate | implemented | Auto-find uses NEG for UART/RS485/Modbus hints. |
| Edge trigger level | `C1:TRLV <level>` | SDS style candidate | known-issue | On firmware 4.8.12.1.1.6.5 this command was observed as possibly not taking effect. AUTO-mode waveform display still works, but stable trigger-level control needs follow-up. |

## Measurement

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Frequency | `C1:PAVA? FREQ` / `PACU FREQ,C1` | SDS style candidate | implemented | Verify exact return format and stability. |
| Vpp | `C1:PAVA? PKPK` / `PACU PKPK,C1` | SDS style candidate | implemented | Verify against known signal. |
| Period | `C1:PAVA? PER` / `PACU PER,C1` | SDS style candidate | implemented | Verify exact command spelling. |
| Rise time | `C1:PAVA? RISE` | SDS style candidate | implemented | Verify before relying on result. |
| Duty cycle | `C1:PAVA? DUTY` | SDS style candidate | implemented | Verify before relying on result. |

## Screenshot and waveform

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Screenshot | `SCDP` | Upstream project | tested / implemented / safe-tool | SDS824X HD returns BMP/raw image bytes through TCP path. |
| Waveform setup | `WFSU SP,1,NP,0,FP,0` | SDS824X HD hardware test | tested / implemented | `SP=0` was rejected/ineffective on SDS824X HD; `SP=1` is current working path. |
| Waveform query | `C1:WF? DAT2` | Upstream project / hardware test | tested / implemented / safe-tool | Returns 8-bit signed waveform bytes; read before DESC for reliability. |
| Waveform descriptor | `C1:WF? DESC` | Hardware test | tested / implemented | Parsed via WAVEDESC offsets and cross-checked against `VDIV?`. |
| Binary block parser | IEEE 488.2 `#<n><len><data>` | Upstream project / tests | implemented | Handles optional ASCII prefixes like `C1:WF DAT2,`. |
| Raw BMP parser | BMP magic `BM` | Upstream project / tests | implemented | Supports screenshot artifact storage; PNG conversion remains future work. |

## Unsafe commands

| Capability | Command family | Status | Notes |
|---|---|---|---|
| Factory reset | `*RST`, factory reset commands | blocked | Do not expose by default. |
| Network config changes | LAN/IP config commands | blocked | Avoid breaking remote access. |
| Firmware update | firmware/service commands | blocked | Not an MCP runtime tool. |
| File deletion | `MMEM:DEL*` style commands | blocked | Development-only if ever needed. |

## Current known issues

| Issue | Impact | Next action |
|---|---|---|
| `C?:TRLV <level>` may not take effect on SDS824X HD firmware 4.8.12.1.1.6.5 | Auto-find can still display waveforms in AUTO mode, but stable edge-trigger level control is not guaranteed. | Test alternative trigger commands from SDS800X HD Programming Guide and record actual query/response pairs. |
| `OFST=vmean` direction still needs square-wave validation | Auto-centering may be inverted if display offset semantics differ from decode offset semantics. | Validate with known 0–3.3V square wave and update `offset_direction_status`. |
| Slow timebase wait uses `max(tdiv*20, 0.2s)` | Very slow TDIV settings can increase capture latency. | Add bounded wait after slow-timebase field behaviour is confirmed. |

## Verification log template

```text
Date:
Instrument:
Firmware:
Connection:
Command:
Expected:
Actual response:
Pass/fail:
Notes:
```
