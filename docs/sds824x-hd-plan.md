# SDS824X HD implementation plan

## Phase 0: local connectivity

- [ ] Confirm LAN IP and VISA resource string.
- [ ] Confirm `*IDN?` response.
- [ ] Record firmware version.
- [ ] Confirm whether instrument is reachable from Windows, WSL, or Linux host.

## Phase 1: safe control MVP

- [x] Project scaffold.
- [x] MCP server scaffold.
- [x] PyVISA transport wrapper.
- [x] `scope_idn` tool.
- [x] run/stop/single tools.
- [x] UART capture setup tool.
- [x] basic measurement query scaffold.

## Phase 2: artifact capture

- [ ] Screenshot export.
- [ ] Waveform binary block export.
- [ ] CSV conversion.
- [ ] Artifact path handling for MCP clients.

## Phase 3: UART analysis

- [x] First-pass CSV analyzer.
- [ ] Decode 8N1 frame from waveform.
- [ ] Estimate baudrate automatically.
- [ ] Detect idle polarity.
- [ ] Detect voltage level class: 3.3 V TTL / 5 V TTL / RS485 differential.
- [ ] Detect overshoot/ringing roughly.

## Phase 4: RS485 workflow

- [ ] Two-channel A/B capture.
- [ ] Math `A-B` processing in Python.
- [ ] Differential threshold check.
- [ ] Optional Modbus RTU frame extraction.

## Phase 5: field report workflow

- [ ] Generate waveform evidence summary.
- [ ] Save screenshot + CSV + JSON analysis.
- [ ] Produce a Markdown test report snippet.

## Acceptance criteria for first usable version

A user can say:

> Capture CH1 2 Mbps UART on the SDS824X HD and tell me whether the bit width and voltage level are normal.

The MCP server should:

1. connect to scope;
2. query identity;
3. configure channel/timebase/trigger;
4. run single capture;
5. save screenshot;
6. save waveform CSV;
7. analyze bit timing and voltage;
8. return a JSON summary plus artifact paths.
