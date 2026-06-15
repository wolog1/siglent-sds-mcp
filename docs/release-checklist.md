# Open-source release checklist

## Repository metadata

- [x] License file exists.
- [x] Python package license metadata aligned with repository license.
- [x] NOTICE file added for upstream reference.
- [x] CONTRIBUTING guide added.
- [x] Dockerfile added.
- [x] CI workflow added.
- [ ] README refreshed after first successful hardware test.

## SDS824X HD validation

- [ ] Official Programming Guide command sections extracted.
- [ ] TCP 5025 confirmed.
- [ ] `*IDN?` confirmed.
- [ ] Channel query commands confirmed.
- [ ] Channel setup commands confirmed.
- [ ] Acquisition/timebase/trigger commands confirmed.
- [ ] Measurement commands confirmed.
- [ ] Screen image command confirmed.
- [ ] Waveform export commands confirmed.
- [ ] Voltage reconstruction formula confirmed.
- [ ] Time-axis reconstruction formula confirmed.

## MCP tools

- [x] `connect_tcp`
- [x] `disconnect_tcp`
- [x] `identify_tcp`
- [x] `safe_scpi_query_tcp`
- [x] `get_channel_tcp`
- [x] `configure_channel_tcp`
- [x] `configure_acquisition_tcp`
- [x] `get_acquisition_status_tcp`
- [x] `measure_tcp`
- [x] `screenshot_tcp`
- [x] `get_waveform_tcp`
- [x] `capture_uart_2mbps_tcp`
- [ ] Mark stable after SDS824X HD hardware test.

## Examples

- [x] TCP identity test.
- [x] SCPI probe script.
- [x] 2 Mbps UART capture example.
- [x] Screen image example.
- [x] Waveform export example.
- [ ] RS485 pair capture example.

## Known pre-release issues

- Unit parsing for mixed-case engineering units must be audited carefully, especially `mV`, `MS`, `M`, `G`, `Sa/s` responses.
- Current waveform conversion follows SDS-style byte conversion from upstream reference and must be checked against SDS800X HD binary format documentation.
- Raw screen image output is saved first; PNG conversion can be added after real image format is confirmed.
