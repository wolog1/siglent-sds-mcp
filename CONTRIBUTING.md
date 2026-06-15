# Contributing

Contributions are welcome.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
ruff check src tests examples scripts
```

## Command verification rule

Do not promote an SCPI command directly from another SDS family into a default MCP tool without marking its status.

Use this state model:

```text
candidate -> official-doc -> hardware-tested -> driver-implemented -> safe-mcp-tool
```

Update:

- `docs/sds824x-hd-command-matrix.md`
- `docs/verification-workflow.md`

## Hardware verification notes

When testing on a real SDS824X HD, include:

```text
Date:
Instrument model:
Serial number if shareable:
Firmware version:
Connection method:
Command:
Expected response:
Actual response:
Pass/fail:
Notes:
```

Do not commit private customer data, confidential waveforms, internal IP addresses, or raw field captures unless they are sanitized and intentionally public.

## Code style

- Python 3.10+
- Prefer small adapter functions over hardcoded MCP logic.
- Keep SDS800X HD command assumptions in `sds_tcp_adapter.py` or command matrix docs.
- Keep MCP tools high-level and recipe-oriented.
- Keep raw SCPI query/write behavior clearly labeled.
