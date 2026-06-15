# Project roadmap

## Phase 0: Repository scaffold

Status: in progress

- [x] README
- [x] Python package scaffold
- [x] MCP server scaffold
- [x] PyVISA driver scaffold
- [x] raw TCP transport scaffold
- [x] UART CSV analyzer scaffold
- [x] upstream reference analysis

## Phase 1: Knowledge base and command matrix

Status: in progress

- [x] official source manifest
- [x] SDS824X HD knowledge-base plan
- [x] command matrix template
- [x] verification workflow
- [ ] locally cache official PDFs
- [ ] extract Programming Guide command sections
- [ ] map upstream commands to SDS800X HD equivalents
- [ ] classify commands by risk level

## Phase 2: Real instrument connectivity

Status: pending hardware access

- [ ] ping scope IP
- [ ] verify TCP 5025 socket
- [ ] run `examples/tcp_idn_test.py`
- [ ] run `scripts/scpi_probe.py`
- [ ] verify fallback path: PyVISA/USBTMC/VXI-11 if needed

## Phase 3: Safe core MCP tools

Status: pending command verification

- [ ] `connect_tcp`
- [ ] `disconnect_tcp`
- [ ] `identify_tcp`
- [ ] `get_channel`
- [ ] `configure_channel`
- [ ] `configure_acquisition`
- [ ] `measure`

## Phase 4: Screenshot and waveform artifacts

Status: pending command verification

- [ ] screenshot command verified
- [ ] BMP/PNG conversion implemented
- [ ] waveform setup command verified
- [ ] waveform query command verified
- [ ] binary block parser validated with real response
- [ ] waveform CSV/JSON metadata export

## Phase 5: Field recipes

Status: design started

- [x] 2 Mbps UART recipe
- [x] RS485 differential recipe
- [x] screenshot verification recipe
- [x] waveform export verification recipe
- [ ] `capture_uart_2mbps` end-to-end tool
- [ ] `capture_rs485_pair` end-to-end tool
- [ ] Modbus RTU timing recipe

## Phase 6: Engineering report output

Status: future

- [ ] screenshot artifact summary
- [ ] waveform analysis JSON summary
- [ ] Markdown report generator
- [ ] optional Word/PDF test report generation

## Preferred development sequence

```text
Official docs -> command matrix -> hardware probe -> core transport -> safe MCP tools -> UART/RS485 recipes -> report generation
```
