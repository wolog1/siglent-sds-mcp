# SDS824X HD verification workflow

## Purpose

This workflow prevents unsafe or wrong SCPI commands from being exposed to AI tools.

The upstream project provides useful command candidates, but SDS824X HD / SDS800X HD must be verified from official documents and real hardware.

## Verification stages

```text
candidate
  -> official-doc
  -> hardware-tested
  -> driver-implemented
  -> safe-mcp-tool
```

## Stage 1: candidate command collection

Sources:

- upstream `MagnusJohansson/siglent-sds-mcp`
- SIGLENT examples
- SDS family examples
- manual front-panel behavior

Output:

- `docs/sds824x-hd-command-matrix.md`

## Stage 2: official document confirmation

Primary source:

- SDS800XHD_Series_ProgrammingGuide

Secondary source:

- SDS800X HD_UserManual
- How to Extract Data from the Binary File

For each command, record:

```text
Command:
Command group:
Official section/page:
Syntax:
Query/write:
Response format:
Risk level:
Notes:
```

## Stage 3: hardware probing

Use:

```bash
python scripts/scpi_probe.py <scope-ip> --port 5025
```

Example with custom commands:

```bash
python scripts/scpi_probe.py 192.168.1.100 \
  --command '*IDN?' \
  --command 'C1:VDIV?' \
  --command 'C1:OFST?' \
  --command 'TDIV?' \
  --command 'SARA?'
```

Output:

```text
artifacts/verification/scpi_probe.csv
```

## Stage 4: implementation

Only implement commands that are either:

- confirmed in the SDS800X HD Programming Guide, or
- tested on real SDS824X HD hardware.

## Stage 5: MCP exposure

Default safe tool exposure requires:

- no permanent network setting changes
- no factory reset
- no file deletion
- no firmware/service operation
- user-purpose constrained operation, such as UART capture setup
- predictable output artifacts

## Risk levels

| Risk | Meaning | Default MCP exposure |
|---|---|---|
| read-only | Query only, no scope state change | allowed |
| temporary-setup | Changes channel/timebase/trigger/acquisition state | allowed only through high-level recipe tools |
| artifact-read | Reads screenshot/waveform data | allowed after command format verified |
| unsafe | reset, delete, network config, firmware, service | blocked |

## First hardware checklist

```text
[ ] scope has LAN IP address
[ ] computer can ping scope
[ ] TCP 5025 open or alternative remote interface found
[ ] *IDN? returns model/serial/firmware
[ ] header mode checked
[ ] basic scalar queries checked
[ ] screenshot binary response checked
[ ] waveform binary response checked
```
