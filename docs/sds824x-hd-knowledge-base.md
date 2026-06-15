# SDS824X HD / SDS800X HD knowledge base

This document is the source index and engineering knowledge base plan for adapting this MCP server to the SIGLENT SDS824X HD oscilloscope.

## Scope

Target model:

- SIGLENT SDS824X HD
- SDS800X HD family compatibility target

Primary engineering use cases:

- AI-assisted oscilloscope control through MCP
- SCPI remote control over LAN/TCP socket and optional VISA paths
- 2 Mbps UART waveform capture
- RS485 differential waveform capture
- Modbus/serial communication bring-up evidence collection
- Screenshot + waveform CSV + JSON summary artifact export

## Source priority

```text
P0: Official SDS800X HD Programming Guide
P1: Official SDS800X HD User Manual
P2: Official SDS800X HD Datasheet
P3: Official Quick Start / Service Manual / Binary File extraction notes
P4: Actual SDS824X HD firmware behavior verified by test scripts
P5: Upstream open-source MCP project for SIGLENT SDS scopes
P6: Community notes / blogs / issue discussions
```

The driver must not promote a command from P5/P6 to production unless it is verified by P0/P4.

## Official source index

| Source | Purpose | Status |
|---|---|---|
| SDS800X HD product page | Model features, interface capabilities, serial decode support | Found |
| SDS800X HD Datasheet | Bandwidth, channel count, sampling rate, memory depth, interfaces | Found in official document list |
| SDS800X HD Quick Start | Front-panel/network setup reference | Found in official document list |
| SDS800XHD Series ProgrammingGuide | SCPI command authority for this project | Found in official document list |
| SDS800X HD ServiceManual | Low-level maintenance reference; not required for normal MCP | Found in official document list |
| How to Extract Data from the Binary File | Binary waveform/file extraction reference | Found in official document list |
| SDS800X HD UserManual | Feature behavior and UI-to-SCPI mapping reference | Found in official document list |
| SDS1000X HD & SDS3000X HD & SDS800X HD Open Source Acknowledgment | Licensing/OSS notice reference | Found in official document list |

## Official product facts to encode

Initial facts to keep in the project README and compatibility matrix:

- SDS800X HD family includes 70 MHz, 100 MHz, and 200 MHz models.
- SDS824X HD is the 200 MHz / 4-channel model.
- The family uses 12-bit ADCs.
- Real-time sampling rate is up to 2 GSa/s.
- SDS824X HD has up to 100 Mpts/ch memory depth.
- The family supports LAN remote web control and SCPI remote control.
- Interfaces include USB Host, USB Device/USBTMC, LAN with VXI-11/Telnet/Socket, Pass/Fail and Trigger Out.
- Serial trigger/decode support includes I2C, SPI, UART, CAN and LIN.

## Upstream open-source reference

Reference repository:

- `MagnusJohansson/siglent-sds-mcp`

Useful ideas:

- raw TCP connection to port 5025
- command/query queue
- newline-terminated SCPI text responses
- IEEE 488.2 definite-length binary block parsing
- raw BMP screenshot parsing and PNG conversion
- waveform voltage/time reconstruction
- MCP tool grouping: connection, channel, acquisition, measurement, waveform, SCPI

Compatibility caveat:

- The upstream project is tested on SDS1104X-E and refers to SDS1000X-E commands.
- SDS824X HD / SDS800X HD commands must be verified using the official SDS800X HD Programming Guide and actual hardware.

## Knowledge base structure to build

```text
docs/
  sds824x-hd-knowledge-base.md       <- source index and plan
  sds824x-hd-command-matrix.md       <- command compatibility and verification status
  upstream-reference.md              <- open-source reference analysis
  capture-recipes/
    uart-2mbps.md                    <- UART capture setup and analysis recipe
    rs485-differential.md            <- RS485 A/B differential capture recipe
    screenshot.md                    <- screenshot command and format notes
    waveform-export.md               <- waveform binary block and voltage conversion notes
```

## Command verification workflow

Every command must pass through this state machine:

```text
candidate
  -> documented_in_sds800xhd_programming_guide
  -> tested_on_sds824xhd
  -> implemented_in_driver
  -> exposed_as_safe_mcp_tool
```

A command may remain as `candidate` or `documented` but must not be exposed as a default MCP tool until it is tested on actual hardware.

## Minimum verified command set

The first milestone should verify only the minimum command set needed for safe field use:

| Function | Candidate command family | Verification required |
|---|---|---|
| Identify instrument | `*IDN?` | Query response format |
| Header control | `CHDR OFF` or equivalent | Whether SDS800X HD supports it |
| Run/stop/single | `RUN`, `STOP`, `SINGLE` or colon-prefixed variants | Exact spelling and behavior |
| Channel display | `C1:TRACE ON` / `:CHANnel1:DISPlay ON` candidates | Exact SDS800X HD command |
| Vertical scale | `C1:VDIV` / `:CHANnel1:SCALe` candidates | Exact SDS800X HD command |
| Offset | `C1:OFST` / `:CHANnel1:OFFSet` candidates | Exact SDS800X HD command |
| Timebase | `TDIV` / `:TIMebase:SCALe` candidates | Exact SDS800X HD command |
| Trigger | `TRSE`, `TRLV`, or modern `:TRIGger` tree candidates | Exact SDS800X HD command |
| Measurement | Vpp, frequency, period queries | Exact measurement command names |
| Screenshot | `SCDP` or documented equivalent | Image format and block framing |
| Waveform setup | `WFSU ...` or documented equivalent | Parameters and response |
| Waveform query | `C1:WF? DAT2` or documented equivalent | Binary format and voltage formula |

## Engineering rule

The MCP should expose business-safe high-level tools first:

- `connect`
- `identify`
- `configure_uart_capture`
- `single_capture`
- `screenshot`
- `get_waveform`
- `analyze_uart_waveform`

Raw SCPI should remain development-only with explicit unsafe mode.
