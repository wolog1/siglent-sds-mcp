# Upstream reference: MagnusJohansson/siglent-sds-mcp

Reference repository:

- `MagnusJohansson/siglent-sds-mcp`
- Public GitHub repository
- Main implementation language: TypeScript / Node.js
- Transport: raw TCP socket to SIGLENT oscilloscope port `5025`

## Why it matters

This project is very relevant because it already implements an MCP server for SIGLENT SDS oscilloscopes. It can be used as a practical reference for:

- MCP tool grouping
- SCPI command naming
- raw TCP transport
- query serialization
- IEEE 488.2 binary block parsing
- screenshot capture
- waveform reconstruction
- MCP client configuration examples

## Key implementation choices observed

### 1. Raw TCP instead of VISA

The reference implementation communicates with the oscilloscope over TCP port `5025`, so it does not require NI-VISA, USBTMC driver setup, or PyVISA.

This is attractive for field deployment because most engineers can configure LAN access more easily than VISA drivers.

### 2. Query queue

The reference implementation serializes SCPI queries through a queue. This is important because oscilloscopes usually process SCPI commands sequentially. Even if an AI client calls multiple tools in parallel, the transport layer should send one command at a time.

### 3. Binary block parsing

The reference implementation handles both:

- raw BMP data from screenshots
- IEEE 488.2 definite-length binary blocks for waveform data

This is a key design point we should reuse.

### 4. Screenshot handling

The reference implementation captures screen data and converts it to PNG for MCP image response. This is very useful for AI-assisted troubleshooting because the AI can see the oscilloscope screen directly.

### 5. Waveform reconstruction

The reference implementation converts raw ADC/sample bytes into voltage/time arrays by reading oscilloscope parameters such as vertical division, offset, time division, and sample rate.

This is required for real signal analysis. Screenshots alone are not enough for engineering diagnosis.

## Compatibility caveat

The reference repository says it was tested with SDS1104X-E and uses SDS1000X-E programming guide commands. Our target is SDS824X HD / SDS800X HD series.

Therefore, commands must be verified against the SDS800X HD Programming Guide and the actual SDS824X HD firmware.

Likely reusable:

- MCP tool structure
- TCP socket transport pattern
- query queue
- binary block parser
- screenshot image conversion concept
- waveform downsampling concept

Must verify on SDS824X HD:

- channel command names
- timebase command names
- trigger command names
- waveform setup command: `WFSU ...`
- waveform query command: `C1:WF? DAT2`
- screenshot command: `SCDP`
- voltage reconstruction formula
- sample-rate query response format

## Recommended decision for this repository

Instead of building a pure PyVISA-first implementation, use a hybrid architecture:

```text
MCP Tools
   |
   v
Scope Service
   |
   +-- Raw TCP 5025 transport     <- preferred for LAN field use
   |
   +-- PyVISA transport           <- optional fallback for USBTMC/LXI/VXI-11
   |
   v
SDS800X HD command adapter
```

## Differentiation for our project

This repository should focus on SDS824X HD engineering use cases:

1. SDS800X HD command verification table
2. 2 Mbps UART capture preset
3. RS485 differential measurement workflow
4. Modbus/serial bus troubleshooting notes
5. artifact export: screenshot + CSV + JSON summary
6. safety whitelist for AI-controlled SCPI operations
7. Chinese field-engineering documentation

## Immediate action items

- Add a raw TCP transport implementation.
- Keep PyVISA support as optional fallback, not the only path.
- Add a compatibility matrix for SDS824X HD verified commands.
- Port/adapt the query queue and binary block parser design.
- Implement `scope_screenshot` using SDS824X HD-verified screenshot SCPI.
- Implement `scope_fetch_waveform` only after validating waveform command and voltage conversion formula.
