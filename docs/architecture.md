# Architecture

## Goal

Build a safe MCP server that allows AI tools to operate a SIGLENT SDS824X HD oscilloscope for engineering bring-up and field diagnostics.

Primary target scenario:

```text
2 Mbps UART / RS485 waveform capture
    -> configure oscilloscope
    -> single trigger
    -> screenshot + waveform export
    -> quantitative analysis
    -> evidence for debugging/reporting
```

## Layered design

```text
┌───────────────────────────────────────┐
│ AI client / MCP host                   │
└───────────────────┬───────────────────┘
                    │ MCP tool call
                    ▼
┌───────────────────────────────────────┐
│ siglent_sds_mcp.server                 │
│ - FastMCP tool registration            │
│ - parameter validation                 │
│ - safe high-level operations           │
└───────────────────┬───────────────────┘
                    │ Python API
                    ▼
┌───────────────────────────────────────┐
│ SiglentSDSDriver                       │
│ - setup channel/timebase/trigger       │
│ - run/stop/single                      │
│ - measurement query                    │
│ - waveform/screenshot export           │
└───────────────────┬───────────────────┘
                    │ SCPI
                    ▼
┌───────────────────────────────────────┐
│ Transport                              │
│ - PyVISA                               │
│ - USBTMC / LAN / VXI-11                │
│ - socket fallback later                │
└───────────────────┬───────────────────┘
                    ▼
┌───────────────────────────────────────┐
│ SIGLENT SDS824X HD                     │
└───────────────────────────────────────┘
```

## Safety principle

The MCP server should expose scenario tools instead of raw instrument control.

Good tool:

```text
scope_setup_uart(resource, channel, baudrate, trigger_level_v)
```

Risky tool:

```text
scope_scpi_write(resource, arbitrary_command)
```

Raw SCPI write should only exist in a development build with a whitelist/denylist and explicit operator confirmation.

## Bring-up sequence

1. Confirm physical connection: LAN/USB.
2. Confirm VISA resource string.
3. Run `scope_idn`.
4. Configure a simple channel/timebase/trigger.
5. Run single trigger.
6. Query basic measurement values.
7. Implement screenshot export.
8. Implement waveform binary block export.
9. Validate UART analyzer against known 0x55 pattern.
10. Add RS485 differential workflow.

## UART 2 Mbps reference

```text
baudrate = 2,000,000 bit/s
bit time = 1 / baudrate = 500 ns
8N1 byte time = 10 bits = 5 us
```

Recommended initial capture setup:

| Item | Suggested value |
|---|---:|
| Timebase | 1 us/div |
| Vertical scale | 1 V/div for 3.3 V TTL |
| Trigger | CH1 falling edge |
| Trigger level | 1.5 V for 3.3 V TTL |
| Coupling | DC |
| Probe | 10X |

## Next architectural decisions

- Whether screenshot export is implemented through SCPI binary block or LXI screenshot endpoint.
- Whether waveform export uses normal mode, maximum memory mode, or screen memory only.
- How to represent returned binary artifacts to MCP clients.
- How to protect instrument state before and after AI-assisted operations.
