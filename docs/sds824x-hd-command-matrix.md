# SDS824X HD command compatibility matrix

This matrix tracks SCPI commands before they are exposed to AI/MCP tools.

Status values:

- `candidate`: seen in upstream project or other SDS family examples
- `official-doc`: confirmed in SDS800X HD Programming Guide
- `tested`: tested on real SDS824X HD hardware
- `implemented`: implemented in this repository
- `safe-tool`: exposed as default MCP tool
- `blocked`: intentionally blocked or unsafe

## Connection and identity

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Identify instrument | `*IDN?` | SCPI common command | candidate | First hardware test command. |
| Header off | `CHDR OFF` | Upstream project | candidate | Verify SDS800X HD support. Useful for clean numeric responses. |
| TCP socket port | `5025` | Upstream project / SIGLENT LAN socket convention | candidate | Verify from SDS824X HD network service. |

## Acquisition

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Run | `RUN` or `:RUN` | Upstream / generic SDS | candidate | Verify exact spelling. |
| Stop | `STOP` or `:STOP` | Upstream / generic SDS | candidate | Verify exact spelling. |
| Single | `SINGLE` or `:SINGLE` | Upstream / generic SDS | candidate | Verify exact spelling. |
| Force trigger | `TRIG FORCE` / `:TRIGger:FORCe` | Generic SCPI candidate | candidate | Verify before implementing. |

## Channel setup

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Channel trace/display | `C1:TRACE ON` or `:CHANnel1:DISPlay ON` | Upstream / generic SCPI | candidate | SDS families differ. Must verify. |
| Vertical division | `C1:VDIV 1V` or `:CHANnel1:SCALe 1` | Upstream / generic SCPI | candidate | The upstream waveform code queries `C1:VDIV?`. |
| Vertical offset | `C1:OFST 0` or `:CHANnel1:OFFSet 0` | Upstream / generic SCPI | candidate | The upstream waveform code queries `C1:OFST?`. |
| Coupling | `C1:CPL D1M` or `:CHANnel1:COUPling DC` | Candidate | candidate | Must map actual SDS800X HD tokens. |
| Bandwidth limit | TBD | SDS800X HD guide required | candidate | Needed for optional noise limiting. |
| Probe ratio | TBD | SDS800X HD guide required | candidate | Avoid writing until verified. |

## Timebase and trigger

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Time division query | `TDIV?` | Upstream project | candidate | Used by upstream for waveform reconstruction. |
| Time division set | `TDIV 1E-6` or `:TIMebase:SCALe 1e-6` | Candidate | candidate | Verify syntax. |
| Sample rate query | `SARA?` | Upstream project | candidate | Used by upstream for time axis reconstruction. |
| Edge trigger source | TBD | SDS800X HD guide required | candidate | Needed for UART capture. |
| Edge trigger slope | TBD | SDS800X HD guide required | candidate | Need POS/NEG mapping. |
| Edge trigger level | TBD | SDS800X HD guide required | candidate | Needed for TTL/RS485. |

## Measurement

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Frequency | measurement query TBD | SDS800X HD guide required | candidate | Verify exact command. |
| Vpp | measurement query TBD | SDS800X HD guide required | candidate | Verify exact command. |
| Period | measurement query TBD | SDS800X HD guide required | candidate | Verify exact command. |
| Rise time | measurement query TBD | SDS800X HD guide required | candidate | Useful for edge quality. |
| Duty cycle | measurement query TBD | SDS800X HD guide required | candidate | Useful for clock/PWM. |

## Screenshot and waveform

| Capability | Candidate command | Source | Status | Notes |
|---|---|---|---|---|
| Screenshot | `SCDP` | Upstream project | candidate | Upstream receives BMP, converts to PNG. Verify SDS824X HD. |
| Waveform setup | `WFSU SP,0,NP,0,FP,0` | Upstream project | candidate | Verify SDS800X HD support and parameter meaning. |
| Waveform query | `C1:WF? DAT2` | Upstream project | candidate | Verify binary block format and voltage conversion. |
| Binary block parser | IEEE 488.2 `#<n><len><data>` | Upstream project | candidate | Reusable design; implement in transport. |
| Raw BMP parser | BMP magic `BM` | Upstream project | candidate | Needed if screenshot returns BMP not PNG. |

## Unsafe commands

| Capability | Command family | Status | Notes |
|---|---|---|---|
| Factory reset | `*RST`, factory reset commands | blocked | Do not expose by default. |
| Network config changes | LAN/IP config commands | blocked | Avoid breaking remote access. |
| Firmware update | firmware/service commands | blocked | Not an MCP runtime tool. |
| File deletion | `MMEM:DEL*` style commands | blocked | Development-only if ever needed. |

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
