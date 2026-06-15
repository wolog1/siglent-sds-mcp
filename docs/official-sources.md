# Official SDS800X HD source manifest

This file tracks official SIGLENT sources for SDS824X HD / SDS800X HD adaptation.

## Verified official pages

| Page | URL | Purpose |
|---|---|---|
| SDS800X HD product page | `https://siglentna.com/digital-oscilloscopes/sds800x-hd-digital-storage-oscilloscope/` | Product capabilities, model table, interface support |
| Digital Oscilloscopes Document Downloads | `https://siglentna.com/resources/documents/digital-oscilloscopes/` | Official document download list |
| SDS800X HD Series Programming Guide page | `https://www.siglent.com/na/sds800x-hd-series-programming-guide/` | Programming guide publication page |

## Product facts from official product page

Facts to keep synchronized with README and command planning:

- SDS800X HD models include 70 MHz, 100 MHz and 200 MHz bandwidth variants.
- SDS824X HD is listed as a 200 MHz, 4-channel model.
- SDS824X HD is listed with 2 GSa/s real-time sampling rate.
- SDS824X HD is listed with 100 Mpts/ch memory depth.
- SDS800X HD uses 12-bit ADCs.
- The product page lists USB Device (USBTMC), LAN (VXI-11/Telnet/Socket), Pass/Fail and Trigger Out interfaces.
- The product page says the built-in web server supports remote control over LAN and SCPI remote control commands.
- Serial trigger/decode support includes I2C, SPI, UART, CAN and LIN.

## Official document list entries

The official document download page lists the following SDS800X HD documents:

| Document entry | Project use | Cache status |
|---|---|---|
| `SDS800X HD_Datasheet` | model limits, interfaces, sampling/memory details | not cached |
| `SDS800X HD_Quick Start` | network setup, front-panel setup reference | not cached |
| `SDS800XHD_Series_ProgrammingGuide` | authoritative SCPI command source | not cached |
| `SDS800X HD_ServiceManual` | maintenance reference; not needed for normal MCP runtime | not cached |
| `How to Extract Data from the Binary File` | binary waveform/file interpretation | not cached |
| `SDS1000X HD&SDS3000X HD&SDS800X HD_Open Source Acknowledgment` | licensing/OSS notice reference | not cached |
| `SDS800X HD_UserManual` | UI behavior and feature semantics | not cached |

## Local cache policy

Official PDFs should not be blindly committed until license and size are checked.

Recommended local-only cache path:

```text
.local-docs/siglent/sds800x-hd/
```

Recommended file names:

```text
.local-docs/siglent/sds800x-hd/SDS800XHD_Series_ProgrammingGuide.pdf
.local-docs/siglent/sds800x-hd/SDS800X_HD_UserManual.pdf
.local-docs/siglent/sds800x-hd/SDS800X_HD_Datasheet.pdf
.local-docs/siglent/sds800x-hd/How_to_Extract_Data_from_the_Binary_File.pdf
```

`.local-docs/` should remain ignored by git.

## Extraction priority

Extract these command groups first from the programming guide:

1. `*IDN?`, common commands and response/header mode
2. TCP/LAN/remote-control notes
3. channel display, scale, offset, coupling, probe ratio
4. timebase scale, delay and sample-rate query
5. edge trigger source, slope and level
6. run/stop/single acquisition
7. basic measurements: Vpp, frequency, period, rise time, duty cycle
8. screenshot command and response format
9. waveform setup/query command and binary format
10. binary file extraction notes

## Rule

The upstream `MagnusJohansson/siglent-sds-mcp` project is a reference implementation. Any command found there must be treated as `candidate` until it is confirmed in SDS800X HD official documents or real SDS824X HD hardware.
