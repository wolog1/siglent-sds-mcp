# Notices

This project is an independent Python implementation targeting SIGLENT SDS824X HD / SDS800X HD oscilloscopes.

## Upstream reference

The project design intentionally studies and references:

- `MagnusJohansson/siglent-sds-mcp`
- https://github.com/MagnusJohansson/siglent-sds-mcp

Useful upstream ideas include:

- MCP tool grouping for oscilloscope control
- raw TCP SCPI transport on port 5025
- serialized SCPI query handling
- IEEE 488.2 binary block parsing
- oscilloscope screenshot retrieval
- waveform voltage/time reconstruction

This repository does not treat upstream SDS1000X-E commands as authoritative for SDS824X HD. All commands should be verified against SDS800X HD official documentation and real SDS824X HD hardware.

## License

This repository currently uses GPL-3.0-only, matching the existing repository `LICENSE` file.
